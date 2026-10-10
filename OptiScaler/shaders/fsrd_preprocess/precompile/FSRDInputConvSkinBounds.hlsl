#define FSRD_SKIN_ENABLED 1
#ifndef FSRD_SKIN_BOUNDS_ENABLED
#define FSRD_SKIN_BOUNDS_ENABLED 1
#endif
#include "FSRDSkinConversion.hlsli"
#if FSRD_SKIN_BOUNDS_ENABLED
#define FSRD_SKIN_ROOT "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=21)), DescriptorTable(UAV(u0, numDescriptors=11))"
#else
#define FSRD_SKIN_ROOT "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=21)), DescriptorTable(UAV(u0, numDescriptors=10))"
#endif
#include "FSRDInputConv.hlsl"
