"""Actual adaptive recorder prefix plus fail-closed CPU metadata controls."""
from pathlib import Path
import copy
import hashlib
import json
import struct
from fsrd_nrd_trace_replay import inspect_capture


def exercise_adaptive(source, legacy_source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((source / "capture.json").read_text(encoding="utf-8-sig"))
    legacy = json.loads((Path(legacy_source) / "capture.json").read_text(encoding="utf-8-sig"))
    checks = []
    def check(condition, name):
        assert condition, name
        checks.append(name)
    def digest(settings):
        return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    def rehash(manifest):
        for frame in manifest["frames"][:manifest["manifest_published_frames"]]:
            frame["settings_sha256"] = digest(frame["settings"])
            if frame["settings"].get("motion_stability", {}).get("enabled") is True:
                normalized = copy.deepcopy(frame["settings"])
                normalized["provider_effective"][1] = normalized["motion_stability"]["moving"]
                frame["settings_lineage_sha256"] = digest(normalized)
    def write(manifest):
        (output / "capture.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    def rejected(name, mutate, base=original):
        manifest = copy.deepcopy(base)
        mutate(manifest)
        write(manifest)
        try:
            inspect_capture(output, verify_payload=False)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError("invalid adaptive trace accepted: " + name)
    def settings_change(manifest, change):
        change(manifest["frames"][1]["settings"])
        rehash(manifest)
    def word(value):
        return struct.unpack("<I", struct.pack("<f", value))[0]
    actual = inspect_capture(source)
    check(actual["published_frames"] == 3 and len(actual["frames"]) == 3, "actual_three_frame_G2_prefix_verified")
    check([f["settings"]["provider_effective"][1] for f in actual["frames"]]
          == [f["settings"]["provider_effective"][1] for f in original["frames"][:3]], "exact_runtime_key2_words_retained")
    check(len({f["settings"]["provider_effective"][1] for f in actual["frames"]}) == 3, "actual_ramp_has_three_values")
    check(not actual["full_temporal_replay_eligible"] and "adaptive_key2_requires_per_frame_tuning_replay" in actual["ineligibility_reasons"],
          "legacy_native_replay_cannot_silently_use_first_key2")
    fixed = copy.deepcopy(original)
    for f in fixed["frames"][:3]:
        f["settings"]["provider_effective"][1] = fixed["frames"][0]["settings"]["provider_effective"][1]
    rehash(fixed);write(fixed)
    check(len(inspect_capture(output, verify_payload=False)["frames"]) == 3, "constant_G2_key2_prefix_accepted")
    def malformed_policy(manifest, bad):
        for frame in manifest["frames"][:3]:
            frame["settings"]["motion_stability"] = bad
            frame["settings"]["provider_effective"][1] = word(.5)
            frame.pop("settings_lineage_sha256", None)
            frame["settings_sha256"] = digest(frame["settings"])
    for bad in (None, [], 0, "enabled"):
        rejected("malformed_policy_"+str(bad), lambda m,b=bad:malformed_policy(m,b))
    def malformed_lighting(manifest, bad):
        for frame in manifest["frames"][:3]:frame["settings"]["lighting_validation"] = bad
        rehash(manifest)
    for bad in (None, [], True, 0, "enabled", {"enabled": True}):
        rejected("malformed_lighting_"+str(bad),lambda m,b=bad:malformed_lighting(m,b))
    for field in ("rotation_degrees", "translation_units"):
        for bad in (True, -1, 1<<32, .5, word(0), word(float("nan")), word(float("inf")), word(181)):
            policy={"enabled":True,"rotation_degrees":word(.1),"translation_units":word(.0015)}
            policy[field]=bad
            rejected("invalid_lighting_"+field+"_"+str(bad),lambda m,b=policy:malformed_lighting(m,b))
    lighting_only=copy.deepcopy(original)
    for frame in lighting_only["frames"][:3]:
        frame["settings"].pop("motion_stability")
        frame["settings"]["provider_effective"][1]=word(.5)
        frame.pop("settings_lineage_sha256",None)
    rehash(lighting_only);write(lighting_only)
    check(len(inspect_capture(output,verify_payload=False)["frames"])==3,"CPU_G3_only_policy_prefix_accepted")
    for field,value in (("rotation_degrees",.2),("translation_units",.002)):
        rejected("G3_only_threshold_change_"+field,lambda m,k=field,v=value:settings_change(m,lambda s:s["lighting_validation"].update({k:word(v)})),lighting_only)
    rejected("full_hash_tamper", lambda m: m["frames"][1].update(settings_sha256="0"*64))
    for bad in (None, "0"*64, 17, "A"*64):
        rejected("bad_lineage_"+str(bad), lambda m,b=bad: m["frames"][1].update(settings_lineage_sha256=b))
    rejected("missing_lineage", lambda m: m["frames"][1].pop("settings_lineage_sha256"))
    rejected("other_effective_key_changes", lambda m: settings_change(m,lambda s:s["provider_effective"].__setitem__(0,word(.75))))
    rejected("requested_key_changes", lambda m: settings_change(m,lambda s:s["requested_values"].__setitem__(1,word(.75))))
    rejected("override_policy_changes", lambda m: settings_change(m,lambda s:s.update(override_mask=17)))
    for field,value in (("still",.9),("moving",.4),("rotation_degrees",.2),("translation_metres",.002),("ramp",.07)):
        rejected("policy_change_"+field,lambda m,k=field,v=value:settings_change(m,lambda s:s["motion_stability"].update({k:word(v)})))
    for enabled in (False, 1, "true"):
        rejected("enabled_type_"+str(enabled),lambda m,b=enabled:settings_change(m,lambda s:s["motion_stability"].update(enabled=b)))
    for field in ("still","moving","rotation_degrees","translation_metres","ramp"):
        for bad in (True,-1,1<<32,0.5,0x7fc00000,0x7f800000):
            rejected("bad_word_"+field+"_"+str(bad),lambda m,k=field,b=bad:settings_change(m,lambda s:s["motion_stability"].update({k:b})))
    for field,value in (("moving",.9),("still",1.1),("rotation_degrees",0),("rotation_degrees",181),
                        ("translation_metres",0),("translation_metres",1.1),("ramp",0),("ramp",1.1)):
        rejected("bad_range_"+field+"_"+str(value),lambda m,k=field,v=value:settings_change(m,lambda s:s["motion_stability"].update({k:word(v)})))
    for bad in (word(.49),word(.9),0x7fc00000,0x7f800000):
        rejected("bad_runtime_key2_"+str(bad),lambda m,b=bad:settings_change(m,lambda s:s["provider_effective"].__setitem__(1,b)))
    rejected("context_break",lambda m:m["frames"][1].update(context_generation=99))
    rejected("provider_break",lambda m:m["frames"][1]["provider"].update(version_id=0))
    rejected("SL_gap",lambda m:m["frames"][1]["identity"].update(streamline_frame=123))
    rejected("SDK_gap",lambda m:m["frames"][1].update(sdk_frame_index=123))
    def off_key2(manifest):
        manifest["frames"][1]["settings"]["provider_effective"][1]=word(.75)
        rehash(manifest)
    rejected("OFF_key2_break",off_key2,legacy)
    rejected("OFF_fake_lineage",lambda m:[f.update(settings_lineage_sha256="0"*64) for f in m["frames"][:2]],legacy)
    check(json.loads((source / "capture.json").read_text(encoding="utf-8-sig")) == original,"source_metadata_unchanged")
    write(original)
    return {"status":"PASS","checks":len(checks),"cases":checks,
            "scope":"actual_WARP_G2_prefix_and_CPU_adversarial_metadata; no_AMD_SDK_or_quality_claim"}
