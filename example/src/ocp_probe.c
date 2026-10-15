#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <napi/native_api.h>
#include <hilog/log.h>
#include <poll.h>
#include <pty.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

enum ProbeMode { PROBE_COMPILE, PROBE_LIFECYCLE };

typedef struct {
    napi_async_work work;
    char directory[PATH_MAX];
    int mode;
} Probe;

static atomic_int state = 0;

static void log_line(FILE *log, const char *line)
{
    if (log) {
        fputs(line, log);
        fflush(log);
    }
    OH_LOG_Print(LOG_APP, LOG_INFO, 0x0c01, "OCP", "%{public}s", line);
}

static int write_source(const char *path, const char *source)
{
    FILE *file = fopen(path, "w");
    if (!file) return -1;
    int result = fputs(source, file) == EOF ? -1 : 0;
    if (fclose(file)) result = -1;
    return result;
}

static void execute(napi_env env, void *data)
{
    (void)env;
    Probe *probe = data;
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/ocp-smoke.log", probe->directory);
    FILE *log = fopen(path, "w");
    struct timespec run_time;
    clock_gettime(CLOCK_MONOTONIC, &run_time);
    snprintf(path, sizeof(path), "OCP_SMOKE_BEGIN=%ld-%09ld-%d\n",
             (long)run_time.tv_sec, run_time.tv_nsec, getpid());
    log_line(log, path);
    snprintf(path, sizeof(path), "OCP_FILES_DIR=%s\n", probe->directory);
    log_line(log, path);
    snprintf(path, sizeof(path), "%s/ocp-smoke", probe->directory);
    if (mkdir(path, 0700) && errno != EEXIST) {
        log_line(log, "OCP_SMOKE_FAILED: cannot create work directory\n");
        atomic_store(&state, 3);
        if (log) fclose(log);
        return;
    }
    char source[PATH_MAX];
    snprintf(source, sizeof(source), "%s/hello.c", path);
    int failed = write_source(source,
        "#include <stdio.h>\nint main(void) { puts(\"OCP_C_OK\"); return 0; }\n");
    snprintf(source, sizeof(source), "%s/hello.zig", path);
    failed |= write_source(source,
        "extern \"c\" fn puts([*:0]const u8) c_int;\n"
        "pub fn main() void { _ = puts(\"OCP_ZIG_OK\"); }\n");
    snprintf(source, sizeof(source), "%s/hello.cpp", path);
    failed |= write_source(source,
        "#include <iostream>\nint main() { std::cout << \"OCP_CXX_OK\\n\"; }\n");
    if (failed) {
        log_line(log, "OCP_SMOKE_FAILED: cannot write source files\n");
        atomic_store(&state, 3);
        if (log) fclose(log);
        return;
    }
    int master;
    pid_t child = forkpty(&master, NULL, NULL, NULL);
    if (child < 0) {
        snprintf(source, sizeof(source), "OCP_SMOKE_FAILED: forkpty errno=%d\n", errno);
        log_line(log, source);
        atomic_store(&state, 3);
        if (log) fclose(log);
        return;
    }
    if (child == 0) {
        // Paths originate from AbilityContext; no user command is evaluated.
        if (chdir(path)) _exit(126);
        setenv("PATH", "/data/service/hnp/bin:/data/app/bin:/system/bin:/vendor/bin", 1);
        setenv("ZIG_GLOBAL_CACHE_DIR", "cache/global", 1);
        setenv("ZIG_LOCAL_CACHE_DIR", "cache/local", 1);
        setenv("TMPDIR", path, 1);
        if (probe->mode == PROBE_LIFECYCLE) {
            execl("/system/bin/sh", "sh", "./native-lifecycle.sh", (char *)NULL);
            _exit(127);
        }
        execl("/system/bin/sh", "sh", "-c",
            "set -eu; "
            "test -t 0; tty; echo OCP_PTY_OK; "
            "command -v zig; test \"$(zig version)\" = " OCP_ZIG_VERSION "; zig version; zig env; "
            "zig cc hello.c -target " OCP_ZIG_TARGET " -O2 -o hello-c; echo OCP_C_COMPILE_OK; "
            "zig build-exe hello.zig -target " OCP_ZIG_TARGET " -lc -O ReleaseFast -femit-bin=hello-zig; echo OCP_ZIG_COMPILE_OK; "
            "zig c++ hello.cpp -target " OCP_ZIG_TARGET " -O2 -o hello-cxx; echo OCP_CXX_COMPILE_OK; "
            "echo OCP_COMPILE_OK", (char *)NULL);
        _exit(127);
    }
    time_t deadline = time(NULL) + (probe->mode == PROBE_LIFECYCLE ? 900 : 300);
    int status = 0;
    int reaped = 0;
    char buffer[2048];
    while (time(NULL) < deadline) {
        struct pollfd descriptor = {.fd = master, .events = POLLIN};
        int ready = poll(&descriptor, 1, 1000);
        if (ready > 0) {
            ssize_t size = read(master, buffer, sizeof(buffer) - 1);
            if (size > 0) {
                buffer[size] = 0;
                log_line(log, buffer);
                continue;
            }
            if (size == 0 || (size < 0 && errno != EINTR && errno != EAGAIN)) break;
        } else if (ready < 0 && errno != EINTR) {
            break;
        }
        if (waitpid(child, &status, WNOHANG) == child) {
            reaped = 1;
            // The next poll drains any remaining PTY output.
            continue;
        }
    }
    if (!reaped) {
        if (waitpid(child, &status, WNOHANG) == 0) {
            kill(-child, SIGKILL);
        }
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    }
    close(master);
    snprintf(buffer, sizeof(buffer), "OCP_PTY_EXIT=%d\n", WIFEXITED(status) ? WEXITSTATUS(status) : 128);
    log_line(log, buffer);
    atomic_store(&state, probe->mode ? 4 :
        (WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 2 : 3));
    if (log) fclose(log);
}

static void complete(napi_env env, napi_status status, void *data)
{
    (void)status;
    Probe *probe = data;
    napi_delete_async_work(env, probe->work);
    free(probe);
}

static napi_value run_smoke(napi_env env, napi_callback_info info)
{
    size_t count = 2;
    napi_value arguments[2];
    napi_value result;
    napi_get_undefined(env, &result);
    if (atomic_load(&state) == 1) return result;
    atomic_store(&state, 1);
    Probe *probe = calloc(1, sizeof(*probe));
    if (!probe) {
        atomic_store(&state, 3);
        return result;
    }
    napi_get_cb_info(env, info, &count, arguments, NULL, NULL);
    size_t length;
    if (count < 1 || napi_get_value_string_utf8(env, arguments[0], probe->directory,
                                               sizeof(probe->directory), &length) != napi_ok) {
        free(probe);
        atomic_store(&state, 3);
        return result;
    }
    if (count == 2 && (napi_get_value_int32(env, arguments[1], &probe->mode) != napi_ok ||
                      probe->mode < PROBE_COMPILE || probe->mode > PROBE_LIFECYCLE)) {
        free(probe);
        atomic_store(&state, 3);
        return result;
    }
    napi_value name;
    napi_create_string_utf8(env, "ocp-pty-smoke", NAPI_AUTO_LENGTH, &name);
    if (napi_create_async_work(env, NULL, name, execute, complete, probe, &probe->work) != napi_ok) {
        free(probe);
        atomic_store(&state, 3);
        return result;
    }
    if (napi_queue_async_work(env, probe->work) != napi_ok) {
        napi_delete_async_work(env, probe->work);
        free(probe);
        atomic_store(&state, 3);
    }
    return result;
}

static napi_value get_status(napi_env env, napi_callback_info info)
{
    (void)info;
    const char *messages[] = {"准备验证", "正在验证 PTY 与 Zig 编译", "PTY 与 C / Zig / C++ 编译通过",
                             "诊断失败，请查看 OCP 日志", "诊断完成，请查看 OCP 日志"};
    napi_value result;
    napi_create_string_utf8(env, messages[atomic_load(&state)], NAPI_AUTO_LENGTH, &result);
    return result;
}

static napi_value initialize(napi_env env, napi_value exports)
{
    napi_property_descriptor properties[] = {
        {"runSmoke", NULL, run_smoke, NULL, NULL, NULL, napi_default, NULL},
        {"getStatus", NULL, get_status, NULL, NULL, NULL, napi_default, NULL}
    };
    napi_define_properties(env, exports, 2, properties);
    return exports;
}

static napi_module module = {.nm_version = 1, .nm_register_func = initialize, .nm_modname = "ocp_probe"};

__attribute__((constructor)) static void register_module(void)
{
    napi_module_register(&module);
}
