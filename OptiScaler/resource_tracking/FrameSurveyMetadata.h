#pragma once
#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>

namespace FrameSurveyMetadata
{
// All reads are bounded by Size. PIX format strings are retained literally;
// printf pointer arguments are never dereferenced in the target process.
inline std::pair<std::string,std::string> DecodeMarker(uint32_t metadata, const void* data, size_t size)
{
    if (!data || !size) return {"","empty"};
    const auto* bytes = static_cast<const uint8_t*>(data);
    size = std::min<size_t>(size,4096);
    bool wide = metadata == 1; size_t offset = 0;
    std::string encoding = wide ? "UTF16" : "ANSI";
    if (metadata == 2)
    {
        if (size < 24) return {"","PIX_truncated"};
        uint64_t header = 0, info = 0; memcpy(&header,bytes,8);
        // Windows legacy GPU events: header, color, string info, string words.
        // V2 has a qword count in low 7 bits and ANSI/color bits in 12..19.
        if ((header & 127) && (header & 127)*8 <= size)
        {
            const uint32_t flags = uint32_t((header >> 12)&255);
            offset = 8 + ((flags&0xf0) == 0xf0 ? 8 : 0) + ((flags&1) ? 8 : 0);
            wide = (flags&2) == 0; encoding = "PIX_v2_format";
        }
        else
        {
            memcpy(&info,bytes+16,8);
            const uint64_t chunk = (info >> 55)&31;
            if (chunk != 8 && chunk != 16) return {"","PIX_unknown_string_info"};
            wide = ((info >> 54)&1) == 0;
            offset = 24 + ((info >> 60)&15); encoding = "PIX_legacy_format";
        }
    }
    else if (metadata > 2) return {"","unsupported_metadata"};
    if (offset >= size) return {"","truncated_string"};
    if (!wide)
    {
        const char* text = reinterpret_cast<const char*>(bytes+offset);
        size_t length = 0; while (length < size-offset && text[length]) ++length;
        const int count = MultiByteToWideChar(CP_ACP,0,text,int(length),nullptr,0);
        std::wstring unicode(count,L'\0');
        if (count) MultiByteToWideChar(CP_ACP,0,text,int(length),unicode.data(),count);
        const int utf8 = WideCharToMultiByte(CP_UTF8,0,unicode.data(),count,nullptr,0,nullptr,nullptr);
        std::string result(utf8,'\0');
        if (utf8) WideCharToMultiByte(CP_UTF8,0,unicode.data(),count,result.data(),utf8,nullptr,nullptr);
        return {std::move(result),encoding};
    }
    std::wstring unicode;
    for (size_t i=offset;i+1<size;i+=2)
    {
        uint16_t word = 0; memcpy(&word,bytes+i,2); if (!word) break;
        unicode.push_back(wchar_t(word));
    }
    const int count = WideCharToMultiByte(CP_UTF8,0,unicode.data(),int(unicode.size()),nullptr,0,nullptr,nullptr);
    std::string result(count,'\0');
    if (count) WideCharToMultiByte(CP_UTF8,0,unicode.data(),int(unicode.size()),result.data(),count,nullptr,nullptr);
    return {std::move(result),encoding};
}
inline bool CandidateExtent(uint64_t width, uint32_t height, uint32_t rw, uint32_t rh)
{
    for (uint32_t scale : {1u,2u,4u})
        if ((width == rw/scale || width == (rw+scale-1)/scale) &&
            (height == rh/scale || height == (rh+scale-1)/scale)) return true;
    return false;
}
}
