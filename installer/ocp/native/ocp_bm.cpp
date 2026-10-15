// Device-side BMS adapter. All operations retain the calling app's token.
#include <IPCKit/ipc_kit.h>
#include <accesstoken/ability_access_control.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <unistd.h>
#include <limits.h>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include "ipc_inner_object.h"
#include "ipc_skeleton.h"
#include "message_option.h"

namespace {
constexpr const char *installerToken = "ohos.appexecfwk.BundleInstaller";
constexpr const char *streamToken = "ohos.appexecfwk.BundleStreamInstaller";
constexpr const char *receiverToken = "ohos.appexecfwk.StatusReceiver";
[[noreturn]] void fail(const std::string &message) {
    std::fprintf(stderr, "ocp-bm: %s\n", message.c_str()); std::exit(1);
}
void check(int status, const char *operation) {
    if (status != 0) fail(std::string(operation) + ": IPC error " + std::to_string(status));
}
using Parcel = std::unique_ptr<OHIPCParcel, decltype(&OH_IPCParcel_Destroy)>;
using Proxy = std::unique_ptr<OHIPCRemoteProxy, decltype(&OH_IPCRemoteProxy_Destroy)>;
Parcel parcel() {
    Parcel value(OH_IPCParcel_Create(), OH_IPCParcel_Destroy);
    if (!value) fail("Cannot allocate IPC parcel"); return value;
}
Proxy proxy(OHIPCRemoteProxy *value) {
    if (!value) fail("BMS returned no remote object");
    return Proxy(value, OH_IPCRemoteProxy_Destroy);
}
void integer(OHIPCParcel *p, int32_t value) { check(OH_IPCParcel_WriteInt32(p, value), "Write integer"); }
int32_t integer(const OHIPCParcel *p) {
    int32_t value = 0; check(OH_IPCParcel_ReadInt32(p, &value), "Read integer"); return value;
}
void token(OHIPCParcel *p, const char *value) { check(OH_IPCParcel_WriteInterfaceToken(p, value), "Write token"); }
void string8(OHIPCParcel *p, const std::string &value) {
    integer(p, static_cast<int32_t>(value.size()));
    check(OH_IPCParcel_WriteBuffer(p, reinterpret_cast<const uint8_t *>(value.c_str()), value.size() + 1), "Write string");
}
void string16(OHIPCParcel *p, const std::string &value) {
    // Bundle identifiers and InstallParam strings are restricted to ASCII here.
    std::vector<uint16_t> bytes(value.begin(), value.end()); bytes.push_back(0);
    integer(p, static_cast<int32_t>(value.size()));
    check(OH_IPCParcel_WriteBuffer(p, reinterpret_cast<const uint8_t *>(bytes.data()), bytes.size() * 2), "Write UTF16");
}
std::string string16(const OHIPCParcel *p) {
    int32_t length = integer(p);
    if (length < 0 || length > 32768) fail("Invalid UTF16 response length");
    auto bytes = OH_IPCParcel_ReadBuffer(p, (length + 1) * 2);
    if (!bytes) fail("Truncated UTF16 response");
    std::string value;
    for (int32_t i = 0; i < length; i++) {
        uint16_t character = bytes[i * 2] | (bytes[i * 2 + 1] << 8);
        if (character < 128) value += static_cast<char>(character);
        else if (character < 2048) { value += char(0xc0 | (character >> 6)); value += char(0x80 | (character & 63)); }
        else { value += char(0xe0 | (character >> 12)); value += char(0x80 | ((character >> 6) & 63)); value += char(0x80 | (character & 63)); }
    }
    return value;
}
void parameters(OHIPCParcel *p, int32_t user) {
    // API 26 image layout. Newer BMS layouts require a separately verified adapter.
    integer(p, 1); // Parcelable present.
    integer(p, 1); integer(p, 1); integer(p, user); integer(p, 0);
    integer(p, 0); check(OH_IPCParcel_WriteInt64(p, 0), "Write deadline"); integer(p, 0);
    string16(p, ""); string16(p, ""); integer(p, 0); string16(p, "");
    integer(p, 0); integer(p, 0); integer(p, 0); integer(p, 0); integer(p, 0);
}
struct Completion {
    std::mutex mutex;
    std::condition_variable condition;
    bool done = false;
    int result = -1, inner = -1;
    std::string message;
};
int receive(uint32_t code, const OHIPCParcel *data, OHIPCParcel *, void *opaque) {
    char *descriptor = nullptr; int32_t length = 0;
    if (OH_IPCParcel_ReadInterfaceToken(data, &descriptor, &length,
        [](int32_t size) -> void * { return size > 0 ? std::malloc(size) : nullptr; }) != 0) return 1909001;
    const bool valid = descriptor && std::strcmp(descriptor, receiverToken) == 0;
    std::free(descriptor); if (!valid) return 1909001;
    if (code != 1) return 0; // Progress notification.
    auto &state = *static_cast<Completion *>(opaque);
    std::lock_guard<std::mutex> guard(state.mutex);
    state.result = integer(data); state.message = string16(data);
    state.inner = OH_IPCParcel_GetReadableBytes(data) >= 4 ? integer(data) : state.result;
    state.done = true; state.condition.notify_one(); return 0;
}
class Backend {
    void *library_;
    using ConstructOption = void (*)(void *, int, int);
    ConstructOption construct_;
    Proxy context_{nullptr, OH_IPCRemoteProxy_Destroy};
    Proxy bms_{nullptr, OH_IPCRemoteProxy_Destroy};
    Proxy installer_{nullptr, OH_IPCRemoteProxy_Destroy};
    int32_t user_;
public:
    Backend() : library_(dlopen("libipc_capi.so", RTLD_NOW | RTLD_LOCAL)), construct_(nullptr),
        user_(static_cast<int32_t>(getuid() / 200000)) {
        if (OH_AT_CheckSelfPermission("ohos.permission.ALLOW_USE_BM") != 1)
            fail("Caller needs approved ALLOW_USE_BM permission (API 26, 2in1, developer mode)");
        if (!library_) fail("Platform IPC runtime unavailable");
        using Context = OHOS::sptr<OHOS::IRemoteObject> (*)();
        auto getter = reinterpret_cast<Context>(dlsym(library_, "_ZN4OHOS11IPCSkeleton16GetContextObjectEv"));
        construct_ = reinterpret_cast<ConstructOption>(dlsym(library_, "_ZN4OHOS13MessageOptionC1Eii"));
        if (!getter || !construct_) fail("Unsupported platform IPC ABI; no installation attempted");
        context_ = proxy(new OHIPCRemoteProxy{getter()});
        auto data = parcel(), reply = parcel();
        token(data.get(), "ohos.samgr.accessToken"); integer(data.get(), 401);
        send(context_.get(), 1, data.get(), reply.get()); bms_ = proxy(OH_IPCParcel_ReadRemoteProxy(reply.get()));
        data = parcel(); reply = parcel(); token(data.get(), "ohos.appexecfwk.BundleMgr");
        send(bms_.get(), 43, data.get(), reply.get()); installer_ = proxy(OH_IPCParcel_ReadRemoteProxy(reply.get()));
        OH_IPCSkeleton_SetMaxWorkThreadNum(2);
        std::thread([] { OH_IPCSkeleton_JoinWorkThread(); }).detach();
    }
    void send(OHIPCRemoteProxy *remote, uint32_t code, OHIPCParcel *data, OHIPCParcel *reply) {
        // The public C wrapper rejects code 0, which BMS uses for CreateStream.
        // Use the platform's real option constructor and virtual proxy method.
        alignas(OHOS::MessageOption) unsigned char storage[sizeof(OHOS::MessageOption)];
        construct_(storage, 0, 8);
        auto &option = *reinterpret_cast<OHOS::MessageOption *>(storage);
        check(remote->remote->SendRequest(code, *data->msgParcel, *reply->msgParcel, option), "BMS request");
        option.~MessageOption();
    }
    void apply(const char *operation, const char *value) {
        // Allocate callback state for process lifetime, including timeout: the
        // remote service can still retain the receiver after a timed-out call.
        auto *completion = new Completion;
        auto receiver = OH_IPCRemoteStub_Create(receiverToken, receive, nullptr, completion);
        if (!receiver) fail("Cannot allocate installation callback");
        uint32_t streamId = 0;
        if (std::strcmp(operation, "install") == 0) {
            int input = open(value, O_RDONLY | O_CLOEXEC);
            if (input < 0) fail("Cannot open HAP: " + std::string(std::strerror(errno)));
            auto data = parcel(), reply = parcel(); token(data.get(), installerToken);
            parameters(data.get(), user_);
            check(OH_IPCParcel_WriteRemoteStub(data.get(), receiver), "Write receiver"); integer(data.get(), 0);
            send(installer_.get(), 8, data.get(), reply.get());
            if (integer(reply.get()) == 0) fail("BMS refused stream installation");
            streamId = integer(reply.get()); auto stream = proxy(OH_IPCParcel_ReadRemoteProxy(reply.get()));
            data = parcel(); reply = parcel(); token(data.get(), streamToken); string8(data.get(), "tool.hap");
            send(stream.get(), 0, data.get(), reply.get());
            int shared = -1; check(OH_IPCParcel_ReadFileDescriptor(reply.get(), &shared), "Read installation descriptor");
            int output = shared; // ReadFileDescriptor returns a caller-owned dup.
            if (output < 0) fail("Cannot duplicate installation descriptor");
            char buffer[65536]; ssize_t length;
            while ((length = read(input, buffer, sizeof buffer)) != 0) {
                if (length < 0) { if (errno == EINTR) continue; fail("Cannot read HAP"); }
                for (ssize_t offset = 0; offset < length;) {
                    ssize_t written = write(output, buffer + offset, length - offset);
                    if (written < 0 && errno == EINTR) continue;
                    if (written <= 0) fail("Cannot write installation stream"); offset += written;
                }
            }
            if (fsync(output)) fail("Cannot flush installation stream");
            close(output); close(input);
            data = parcel(); reply = parcel(); token(data.get(), streamToken); send(stream.get(), 1, data.get(), reply.get());
        } else {
            auto data = parcel(), reply = parcel(); token(data.get(), installerToken); string16(data.get(), value);
            parameters(data.get(), user_); check(OH_IPCParcel_WriteRemoteStub(data.get(), receiver), "Write receiver");
            send(installer_.get(), 2, data.get(), reply.get());
        }
        std::unique_lock<std::mutex> lock(completion->mutex);
        if (!completion->condition.wait_for(lock, std::chrono::seconds(180), [&] { return completion->done; }))
            fail("BMS callback timed out; run ocp sync before retrying");
        int result = completion->result, inner = completion->inner; std::string message = completion->message;
        lock.unlock(); OH_IPCRemoteStub_Destroy(receiver);
        if (streamId) {
            auto data = parcel(), reply = parcel(); token(data.get(), installerToken); integer(data.get(), streamId);
            send(installer_.get(), 9, data.get(), reply.get());
        }
        if (result || inner) fail("BMS rejected operation: " + std::to_string(result) + "/" + std::to_string(inner) + " " + message);
        std::printf("%s succeeded (BMS callback 0)\n", operation);
    }
};
}

#include "payload.h"

namespace {
bool identifier(const std::string &value) {
    return !value.empty() && value != "." && value != ".."
        && value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") == std::string::npos;
}
void identity(const std::string &bundle, const std::string &hnp) {
    constexpr const char *prefix = "com.richerfu.ocp.pkg.";
    if (bundle.compare(0, std::strlen(prefix), prefix) || !identifier(bundle.substr(std::strlen(prefix))))
        fail("Only catalog-owned com.richerfu.ocp.pkg.* bundles can be changed");
    auto suffix = bundle.substr(std::strlen(prefix)); std::replace(suffix.begin(), suffix.end(), '.', '_');
    if (hnp != "ocp_" + suffix) fail("HNP name does not match bundle namespace");
}
std::string resolved(const std::string &command) {
    char path[PATH_MAX]; const auto input = "/data/service/hnp/bin/" + command;
    return realpath(input.c_str(), path) ? std::string(path) : std::string();
}
bool installed(const std::string &hnp, const std::string &version, const std::string &csv) {
    if (!identifier(hnp) || !identifier(version)) fail("Invalid HNP identity");
    const auto prefix = "/data/service/hnp/" + hnp + ".org/" + hnp + "_" + version + "/";
    for (const auto &command : payload::commands(csv)) {
        const auto path = resolved(command);
        if (path.compare(0, prefix.size(), prefix) || access(path.c_str(), X_OK)) return false;
    }
    return true;
}
}

int main(int argc, char **argv) {
    if (argc == 2 && std::strcmp(argv[1], "doctor") == 0) {
        Backend backend; std::puts("Device BMS ready: caller permission approved, native IPC available"); return 0;
    }
    if (argc == 5 && std::strcmp(argv[1], "status") == 0)
        return installed(argv[2], argv[3], argv[4]) ? 0 : 3;
    if (argc == 8 && std::strcmp(argv[1], "install") == 0) {
        identity(argv[3], argv[6]);
        payload::validate(argv[2], argv[3], argv[4], argv[5], argv[6], argv[7]);
        const auto prefix = std::string("/data/service/hnp/") + argv[6] + ".org/";
        for (const auto &command : payload::commands(argv[7])) {
            const auto path = resolved(command);
            if (!path.empty() && path.compare(0, prefix.size(), prefix)) fail("Command already owned by another installed HNP: " + command);
        }
        Backend backend; backend.apply("install", argv[2]); return 0;
    }
    if (argc == 3 && std::strcmp(argv[1], "uninstall") == 0) {
        std::string bundle = argv[2]; constexpr const char *prefix = "com.richerfu.ocp.pkg.";
        if (bundle.compare(0, std::strlen(prefix), prefix) || !identifier(bundle.substr(std::strlen(prefix)))) fail("Refusing non-tool bundle uninstall");
        Backend backend; backend.apply("uninstall", argv[2]); return 0;
    }
    std::fputs("Usage: ocp-bm doctor | status HNP VERSION COMMANDS | install HAP BUNDLE VERSION ABI HNP COMMANDS | uninstall BUNDLE\n", stderr);
    return 2;
}
