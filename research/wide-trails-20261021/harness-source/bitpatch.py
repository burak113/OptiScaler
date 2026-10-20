"""Minimal LLVM 3.7 / DXIL bitstream reader for surgical in-place operand patches.

Parses a DXBC container's DXIL part, walks every block with abbreviation support, numbers values like the LLVM reader
(module globals/functions -> module constants -> function constants -> value-producing instructions) and records the
bit position/width/encoding of every record operand so a single operand can be rewritten in place when its new
encoding has exactly the same bit length."""
import struct

class Bits:
    def __init__(s, data: bytearray, base_bit: int, end_bit: int):
        s.d = data; s.pos = base_bit; s.end = end_bit
    def read(s, n):
        if n == 0: return 0
        p = s.pos; b0 = p >> 3; b1 = (p + n + 7) >> 3
        v = int.from_bytes(s.d[b0:b1], 'little') >> (p & 7)
        s.pos += n; return v & ((1 << n) - 1)
    def vbr(s, n):
        start = s.pos; v = 0; shift = 0; hi = 1 << (n - 1)
        while True:
            c = s.read(n); v |= (c & (hi - 1)) << shift; shift += n - 1
            if not c & hi: return v, start, s.pos - start
    def align32(s): s.pos = (s.pos + 31) & ~31

def write_bits(d: bytearray, pos, width, value):
    for i in range(width):
        byte, bit = (pos + i) >> 3, (pos + i) & 7
        if (value >> i) & 1: d[byte] |= 1 << bit
        else: d[byte] &= ~(1 << bit) & 0xff

def vbr_encode(value, n):
    """Returns (bits as int, total width) of a VBR-n encoding."""
    hi = 1 << (n - 1); out = 0; w = 0
    while True:
        c = value & (hi - 1); value >>= n - 1
        if value: c |= hi
        out |= c << w; w += n
        if not value: return out, w

class Op:  # one decoded record operand
    __slots__ = ('value', 'pos', 'width', 'enc', 'n')
    def __init__(s, value, pos, width, enc, n): s.value, s.pos, s.width, s.enc, s.n = value, pos, width, enc, n

class Record:
    __slots__ = ('block', 'code', 'ops', 'abbrev', 'inst_id', 'value_id')
    def __init__(s, block, code, ops, abbrev): s.block, s.code, s.ops, s.abbrev = block, code, ops, abbrev; s.inst_id = s.value_id = None

def parse_module(data: bytearray, bit_start: int, bit_end: int):
    """Returns list of (block_id, depth, Record) in stream order."""
    b = Bits(data, bit_start, bit_end)
    magic = b.read(32)
    assert magic == 0xdec04342, hex(magic)  # 'BC' 0xC0DE
    blockinfo = {}; out = []
    def read_abbrev_def(b):
        n, _, _ = b.vbr(5); ops = []
        while len(ops) < n:
            if b.read(1): v, _, _ = b.vbr(8); ops.append(('lit', v))
            else:
                e = b.read(3)
                if e in (1, 2): w, _, _ = b.vbr(5); ops.append(('fixed' if e == 1 else 'vbr', w))
                elif e == 3: ops.append(('array', None))
                elif e == 4: ops.append(('char6', None))
                elif e == 5: ops.append(('blob', None))
                else: raise ValueError(e)
        return ops
    def read_scalar(b, op):
        kind, w = op
        if kind == 'lit': return Op(w, None, 0, 'lit', 0)
        if kind == 'fixed': p = b.pos; return Op(b.read(w), p, w, 'fixed', w)
        if kind == 'vbr': v, p, width = b.vbr(w); return Op(v, p, width, 'vbr', w)
        if kind == 'char6': p = b.pos; return Op(b.read(6), p, 6, 'char6', 6)
        raise ValueError(kind)
    def block(b, block_id, width, depth, end):
        abbrevs = list(blockinfo.get(block_id, [])); cur_bi = None
        while b.pos < end:
            aid = b.read(width)
            if aid == 0: b.align32(); return            # END_BLOCK
            if aid == 1:                                # ENTER_SUBBLOCK
                bid, _, _ = b.vbr(8); nw, _, _ = b.vbr(4); b.align32(); nwords = b.read(32)
                sub_end = b.pos + nwords * 32
                if bid == 0: blockinfo_block(b, nw, sub_end)
                else: block(b, bid, nw, depth + 1, sub_end)
                b.pos = sub_end; continue
            if aid == 2: abbrevs.append(read_abbrev_def(b)); continue
            if aid == 3:                                # UNABBREV_RECORD
                code, p, w = b.vbr(6); n, _, _ = b.vbr(6)
                ops = [b.vbr(6) for _ in range(n)]
                rec = Record(block_id, code, [Op(v, p2, w2, 'vbr', 6) for v, p2, w2 in ops], None)
                out.append((block_id, depth, rec)); continue
            ab = abbrevs[aid - 4]; vals = []; i = 0
            while i < len(ab):
                kind = ab[i][0]
                if kind == 'array':
                    n, _, _ = b.vbr(6); elt = ab[i + 1]
                    vals.extend(read_scalar(b, elt) for _ in range(n)); i += 2; continue
                if kind == 'blob':
                    n, _, _ = b.vbr(6); b.align32(); p = b.pos; b.pos += n * 8; b.align32()
                    vals.append(Op(bytes(data[p >> 3:(p >> 3) + n]), p, n * 8, 'blob', 0)); i += 1; continue
                vals.append(read_scalar(b, ab[i])); i += 1
            out.append((block_id, depth, Record(block_id, vals[0].value, vals[1:], aid)))
    def blockinfo_block(b, width, end):
        cur = None; abbrevs_local = []
        while b.pos < end:
            aid = b.read(width)
            if aid == 0: b.align32(); return
            if aid == 2: blockinfo.setdefault(cur, []).append(read_abbrev_def(b)); continue
            if aid == 3:
                code, _, _ = b.vbr(6); n, _, _ = b.vbr(6); ops = [b.vbr(6)[0] for _ in range(n)]
                if code == 1: cur = ops[0]       # SETBID
                continue
            raise ValueError('abbreviated record in BLOCKINFO')
    # top level: abbrev width 2
    while b.pos + 32 <= bit_end:
        aid = b.read(2)
        if aid != 1: break
        bid, _, _ = b.vbr(8); nw, _, _ = b.vbr(4); b.align32(); nwords = b.read(32); sub_end = b.pos + nwords * 32
        if bid == 0: blockinfo_block(b, nw, sub_end)
        else: block(b, bid, nw, 0, sub_end)
        b.pos = sub_end
    return out

CHAR6 = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._'
MODULE, PARAMATTR, CONSTANTS, FUNCTION, VST, TYPES = 8, 9, 11, 12, 14, 17
VALUE_INSTS = {2, 3, 4, 5, 6, 7, 8, 9, 16, 19, 20, 23, 26, 27, 28, 29, 30, 37, 38, 40, 41, 43, 46, 47}

def number_values(records):
    """Annotates records with value ids. Returns (values, types, names) where values[id] = (kind, info)."""
    types = []; values = []; names = {}; cur_type = None
    in_function = False; func_base = None
    for bid, depth, r in records:
        if bid == TYPES:
            if r.code not in (1, 19): types.append((r.code, [o.value for o in r.ops]))
        elif bid == MODULE:
            if r.code in (7, 8, 14, 9):   # GLOBALVAR, FUNCTION, ALIAS(new/old)
                r.value_id = len(values); values.append(('global', r.code, [o.value for o in r.ops]))
        elif bid == CONSTANTS:
            if r.code == 1: cur_type = r.ops[0].value
            else: r.value_id = len(values); values.append(('const', cur_type, r.code, [o.value for o in r.ops]))
        elif bid == VST and depth == 1:  # module-level symbol table
            if r.code in (1, 3):          # VST_ENTRY [id, chars] / VST_FNENTRY [id, offset, chars]
                chars = r.ops[1:] if r.code == 1 else r.ops[2:]
                names[r.ops[0].value] = ''.join(CHAR6[o.value] if o.enc == 'char6' else chr(o.value) for o in chars)
        elif bid == FUNCTION:
            if r.code == 1: continue      # DECLAREBLOCKS
            r.inst_id = len(values)
            produces = r.code in VALUE_INSTS
            if r.code == 34:              # CALL: [attr, cc, fnty, callee, args...] (explicit type)
                cc = r.ops[1].value; assert cc & (1 << 15), 'expected explicit-type CALL'
                fnty = types[r.ops[2].value]; assert fnty[0] == 21, fnty
                produces = types[fnty[1][1]][0] != 2   # FUNCTION: [vararg, retty, ...]; VOID code 2
            if produces: r.value_id = len(values); values.append(('inst', r.code, r))
    return values, types, names

def parse_container(blob: bytes):
    assert blob[:4] == b'DXBC'
    n = struct.unpack_from('<I', blob, 28)[0]
    parts = {}
    for k in range(n):
        off = struct.unpack_from('<I', blob, 32 + 4 * k)[0]
        parts[bytes(blob[off:off + 4])] = (off + 8, struct.unpack_from('<I', blob, off + 4)[0])
    return parts

def dxil_bitcode_range(blob: bytes):
    off, size = parse_container(blob)[b'DXIL']
    magic, ver, bc_off, bc_size = struct.unpack_from('<4I', blob, off + 8)
    assert magic == 0x4c495844, hex(magic)
    start = off + 8 + bc_off
    return start, bc_size
