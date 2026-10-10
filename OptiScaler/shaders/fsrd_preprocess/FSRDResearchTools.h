#pragma once
#include <d3d12.h>
#include <DirectXMath.h>
#include <memory>
#include <string>
#include <vector>
#include <span>
#include <array>

class FSRDStageTimings;
namespace FSRDResearch
{
struct Input
{
    std::string name, key;
    ID3D12Resource* resource = nullptr;
    uint32_t x = 0, y = 0, width = 0, height = 0;
};
struct Row
{
    std::string name, status;
    uint32_t format = 0, width = 0, height = 0, x = 0, y = 0;
    bool bound = false, sampled = false;
    std::array<float,4> mean {}, maximum {}, nonzero {}, nonfinite {};
};
struct Status
{
    bool busy = false;
    uint32_t frames = 0, target = 0;
    std::string message = "No research capture requested.", folder;
    std::vector<Row> rows;
};
bool RequestProbe();
bool RequestReference(uint32_t frames);
void RequestStop();
bool WantsInputs();
bool ReferenceActive();
Status GetStatus();
class Session
{
    struct Impl;
    std::unique_ptr<Impl> impl;
public:
    Session();
    ~Session();
    void SetTimings(FSRDStageTimings*);
    void Begin(ID3D12Device*, ID3D12GraphicsCommandList*, std::span<const Input>,
               uint32_t width, uint32_t height, const DirectX::XMFLOAT4X4& camera, bool normal);
    void Finish(ID3D12GraphicsCommandList*, ID3D12Resource* finalColor,
                ID3D12Resource* linearDepth, ID3D12Resource* packedNormals,
                const std::string& settings, const std::string& controls);
    void Abort(const char* reason);
};
}
