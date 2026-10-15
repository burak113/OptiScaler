"""Nominal D07/WP10 memory arithmetic for the separate lobe recovery plan.

Ek B of NRD_Bridge_Takip_Raporu_bdab0c01.md recomputed from the S1 formulas
only. Every value is a LOGICAL TEXEL PAYLOAD in bytes with GiB=2**30; it is
not a padded D3D allocation, not a provider cost and not resident VRAM. The
staging-row numbers share the same caveat. No game, D3D12 or repository state
is consulted.
"""
from dataclasses import dataclass
import math

GIB = 2**30
MIB = 2**20
GRAPH_BYTE_LIMIT = 2 * GIB  # LobeRecovery::Family::GraphByteLimit (nominal planning cap)
STAGING_SLOT_LIMIT = 32     # Context staging capacity, unretired recordings per context
STAGING_WARM_SLOTS = 4      # Initialized warm pairs per context


@dataclass(frozen=True)
class PlanBytes:
    """Named plan classes of one full recovery graph plus its staging slot."""
    full: int
    mixed: int
    staging_slot: int


def payload_bytes(width: int, height: int) -> PlanBytes:
    """S1/Recovery and staging nominal payload formulas at one internal size.

    w[l+1] = ceil(w[l]/2), N[l] = w[l]*h[l]
    Full  = 144*N0 + 48*sum(N0..N6) + 64*sum(N0..N5)
    Mixed =  96*N0 + 24*sum(N0..N6) + 48*sum(N0..N5)
    Staging slot = 16 * width * height  (two RGBA16 outputs per slot)
    """
    if type(width) is not int or type(height) is not int:
        raise TypeError("width and height must be integers")
    if width <= 0 or height <= 0:
        raise ValueError("positive internal render extent required")
    pixels = []
    w, h = width, height
    for _ in range(7):
        pixels.append(w * h)
        w, h = (w + 1) // 2, (h + 1) // 2
    return PlanBytes(
        full=144 * pixels[0] + 48 * sum(pixels) + 64 * sum(pixels[:-1]),
        mixed=96 * pixels[0] + 24 * sum(pixels) + 48 * sum(pixels[:-1]),
        staging_slot=16 * width * height,
    )


def graph_texture_plan_count() -> int:
    """55 planned textures of FSRDNrdLobeRecovery_Dx12::CreateContext.

    history 2 inputs *4, pyramid 7 levels *3, noise 2 lobes *6 levels,
    correction 2 lobes *6 levels, owned outputs 2. This ties the nominal
    model to the actual plan shape without touching native code.
    """
    history, pyramid, noise, correction, outputs = 2 * 4, 7 * 3, 2 * 6, 2 * 6, 2
    return history + pyramid + noise + correction + outputs


def chain_plan(name: str, chains: int, width: int, height: int) -> int:
    """Two-chain (A+B) nominal selection input. 'full' or 'mixed'."""
    plan = payload_bytes(width, height)
    total = getattr(plan, name)
    if chains <= 0:
        raise ValueError("chains must be positive")
    return chains * total


def crosses_plan_limit(name: str, chains: int, width: int, height: int,
                       limit: int = GRAPH_BYTE_LIMIT) -> bool:
    """True when the nominal payload alone already exceeds the shared cap.

    Passing this predicate proves a plan CANNOT fit the cap; failing it says
    nothing decisive about real allocation, retention or residency.
    """
    return chain_plan(name, chains, width, height) > limit


def staging_bytes(width: int, height: int, slots: int,
                  debug_targets_per_slot: int = 0) -> int:
    """Nominal staging ledger input, resolution-aware.

    slot = two RGBA16 outputs (16 B/px); one optional native debug RGBA16
    target participates in the same ledger class when debug is enabled.
    """
    if type(slots) is not int or slots <= 0 or slots > STAGING_SLOT_LIMIT:
        raise ValueError("staging slots must be within1..32")
    slot = 16 * width * height * (1 + debug_targets_per_slot)
    return slot * slots


class StagingByteLedgerModel:
    """Sequential model of NrdBridge::Context's shared staging byte ledger.

    Mirrors the host ledger contract (metadata-only atomics; no GPU state):
    admission counts current retained bytes plus the candidate slot, a 0
    limit disables byte admission, retirement always returns the exact
    admitted bytes, and the retained high-water observed peak is recorded.
    """

    def __init__(self, limit: int, width: int, height: int,
                 debug_targets_per_slot: int = 0):
        if limit < 0:
            raise ValueError("ledger limit cannot be negative")
        self.limit = limit
        self.slot = 16 * width * height * (1 + debug_targets_per_slot)
        if not self.slot:
            raise ValueError("slot payload must be positive")
        if limit and self.slot > limit:
            raise ValueError("one slot already exceeds the whole ledger limit")
        self.retained = 0
        self.retired_total = 0
        self.retained_peak = 0
        self.rejected = 0

    def admit(self, slots: int) -> bool:
        if self.limit and self.slot * (self.retained_slots() + slots) > self.limit:
            self.rejected += 1
            return False
        self.retained += self.slot * slots
        self.retained_peak = max(self.retained_peak, self.retained)
        return True

    def retained_slots(self) -> int:
        return self.retained // self.slot if self.slot else 0

    def retire(self, slots: int) -> bool:
        if slots <= 0 or self.slot * (self.retained_slots() - slots) < 0:
            return False
        self.retired_total += self.slot * slots
        self.retained -= self.slot * slots
        return True

    @property
    def byte_admission_active(self) -> bool:
        return self.limit != 0


def summary_table() -> dict:
    """Reproducible arithmetic snapshot for reports (logical payload only)."""
    rows: dict = {}
    for width, height in ((1505, 847), (1920, 1080), (2560, 1440), (3840, 2160)):
        plan = payload_bytes(width, height)
        rows[f"{width}x{height}"] = {
            "full_single": plan.full,
            "full_chain_ab": 2 * plan.full,
            "mixed_single": plan.mixed,
            "mixed_chain_ab": 2 * plan.mixed,
            "staging_slot_mib": round(plan.staging_slot / MIB, 6),
            "staging4_mib": round(plan.staging_slot * STAGING_WARM_SLOTS / MIB, 6),
            "staging32_mib": round(plan.staging_slot * STAGING_SLOT_LIMIT / MIB, 6),
            "full_single_gib": round(plan.full / GIB, 6),
            "full_chain_ab_gib": round(2 * plan.full / GIB, 6),
            "mixed_single_gib": round(plan.mixed / GIB, 6),
            "mixed_chain_ab_gib": round(2 * plan.mixed / GIB, 6),
        }
    rows["graph_texture_plan_count"] = graph_texture_plan_count()
    rows["graph_byte_limit"] = GRAPH_BYTE_LIMIT
    return rows


# Exact values asserted by the tests; S1's KiB-rounded table cells reproduce
# these formula results (no discrepancy was found).
S1_FULL_GIB = {
    (1505, 847): 0.348325, (1920, 1080): 0.566443,
    (2560, 1440): 1.006996, (3840, 2160): 2.265746,
}
S1_MIXED_GIB = {
    (1505, 847): 0.227991, (1920, 1080): 0.370760,
    (2560, 1440): 0.659120, (3840, 2160): 1.483023,
}
S1_STAGING_MIB = {(1505, 847): 19.451, (1920, 1080): 31.641,
                  (2560, 1440): 56.250, (3840, 2160): 126.562}
