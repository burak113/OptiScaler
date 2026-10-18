"""General ROI GAME_TRACE loader (any origin/extent) + camera-based reprojection for that ROI."""
import json
from pathlib import Path
import numpy as np
ROOT = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE')
f32 = lambda w: np.array(w, np.uint32).view(np.float32)
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
class Cap:
    def __init__(s, uuid):
        s.dir = next(ROOT.glob(uuid+'*')); s.j = json.loads((s.dir/'capture.json').read_text()); s.frames = s.j['frames']
        s.n = s.j['manifest_published_frames']; r = s.j['roi']
        s.X0, s.Y0 = r['origin']; s.W, s.H = r['extent']; s.RW, s.RH = s.j['render_extent']
    def img(s, i, name, dt=np.float16, c=4):
        im = {x['name']: x for x in s.frames[i]['images']}[name]
        a = np.frombuffer((s.dir/im['file']).read_bytes(), dt)
        return a.reshape(s.H, s.W, c).astype(np.float32) if c > 1 else a.reshape(s.H, s.W)
    def rough(s, i, name='recovery_original_normal_roughness'):
        return (s.img(i, name, np.uint32, 1) >> 20) & 1023
    def camera(s, i):
        fp = s.frames[i]['frame_parameters']; cam = fp['camera']
        return f32(fp['camera_position']), f32(fp['previous_camera_position']), f32(cam['view']).reshape(4, 4), f32(cam['projection']).reshape(4, 4)
    def rgb(s, i, kind):
        if kind == 'rr': return s.img(i, 'selected_rr_diffuse')[..., :3] + s.img(i, 'selected_rr_specular')[..., :3]
        if kind == 'raw': return s.img(i, 'raw_rr_diffuse')[..., :3] + s.img(i, 'raw_rr_specular')[..., :3]
        return s.img(i, 'input_diffuse')[..., :3] + s.img(i, 'input_specular')[..., :3]
    def pix(s):
        yy, xx = np.mgrid[0:s.H, 0:s.W].astype(np.float64); return xx+s.X0+0.5, yy+s.Y0+0.5
    def world(s, V, P, z):
        px, py = s.pix(); nx, ny = px/s.RW*2-1, 1-py/s.RH*2
        d = np.stack([nx*z/P[0, 0], ny*z/P[1, 1], z], -1); Vi = np.linalg.inv(V.astype(np.float64))
        return d @ Vi[:3, :3].T + Vi[:3, 3]
    def project(s, V, P, X):
        xv = X @ V[:3, :3].T.astype(np.float64) + V[:3, 3]; z = xv[..., 2]
        nx, ny = P[0, 0]*xv[..., 0]/z, P[1, 1]*xv[..., 1]/z
        return (nx+1)/2*s.RW-s.X0-0.5, (1-ny)/2*s.RH-s.Y0-0.5, z
    def sample(s, img, qx, qy):
        x0 = np.floor(qx).astype(int); y0 = np.floor(qy).astype(int); fx = qx-x0; fy = qy-y0
        ok = (x0 >= 0) & (y0 >= 0) & (x0 < s.W-1) & (y0 < s.H-1)
        x0c, y0c = np.clip(x0, 0, s.W-2), np.clip(y0, 0, s.H-2)
        w = [((1-fx)*(1-fy)), (fx*(1-fy)), ((1-fx)*fy), (fx*fy)]
        v = [img[y0c, x0c], img[y0c, x0c+1], img[y0c+1, x0c], img[y0c+1, x0c+1]]
        if img.ndim == 3: w = [a[..., None] for a in w]
        return sum(a*b for a, b in zip(w, v)), ok
    def warp(s, a, t, img):
        """Bring frame t's image into frame a's view (camera reprojection with frame a's depth)."""
        _, _, Va, Pa = s.camera(a); z = s.img(a, 'input_depth', np.float32, 1).astype(np.float64)
        _, _, V, P = s.camera(t); qx, qy, _ = s.project(V, P, s.world(Va, Pa, z))
        return s.sample(img, qx, qy)
    def rotation(s):
        r = [0.0]
        for i in range(1, s.n):
            R0 = s.camera(i-1)[2][:3, :3]; R1 = s.camera(i)[2][:3, :3]
            r.append(float(np.degrees(np.arccos(np.clip((np.trace(R1 @ R0.T)-1)/2, -1, 1)))))
        return np.array(r)
