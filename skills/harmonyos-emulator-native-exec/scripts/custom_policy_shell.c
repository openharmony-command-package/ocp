// Emulator diagnostic: run a command with the original MateBook app_custom filter.
// SetSeccompPolicyWithName is the OpenHarmony startup_init inner API; APP = 2.
// The probe adds restrictions and requires an existing developer execution domain.
#include <dlfcn.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    char context[160] = {0};
    FILE *file = fopen("/proc/self/attr/current", "r");
    if (!file || !fgets(context, sizeof(context), file)) {
        fprintf(stderr, "Cannot read execution domain\n");
        return 126;
    }
    fclose(file);
    if (strcmp(context, "u:r:develop_tools_debug_hap:s0") != 0) {
        fprintf(stderr, "Expected developer debug domain, received %s\n", context);
        return 126;
    }
    if (argc < 2) {
        fprintf(stderr, "Usage: custom-policy-shell COMMAND [ARG...]\n");
        return 2;
    }
    void *library = dlopen("/system/lib64/libseccomp.z.so", RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        fprintf(stderr, "Cannot load factory seccomp library: %s\n", dlerror());
        return 126;
    }
    bool (*set_policy)(int, const char *) = dlsym(library, "SetSeccompPolicyWithName");
    if (!set_policy || prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 || !set_policy(2, "app_custom")) {
        fprintf(stderr, "Factory app_custom policy failed, errno=%d\n", errno);
        return 126;
    }
    int seccomp = -1;
    char line[256];
    file = fopen("/proc/self/status", "r");
    if (!file) {
        perror("Cannot verify seccomp status");
        return 126;
    }
    while (fgets(line, sizeof(line), file)) {
        if (sscanf(line, "Seccomp: %d", &seccomp) == 1 ||
            strncmp(line, "Seccomp_filters:", 16) == 0 ||
            strncmp(line, "NoNewPrivs:", 11) == 0) {
            fputs(line, stdout);
        }
    }
    fclose(file);
    if (seccomp != 2) {
        fprintf(stderr, "Factory filter was not activated (Seccomp=%d)\n", seccomp);
        return 126;
    }
    printf("Domain: %s\nFactory policy: app_custom\n", context);
    fflush(stdout);
    execvp(argv[1], &argv[1]);
    perror("Command exec failed");
    return 126;
}
