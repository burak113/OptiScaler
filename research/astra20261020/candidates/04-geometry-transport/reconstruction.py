"""CPU reference for support-certified reconstruction, NOT an RR estimator.

Coordinates are pixel-edge coordinates: texel (x,y) is at (x+.5,y+.5).
No colour, hit distance, material ID, or candidate output determines geometry.
The certificate is a required input contract. It is not present in the frozen
native gain texture and cannot be reconstructed from that texture alone.
"""
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Policy:
    cell: int = 8
    plane_absolute_tolerance: float = 1e-5
    plane_relative_tolerance: float = 1e-4
    normal_cosine: float = math.cos(math.radians(3.0))
    minimum_weight: float = 1e-8

    def __post_init__(self):
        if (isinstance(self.cell, (bool, np.bool_)) or
                not isinstance(self.cell, (int, np.integer)) or self.cell < 1):
            raise ValueError("cell must be a positive integer")
        values = (self.plane_absolute_tolerance, self.plane_relative_tolerance,
                  self.normal_cosine, self.minimum_weight)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("support policy values must be finite")
        if (self.plane_absolute_tolerance < 0 or self.plane_relative_tolerance < 0 or
                not 0 < self.normal_cosine <= 1 or not 0 <= self.minimum_weight < 1):
            raise ValueError("invalid support policy ranges")


@dataclass
class GeometryField:
    """Positions/normals in ONE declared camera or world basis, linear units.

    observed is a BASE-derived observation-domain mask; eligible is a separate
    BASE-derived correspondence/static/history mask. A zero/invalid normal or
    zero/invalid signed view depth is unknown, never a colour-derived fallback.
    For world-space positions, pass explicit depth instead of world position.z.
    """
    position: np.ndarray
    normal: np.ndarray
    observed: np.ndarray
    eligible: np.ndarray
    depth: np.ndarray | None = None


@dataclass
class CellSupport:
    position: np.ndarray
    normal: np.ndarray
    depth_scale: np.ndarray
    valid: np.ndarray
    observed_fraction: np.ndarray
    eligible_fraction: np.ndarray
    extent: tuple
    policy: Policy


@dataclass
class EstimatorSupport:
    """Certifies the actual NONZERO donor footprint, including recalled support.

    A caller must additionally certify temporal correspondence of every donor
    (donor_valid). This arithmetic cannot prove a key selection from absent keys.
    """
    cells: CellSupport
    valid: np.ndarray
    donor_count: np.ndarray
    kind: str


@dataclass
class Reconstruction:
    gain: np.ndarray
    support_mass: np.ndarray
    contributor_count: np.ndarray
    query_eligible: np.ndarray


def _geometry(field):
    p, n = np.asarray(field.position, float), np.asarray(field.normal, float)
    if p.ndim != 3 or p.shape[-1] != 3 or n.shape != p.shape:
        raise ValueError("position and normal must be matching H x W x 3")
    obs, eligible = np.asarray(field.observed), np.asarray(field.eligible)
    if obs.dtype.kind != "b" or eligible.dtype.kind != "b":
        raise ValueError("observation and eligibility masks must be Boolean")
    depth = p[..., 2] if field.depth is None else np.asarray(field.depth, float)
    if obs.shape != p.shape[:2] or eligible.shape != obs.shape or depth.shape != obs.shape:
        raise ValueError("mask/depth extent mismatch")
    with np.errstate(invalid="ignore",over="ignore"):
        length = np.linalg.norm(n, axis=-1)
    valid = (obs & np.isfinite(p).all(-1) & np.isfinite(n).all(-1) &
             np.isfinite(depth) & (np.abs(depth) > 1e-8) & np.isfinite(length) & (length > 1e-8))
    unit = np.zeros_like(n)
    np.divide(n, length[..., None], out=unit, where=valid[..., None])
    return (np.where(valid[...,None],p,0.), unit, np.where(valid,depth,0.),
            valid, eligible & valid)


def certify_cells(field, policy=Policy()):
    """Conservative full-cell certificate, including all 64 pixels at C8.

    Partial right/bottom cells are UNKNOWN. Four sparse bilinear measurements
    cannot certify a hidden one-pixel surface; hence every pixel is checked.
    This deliberately spends more support than the baseline Stats observes.
    """
    if policy.cell < 1 or not 0 < policy.normal_cosine <= 1:
        raise ValueError("invalid support policy")
    p, n, depth, observed, eligible = _geometry(field)
    h, w = observed.shape
    c = policy.cell
    gh, gw = max(1, (h + c - 1)//c), max(1, (w + c - 1)//c)
    centre = np.zeros((gh, gw, 3))
    normal = np.zeros_like(centre)
    scale = np.zeros((gh, gw))
    valid = np.zeros((gh, gw), bool)
    obs_fraction = np.zeros((gh, gw))
    eligible_fraction = np.zeros((gh, gw))
    for cy in range(gh):
        for cx in range(gw):
            yy, xx = slice(cy*c, min((cy+1)*c,h)), slice(cx*c,min((cx+1)*c,w))
            o, e = observed[yy,xx], eligible[yy,xx]
            obs_fraction[cy,cx], eligible_fraction[cy,cx] = o.sum()/(c*c), e.sum()/(c*c)
            if o.size != c*c or not o.all() or not e.all():
                continue
            pts, ns = p[yy,xx].reshape(-1,3), n[yy,xx].reshape(-1,3)
            nn = ns.mean(0)
            ln = np.linalg.norm(nn)
            if not ln > 1e-8:
                continue
            nn /= ln
            pp = pts.mean(0)
            ds = float(np.abs(depth[yy,xx]).max())
            tol = policy.plane_absolute_tolerance + policy.plane_relative_tolerance*ds
            pure = ((ns@nn >= policy.normal_cosine).all() and
                    (np.abs((pts-pp)@nn) <= tol).all())
            centre[cy,cx], normal[cy,cx], scale[cy,cx] = pp, nn, ds
            valid[cy,cx] = pure
    return CellSupport(centre, normal, scale, valid, obs_fraction,
                       eligible_fraction, (w,h), policy)


def local_estimator_support(cells, donor_valid):
    """For a gain computed ONLY from this certified cell and valid key support."""
    donor_valid = np.asarray(donor_valid)
    if donor_valid.dtype.kind != 'b' or donor_valid.shape != cells.valid.shape:
        raise ValueError("donor validity extent mismatch")
    valid = cells.valid & donor_valid
    return EstimatorSupport(cells, valid, valid.astype(np.int32), "local_exact_footprint")


def certify_estimator_support(cells, donor_weights, donor_valid, offsets):
    """Reject gain contaminated by any nonzero donor of a different surface.

    offsets is the ACTUAL estimator support, e.g. native +/-3 cells in x/y.
    Its edge-clamped repeated taps are preserved, but unknown cells remain
    invalid. This certificate does not repair contamination by renormalization.
    donor_valid must refer to valid original/recalled measurements, not gain!=1.
    """
    weights, dv = np.asarray(donor_weights,float), np.asarray(donor_valid)
    if dv.dtype.kind != 'b' or weights.shape != cells.valid.shape or dv.shape != weights.shape:
        raise ValueError("donor support extent mismatch")
    if not offsets:
        raise ValueError("the estimator footprint must be explicit")
    h,w = weights.shape
    yy,xx = np.mgrid[:h,:w]
    valid = cells.valid.copy()
    count = np.zeros((h,w),np.int32)
    for dx,dy in offsets:
        x,y = np.clip(xx+dx,0,w-1), np.clip(yy+dy,0,h-1)
        wt = weights[y,x]
        valid &= np.isfinite(wt) & (wt >= 0)
        uses = wt > 0
        count += uses
        pp,nn = cells.position[y,x], cells.normal[y,x]
        tol = (cells.policy.plane_absolute_tolerance + cells.policy.plane_relative_tolerance*
               np.maximum(cells.depth_scale,cells.depth_scale[y,x]))
        # Symmetric plane check avoids a tilted target admitting a parallel donor.
        delta = pp-cells.position
        same = ((np.sum(nn*cells.normal,axis=-1) >= cells.policy.normal_cosine) &
                (np.abs(np.sum(delta*cells.normal,axis=-1)) <= tol) &
                (np.abs(np.sum(delta*nn,axis=-1)) <= tol))
        valid &= ~uses | (cells.valid[y,x] & dv[y,x] & same)
    valid &= count > 0
    return EstimatorSupport(cells,valid,count,"all_nonzero_estimator_donors")


def _taps(h,w,gh,gw,cell,mode):
    y,x=np.mgrid[:h,:w]
    if mode == "physical":
        qx,qy=(x+.5)/cell-.5,(y+.5)/cell-.5
    elif mode == "normalized_baseline":
        qx,qy=(x+.5)*gw/w-.5,(y+.5)*gh/h-.5
    elif mode == "wrong_half_pixel":
        qx,qy=(x+1.)/cell-.5,(y+1.)/cell-.5
    else:
        raise ValueError("unknown coordinate mode")
    ix,iy=np.floor(qx).astype(int),np.floor(qy).astype(int)
    fx,fy=qx-ix,qy-iy
    for dx,dy,wt in ((0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),
                     (0,1,(1-fx)*fy),(1,1,fx*fy)):
        xx,yy=ix+dx,iy+dy
        inside=(xx>=0)&(xx<gw)&(yy>=0)&(yy<gh)
        # Safe array indexing only: inside always gates support; this is not a
        # claim that an out-of-grid coordinate belongs to the boundary texel.
        yield np.clip(xx,0,gw-1),np.clip(yy,0,gh-1),wt,inside


def bilinear_gain(gain, extent, cell=8, coordinate_mode="physical"):
    """Ordinary CLAMP bilinear negative control, with explicit grid mapping."""
    g=np.asarray(gain,float)
    if g.ndim != 2:
        raise ValueError("scalar coarse gain required")
    w,h=extent
    result=np.zeros((h,w))
    for x,y,wt,_ in _taps(h,w,*g.shape,cell,coordinate_mode):
        result+=wt*g[y,x]
    return result


def reconstruct(gain, support, query, *, enabled=True, method="supported",
                coordinate_mode="physical"):
    """Convex reconstruction of certified gains; unsupported output is identity.

    supported: discard unsupported taps and renormalize only their actual weight.
    hard: identity unless the entire positive-weight stencil is supported.
    support_mass is never renormalized: consumers can distinguish partial/full
    support. It MUST NOT be used to publish temporal history as fully observed.
    """
    g=np.asarray(gain,float)
    cells=support.cells
    if g.shape != cells.valid.shape or support.valid.shape != g.shape:
        raise ValueError("gain and certificate extent mismatch")
    p,n,d,obs,eligible=_geometry(query)
    h,w=obs.shape
    if (w,h) != cells.extent:
        raise ValueError("query active extent differs from certified extent")
    if method not in ("supported","hard"):
        raise ValueError("unknown reconstruction method")
    out=np.ones((h,w))
    mass=np.zeros((h,w))
    count=np.zeros((h,w),np.int32)
    if not enabled:
        return Reconstruction(out,mass,count,eligible)
    correction=np.zeros((h,w))
    complete=np.ones((h,w),bool)
    for x,y,wt,inside in _taps(h,w,*g.shape,cells.policy.cell,coordinate_mode):
        cn,cp=cells.normal[y,x],cells.position[y,x]
        delta=p-cp
        tol=(cells.policy.plane_absolute_tolerance + cells.policy.plane_relative_tolerance*
             np.maximum(np.abs(d),cells.depth_scale[y,x]))
        same=((np.sum(n*cn,axis=-1)>=cells.policy.normal_cosine)&
              (np.abs(np.sum(delta*cn,axis=-1))<=tol)&
              (np.abs(np.sum(delta*n,axis=-1))<=tol))
        accepted=(inside & eligible & support.valid[y,x] & same &
                  np.isfinite(g[y,x]) & (g[y,x]>=0) & (g[y,x]<=1))
        positive=wt>cells.policy.minimum_weight
        complete &= ~positive | accepted
        ww=np.where(accepted,wt,0.)
        mass+=ww
        count+=accepted&positive
        # np.where prevents 0*NaN from contaminating rejected contributions.
        correction+=ww*np.where(accepted,1-g[y,x],0.)
    use=mass>cells.policy.minimum_weight
    if method == "hard":
        use &= complete
    np.divide(correction,mass,out=correction,where=use)
    out[use]=1-correction[use]
    if method == "hard":
        mass[~use]=0
        count[~use]=0
    return Reconstruction(out,mass,count,eligible)


def apply_rgba(rgba, gain):
    """Reference multiplication; alpha payload and exact identity are preserved.

    This models NumPy nearest FP16 store if the source dtype is FP16, not D3D
    RTZ. Job01 owns numerical parity. No colour guide is changed or fed back.
    """
    src=np.asarray(rgba)
    g=np.asarray(gain)
    if src.ndim != 3 or src.shape[-1]!=4 or g.shape!=src.shape[:2]:
        raise ValueError("RGBA and gain extents differ")
    out=src.copy()
    changed=g!=1
    out[changed,:3]=(src[changed,:3].astype(np.float64)*g[changed,None]).astype(src.dtype)
    return out
