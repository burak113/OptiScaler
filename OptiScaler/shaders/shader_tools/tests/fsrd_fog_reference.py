"""Reference (numpy, float64) of the FSRD fog-consistent guides; all five production passes mirror it.

Pass 1  FSRDFogStats   (8x8 group per tile) original pair -> tile stats; reprojected EMA (rate 1/16)
        history A: Ls.rgb, age      B: Ld.rgb, Cbar (EMA of the tile mean radiance, luminance)
                C: N, D, S, logz    (sums over the tile: hp(C) P, P^2, hp(C)^2;  hp = minus the tile mean)
        per frame G: Qs mean (current pair).rgb, logz   H: Qd mean (current pair).rgb, valid fraction
Pass 2  FSRDFogKappa   (thread per tile) local 3x3-tent MAP estimate (prior 1, conservative bound) where the guides
        have texture, depth-aware wide estimate (no bound) where they do not
Pass 3  FSRDFogRank    (thread per tile) same-depth 5x5 median rejects isolated model failures
Pass 4  FSRDFogSmooth  (thread per tile) depth-aware Gaussian, sigma 3 tiles
Pass 5  FSRDFogRoute   (pixel) bilinear kappa; level-preserving per-lobe flattening toward a depth-aware 5x5-tile
        guide mean; with distance the fog share moves to the specular lobe with a neutral guide.
"""
import numpy as np

LUMA = np.array([.2126, .7152, .0722], np.float32)
FLOOR = 0.008
P = dict(rate=1 / 16, tau=.35, z=1.0, tau_fill=2.0, z_fill=0.0, fill_r=4, fill_zsig=.6, mass_local=144.0,
         sig0=.005, sig1=.015, rank_r=2, rank_percentile=50.0, rank_dz=.3, smooth_sigma=3.0, smooth_zsig=.6,
         near=8.0, far=60.0, target_zsig=.1, reproj_dz=.1)


def lum(x): return x @ LUMA


class FogGuides:
    def __init__(self, W, H, params=None):
        self.W, self.H = W, H; self.TW, self.TH = (W + 7) // 8, (H + 7) // 8
        self.p = dict(P); self.p.update(params or {})
        self.hist = None

    # ---------- helpers
    def tiles_sum(self, x):
        pad = np.zeros((self.TH * 8, self.TW * 8) + x.shape[2:], np.float64); pad[:self.H, :self.W] = x
        return pad.reshape(self.TH, 8, self.TW, 8, *x.shape[2:]).sum((1, 3))

    def tiles_count(self):
        return self.tiles_sum(np.ones((self.H, self.W)))

    def near(self, t): return np.repeat(np.repeat(t, 8, 0), 8, 1)[:self.H, :self.W]

    # ---------- pass 1
    def stats(self, orig, cur, depth, motion, reset, history_jitter_delta=(0.0, 0.0)):
        """Motion is unjittered previous-current UV; history_jitter_delta is Jprev-Jcur in pixels."""
        p = self.p; r = p["rate"]; F = FLOOR
        cnt = self.tiles_count()
        qs, qd, U, V = orig["qs"], orig["qd"], orig["U"], orig["V"]
        Rs = np.where(qs > F, U * qs, 0.0); Rd = np.where(qd > F, V * qd, 0.0)
        C = lum(Rs + Rd)
        ls = self.tiles_sum(U) / cnt[..., None]; ld = self.tiles_sum(V) / cnt[..., None]
        cbar = self.tiles_sum(C) / cnt
        z = np.abs(depth); zv = np.isfinite(z) & (z > 0)
        nz = self.tiles_sum(zv.astype(np.float64))
        logz = np.where(nz > 0, self.tiles_sum(np.where(zv, np.log(np.maximum(z, 1e-6)), 0.0)) / np.maximum(nz, 1), 0.0)
        # reprojection of the tile centre
        TH, TW, H, W = self.TH, self.TW, self.H, self.W
        ty, tx = np.mgrid[0:TH, 0:TW]; cy = np.minimum(ty * 8 + 4, H - 1); cx = np.minimum(tx * 8 + 4, W - 1)
        mv = motion[cy, cx]
        ppx = cx + .5 + mv[..., 0] * W + history_jitter_delta[0]
        ppy = cy + .5 + mv[..., 1] * H + history_jitter_delta[1]
        ptx, pty = np.floor(ppx / 8).astype(int), np.floor(ppy / 8).astype(int)
        ok = (not reset) & (self.hist is not None) & (ptx >= 0) & (ptx < TW) & (pty >= 0) & (pty < TH) & (mv[..., 3] > 0) & (nz > 0)
        if self.hist is not None:
            ptxc, ptyc = np.clip(ptx, 0, TW - 1), np.clip(pty, 0, TH - 1)
            A0, B0, C0 = (h[ptyc, ptxc] for h in self.hist)
            ok = ok & (A0[..., 3] > 0) & (np.abs(C0[..., 3] - logz) <= p["reproj_dz"])
        else:
            A0 = B0 = C0 = None
        okb = ok[..., None]
        Ls = np.where(okb, A0[..., :3] + r * (ls - A0[..., :3]), ls) if A0 is not None else ls
        Ld = np.where(okb, B0[..., :3] + r * (ld - B0[..., :3]), ld) if B0 is not None else ld
        Cb = np.where(ok, B0[..., 3] + r * (cbar - B0[..., 3]), cbar) if B0 is not None else cbar
        qsm = self.tiles_sum(qs) / cnt[..., None]; qdm = self.tiles_sum(qd) / cnt[..., None]
        Pp = lum(self.near(Ls) * (qs - self.near(qsm)) + self.near(Ld) * (qd - self.near(qdm)))
        Ch = C - self.near(cbar)
        n, d, s = self.tiles_sum(Ch * Pp), self.tiles_sum(Pp * Pp), self.tiles_sum(Ch * Ch)
        if C0 is not None:
            N = np.where(ok, C0[..., 0] + r * (n - C0[..., 0]), n); D = np.where(ok, C0[..., 1] + r * (d - C0[..., 1]), d)
            S = np.where(ok, C0[..., 2] + r * (s - C0[..., 2]), s)
            age = np.where(ok, np.minimum(A0[..., 3] + 1, 1 / r), 1.0)
        else:
            N, D, S, age = n, d, s, np.ones((TH, TW))
        age = np.where(nz > 0, age, 0.0)   # tiles without geometry hold no history
        A = np.concatenate([Ls, age[..., None]], -1); B = np.concatenate([Ld, Cb[..., None]], -1)
        Cst = np.stack([N, D, S, logz], -1)
        self.hist = (A, B, Cst)
        G = np.concatenate([self.tiles_sum(cur["qs"]) / cnt[..., None], logz[..., None]], -1)
        Hm = np.concatenate([self.tiles_sum(cur["qd"]) / cnt[..., None], (nz / cnt)[..., None]], -1)
        return A, B, Cst, G, Hm

    # ---------- pass 2
    def solve(self, N, D, S, age, mass, tau, z):
        k1 = N / np.maximum(D, 1e-30)
        s2 = np.maximum(S - k1 * N, 0) / mass
        w1 = np.maximum(age, 1) / np.maximum(s2, 1e-30)
        ip = 1 / tau ** 2
        P1 = D * w1 + ip
        m1 = (N * w1 + ip) / P1
        k = np.clip(m1 + z * np.sqrt(1 / P1), 0, 1)
        return np.where(np.isfinite(k), k, 1.0)

    def kappa(self, A, B, Cst):
        p = self.p; TH, TW = self.TH, self.TW
        N, D, S, logz = (Cst[..., i] for i in range(4)); age = A[..., 3]; Cb = B[..., 3]
        # local 3x3 tent (edge-normalised average of tile sums)
        def tent(t):
            pad = np.pad(t, 1); one = np.pad(np.ones((TH, TW)), 1); w = (1., 2., 1.); acc = np.zeros((TH, TW)); ws = np.zeros((TH, TW))
            for dy in range(3):
                for dx in range(3):
                    acc += w[dy] * w[dx] * pad[dy:dy + TH, dx:dx + TW]; ws += w[dy] * w[dx] * one[dy:dy + TH, dx:dx + TW]
            return acc / ws
        Nl, Dl, Sl, Rl = tent(N), tent(D), tent(S), tent(Cb)
        kl = self.solve(Nl, Dl, Sl, age, p["mass_local"], p["tau"], p["z"])
        # wide, depth-aware Gaussian sums
        r = p["fill_r"]; sig = r / 1.5
        acc = [np.zeros((TH, TW)) for _ in range(3)]
        pads = [np.pad(x, r) for x in (N, D, S)]; pz = np.pad(logz, r, mode="edge"); pm = np.pad((age > 0).astype(float), r)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                sl = (slice(r + dy, r + dy + TH), slice(r + dx, r + dx + TW))
                w = np.exp(-(dy * dy + dx * dx) / (2 * sig * sig)) * pm[sl] * np.exp(-((pz[sl] - logz) ** 2) / (2 * p["fill_zsig"] ** 2))
                for i in range(3): acc[i] += w * pads[i][sl]
        mass_w = 64.0 * 2 * np.pi * sig * sig
        kw = self.solve(acc[0], acc[1], acc[2], age, mass_w, p["tau_fill"], p["z_fill"])
        sigtex = np.sqrt(np.maximum(Dl, 0) / p["mass_local"]) / np.maximum(Rl, 1e-8)
        ws = np.clip((sigtex - p["sig0"]) / p["sig1"], 0, 1)
        k = ws * kl + (1 - ws) * kw
        return np.where(age > 0, k, 1.0)

    # ---------- pass 3
    def rank(self, k, logz, valid):
        """Percentile of valid same-depth neighbours; invalid tiles keep their own estimate."""
        p = self.p; TH, TW = self.TH, self.TW; r = int(np.clip(p["rank_r"], 0, 3))
        pk = np.pad(k, r, constant_values=0.0); pz = np.pad(logz, r, constant_values=0.0)
        pv = np.pad(valid, r, constant_values=False)
        values = []; count = np.zeros((TH, TW), np.int32)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                sl = (slice(r + dy, r + dy + TH), slice(r + dx, r + dx + TW))
                keep = pv[sl] & (np.abs(pz[sl] - logz) <= p["rank_dz"])
                count += keep
                values.append(np.where(keep, pk[sl], np.inf))
        ordered = np.sort(np.stack(values), axis=0)
        position = np.maximum(count - 1, 0) * np.clip(p["rank_percentile"] / 100.0, 0, 1)
        i0 = np.floor(position).astype(np.int32); i1 = np.minimum(i0 + 1, np.maximum(count - 1, 0))
        v0 = np.take_along_axis(ordered, i0[None], axis=0)[0]
        v1 = np.take_along_axis(ordered, i1[None], axis=0)[0]
        v0 = np.where(count > 0, v0, k); v1 = np.where(count > 0, v1, k)
        return np.where(valid & (count > 0), v0 + (v1 - v0) * (position - i0), k)

    # ---------- pass 4
    def smooth(self, k, logz, valid):
        p = self.p; TH, TW = self.TH, self.TW; sg = p["smooth_sigma"]; r = int(np.ceil(2 * sg))
        pk = np.pad(k, r, mode="edge"); pz = np.pad(logz, r, mode="edge"); pv = np.pad(valid.astype(float), r, mode="edge")
        acc = np.zeros((TH, TW)); ws = np.zeros((TH, TW))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                sl = (slice(r + dy, r + dy + TH), slice(r + dx, r + dx + TW))
                w = np.exp(-(dy * dy + dx * dx) / (2 * sg * sg)) * np.exp(-((pz[sl] - logz) ** 2) / (2 * p["smooth_zsig"] ** 2)) * np.maximum(pv[sl], 1e-3)
                acc += w * pk[sl]; ws += w
        return acc / ws

    # ---------- pass 5
    def upsample(self, t):
        H, W, TH, TW = self.H, self.W, self.TH, self.TW
        ys = (np.arange(H) + .5) / 8 - .5; xs = (np.arange(W) + .5) / 8 - .5
        y0 = np.floor(ys).astype(int); x0 = np.floor(xs).astype(int)
        fy = (ys - y0)[:, None]; fx = (xs - x0)[None, :]
        Y0, Y1 = np.clip(y0, 0, TH - 1), np.clip(y0 + 1, 0, TH - 1); X0, X1 = np.clip(x0, 0, TW - 1), np.clip(x0 + 1, 0, TW - 1)
        return t[Y0][:, X0] * (1 - fy) * (1 - fx) + t[Y0][:, X1] * (1 - fy) * fx + t[Y1][:, X0] * fy * (1 - fx) + t[Y1][:, X1] * fy * fx

    def targets(self, G, Hm, depth):
        """depth-aware 5x5-tile tent mean of the current pair's tile guide means."""
        H, W, TH, TW = self.H, self.W, self.TH, self.TW; p = self.p
        z = np.abs(depth); lz = np.where(np.isfinite(z) & (z > 0), np.log(np.maximum(z, 1e-6)), 0.0)
        yy, xx = np.mgrid[0:H, 0:W]
        py = (yy + .5) / 8 - .5; px = (xx + .5) / 8 - .5
        oy, ox = np.floor(py).astype(int), np.floor(px).astype(int)
        accs = np.zeros((H, W, 3)); accd = np.zeros((H, W, 3)); ws = np.zeros((H, W))
        for j in range(-2, 4):
            for i in range(-2, 4):
                ty, tx = oy + j, ox + i
                inb = (ty >= 0) & (ty < TH) & (tx >= 0) & (tx < TW)
                tyc, txc = np.clip(ty, 0, TH - 1), np.clip(tx, 0, TW - 1)
                g = np.clip(1 - np.abs(py - ty) / 3, 0, 1) * np.clip(1 - np.abs(px - tx) / 3, 0, 1)
                gz = np.exp(-((G[tyc, txc, 3] - lz) ** 2) / (2 * p["target_zsig"] ** 2))
                w = np.where(inb & (Hm[tyc, txc, 3] > 0), g * gz * Hm[tyc, txc, 3], 0.0)
                accs += w[..., None] * G[tyc, txc, :3]; accd += w[..., None] * Hm[tyc, txc, :3]; ws += w
        return accs, accd, ws

    def route(self, cur8, k, depth, G, Hm):
        """cur8: dict(qs8, qd8 uint8 rgb, U, V rgb). Returns new (qs8, qd8, U, V) rgb."""
        p = self.p; F = FLOOR
        qs8, qd8, U, V = cur8["qs8"], cur8["qd8"], cur8["U"], cur8["V"]
        qs, qd = qs8.astype(np.float32) / 255, qd8.astype(np.float32) / 255
        vs, vd = qs > F, qd > F
        Rs, Rd = np.where(vs, U * qs, 0.0), np.where(vd, V * qd, 0.0)
        K = k[..., None]
        z = np.abs(depth); zc = np.where(np.isfinite(z) & (z > 0), z, 1e9)
        w = np.clip(np.log(zc / p["near"]) / np.log(p["far"] / p["near"]), 0, 1)[..., None]
        accs, accd, ws = self.targets(G, Hm, depth)
        has = (ws > 1e-6)[..., None]
        Ts = np.where(has, accs / np.maximum(ws[..., None], 1e-12), qs); Td = np.where(has, accd / np.maximum(ws[..., None], 1e-12), qd)
        q1s = K * qs + (1 - K) * Ts; q1d = K * qd + (1 - K) * Td
        m = w * (1 - K)
        alld = np.all(vd, -1, keepdims=True)
        q1d_min = np.min(np.where(vd, q1d, 1.0), -1, keepdims=True)
        kd = (1 - m) * np.clip(((1 - m) * q1d_min - F) / F, 0, 1)
        kd = np.where(alld, kd, 1.0)
        qd_n = np.rint(np.clip(kd * q1d, 0, 1) * 255)
        keep = np.all(qd_n > F * 255, -1, keepdims=True) & (kd > 0)
        alone = ~alld
        Rd2 = np.where(alone, Rd, np.where(keep, kd * Rd, 0.0)); Mv = Rd - Rd2
        qs_n = np.rint(np.clip((1 - m) * q1s + m, 0, 1) * 255)
        can = np.all(qs_n > F * 255, -1, keepdims=True)
        unchanged = (K >= 1) | ~can
        U2 = np.where(unchanged, U, (Rs + Mv) / np.maximum(qs_n / 255, 1e-6))
        qd_out = np.where(alone, qd8.astype(np.float32), np.where(keep, qd_n, 0.0))
        V2 = np.where(unchanged, V, np.where(alone, V, np.where(keep, Rd2 / np.maximum(qd_n / 255, 1e-6), 0.0)))
        representable = (np.all(np.isfinite(U2), -1, keepdims=True) & np.all(np.isfinite(V2), -1, keepdims=True) &
                         np.all(np.abs(U2) <= 65504.0, -1, keepdims=True) & np.all(np.abs(V2) <= 65504.0, -1, keepdims=True))
        unchanged |= ~representable
        U2 = np.where(unchanged, U, U2); V2 = np.where(unchanged, V, V2)
        return (np.where(unchanged, qs8, qs_n).astype(np.uint8), np.where(unchanged, qd8, qd_out).astype(np.uint8),
                U2.astype(np.float32), V2.astype(np.float32))

    def frame(self, orig8, cur8, depth, motion, reset, history_jitter_delta=(0.0, 0.0)):
        f32 = lambda d: dict(qs=d["qs8"].astype(np.float32) / 255, qd=d["qd8"].astype(np.float32) / 255, U=d["U"], V=d["V"])
        A, B, Cst, G, Hm = self.stats(f32(orig8), f32(cur8), depth, motion, reset, history_jitter_delta)
        kr = self.kappa(A, B, Cst)
        km = self.rank(kr, Cst[..., 3], A[..., 3] > 0)
        ks = self.smooth(km, Cst[..., 3], A[..., 3] > 0)
        k = np.clip(self.upsample(ks), 0, 1)
        return self.route(cur8, k, depth, G, Hm), k
