"""Read-only, published-only FRAME_SURVEY payload and provenance loader.

Survey ordinals are command-list recordings, not rendered frame identifiers.
Bindings are potential accesses; resource identity does not prove temporal equality.
No camera, albedo, shader register or unrecorded native input is synthesized.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

DEFAULT_IDS = (
    "3a443dbc5490c7708e2304aeb914d572", "fbb771d08b5e48b98f4954d45799f455",
    "8428f1ccbcc37b3d2f888d82890fb29d", "65a96b75fcf97c51322e80b81c6007a1",
    "3fa11b37280b94d622372f8168097cbb",
)
DEFAULT_ROOT = Path("F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY")
ROLE_HEADER = Path(__file__).resolve().parents[1] / "fsrd_preprocess/FSRDNrdDiscovery.h"
GUIDE_WRITER_SHA256 = "3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed"
PREPASS_SHA256 = "442e2282fcde781030081198a587d168d46b5ab9f89f79d6d6abcbf163b24d9e"


class ContractError(ValueError):
    pass


def writable_output(path: Path) -> None:
    resolved = str(path.resolve()).replace("\\", "/").casefold().rstrip("/")
    for forbidden in ("f:/ultra yedek 2", "f:/steamlibrary/steamapps/common/cyberpunk 2077"):
        if resolved == forbidden or resolved.startswith(forbidden + "/"):
            raise ContractError("Export destination is inside a protected game/capture tree")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    writable_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)  # Peers never see a partially rebuilt dataset index.


def roles_from_header(path: Path = ROLE_HEADER) -> dict[str, str]:
    values = dict(re.findall(r'\{"([a-f0-9]{64})",Role::(\w+)\}', path.read_text()))
    if len(values) != 10:
        raise ContractError("Expected the ten exact production ShaderRoles")
    return values


def payload_path(folder: Path, image: dict, ordinal: int) -> Path:
    relative = PurePosixPath(image["file"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
        raise ContractError("Payload path escapes its capture")
    if len(relative.parts) != 3 or relative.parts[:2] != ("frames", str(ordinal)):
        raise ContractError("Payload belongs to another recording ordinal")
    path = (folder / Path(*relative.parts)).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ContractError("Resolved payload escapes its capture")
    return path


def published_frames(manifest: dict) -> list[dict]:
    count = manifest.get("manifest_published_frames")
    if type(count) is not int or count < 0:
        raise ContractError("Missing or invalid manifest_published_frames")
    selected = [row for row in manifest.get("frames", [])
                if type(row.get("ordinal")) is int and 0 <= row["ordinal"] < count]
    if sorted(row["ordinal"] for row in selected) != list(range(count)):
        raise ContractError("Published ordinals are missing or duplicated")
    for row in selected:
        proof = row.get("ticket_proof", {})
        if not all(row.get(key) is True for key in (
                "cpu_snapshot_immutable", "gpu_submission_verified", "submission_gate_protected")):
            raise ContractError("Published row lacks immutable/submitted GPU proof")
        if any(proof.get(key) for key in ("invalid", "abandoned", "ambiguous_submission", "signal_failed")):
            raise ContractError("Published row has a failed or ambiguous ticket")
        if not proof.get("submitted") or proof.get("pending_signals", 1) != 0:
            raise ContractError("Published row has no completed submission")
        expected = proof.get("fence_expected")
        completed = proof.get("fence_completed")
        if type(expected) is not int or expected < 1 or type(completed) is not int or completed < expected:
            raise ContractError("Published row fence is incomplete")
    return sorted(selected, key=lambda row: row["ordinal"])


def validate_image(folder: Path, row: dict, image: dict, verify_hash: bool) -> dict:
    path = payload_path(folder, image, row["ordinal"])
    width, height = image["extent"]
    expected = width * height * image["bytes_per_pixel"]
    if min(width, height) < 1 or expected != image["bytes"] or path.stat().st_size != expected:
        raise ContractError("Payload length disagrees with packed extent and bytes_per_pixel")
    if image.get("storage") != "original_little_endian_gpu_words":
        raise ContractError("Unsupported payload storage")
    if verify_hash and sha256(path) != image["sha256"]:
        raise ContractError("Payload SHA256 mismatch")
    return dict(image, absolute_file=str(path), ordinal=row["ordinal"], list_id=row["list_id"],
                hash_verified=verify_hash, source_read_only=True)


def _pass_row(command_list: dict, row: dict, roles: dict[str, str]) -> dict:
    shader = row.get("pso", {}).get("shader_hashes", {}).get("CS")
    result = {key: row[key] for key in (
        "local_pass", "kind", "arguments", "pso", "root_signature_pointer",
        "root_signature_sha256", "binding_semantics", "unresolved", "targeted_snapshot",
        "root_constant_buffers") if key in row}
    result.update(list_id=command_list["id"], command_list=command_list.get("pointer"),
                  role=roles.get(shader), shader_sha256=shader,
                  reads=row.get("reads", []), writes=row.get("writes", []))
    return result


def _slot_rows(row: dict, access: str, root_parameter: int) -> list[dict]:
    values = [binding for binding in row.get(access, [])
              if binding.get("root_parameter") == root_parameter]
    if not values:
        return []
    indices = [binding.get("descriptor_index") for binding in values]
    if (any(type(index) is not int for index in indices) or len(indices) != len(set(indices))
            or len({value.get("descriptor_heap") for value in values}) != 1):
        return values
    minimum = min(indices)
    return [dict(binding, offset_from_lowest_observed_descriptor=binding["descriptor_index"] - minimum,
                 offset_scope="relative_observed_index_not_independent_shader_register_proof")
            for binding in sorted(values, key=lambda value: value["descriptor_index"])]


def analysis_sets(capture: dict) -> list[dict]:
    """Name the attested Recon profile; never borrow later/other-list snapshots."""
    results = []
    for recon in capture["nrd_passes"]:
        if recon["role"] != "Recon":
            continue
        srv = {v["offset_from_lowest_observed_descriptor"]: v for v in recon["root1_srv"]
               if "offset_from_lowest_observed_descriptor" in v}
        uav = {v["offset_from_lowest_observed_descriptor"]: v for v in recon["root5_uav"]
               if "offset_from_lowest_observed_descriptor" in v}
        if any(srv.get(i, {}).get("view_format") != fmt for i, fmt in enumerate((10, 10, 24, 41))):
            continue
        if any(uav.get(i, {}).get("view_format") != 10 for i in (0, 1)):
            continue
        def node(binding: dict, exact_pass: int | None = None, before: int | None = None) -> dict:
            matches = [row for row in capture["snapshots"] if row["list_id"] == recon["list_id"]
                       and row["resource"] == binding["resource"] and row.get("subresource", 0) == binding.get("subresource", 0)
                       and (exact_pass is None or row.get("writer_local_pass") == exact_pass)
                       and (before is None or row.get("writer_local_pass", before) < before)]
            latest = max(matches, key=lambda row: row.get("writer_local_pass", -1)) if matches else None
            return {"binding": binding, "snapshot": latest,
                    "payloads": latest["payloads"] if latest else [],
                    "state": "published_exact_writer_snapshot" if latest else "binding_metadata_only"}
        signals = {name: node(srv[offset], before=recon["local_pass"])
                   for offset, name in enumerate(("input_spec", "input_diff", "normal_roughness", "view_z"))}
        signals.update(recon_spec=node(uav[0], exact_pass=recon["local_pass"]),
                       recon_diff=node(uav[1], exact_pass=recon["local_pass"]))
        following = [row for row in capture["nrd_passes"] if row["list_id"] == recon["list_id"]
                     and row["local_pass"] > recon["local_pass"]]
        prepass = next((row for row in following if row["role"] == "PrePass"
                        and row.get("shader_sha256") == PREPASS_SHA256), None)
        if prepass:
            magnitude = next((v for v in prepass["root5_uav"]
                              if v.get("offset_from_lowest_observed_descriptor") == 2 and v["view_format"] == 41), None)
            if magnitude:
                signals["view_z_magnitude"] = node(magnitude, exact_pass=prepass["local_pass"])
                signals["view_z_magnitude"]["semantic_proof"] = {
                    "shader_sha256": PREPASS_SHA256,
                    "native_DXIL": "u2=max(abs(t3[threadID+cb6_rect_origin].R),9.999999974752427e-7)",
                    "scope": "Native PrePass output; original ViewZ sign is lost; rect-origin constants are not serialized"}
        temporal = next((row for row in following if row["role"] == "Temporal"), None)
        if temporal:
            motion = next((v for v in temporal["root1_srv"]
                           if v.get("offset_from_lowest_observed_descriptor") == 2 and v["view_format"] == 10), None)
            if motion:
                signals["motion"] = node(motion, before=temporal["local_pass"])
                signals["motion"]["candidate_tag_payloads_other_recordings"] = [
                    {"list_id": tag["list_id"], "source": tag["source_scope"], "payloads": tag["payloads"]}
                    for tag in capture["tags"] if tag.get("resource") == motion["resource"]
                    and tag["name"] == "MotionVectors" and tag["payloads"]]
        consumer = next((row for row in following if row["role"] == "Consumer"), None)
        if consumer:
            slots = {v["offset_from_lowest_observed_descriptor"]: v for v in consumer["root5_uav"]
                     if "offset_from_lowest_observed_descriptor" in v}
            for offset, name in ((0, "consumer_diff"), (1, "consumer_spec")):
                if slots.get(offset, {}).get("view_format") == 10:
                    signals[name] = node(slots[offset], exact_pass=consumer["local_pass"])
                    signals[name]["content_scope"] = "post_Consumer; RR_commit_contamination_possible; not_clean_native_reference"
        results.append({"list_id": recon["list_id"], "recon_pass": recon["local_pass"],
                        "temporal_pass": temporal["local_pass"] if temporal else None,
                        "consumer_pass": consumer["local_pass"] if consumer else None,
                        "slot_contract": "Production ChainDiscovery Recon root1+0..3/root5+0..1 and reversed Consumer outputs; observed descriptor minima, full shader SHA and formats checked",
                        "signals": signals,
                        "native_recon_pair_complete": bool(signals["recon_spec"]["payloads"] and signals["recon_diff"]["payloads"]),
                        "temporal_RR_replay_ready": False,
                        "temporal_scope": "No serialized camera/frame ID or complete consecutive input tuple; individual arrays remain usable"})
    return results


def index_capture(folder: Path, roles: dict[str, str], verify_hash: bool = True) -> dict:
    manifest_path = folder / "capture.json"
    before = manifest_path.stat()
    with manifest_path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema") != "fsrd-frame-survey-v1" or manifest.get("capture_uuid") != folder.name:
        raise ContractError("Capture identity/schema mismatch")
    frames = published_frames(manifest)
    images, frame_rows, shader_files = [], [], []
    shader_suffixes = {".cso", ".dxil", ".dxbc", ".asm", ".ll"}
    shader_files.extend(str(path) for path in folder.iterdir() if path.is_file() and path.suffix.lower() in shader_suffixes)
    for row in frames:
        frame_json = folder / "frames" / str(row["ordinal"]) / "frame.json"
        durable = json.loads(frame_json.read_text(encoding="utf-8"))
        if durable != row:
            raise ContractError("Published manifest and durable frame.json disagree")
        shader_files.extend(str(path) for path in frame_json.parent.iterdir()
                            if path.is_file() and path.suffix.lower() in shader_suffixes)
        frame_rows.append({key: value for key, value in row.items() if key != "images"})
        names = [image["name"] for image in row.get("images", [])]
        if len(names) != len(set(names)):
            raise ContractError("Duplicate payload name within a recording")
        images.extend(validate_image(folder, row, image, verify_hash) for image in row.get("images", []))
    image_by_key: dict[tuple, list] = {}
    for image in images:
        image_by_key.setdefault((image["list_id"], image["name"]), []).append(image)
    snapshots = []
    for row in manifest.get("snapshots", []):
        matches = image_by_key.get((row["list_id"], row["key"]), [])
        if matches:
            snapshots.append(dict(row, payloads=[image["file"] for image in matches]))
    snapshot_passes = {row.get("writer_local_pass") for row in snapshots}
    passes, nrd_passes, constants, catalog, guide_writers = [], [], [], [], []
    for command_list in manifest.get("command_lists", []):
        for row in command_list.get("passes", []):
            shader = row.get("pso", {}).get("shader_hashes", {}).get("CS")
            catalog.append({"list_id": command_list["id"], "local_pass": row["local_pass"],
                            "kind": row["kind"], "pso": row.get("pso"),
                            "root_signature_sha256": row.get("root_signature_sha256"),
                            "role": roles.get(shader),
                            "writes": sorted({v["resource"] for v in row.get("writes", [])})})
            if shader in roles or shader == GUIDE_WRITER_SHA256 or row.get("root_constant_buffers") or row["local_pass"] in snapshot_passes:
                entry = _pass_row(command_list, row, roles)
                passes.append(entry)
                if shader == GUIDE_WRITER_SHA256:
                    guide_writers.append(entry)
                if entry["role"]:
                    compact = dict(entry)
                    compact["root1_srv"] = _slot_rows(entry, "reads", 1)
                    compact["root5_uav"] = _slot_rows(entry, "writes", 5)
                    compact["root0_cbv_candidates"] = [v for v in entry["reads"]
                        if v.get("root_parameter") == 0 and v.get("kind") == 2]
                    # Full bindings remain in passes; common analysis stays small.
                    compact.pop("reads"); compact.pop("writes")
                    nrd_passes.append(compact)
                for cbv in row.get("root_constant_buffers", []):
                    matches = image_by_key.get((command_list["id"], cbv["snapshot_key"]), [])
                    if matches:
                        constants.append(dict(cbv, list_id=command_list["id"], local_pass=row["local_pass"],
                                              shader_sha256=shader, role=roles.get(shader),
                                              payloads=[image["file"] for image in matches]))
    tags = []
    for tag in manifest.get("tags", []):
        matches = image_by_key.get((tag["list_id"], tag.get("snapshot_key")), [])
        tags.append(dict(tag, payloads=[image["file"] for image in matches],
                         source_scope="Streamline" if tag.get("source") == "current_Streamline_tag_call" else "NGX"))
    after = manifest_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ContractError("Manifest changed while indexing")
    result = {key: manifest.get(key) for key in (
        "capture_uuid", "schema", "source", "phase", "complete", "manifest_published_frames",
        "committed_frames", "payload_ordinal_unit", "capture_start", "capture_end", "presents_in_window",
        "render_extent", "ordering", "snapshot_scope", "coverage_gaps", "errors", "evaluate_entries")}
    result.update(folder=str(folder.resolve()), manifest_bytes=before.st_size,
                  manifest_sha256=sha256(manifest_path), frames=frame_rows, images=images,
                  snapshots=snapshots, tags=tags, passes=passes, nrd_passes=nrd_passes,
                  pass_catalog=catalog, guide_writer_passes=guide_writers,
                  constants=constants, resources=manifest.get("resources", []),
                  batches=manifest.get("batches", []),
                  camera_snapshot_present=False, camera_scope="No serialized SL constants in this survey schema",
                  shader_payload_files_present=bool(shader_files), shader_payload_files=shader_files,
                  shader_payload_file_scope="capture_root_and_published_frame_directories_only",
                  consecutive_rendered_frames_proved=False,
                  contamination_policy="Targeted immediate post-pass snapshots precede coordinator AfterDispatch; Consumer snapshots may follow injected RR commit. Runtime setting is not serialized.")
    result["analysis_sets"] = analysis_sets(result)
    return result


def load_image(capture: dict, image: dict, interpretation: str | None = None):
    """Map original words read-only. Typeless32 needs an explicit interpretation."""
    import numpy as np
    formats = {10: ("<f2", 4), 34: ("<f2", 2), 41: ("<f4", 1),
               54: ("<f2", 1), 28: ("u1", 4), 29: ("u1", 4),
               49: ("u1", 2), 61: ("u1", 1), 0: ("u1", 1)}
    fmt = image["dxgi_format"]
    if fmt == 39 and interpretation not in ("r32f", "u32"):
        raise ContractError("R32_TYPELESS requires explicit r32f or u32 interpretation")
    if fmt in (24, 26):
        if interpretation != "u32":
            raise ContractError("Packed format requires explicit u32 words; do not assume float32 RGBA")
        dtype, channels = "<u4", 1
    elif fmt == 39:
        dtype, channels = ("<f4" if interpretation == "r32f" else "<u4"), 1
    elif fmt in formats:
        dtype, channels = formats[fmt]
    else:
        raise ContractError("Unsupported exact DXGI payload interpretation: " + str(fmt))
    if np.dtype(dtype).itemsize * channels != image["bytes_per_pixel"]:
        raise ContractError("DXGI component shape disagrees with native byte size")
    path = payload_path(Path(capture["folder"]), image, image["ordinal"])
    if path.stat().st_size != image["bytes"] or sha256(path) != image["sha256"]:
        raise ContractError("Payload changed after index publication")
    width, height = image["extent"]
    return np.memmap(path, mode="r", dtype=dtype, shape=(height, width, channels))


def export_crops(index: dict, output: Path, size: int = 256) -> dict:
    import numpy as np
    writable_output(output)
    if size < 1 or size > 512:
        raise ContractError("Crop size must be within the bounded 1..512 range")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for capture in index["captures"]:
        for image in capture["images"]:
            width, height = image["extent"]
            if height <= 1:
                continue
            interpretation = "r32f" if image["dxgi_format"] == 39 else "u32" if image["dxgi_format"] in (24, 26) else None
            source = load_image(capture, image, interpretation)
            x, y = max(0, (width - size) // 2), max(0, (height - size) // 2)
            crop = np.array(source[y:y + size, x:x + size], copy=True)
            relative = Path(capture["capture_uuid"]) / (image["name"] + ".npy")
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            np.save(destination, crop, allow_pickle=False)
            rows.append(dict(capture=capture["capture_uuid"], source=image["file"], source_sha256=image["sha256"],
                             crop_file=str(destination), crop_sha256=sha256(destination),
                             origin=[x, y], extent=[crop.shape[1], crop.shape[0]],
                             dtype=str(crop.dtype), channels=crop.shape[2], interpretation=interpretation))
            del source, crop
    result = {"schema": "fsrd-survey-crops-v1", "scope": "Exact center crops; no temporal pairing or inferred camera", "crops": rows}
    write_json(output / "crops.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--capture", action="append")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crops", type=Path)
    args = parser.parse_args()
    writable_output(args.output)
    if args.crops:
        writable_output(args.crops)
    role_map = roles_from_header()
    captures = []
    for identity in args.capture or DEFAULT_IDS:
        if not re.fullmatch("[0-9a-f]{32}", identity):
            raise ContractError("Expected an exact capture UUID")
        captures.append(index_capture(args.survey_root / identity, role_map))
        gc.collect()  # Only the compact result survives; never retain two large manifests.
    result = {"schema": "fsrd-survey-dataset-v1", "role_header": str(ROLE_HEADER),
              "role_header_sha256": sha256(ROLE_HEADER), "roles": role_map, "captures": captures,
              "scope": "Published recording ordinals only; exact original payloads; no invented temporal/camera equivalence"}
    write_json(args.output, result)
    crops = export_crops(result, args.crops) if args.crops else None
    print(json.dumps({"index": str(args.output), "captures": len(captures),
                      "published_recordings": sum(len(row["frames"]) for row in captures),
                      "payloads": sum(len(row["images"]) for row in captures),
                      "crops": len(crops["crops"]) if crops else 0}))


if __name__ == "__main__":
    main()
