#pragma once
#include <nlohmann/json.hpp>
#include <sys/mman.h>
#include <sys/stat.h>
#include <zlib.h>
#include <algorithm>
#include <set>
#include <string_view>

// Only reads archives; never extracts paths from untrusted payloads.
namespace payload {
using Json = nlohmann::json;
struct Bytes { const uint8_t *data; size_t size; };
inline uint16_t u16(const uint8_t *p) { return p[0] | (uint16_t(p[1]) << 8); }
inline uint32_t u32(const uint8_t *p) { return u16(p) | (uint32_t(u16(p + 2)) << 16); }
class Mapping {
    int fd_;
    void *data_;
    size_t size_;
public:
    explicit Mapping(const char *path) : fd_(open(path, O_RDONLY | O_CLOEXEC)), data_(MAP_FAILED), size_(0) {
        struct stat info{};
        if (fd_ < 0 || fstat(fd_, &info) || !S_ISREG(info.st_mode) || info.st_size <= 0 || uint64_t(info.st_size) >= UINT32_MAX)
            fail("Invalid HAP file");
        size_ = info.st_size; data_ = mmap(nullptr, size_, PROT_READ, MAP_PRIVATE, fd_, 0);
        if (data_ == MAP_FAILED) fail("Cannot map HAP file");
    }
    ~Mapping() { munmap(data_, size_); close(fd_); }
    Bytes bytes() const { return {static_cast<const uint8_t *>(data_), size_}; }
};
struct Entry { std::string name; uint32_t local, compressed, size, crc; uint16_t method; };
class Zip {
    Bytes bytes_;
    std::vector<Entry> entries_;
    const uint8_t *at(size_t offset, size_t count) const {
        if (offset > bytes_.size || count > bytes_.size - offset) fail("Truncated ZIP payload");
        return bytes_.data + offset;
    }
public:
    explicit Zip(Bytes bytes) : bytes_(bytes) {
        if (bytes.size < 22) fail("Missing ZIP footer");
        size_t footer = bytes.size - 22;
        while (u32(at(footer, 4)) != 0x06054b50 || footer + 22 + u16(at(footer + 20, 2)) != bytes.size) {
            if (footer == 0 || bytes.size - footer > 65557) fail("Invalid ZIP footer"); --footer;
        }
        const auto p = at(footer, 22);
        if (u16(p + 4) || u16(p + 6) || u16(p + 8) != u16(p + 10) || u16(p + 10) == 65535) fail("Multi-disk/ZIP64 payload unsupported");
        size_t offset = u32(p + 16), end = offset + u32(p + 12);
        if (end != footer) fail("Invalid ZIP directory");
        std::set<std::string> names;
        for (unsigned i = 0; i < u16(p + 10); i++) {
            auto record = at(offset, 46);
            if (u32(record) != 0x02014b50 || (u16(record + 8) & 1)) fail("Invalid or encrypted ZIP entry");
            const size_t length = u16(record + 28), extra = u16(record + 30), comment = u16(record + 32);
            std::string name(reinterpret_cast<const char *>(at(offset + 46, length)), length);
            if (name.empty() || name.front() == '/' || name.find('\0') != std::string::npos || name.find('\\') != std::string::npos
                || name == ".." || name.find("../") != std::string::npos || !names.insert(name).second) fail("Unsafe or duplicate ZIP entry");
            entries_.push_back({name, u32(record + 42), u32(record + 20), u32(record + 24), u32(record + 16), u16(record + 10)});
            offset += 46 + length + extra + comment;
            if (offset > end) fail("ZIP directory overflow");
        }
        if (offset != end) fail("ZIP directory size mismatch");
    }
    const Entry &entry(const std::string &name) const {
        for (const auto &item : entries_) if (item.name == name) return item;
        fail("Missing archive entry: " + name);
    }
    Bytes stored(const Entry &item) const {
        const auto local = at(item.local, 30);
        if (u32(local) != 0x04034b50 || u16(local + 8) != item.method) fail("ZIP local header mismatch");
        const size_t length = u16(local + 26), extra = u16(local + 28);
        if (std::string_view(reinterpret_cast<const char *>(at(item.local + 30, length)), length) != item.name) fail("ZIP local name mismatch");
        return {at(size_t(item.local) + 30 + length + extra, item.compressed), item.compressed};
    }
    std::vector<uint8_t> read(const std::string &name, size_t limit = 1048576) const {
        const auto &item = entry(name); auto source = stored(item);
        if (item.size > limit) fail("Archive metadata exceeds size limit");
        std::vector<uint8_t> output(item.size);
        if (item.method == 0) {
            if (item.compressed != item.size) fail("Stored ZIP size mismatch");
            std::copy(source.data, source.data + source.size, output.begin());
        } else if (item.method == 8) {
            z_stream stream{}; stream.next_in = const_cast<uint8_t *>(source.data); stream.avail_in = source.size;
            stream.next_out = output.data(); stream.avail_out = output.size();
            if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) fail("Cannot initialize ZIP decoder");
            int status = inflate(&stream, Z_FINISH); inflateEnd(&stream);
            if (status != Z_STREAM_END || stream.total_out != item.size || stream.total_in != source.size) fail("Invalid deflated ZIP entry");
        } else fail("Unsupported ZIP compression");
        if (crc32(0, output.data(), output.size()) != item.crc) fail("ZIP CRC mismatch");
        return output;
    }
};
inline Json json(const std::vector<uint8_t> &bytes) {
    std::map<int, std::set<std::string>> keys;
    auto value = Json::parse(bytes.begin(), bytes.end(), [&](int depth, Json::parse_event_t event, Json &part) {
        if (depth > 32) fail("JSON nesting exceeds limit");
        if (event == Json::parse_event_t::object_start) keys[depth + 1].clear();
        if (event == Json::parse_event_t::key && !keys[depth].insert(part.get<std::string>()).second) fail("Duplicate JSON key");
        return true;
    }, false);
    if (value.is_discarded() || !value.is_object()) fail("Invalid package JSON"); return value;
}
inline const Json &member(const Json &object, const char *key) {
    if (!object.is_object() || !object.contains(key)) fail(std::string("Missing metadata: ") + key); return object.at(key);
}
inline std::string text(const Json &object, const char *key) {
    const auto &value = member(object, key); if (!value.is_string()) fail("Invalid package string"); return value.get<std::string>();
}
inline std::set<std::string> commands(const std::string &csv) {
    std::set<std::string> values;
    for (size_t start = 0;;) {
        size_t end = csv.find(',', start); std::string value = csv.substr(start, end - start);
        if (value.empty() || value == "." || value == ".." || value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-") != std::string::npos
            || value == "ocp" || value == "ocp-maker" || value == "ocp-bm" || !values.insert(value).second) fail("Invalid or reserved exported command");
        if (end == std::string::npos) return values; start = end + 1;
    }
}
inline void validate(const char *path, const std::string &bundle, const std::string &version, const std::string &abi,
    const std::string &name, const std::string &csv) {
    Mapping mapping(path); Zip hap(mapping.bytes()); Json config = json(hap.read("module.json"));
    const auto &app = member(config, "app"), &module = member(config, "module");
    if (text(app, "bundleName") != bundle || text(app, "versionName") != version) fail("HAP bundle/version does not match catalog");
    for (const char *key : {"abilities", "extensionAbilities", "requestPermissions", "definePermissions"})
        if (module.contains(key) && (!module.at(key).is_array() || !module.at(key).empty())) fail("Tool HAP must contain no UI, extensions or permissions");
    const auto &packages = member(module, "hnpPackages");
    if (!packages.is_array() || packages.size() != 1 || text(packages[0], "package") != name + ".hnp" || text(packages[0], "type") != "public") fail("Unexpected HNP declaration");
    const auto &nativeEntry = hap.entry("hnp/" + abi + "/" + name + ".hnp");
    // SDK-packed HNPs are stored in HAP. Reject compression of the whole HNP to
    // keep validation bounded in memory even for LLVM-sized tools.
    if (nativeEntry.method || nativeEntry.size != nativeEntry.compressed) fail("HNP must be stored in the HAP");
    Zip native(hap.stored(nativeEntry)); Json metadata = json(native.read(name + "/hnp.json"));
    if (text(metadata, "name") != name || text(metadata, "version") != version) fail("HNP identity/version mismatch");
    const auto expected = commands(csv); std::set<std::string> actual;
    const auto &links = member(member(metadata, "install"), "links");
    if (!links.is_array()) fail("Invalid HNP links");
    const int machine = abi == "arm64-v8a" ? 183 : abi == "x86_64" ? 62 : abi == "armeabi-v7a" ? 40 : 0;
    if (!machine) fail("Unsupported tool ABI");
    for (const auto &link : links) {
        auto target = text(link, "target"), source = text(link, "source");
        if (!actual.insert(target).second || !expected.count(target) || source.empty() || source.front() == '/' || source.find("..") != std::string::npos) fail("Unexpected HNP command link");
        const auto &entry = native.entry(name + "/" + source);
        // Executables can be compressed in the HNP; decode only the prefix.
        auto bytes = native.stored(entry); uint8_t prefix[20]{};
        if (entry.method == 0 && bytes.size >= sizeof prefix) std::memcpy(prefix, bytes.data, sizeof prefix);
        else if (entry.method == 8) {
            z_stream stream{}; stream.next_in = const_cast<uint8_t *>(bytes.data); stream.avail_in = bytes.size;
            stream.next_out = prefix; stream.avail_out = sizeof prefix;
            if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) fail("Cannot decode command header");
            int status = inflate(&stream, Z_NO_FLUSH); inflateEnd(&stream);
            if ((status != Z_OK && status != Z_STREAM_END) || stream.total_out < sizeof prefix) fail("Invalid command header");
        } else fail("Command entry too small or compression unsupported");
        if (std::memcmp(prefix, "#!/system/bin/sh\n", 17) != 0
            && (std::memcmp(prefix, "\x7f" "ELF", 4) || prefix[5] != 1 || u16(prefix + 18) != machine)) fail("HNP command ABI mismatch");
    }
    if (actual != expected) fail("Exported commands disagree with catalog");
}
}
