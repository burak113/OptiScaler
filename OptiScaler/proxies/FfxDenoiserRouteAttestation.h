#pragma once

// Diagnostic witnesses for the function pointers actually called by the proxy.
// Disk bytes are a snapshot at the first diagnostic request, not a hash of the
// loaded image, its backing section, or an associated SDK provider.
#include <windows.h>
#include <psapi.h>
#include <bcrypt.h>
#include <json.hpp>
#include <array>
#include <atomic>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "psapi.lib")

namespace FfxDenoiserRouteAttestation
{
using Json = nlohmann::json;
enum Operation : size_t { Create, Configure, Dispatch, Query, Destroy, OperationCount };
inline constexpr std::array<const char*, OperationCount> OperationNames {
    "create", "configure", "dispatch", "query", "destroy" };

struct TargetOrigin
{
    uintptr_t resolvedTarget = 0;
    uintptr_t committedTrampoline = 0;
};

struct Route
{
    const char* name = "unavailable";
    HMODULE selectedModule = nullptr;
    std::array<uintptr_t, OperationCount> calledTargets {};
    std::array<TargetOrigin, OperationCount> origins {};
};

inline std::string Hex(uint64_t value)
{
    const char digits[] = "0123456789abcdef";
    std::string out(18, '0'); out[0] = '0'; out[1] = 'x';
    for (size_t i = 0; i < 16; ++i) out[17-i] = digits[(value >> (i*4)) & 15];
    return out;
}

inline std::string Utf8(const std::wstring& value)
{
    if (value.empty()) throw std::runtime_error("Empty module path");
    const int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
        static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (length <= 0) throw std::runtime_error("Module path UTF-8 conversion failed");
    std::string out(length, '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()),
        out.data(), length, nullptr, nullptr) != length)
        throw std::runtime_error("Module path UTF-8 conversion failed");
    return out;
}

inline std::wstring ModulePath(HMODULE module)
{
    std::vector<wchar_t> path(32768);
    const DWORD length = GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) throw std::runtime_error("Actual target module path unavailable");
    std::wstring out(path.data(), length);
    if (out.size() < 3 || ((out[1] != L':' || (out[2] != L'\\' && out[2] != L'/')) && out.rfind(L"\\\\", 0) != 0))
        throw std::runtime_error("Actual target module path is not absolute");
    return out;
}

inline std::wstring MappedPath(HMODULE module)
{
    std::vector<wchar_t> path(32768);
    const DWORD length = GetMappedFileNameW(GetCurrentProcess(), module, path.data(), static_cast<DWORD>(path.size()));
    if (!length || length >= path.size()) throw std::runtime_error("Actual target mapped path unavailable");
    return std::wstring(path.data(), length);
}

struct TargetWitness
{
    uintptr_t called = 0;
    uintptr_t resolved = 0;
    HMODULE owner = nullptr;
    std::wstring path;
    std::wstring mappedPath;
    bool trampoline = false;
};

// Caller can supply the proxy's unhooked KernelBase function. No module-name or
// file-size heuristic participates in target ownership resolution.
using ModuleFromAddress = decltype(&GetModuleHandleExW);
inline TargetWitness Witness(uintptr_t called, TargetOrigin origin, ModuleFromAddress getModule)
{
    if (!called || !getModule) throw std::runtime_error("Missing called target or module resolver");
    TargetWitness out; out.called = called;
    if (origin.committedTrampoline && called == origin.committedTrampoline)
    {
        MEMORY_BASIC_INFORMATION region {};
        if (!origin.resolvedTarget || !VirtualQuery(reinterpret_cast<void*>(called), &region, sizeof(region)) ||
            region.State != MEM_COMMIT || region.Type != MEM_PRIVATE || (region.Protect & PAGE_GUARD) ||
            !(region.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)))
            throw std::runtime_error("Tracked Detours trampoline is not executable private memory");
        out.resolved = origin.resolvedTarget; out.trampoline = true;
    }
    else
    {
        // An unexpected pointer change cannot borrow an old export's provenance.
        if (origin.resolvedTarget && called != origin.resolvedTarget)
            throw std::runtime_error("Called target differs from resolved export and committed trampoline");
        out.resolved = called;
    }
    if (!getModule(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(out.resolved), &out.owner) || !out.owner)
        throw std::runtime_error("Called target has no resolved image module");
    MEMORY_BASIC_INFORMATION image {};
    if (!VirtualQuery(reinterpret_cast<void*>(out.resolved), &image, sizeof(image)) || image.State != MEM_COMMIT ||
        image.Type != MEM_IMAGE || image.AllocationBase != out.owner || (image.Protect & PAGE_GUARD) ||
        !(image.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)))
        throw std::runtime_error("Resolved target module disagrees with image mapping");
    out.path = ModulePath(out.owner); out.mappedPath = MappedPath(out.owner);
    return out;
}

struct FileSnapshot
{
    HANDLE file = INVALID_HANDLE_VALUE;
    Json identity;
    ~FileSnapshot() { if (file != INVALID_HANDLE_VALUE) CloseHandle(file); }
};

inline Json FileIdentity(HANDLE file)
{
    FILE_ID_INFO id {}; FILE_STANDARD_INFO standard {}; FILE_BASIC_INFO basic {};
    if (!GetFileInformationByHandleEx(file, FileIdInfo, &id, sizeof(id)) ||
        !GetFileInformationByHandleEx(file, FileStandardInfo, &standard, sizeof(standard)) ||
        !GetFileInformationByHandleEx(file, FileBasicInfo, &basic, sizeof(basic)) ||
        standard.Directory || standard.EndOfFile.QuadPart < 0)
        throw std::runtime_error("Module FILE_ID/size/time unavailable");
    std::string fileId;
    const char digits[] = "0123456789abcdef";
    for (auto byte : id.FileId.Identifier) { fileId += digits[byte >> 4]; fileId += digits[byte & 15]; }
    return {{"volume_serial", Hex(id.VolumeSerialNumber)}, {"file_id", fileId},
        {"disk_size", standard.EndOfFile.QuadPart}, {"last_write_time", basic.LastWriteTime.QuadPart},
        {"change_time", basic.ChangeTime.QuadPart}};
}

// Same Windows BCrypt SHA256 primitive as RRTraceAdditiveIO, streamed to avoid
// allocating an entire SDK DLL. Hash object storage outlives BCryptDestroyHash.
inline std::string HashFile(HANDLE file)
{
    struct Algorithm
    {
        BCRYPT_ALG_HANDLE value = nullptr;
        ~Algorithm() { if (value) BCryptCloseAlgorithmProvider(value, 0); }
    } algorithm;
    if (BCryptOpenAlgorithmProvider(&algorithm.value, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        throw std::runtime_error("Module SHA256 provider failed");
    ULONG objectBytes = 0, written = 0;
    if (BCryptGetProperty(algorithm.value, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&objectBytes),
        sizeof(objectBytes), &written, 0) < 0 || !objectBytes)
        throw std::runtime_error("Module SHA256 object length failed");
    std::vector<uint8_t> object(objectBytes);
    struct Hash
    {
        BCRYPT_HASH_HANDLE value = nullptr;
        ~Hash() { if (value) BCryptDestroyHash(value); }
    } hash;
    if (BCryptCreateHash(algorithm.value, &hash.value, object.data(), objectBytes, nullptr, 0, 0) < 0)
        throw std::runtime_error("Module SHA256 create failed");
    std::vector<uint8_t> bytes(1u << 20);
    DWORD count = 0;
    do
    {
        if (!ReadFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &count, nullptr))
            throw std::runtime_error("Module disk file read failed");
        if (count && BCryptHashData(hash.value, bytes.data(), count, 0) < 0)
            throw std::runtime_error("Module SHA256 update failed");
    } while (count);
    std::array<uint8_t, 32> digest {};
    if (BCryptFinishHash(hash.value, digest.data(), static_cast<ULONG>(digest.size()), 0) < 0)
        throw std::runtime_error("Module SHA256 finish failed");
    const char digits[] = "0123456789abcdef"; std::string out;
    for (auto byte : digest) { out += digits[byte >> 4]; out += digits[byte & 15]; }
    return out;
}

inline std::shared_ptr<FileSnapshot> Snapshot(const TargetWitness& target)
{
    // Prevent future writes/deletes while this diagnostic context holds the
    // snapshot. This does not establish equality with the already loaded image.
    auto out = std::make_shared<FileSnapshot>();
    out->file = CreateFileW(target.path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (out->file == INVALID_HANDLE_VALUE) throw std::runtime_error("Module disk file cannot be frozen for attestation");
    const Json before = FileIdentity(out->file);
    std::vector<wchar_t> finalPath(32768);
    const DWORD finalLength = GetFinalPathNameByHandleW(out->file, finalPath.data(),
        static_cast<DWORD>(finalPath.size()), FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (!finalLength || finalLength >= finalPath.size())
        throw std::runtime_error("Module disk handle final path unavailable");
    const std::string hash = HashFile(out->file);
    if (FileIdentity(out->file) != before) throw std::runtime_error("Module file identity changed during hashing");
    FILE_ATTRIBUTE_TAG_INFO attributes {};
    if (!GetFileInformationByHandleEx(out->file, FileAttributeTagInfo, &attributes, sizeof(attributes)) ||
        (attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
        throw std::runtime_error("Module disk snapshot attributes unavailable or reparse point");
    out->identity = before;
    out->identity.update({{"module_base", Hex(reinterpret_cast<uintptr_t>(target.owner))},
        {"module_path", Utf8(target.path)}, {"mapped_path", Utf8(target.mappedPath)}, {"disk_sha256", hash},
        {"disk_handle_path", Utf8(std::wstring(finalPath.data(), finalLength))},
        {"hash_scope", "disk_file_at_actual_target_module_path_at_attestation_time"},
        {"hash_snapshot", "first_diagnostic_request"}, {"file_immutable_while_context_attestation_alive", true},
        {"memory_image_attested", false}, {"backing_section_file_identity_attested", false}});
    return out;
}

struct Observation
{
    Route route;
    uintptr_t called = 0;
    uint64_t result = 0;
    uint64_t count = 0;
    uintptr_t queryContext = 0;
    bool nullQuery = false;
};

struct ContextRecord
{
    Route route;
    uintptr_t key = 0;
    uint64_t generation = 0;
    std::array<TargetWitness, OperationCount> targets {};
    std::array<Observation, OperationCount> observed {};
    Observation nullQuery;
    std::string failure;
    std::shared_ptr<FileSnapshot> snapshot;
    ModuleFromAddress resolver = nullptr;
};

class Registry
{
    std::mutex mutex;
    std::map<uintptr_t, std::shared_ptr<ContextRecord>> contexts;
    std::map<std::pair<uintptr_t, uint64_t>, std::string> completed;
    std::atomic<uint64_t> generation {0};
    std::atomic<bool> witnessException {false};

    static Json TargetJson(const TargetWitness& target)
    {
        return {{"called_target", Hex(target.called)}, {"resolved_module_target", Hex(target.resolved)},
            {"module_base", Hex(reinterpret_cast<uintptr_t>(target.owner))},
            {"provenance", !target.owner ? "unavailable" : target.trampoline ? "tracked_detours_trampoline" : "module_owned"}};
    }

    static Json ObservationJson(const ContextRecord& record, const Observation& call, Operation operation)
    {
        Json target {{"called_target", Hex(call.called)}, {"resolved_module_target", nullptr},
            {"module_base", nullptr}, {"provenance", "unavailable"}};
        try { target = TargetJson(Witness(call.called, call.route.origins[operation], record.resolver)); }
        catch (const std::exception&) {} // An unknown actual target never borrows the frozen target's module.
        return {{"route", call.route.name}, {"selected_module_base", Hex(reinterpret_cast<uintptr_t>(call.route.selectedModule))},
            {"target", target}, {"called_target", Hex(call.called)}, {"return_code", call.result},
            {"count", call.count}, {"query_context_key", Hex(call.queryContext)}};
    }

    static void Validate(ContextRecord& record, const Observation& observed, Operation operation)
    {
        const auto& expected = record.targets[operation];
        if (observed.route.selectedModule != record.route.selectedModule ||
            std::string(observed.route.name) != record.route.name || observed.called != expected.called ||
            observed.route.origins[operation].resolvedTarget != record.route.origins[operation].resolvedTarget ||
            observed.route.origins[operation].committedTrampoline != record.route.origins[operation].committedTrampoline)
            throw std::runtime_error("Actual call route/target differs from frozen successful create route");
        const auto actual = Witness(observed.called, observed.route.origins[operation], record.resolver);
        if (actual.owner != expected.owner || actual.resolved != expected.resolved ||
            actual.path != expected.path || actual.mappedPath != expected.mappedPath)
            throw std::runtime_error("Actual call target module mapping changed since creation");
    }

    static void RecordObservation(ContextRecord& record, Operation operation, const Route& route, uintptr_t called,
        uint64_t result, bool nullQuery, uintptr_t queryContext)
    {
        auto& observed = nullQuery ? record.nullQuery : record.observed[operation];
        observed = {route, called, result, observed.count+1, queryContext, nullQuery};
        if (record.failure.empty() &&
            (route.selectedModule != record.route.selectedModule || std::string(route.name) != record.route.name ||
             called != record.route.calledTargets[operation] ||
             route.origins[operation].resolvedTarget != record.route.origins[operation].resolvedTarget ||
             route.origins[operation].committedTrampoline != record.route.origins[operation].committedTrampoline))
            record.failure = "Actual call route/target differs from frozen successful create route";
    }

  public:
    // Pointer/module-path witnesses are captured for every successful RR create,
    // including contexts created before the capture checkbox is enabled. No hash
    // or retained disk handle is acquired until Get() is requested.
    void Created(uintptr_t key, const Route& route, uint64_t result, ModuleFromAddress resolver) noexcept
    {
        try
        {
            // If allocation subsequently fails, an address reused for a new
            // context must never expose the old context's successful witness.
            { std::lock_guard lock(mutex); contexts.erase(key); }
            auto record = std::make_shared<ContextRecord>();
            record->key = key; record->route = route; record->resolver = resolver;
            record->generation = ++generation;
            record->observed[Create] = {route, route.calledTargets[Create], result, 1};
            try
            {
                for (size_t i = 0; i < OperationCount; ++i)
                    record->targets[i] = Witness(route.calledTargets[i], route.origins[i], resolver);
                const auto owner = record->targets[Create].owner;
                for (const auto& target : record->targets)
                    if (target.owner != owner) throw std::runtime_error("Frozen route targets span different image modules");
            }
            catch (const std::exception& error) { record->failure = error.what(); }
            std::lock_guard lock(mutex);
            contexts[key] = std::move(record);
        }
        catch (...) { witnessException = true; } // Never an SDK failure.
    }

    void Observe(uintptr_t key, Operation operation, const Route& route, uintptr_t called,
        uint64_t result, bool nullQuery = false, uintptr_t queryContext = 0) noexcept
    {
        try
        {
            std::lock_guard lock(mutex);
            const auto it = contexts.find(key);
            if (it == contexts.end()) return;
            // Scalar comparison per call; module mappings are checked at Get().
            RecordObservation(*it->second, operation, route, called, result, nullQuery, queryContext);
        }
        catch (...) { witnessException = true; }
    }

    void ObserveRetiring(const std::shared_ptr<ContextRecord>& record, const Route& route,
        uintptr_t called, uint64_t result) noexcept
    {
        if (!record) return;
        try { std::lock_guard lock(mutex); RecordObservation(*record, Destroy, route, called, result, false, 0); }
        catch (...) { witnessException = true; }
    }

    void Completed(const std::shared_ptr<ContextRecord>& record) noexcept
    {
        if (!record || !record->snapshot) return;
        try
        {
            std::lock_guard lock(mutex);
            const auto& call = record->observed[Destroy];
            Json out {{"schema_version", 1}, {"attested", record->failure.empty() && call.count > 0},
                {"failure", record->failure}, {"context_alive", false}, {"context_key", Hex(record->key)},
                {"context_generation", record->generation}, {"creation_route", record->route.name},
                {"implementation_identity", record->snapshot->identity},
                {"destroy", {{"route", call.route.name}, {"called_target", Hex(call.called)},
                    {"expected_target", TargetJson(record->targets[Destroy])},
                    {"return_code", call.result}, {"count", call.count}}}};
            completed[{record->key, record->generation}] = out.dump();
            while (completed.size() > 64) completed.erase(completed.begin());
        }
        catch (...) { witnessException = true; }
    }

    std::string Destroyed(uintptr_t key, uint64_t contextGeneration) noexcept
    {
        try
        {
            std::lock_guard lock(mutex);
            const auto it = completed.find({key, contextGeneration});
            if (witnessException || it == completed.end())
                return R"({"schema_version":1,"attested":false,"failure":"No completed diagnostic destroy witness"})";
            return it->second;
        }
        catch (...) { return {}; } // Allocation-free failure: caller rejects missing JSON.
    }

    std::shared_ptr<ContextRecord> Take(uintptr_t key) noexcept
    {
        try
        {
            std::lock_guard lock(mutex); const auto it = contexts.find(key);
            if (it == contexts.end()) return {};
            auto record = it->second; contexts.erase(it); return record;
        }
        catch (...) { witnessException = true; return {}; }
    }

    void Restore(const std::shared_ptr<ContextRecord>& record) noexcept
    {
        if (!record) return;
        try { std::lock_guard lock(mutex); contexts.try_emplace(record->key, record); }
        catch (...) { witnessException = true; }
    }

    // Diagnostic query uses a copy of the target captured by the successful
    // create. It never asks generic query routing to infer a module from a header.
    uintptr_t QueryTarget(uintptr_t key, Route& route) noexcept
    {
        try
        {
            std::lock_guard lock(mutex); const auto it = contexts.find(key);
            if (witnessException || it == contexts.end() || !it->second->failure.empty()) return 0;
            auto& record = *it->second;
            Observation frozen {record.route, record.route.calledTargets[Query]};
            try { Validate(record, frozen, Query); }
            catch (const std::exception& error) { record.failure = error.what(); return 0; }
            route = record.route; return route.calledTargets[Query];
        }
        catch (...) { witnessException = true; return 0; }
    }

    std::string Get(uintptr_t key) noexcept
    {
        try
        {
            std::lock_guard lock(mutex);
            if (witnessException)
                return R"({"schema_version":1,"attested":false,"failure":"A proxy witness operation raised an exception"})";
            const auto it = contexts.find(key);
            if (it == contexts.end())
                return R"({"schema_version":1,"attested":false,"failure":"No successful proxy RR create witness"})";
            auto& record = *it->second;
            Json targets = Json::object(), observed = Json::object();
            try
            {
                if (record.failure.empty())
                {
                    for (size_t i = 0; i < OperationCount; ++i)
                    {
                        Observation frozen {record.route, record.route.calledTargets[i]};
                        Validate(record, frozen, static_cast<Operation>(i));
                    }
                    if (!record.snapshot) record.snapshot = Snapshot(record.targets[Create]);
                }
                for (size_t i = 0; i < OperationCount; ++i)
                {
                    targets[OperationNames[i]] = TargetJson(record.targets[i]);
                    const auto& call = record.observed[i];
                    if (call.count)
                    {
                        if (record.failure.empty()) Validate(record, call, static_cast<Operation>(i));
                        observed[OperationNames[i]] = ObservationJson(record, call, static_cast<Operation>(i));
                    }
                }
                if (record.nullQuery.count)
                {
                    const auto& call = record.nullQuery;
                    if (record.failure.empty()) Validate(record, call, Query);
                    observed["null_query"] = ObservationJson(record, call, Query);
                }
            }
            catch (const std::exception& error) { record.failure = error.what(); }
            Json out {{"schema_version", 1}, {"attested", record.failure.empty() && bool(record.snapshot)},
                {"failure", record.failure}, {"context_key", Hex(record.key)}, {"context_generation", record.generation},
                {"context_alive", true},
                {"creation", {{"route", record.route.name}, {"selected_module_base", Hex(reinterpret_cast<uintptr_t>(record.route.selectedModule))},
                    {"implementation_identity", record.snapshot ? record.snapshot->identity : Json(nullptr)}, {"targets", targets}}},
                {"observed", observed}, {"provider_query_attested", false}, {"memory_image_attested", false}};
            return out.dump();
        }
        catch (...) { return {}; } // A second allocation failure must not terminate the game.
    }
};
}
