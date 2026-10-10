"""CPU-only ABI and generated-byte checks for isolated paired detail shaders."""
from pathlib import Path
import argparse
import json
import re
from fsrd_recovery_detail_gpu import PRE, PREFIX, SCHEMAS, constants, mirror_module, sha


def run(output):
    checks, layouts = [], {}
    for suffix, (expected_size, inputs, outputs, threads) in SCHEMAS.items():
        name = PREFIX + suffix
        source = (PRE / (name+".hlsl")).read_text()
        mirror = mirror_module()
        body = mirror.brace_body(source, "cbuffer CB_Detail"+suffix)
        fields, size = mirror.hlsl_cbuffer_fields(body, name)
        layouts[name] = dict(bytes=size, fields=fields, srv_formats=inputs,
            uav_formats=outputs, threads=threads, source_sha256=sha(PRE/(name+".hlsl")),
            cso_sha256=sha(PRE/(name+"_Shader.cso")))
        generated = (PRE/(name+"_Shader.h")).read_text()
        array = generated.split("const unsigned char "+name+"_cso[] = {", 1)[1].split("};", 1)[0]
        binary = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", array))
        items = [
            ("CB layout", not mirror.errors and size == expected_size and len(constants(suffix, {})) == expected_size),
            ("descriptor table counts", f"SRV(t0, numDescriptors = {len(inputs)})" in source and
               f"UAV(u0, numDescriptors = {len(outputs)})" in source),
            ("dispatch topology", f"numthreads({threads[0]}, {threads[1]}, {threads[2]})" in source),
            ("generated header equals binary", binary == (PRE/(name+"_Shader.cso")).read_bytes()),
        ]
        for label, passed in items:
            checks.append(dict(name=name+" "+label, passed=bool(passed)))
            print(("PASS " if passed else "FAIL ")+checks[-1]["name"], flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    failures = sum(not row["passed"] for row in checks)
    output.write_text(json.dumps(dict(checks=checks, failures=failures, layouts=layouts,
                                     gpu_executed=False), indent=2))
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().output))
