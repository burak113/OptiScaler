"""Reproducible analytic transport measurements; no capture/GPU quality claim.

Run from any directory: python path/to/transport_experiment.py [--output DIR]
The root candidate runner may import run(output_directory).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from transport import (Camera, RasterDomain, Plane, perspective_col, view_from_pose,
                       project_world, unproject_pixels, surface_motion, motion_to_previous,
                       bilinear_sample, correspondence_support, visibility_order,
                       native_shader_view_position, native_key_depth, native_recall_depth_match,
                       mirror_virtual_point, construct_virtual_point, render_planes)
from history import HistoryModel


ROOT = Path(__file__).resolve().parent


def _summary(errors):
    errors = np.asarray(errors, dtype=np.float64).ravel()
    return {"count": int(errors.size), "max": float(np.max(errors)),
            "rms": float(np.sqrt(np.mean(errors*errors))),
            "median": float(np.median(errors)), "p95": float(np.quantile(errors, .95))}


def _camera(extent, hand, position, yaw, pitch, shift, aspect=1.):
    return Camera(view_from_pose(position, yaw, pitch),
                  perspective_col(extent, handedness=hand, pixel_aspect=aspect),
                  extent, hand, shift)


def _closed_form_project(world, *, extent, hand, position, yaw, pitch, shift, aspect=1.):
    """Independent scalar-component rigid-camera oracle; never calls Camera math."""
    d = np.asarray(world)-position
    y, p = np.deg2rad([yaw, pitch])
    x0 = np.cos(y)*d[..., 0]-np.sin(y)*d[..., 2]
    z0 = np.sin(y)*d[..., 0]+np.cos(y)*d[..., 2]
    vy = np.cos(p)*d[..., 1]+np.sin(p)*z0
    vz = -np.sin(p)*d[..., 1]+np.cos(p)*z0
    forward = vz*(1 if hand == "LH" else -1)
    fy = 1/np.tan(np.pi/6)
    fx = fy/(extent[0]*aspect/extent[1])
    qx = (1+fx*x0/forward)*extent[0]/2+shift[0]
    qy = (1-fy*vy/forward)*extent[1]/2+shift[1]
    return np.stack((qx, qy), axis=-1), vz


def correspondence_metrics():
    cases, all_errors, all_world_errors = [], [], []
    x, y = np.meshgrid(np.linspace(-1.1, 1.4, 11), np.linspace(-.8, .9, 7))
    for hand, sign in (("LH", 1), ("RH", -1)):
        for extent, previous_extent in (((137, 131), (137, 131)), ((83, 29), (83, 29)),
                                        ((137, 131), (101, 87)), ((83, 29), (47, 25))):
            for aspect in (1., 1.25):
                for scenario, previous_yaw, current_yaw, previous_pitch, current_pitch in (
                        ("translation", 0., 0., 0., 0.),
                        ("translation_rotation", -4., 7., -3., 2.)):
                    previous_pose = dict(extent=previous_extent, hand=hand, position=(.2, -.1, .1),
                                         yaw=previous_yaw, pitch=previous_pitch, shift=(-.19, .27), aspect=aspect)
                    current_pose = dict(extent=extent, hand=hand, position=(-.12, .03, -.08),
                                        yaw=current_yaw, pitch=current_pitch, shift=(.31, -.21), aspect=aspect)
                    current = _camera(**current_pose)
                    previous = _camera(**previous_pose)
                    world = np.stack((x, y, sign*(4+.1*x+.2*y)), axis=-1)
                    cur = project_world(world, current)
                    oracle_current, oracle_depth = _closed_form_project(world, **current_pose)
                    expected, _ = _closed_form_project(world, **previous_pose)
                    # Domains intentionally have crops and allocations unrelated to active sizes.
                    cur_domain = RasterDomain(extent, (256, 256), (11, 7), (extent[0]-20, extent[1]-12))
                    old_domain = RasterDomain(previous_extent, (256, 256), (3, 2),
                                              (previous_extent[0]-7, previous_extent[1]-6))
                    motion, valid = surface_motion(world, world, current, previous)
                    recalled = motion_to_previous(cur.pixel_xy-cur_domain.crop_origin, motion, cur_domain, old_domain)
                    errors = np.linalg.norm(recalled+old_domain.crop_origin-expected, axis=-1)
                    rebuilt, rebuilt_valid = unproject_pixels(oracle_current, oracle_depth, current)
                    world_errors = np.linalg.norm(rebuilt-world, axis=-1)
                    all_errors.extend(errors.ravel())
                    all_world_errors.extend(world_errors.ravel())
                    cases.append({"scenario": scenario, "handedness": hand, "current_extent": list(extent),
                                  "previous_extent": list(previous_extent), "allocation_extent": [256, 256],
                                  "current_crop_origin": [11, 7], "previous_crop_origin": [3, 2],
                                  "pixel_aspect": aspect, "point_count": int(errors.size),
                                  "valid_front_geometry_count": int(np.count_nonzero(valid & rebuilt_valid)),
                                  "current_oracle_projection_error_px": _summary(np.linalg.norm(cur.pixel_xy-oracle_current, axis=-1)),
                                  "true_correspondence_error_px": _summary(errors),
                                  "unprojection_world_error": _summary(world_errors)})
    return {"truth": "closed-form scalar-component rigid pose projection of fixed analytic world points",
            "motion_contract": "previous active UV minus current active UV, including raster shift",
            "scope": "geometric endpoints, not a claim that all projected points have observed ROI support",
            "true_correspondence_error_px": _summary(all_errors),
            "unprojection_world_error": _summary(all_world_errors), "cases": cases}


def phase_metrics():
    cases, errors = [], []
    # 32 phases per axis at quarter-pixel spacing, including full independent XY combinations.
    phase = np.arange(32)*.25
    px, py = np.meshgrid(phase, phase)
    points = np.stack((12+px, 12+py), axis=-1)
    for hand, sign in (("LH", 1), ("RH", -1)):
        for extent in ((137, 131), (83, 29)):
            camera = _camera(extent, hand, (1.2, -.3, .8), 11., -4., (.31, -.21), 1.3)
            depths = sign*(2+.003*points[..., 0]+.005*points[..., 1])
            world, valid = unproject_pixels(points, depths, camera)
            projected = project_world(world, camera)
            error = np.linalg.norm(projected.pixel_xy-points, axis=-1)
            errors.extend(error.ravel())
            cases.append({"handedness": hand, "extent": list(extent), "valid_count": int(np.count_nonzero(valid)),
                          "roundtrip_error_px": _summary(error)})
    return {"phase_step_px": .25, "phase_values": phase.tolist(), "cell_size_px": 8,
            "phase_xy_combinations_per_case": 1024, "roundtrip_error_px": _summary(errors), "cases": cases}


def support_metrics():
    extent = (81, 55)
    camera = _camera(extent, "LH", (0, 0, 0), 0, 0, (0, 0))
    focal = camera.projection_col[0, 0]*extent[0]/2
    half_width, shift = 1/focal, 6/focal
    wall = Plane((0, 0, 1), -8, 1)
    old_strip = Plane((0, 0, 1), -2, 2, (-half_width, -100, 1.9), (half_width, 100, 2.1))
    new_strip = Plane((0, 0, 1), -2, 2, (shift-half_width, -100, 1.9), (shift+half_width, 100, 2.1))
    old = render_planes(camera, [wall, old_strip])
    current = render_planes(camera, [wall, new_strip])
    previous_xy = current["pixel_xy"].copy()
    foreground = current["surface_id"] == 2
    previous_xy[..., 0][foreground] -= 3  # analytic object motion, exact integer endpoints
    depth = bilinear_sample(np.abs(old["depth"]), previous_xy)
    normal = bilinear_sample(old["normal"], previous_xy)
    old_ids = bilinear_sample(old["surface_id"], previous_xy)
    known = depth.valid & normal.valid & old_ids.valid
    accept = correspondence_support(np.abs(current["depth"]), depth.values, current["normal"], normal.values, known)
    identity_correct = old_ids.values == current["surface_id"]
    disoccluded = (old["surface_id"] == 2) & (current["surface_id"] == 1)
    order = visibility_order(np.abs(current["depth"]), depth.values, known)
    # Partial histories: endpoints outside the observation rectangle remain invalid.
    query = np.array([[.1, 4.5], [-2.5, 7.5], [18.9, 4.5], [21.5, 7.5], [9.5, 7.5]])
    sample = bilinear_sample(np.ones((15, 19)), query)
    truly_unknown = np.array([True, True, True, True, False])
    return {"scene": "one-pixel foreground strip at Z2 moving three pixels over static wall Z8",
            "extent": list(extent), "baseline_pixel_denominator": int(accept.size),
            "foreground_pixel_count": int(np.count_nonzero(foreground)),
            "genuine_disocclusion_pixel_count": int(np.count_nonzero(disoccluded)),
            "accepted_pixel_count": int(np.count_nonzero(accept)),
            "depth_normal_support_purity": float(np.count_nonzero(accept & identity_correct)/np.count_nonzero(accept)),
            "occlusion_leakage_count": int(np.count_nonzero(accept & disoccluded)),
            "occlusion_leakage_rate": float(np.mean(accept[disoccluded])),
            "expected_occlusion_order_count": int(np.count_nonzero((order == 2) & disoccluded)),
            "partial_domain_queries": query.tolist(), "partial_domain_known": sample.valid.tolist(),
            "partial_domain_weight_coverage": sample.coverage.tolist(),
            "unknown_query_count": int(np.count_nonzero(truly_unknown)),
            "invalid_to_valid_count": int(np.count_nonzero(truly_unknown & sample.valid)),
            "invalid_to_valid_rate": float(np.mean(sample.valid[truly_unknown])),
            "limitation": "exact analytic geometry and object motion; not a mixed-coarse-cell or captured-key purity claim"}


def native_witness_metrics():
    cases = []
    for hand, sign in (("LH", 1), ("RH", -1)):
        extent = (137, 131)
        camera = _camera(extent, hand, (0, 0, 0), 0, 0, (0, 0))
        x, y = np.meshgrid(np.arange(extent[0]//8)*8+4., np.arange(extent[1]//8)*8+4.)
        centres = np.stack((x, y), axis=-1)
        depths = sign*(2+.003*x+.005*y)
        view = native_shader_view_position(centres, depths, camera.projection_col, extent)
        delta = project_world(view, camera).pixel_xy-centres
        expected_clip_w = sign*depths
        absolute = native_recall_depth_match(native_key_depth(depths), expected_clip_w, sign)
        signed = native_recall_depth_match(depths, expected_clip_w, sign)
        cases.append({"handedness": hand, "extent": list(extent), "cell_count": int(depths.size),
                      "mean_signed_identity_phase_xy_px": np.mean(delta, axis=(0, 1)).tolist(),
                      "identity_correspondence_error_px": _summary(np.linalg.norm(delta, axis=-1)),
                      "absolute_key_match_count": int(np.count_nonzero(absolute)),
                      "signed_key_match_count": int(np.count_nonzero(signed)),
                      "signed_key_mismatch_count": int(np.count_nonzero(~signed))})
    return {"scope": "source-derived arithmetic witnesses; no GPU execution and no source change",
            "extra_half_pixel_is_separate_from_jitter": True, "cases": cases,
            "near_zero_native_tolerance_floor_accepts_stored_zero": bool(native_recall_depth_match(0., 1.1e-6, 1.)),
            "near_zero_caveat": "preserved baseline arithmetic; generic correspondence support rejects zero depth"}


def virtual_metrics():
    extent = (101, 71)
    current = _camera(extent, "LH", (.4, 0, 0), 0, 0, (0, 0))
    previous = _camera(extent, "LH", (0, 0, 0), 0, 0, (0, 0))
    real = np.array([1., 0, 2.])
    virtual = mirror_virtual_point(real, (0, 0, 1), (0, 0, 5))
    origin = np.array([.4, 0, 0])
    surface = origin+(virtual-origin)*(5/8)
    distance = np.linalg.norm(real-surface)
    estimate, valid = construct_virtual_point(surface, surface-origin, distance, observation_role="reflection_distance")
    surface_mv, _ = surface_motion(surface, surface, current, previous)
    virtual_mv, _ = surface_motion(virtual, virtual, current, previous)
    _, unsupported = construct_virtual_point(surface, surface-origin, distance, observation_role="surface_property")
    return {"scene": "planar mirror Z5; real point (1,0,2); virtual image (1,0,8); camera translates +.4X",
            "extent": list(extent), "surface_position_world": surface.tolist(), "virtual_position_world": virtual.tolist(),
            "usable_reflection_distance": float(distance), "reconstructed_virtual_point_valid": bool(valid),
            "virtual_reconstruction_error_world": float(np.linalg.norm(estimate-virtual)),
            "surface_motion_px": (surface_mv*extent).tolist(), "virtual_motion_px": (virtual_mv*extent).tolist(),
            "surface_vs_virtual_correspondence_error_px": float(np.linalg.norm((surface_mv-virtual_mv)*extent)),
            "surface_to_virtual_parallax_ratio": float(surface_mv[0]/virtual_mv[0]),
            "generic_surface_property_accepted_as_reflection_distance": bool(unsupported),
            "scope": "analytic planar mirror only; captured alpha/direction role remains unverified"}


def history_trajectory_metrics():
    model = HistoryModel()
    rows = []

    def observe(event, token=None, reasons=(), **details):
        physical_pending = [c.token for c in model.captures.values()
                            if c.fence is not None and c.fence > model.completed_fence]
        rows.append({"frame": model.current_frame, "event": event, "epoch": model.epoch,
                     "active_extent": list(model.extent), "enabled": model.enabled,
                     "reset_reasons": list(reasons), "token": token,
                     "capture_state": None if token is None else model.captures[token].state,
                     "capture_slot": None if token is None else model.captures[token].slot,
                     "valid_key_frames": [c.frame for c in model.valid_keys()],
                     "submitted_not_completed_tokens": physical_pending,
                     "completed_fence": model.completed_fence, **details})

    def begin(frame, extent=(137, 131), **kwargs):
        reasons = model.begin_frame(frame, extent, **kwargs)
        observe("begin_frame", reasons=reasons)

    def full_capture(fence):
        token = model.schedule_capture({"camera_frame": model.current_frame})
        observe("scheduled", token)
        model.submit(token, fence)
        observe("submitted", token)
        model.complete(fence)
        observe("completed", token)
        model.publish(token)
        observe("valid", token)
        return token

    begin(100, previous_camera_valid=False)
    full_capture(10)
    begin(101)
    full_capture(20)
    begin(102, explicit_reset=True)
    full_capture(30)
    begin(105)  # a real frame gap, never loop the clip
    full_capture(40)
    begin(106, (101, 87))
    full_capture(50)
    begin(107, (101, 87), enabled=False)
    begin(108, (101, 87), enabled=True)
    discarded = model.schedule_capture({"camera_frame": 108})
    observe("scheduled", discarded)
    model.discard(discarded)
    observe("discarded_unsubmitted", discarded)
    begin(109, (101, 87))
    old = model.schedule_capture({"camera_frame": 109})
    observe("scheduled", old)
    model.submit(old, 60)
    observe("submitted", old)
    begin(110, (101, 87), previous_camera_valid=False)
    blocked = False
    try:
        model.schedule_capture({"camera_frame": 110})
    except RuntimeError:
        blocked = True
    observe("physical_slot_reuse_attempt", old, blocked_by_uncompleted_fence=blocked)
    model.complete(60)
    observe("old_epoch_fence_completed", old)
    resurrected = False
    try:
        model.publish(old)
        resurrected = True
    except RuntimeError:
        pass
    observe("old_epoch_publication_attempt", old, old_metadata_resurrected=resurrected)
    full_capture(70)
    begin(111, (101, 87), camera_cut=True)
    full_capture(80)
    begin(112, (101, 87))
    unsubmitted = model.schedule_capture({"camera_frame": 112})
    observe("scheduled", unsubmitted)
    begin(113, (101, 87))  # previous scheduled graph has not been submitted
    full_capture(90)
    unique_frames = sorted(set(row["frame"] for row in rows))
    return {"scope": "CPU contract with one physical six-slot bank; no actual command lists/fences executed",
            "frame_ids": unique_frames, "unlooped_strictly_increasing_frame_ids": all(a < b for a, b in zip(unique_frames, unique_frames[1:])),
            "physical_slot_reuse_blocked_after_reset": blocked,
            "old_epoch_completion_resurrected_history": resurrected,
            "all_published_keys_have_matching_camera_frame": all(c.frame == c.metadata["camera_frame"] for c in model.valid_keys()),
            "reset_log": model.reset_log, "events": rows}


def run(output_directory=None,executor="direct CPU invocation"):
    output = Path(output_directory) if output_directory is not None else ROOT/"evidence"
    output.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "executor": executor,
              "implementation_author": "transport_implementation subagent",
              "evidence_class": "deterministic generated analytic scenes and source arithmetic witnesses",
              "gpu_executed": False, "captured_key_transport_executed": False,
              "base_tag": "astra-handoff-20261020", "resolved_base_commit": "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8",
              "dependency_numpy_version": np.__version__, "random_seeds": [],
              "source_sha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                for name in ("transport.py", "history.py", "transport_experiment.py")},
              "correspondence": correspondence_metrics(), "phase_sweep": phase_metrics(),
              "analytic_support": support_metrics(), "native_witnesses": native_witness_metrics(),
              "virtual_transport": virtual_metrics(), "history_trajectory": history_trajectory_metrics()}
    (output/"transport_metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"evidence")
    parser.add_argument("--executor", default="direct CPU invocation")
    args = parser.parse_args()
    result = run(args.output,args.executor)
    print(json.dumps({"output": str(args.output/"transport_metrics.json"),
                      "correspondence": result["correspondence"]["true_correspondence_error_px"],
                      "support_purity": result["analytic_support"]["depth_normal_support_purity"],
                      "occlusion_leakage_count": result["analytic_support"]["occlusion_leakage_count"],
                      "invalid_to_valid_count": result["analytic_support"]["invalid_to_valid_count"]}, indent=2))
