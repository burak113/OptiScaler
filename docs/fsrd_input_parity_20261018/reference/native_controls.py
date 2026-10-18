"""Captured native control suffix, cropped to ROI. Snapshot of turn/replay.py, 2026-10-18."""
import numpy as np
def controls(c, i, flags_hook=None):
    b = bytearray((c.dir/f'frames/{i}/provider_controls.bin').read_bytes()); a = np.frombuffer(b, np.float32).copy(); u = a.view(np.uint32)
    P = a[24:40].reshape(4, 4).astype(np.float64)              # row-vector convention: clip = v @ P
    ax, bx = c.RW/c.W, (c.RW-2*c.X0-c.W)/c.W                    # ndc_roi = a*ndc_full + b (x)
    ay, by = c.RH/c.H, (c.H-c.RH+2*c.Y0)/c.H                    # (y up)
    P[:, 0] = ax*P[:, 0]+bx*P[:, 3]; P[:, 1] = ay*P[:, 1]+by*P[:, 3]
    a[24:40] = P.astype(np.float32).ravel(); u[42], u[43] = c.W, c.H
    if flags_hook is not None: u[45] = flags_hook(c, i, int(u[45]))
    return a.tobytes()
