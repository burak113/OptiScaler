"""DXIL/DXBC container digest (DXC ComputeHashRetail: MD5 rounds with the container-specific padding/length layout).
The digest sits at bytes 4..20 of the container and covers bytes 20..end."""
import struct
S = [7, 12, 17, 22]*4 + [5, 9, 14, 20]*4 + [4, 11, 16, 23]*4 + [6, 10, 15, 21]*4
import math
K = [int(abs(math.sin(i+1)) * 2**32) & 0xffffffff for i in range(64)]
def rol(x, c): x &= 0xffffffff; return ((x << c) | (x >> (32-c))) & 0xffffffff
def md5_block(state, x):
    a, b, c, d = state
    for i in range(64):
        if i < 16: f = (b & c) | (~b & d); g = i
        elif i < 32: f = (d & b) | (~d & c); g = (5*i+1) % 16
        elif i < 48: f = b ^ c ^ d; g = (3*i+5) % 16
        else: f = c ^ (b | ~d); g = (7*i) % 16
        f = (f + a + K[i] + x[g]) & 0xffffffff
        a, d, c = d, c, b; b = (b + rol(f, S[i])) & 0xffffffff
    return [(state[0]+a) & 0xffffffff, (state[1]+b) & 0xffffffff, (state[2]+c) & 0xffffffff, (state[3]+d) & 0xffffffff]
PADDING = bytes([0x80]) + bytes(63)
def hash_retail(data: bytes) -> bytes:
    n = len(data); left = n & 63
    if left < 56: pad = 56 - left; two = False
    else: pad = 120 - left; two = True
    N = (n + pad + 8) >> 6
    state = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476]
    end = N-2 if two else N-1
    for i in range(N):
        off = i*64
        if i == end and not two:
            rem = n - off
            blk = struct.pack('<I', n << 3) + data[off:off+rem] + PADDING[:pad] + struct.pack('<I', (1 | (n << 1)) & 0xffffffff)
        elif two and i == N-2:
            rem = n - off
            blk = data[off:off+rem] + PADDING[:pad-56]
        elif two and i == N-1:
            blk = struct.pack('<I', n << 3) + PADDING[pad-56:pad] + struct.pack('<I', (1 | (n << 1)) & 0xffffffff)
        else:
            blk = data[off:off+64]
        assert len(blk) == 64, (i, len(blk))
        state = md5_block(state, struct.unpack('<16I', blk))
    return struct.pack('<4I', *state)
def sign(container: bytearray) -> bytearray:
    container[4:20] = hash_retail(bytes(container[20:])); return container
if __name__ == '__main__':
    import sys, glob
    ok = bad = 0
    for p in sorted(glob.glob('F:/FSRD/amd_rr_reverse_20261018/dxil/*.dxil'))[:int(sys.argv[1]) if len(sys.argv) > 1 else 40]:
        b = open(p, 'rb').read()
        if hash_retail(b[20:]) == b[4:20]: ok += 1
        else: bad += 1; print('mismatch', p, b[4:20].hex(), hash_retail(b[20:]).hex())
    print('digest matches', ok, 'mismatches', bad)
