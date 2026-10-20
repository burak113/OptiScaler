"""Conservative mathematical history-publication contract, not a D3D12 wrapper.

This executable contract deliberately requires observed fence completion before
publication. An integration may permit ordered GPU consumers earlier only with
an explicit same-queue dependency/wait proof; recording on the CPU is never it.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy


@dataclass
class Capture:
    token: int
    epoch: int
    frame: int
    slot: int
    metadata: dict
    state: str = "scheduled"
    fence: int | None = None


class HistoryModel:
    """Six physical slots by default, each published with its own camera payload.

    The model owns copies of metadata. A stale epoch cannot publish even when
    its old GPU fence completes after a reset. Reserved slots cannot be reused
    while a submitted write remains in flight. A discard resets the whole
    generation, conservatively matching the native discard-history contract.
    """

    def __init__(self, ring_size=6):
        if not isinstance(ring_size, int) or ring_size < 1:
            raise ValueError("ring_size must be positive")
        self.ring_size = ring_size
        self.epoch = 0
        self.enabled = False
        self.last_frame = None
        self.current_frame = None
        self.extent = None
        self.write_slot = 0
        self.slots = [None]*ring_size
        self.captures = {}
        self._next_token = 1
        self.last_submitted_fence = 0
        self.completed_fence = 0
        self.reset_log = []

    def reset(self, reason):
        self.epoch += 1
        self.slots = [None]*self.ring_size
        self.write_slot = 0
        for capture in self.captures.values():
            if capture.state in ("scheduled", "submitted", "completed", "valid"):
                capture.state = "invalidated"
        self.reset_log.append({"frame": self.current_frame, "epoch": self.epoch, "reason": reason})

    def begin_frame(self, frame, extent, *, enabled=True, previous_camera_valid=True,
                    explicit_reset=False, camera_cut=False):
        if not isinstance(frame, int) or frame < 0:
            raise ValueError("frame must be a nonnegative integer")
        if self.last_frame is not None and frame <= self.last_frame:
            raise ValueError("unlooped chronology requires strictly increasing frame IDs")
        extent = tuple(extent)
        if len(extent) != 2 or min(extent) <= 0 or any(int(x) != x for x in extent):
            raise ValueError("extent must contain two positive integers")
        self.current_frame = frame
        reasons = []
        if enabled != self.enabled:
            reasons.append("option_toggle")
        if self.last_frame is not None and frame != self.last_frame+1:
            reasons.append("frame_gap")
        if self.extent is not None and extent != self.extent:
            reasons.append("DRS_extent_change")
        if not previous_camera_valid:
            reasons.append("invalid_previous_camera")
        if explicit_reset:
            reasons.append("explicit_reset")
        if camera_cut:
            reasons.append("camera_cut")
        if any(c.epoch == self.epoch and c.state == "scheduled" for c in self.captures.values()):
            reasons.append("unsubmitted_previous_graph")
        if reasons:
            self.reset(";".join(reasons))
        self.last_frame, self.extent, self.enabled = frame, extent, bool(enabled)
        return tuple(reasons)

    def schedule_capture(self, metadata):
        if not self.enabled or self.current_frame is None:
            raise RuntimeError("cannot schedule while disabled or before begin_frame")
        # Logical invalidation does not release physical write ownership. This
        # model reuses one physical bank: old-epoch fences still reserve slots.
        # An integration allocating another bank must track both banks' owners.
        if any(c.slot == self.write_slot and
               ((c.epoch == self.epoch and c.state == "scheduled") or
                (c.fence is not None and c.fence > self.completed_fence))
               for c in self.captures.values()):
            raise RuntimeError("physical slot still has an uncompleted write")
        token = self._next_token
        self._next_token += 1
        capture = Capture(token, self.epoch, self.current_frame, self.write_slot, deepcopy(metadata))
        self.captures[token] = capture
        # Conservatively retire the overwritten slot immediately. No camera for
        # the new capture is exposed until explicit successful publication.
        previous_token = self.slots[self.write_slot]
        if previous_token is not None:
            self.captures[previous_token].state = "retired"
        self.slots[self.write_slot] = None
        self.write_slot = (self.write_slot+1) % self.ring_size
        return token

    def _current(self, token):
        capture = self.captures[token]
        if capture.epoch != self.epoch or capture.state == "invalidated":
            raise RuntimeError("capture belongs to an invalidated generation")
        return capture

    def submit(self, token, fence):
        capture = self._current(token)
        if capture.state != "scheduled":
            raise RuntimeError("only a scheduled graph can be submitted once")
        if not isinstance(fence, int) or fence <= self.last_submitted_fence:
            raise ValueError("submission fence must be strictly increasing")
        capture.state, capture.fence = "submitted", fence
        self.last_submitted_fence = fence

    def complete(self, fence):
        if not isinstance(fence, int) or fence < self.completed_fence:
            raise ValueError("completion fence must be monotone")
        if fence > self.last_submitted_fence:
            raise ValueError("cannot complete a fence that was never submitted")
        self.completed_fence = fence
        for capture in self.captures.values():
            if (capture.epoch == self.epoch and capture.state == "submitted"
                    and capture.fence <= fence):
                capture.state = "completed"

    def publish(self, token):
        capture = self._current(token)
        if capture.state != "completed":
            raise RuntimeError("publication requires observed completion, not CPU recording")
        # A completed but unpublished slot might already have been scheduled for
        # a newer write. Never publish its old metadata over that newer owner.
        if any(c.epoch == self.epoch and c.slot == capture.slot and c.token > token
               and c.state != "invalidated" for c in self.captures.values()):
            raise RuntimeError("physical slot has a newer owner")
        old = self.slots[capture.slot]
        if old is not None:
            self.captures[old].state = "retired"
        self.slots[capture.slot] = token
        capture.state = "valid"

    def discard(self, token):
        capture = self._current(token)
        if capture.state != "scheduled":
            raise RuntimeError("only an unsubmitted graph can be discarded")
        self.reset("discarded_unsubmitted_graph")

    def valid_keys(self):
        """Return physical-slot-labelled copies, newest capture first."""
        keys = [deepcopy(self.captures[t]) for t in self.slots if t is not None]
        return sorted(keys, key=lambda c: c.frame, reverse=True)
