// Optional streaming body backend for power_vcd.py. Build: g++ -O3 -std=c++11.
// Header/interval validation and gzip/checksum receipts stay in the Python API.
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using U64 = uint64_t;
static void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
static U64 number(const std::string& text) {
    require(!text.empty(), "empty integer");
    U64 value = 0;
    for (char c : text) {
        require(c >= '0' && c <= '9', "invalid integer");
        unsigned digit = c - '0';
        require(value <= (std::numeric_limits<U64>::max() - digit) / 10,
                "integer exceeds native uint64 range");
        value = value * 10 + digit;
    }
    return value;
}
class Reader {
    FILE* file;
    char buffer[1048576];
    size_t index = 0, count = 0;
    static bool space(int c) { return c == ' ' || (c >= 9 && c <= 13); }
    int get() {
        if (index == count) {
            count = fread(buffer, 1, sizeof(buffer), file);
            index = 0;
            if (!count) {
                require(!ferror(file), "source read error");
                return EOF;
            }
        }
        return static_cast<unsigned char>(buffer[index++]);
    }
public:
    explicit Reader(FILE* source) : file(source) {}
    bool next(std::string& token) {
        token.clear();
        int c;
        do { c = get(); } while (c != EOF && space(c));
        if (c == EOF) return false;
        do {
            require(c < 128 && c >= 33, "non-ASCII VCD token");
            token += static_cast<char>(c);
            require(token.size() <= 1048576, "VCD token exceeds 1 MiB");
            c = get();
        } while (c != EOF && !space(c));
        return true;
    }
};
struct Var { std::string id, bits; size_t width; };
struct Window { U64 start, end; };
class Exporter {
public:
    std::string header, directory;
    std::vector<Var> vars;
    std::unordered_map<std::string, size_t> ids;
    std::vector<Window> windows;
    size_t index = 0;
    U64 time = 0, last_written = 0;
    bool enabled = true;
    FILE* active = nullptr;
    ~Exporter() { if (active) fclose(active); }
    void write(const std::string& text) {
        require(fwrite(text.data(), 1, text.size(), active) == text.size(), "output write error");
    }
    std::string format(const Var& v) {
        return (v.width == 1 ? v.bits + v.id : "b" + v.bits + " " + v.id) + "\n";
    }
    void ensure_open() {
        if (active || index == windows.size()) return;
        const auto& w = windows[index];
        if (!(w.start <= time && time < w.end)) return;
        require(enabled, "selected interval intersects disabled VCD dumping");
        char name[64];
        std::snprintf(name, sizeof(name), "/task_%02u.vcd", unsigned(index));
        std::string path = directory + name;
        active = fopen(path.c_str(), "wb");
        require(active != nullptr, "cannot create output");
        setvbuf(active, nullptr, _IOFBF, 1048576);
        write(header);
        if (header.empty() || header.back() != '\n') write("\n");
        write("#0\n$dumpvars\n");
        for (const auto& v : vars) write(format(v));
        write("$end\n");
        last_written = 0;
    }
    void close() {
        write("#" + std::to_string(windows[index].end - windows[index].start) + "\n");
        FILE* closed = active;
        active = nullptr;
        require(fclose(closed) == 0, "output close error");
        ++index;
    }
    void advance(U64 timestamp) {
        require(timestamp >= time, "VCD timestamps are not monotonic");
        while (index < windows.size()) {
            const auto& w = windows[index];
            if (w.start >= timestamp) break;
            if (time < w.start) time = w.start;
            ensure_open();
            if (w.end > timestamp) break;
            close();
        }
        time = timestamp;
    }
    void change(Reader& reader, const std::string& token, int section) {
        std::string bits, identifier;
        char first = token[0];
        bool scalar = false;
        if (first == 'b' || first == 'B') {
            bits = token.substr(1);
            require(reader.next(identifier), "truncated VCD vector");
            require(!bits.empty(), "empty VCD vector");
        } else {
            require(first == '0' || first == '1' || first == 'x' || first == 'X' ||
                    first == 'z' || first == 'Z', "malformed VCD value");
            scalar = true;
            bits = token.substr(0, 1);
            identifier = token.substr(1);
        }
        auto found = ids.find(identifier);
        require(found != ids.end(), "unknown VCD identifier");
        auto& v = vars[found->second];
        require(!scalar || v.width == 1, "scalar VCD width mismatch");
        require(bits.size() <= v.width, "vector VCD width mismatch");
        for (char& c : bits) {
            if (c == 'X') c = 'x';
            if (c == 'Z') c = 'z';
            require(c == '0' || c == '1' || c == 'x' || c == 'z', "malformed VCD vector");
        }
        if (section == 3) return; // Entire artificial dump-off section discarded.
        require(enabled || section == 2, "value while VCD dumping disabled");
        bool snapshot = section == 1 || section == 2;
        if (!snapshot) ensure_open();
        char fill = bits[0] == 'x' || bits[0] == 'z' ? bits[0] : '0';
        bits.insert(0, v.width - bits.size(), fill);
        v.bits.swap(bits);
        if (active) {
            U64 offset = time - windows[index].start;
            if (offset != last_written) {
                write("#" + std::to_string(offset) + "\n");
                last_written = offset;
            }
            write(format(v));
        }
    }
};

int main(int argc, char** argv) {
    FILE* input = nullptr;
    try {
        require(argc == 5, "usage: power_vcd_fast INPUT HEADER MANIFEST OUTPUT_DIR");
        Exporter out;
        out.directory = argv[4];
        std::ifstream header(argv[2], std::ios::binary);
        require(bool(header), "cannot read prepared header");
        out.header.assign(std::istreambuf_iterator<char>(header), std::istreambuf_iterator<char>());
        std::ifstream manifest(argv[3]);
        U64 offset, count, windows;
        require(bool(manifest >> offset >> count >> windows), "invalid manifest");
        require(count > 0 && windows > 0, "empty manifest");
        for (U64 i = 0; i < count; ++i) {
            Var v;
            require(bool(manifest >> v.width >> v.id) && v.width > 0, "invalid variable manifest");
            v.bits.assign(v.width, 'x');
            out.ids[v.id] = out.vars.size();
            out.vars.push_back(v);
        }
        for (U64 i = 0; i < windows; ++i) {
            Window w;
            require(bool(manifest >> w.start >> w.end) && w.start < w.end &&
                    (out.windows.empty() || w.start >= out.windows.back().end), "invalid interval manifest");
            out.windows.push_back(w);
        }
        input = fopen(argv[1], "rb");
        require(input != nullptr, "cannot open input");
#ifdef _WIN32
        require(_fseeki64(input, static_cast<__int64>(offset), SEEK_SET) == 0, "source seek failed");
#else
        require(fseeko(input, static_cast<off_t>(offset), SEEK_SET) == 0, "source seek failed");
#endif
        Reader reader(input);
        std::string token;
        int section = 0;
        bool saw_timestamp = false, saw_initial_values = false;
        while (reader.next(token)) {
            if (token == "$comment") {
                bool ended = false;
                while (reader.next(token)) if (token == "$end") { ended = true; break; }
                require(ended, "truncated VCD comment");
            } else if (token == "$dumpvars" || token == "$dumpon" ||
                       token == "$dumpoff" || token == "$dumpall") {
                require(section == 0, "nested VCD dump section");
                section = token == "$dumpvars" ? 1 : token == "$dumpon" ? 2 : token == "$dumpoff" ? 3 : 4;
                if (section == 2) for (auto& v : out.vars) v.bits.assign(v.width, 'x');
                if (section == 3) {
                    out.ensure_open();
                    require(!out.active, "dump disabled during selected window");
                    out.enabled = false;
                }
            } else if (token == "$end") {
                require(section != 0, "unexpected VCD $end");
                if (section == 2) out.enabled = true;
                section = 0;
            } else if (token[0] == '#') {
                require(section == 0, "timestamp inside dump section");
                U64 timestamp = number(token.substr(1));
                require(saw_timestamp || saw_initial_values || timestamp <= out.windows[0].start,
                        "selected interval precedes source activity");
                out.advance(timestamp);
                saw_timestamp = true;
            } else {
                if (!saw_timestamp) saw_initial_values = true;
                out.change(reader, token, section);
            }
        }
        require(section == 0, "truncated VCD dump section");
        require(saw_timestamp && out.index == out.windows.size(), "EOF does not cover selected intervals");
        require(fclose(input) == 0, "source close error");
        input = nullptr;
        return 0;
    } catch (const std::exception& error) {
        if (input) fclose(input);
        std::cerr << "power_vcd_fast: " << error.what() << '\n';
        return 1;
    }
}
