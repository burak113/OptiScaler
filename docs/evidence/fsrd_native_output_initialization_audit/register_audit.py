"""Read-only audit preregistration. Writes only into its owned audit directory."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess

ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
HERE = Path(__file__).resolve().parent
WORK = ROOT/'tools_tmp/native_output_initialization_diagnostic_20260930'
ARCHIVE = ROOT/'docs/evidence/fsrd_native_output_initialization'

def identity(p):
    data = p.read_bytes()
    return {'path':str(p), 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}

def save(p, value):
    with p.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')

def git(*args):
    return subprocess.check_output(['git','-C',str(ROOT),*args]).decode().strip()

if __name__ == '__main__':
    files = sorted(p for p in WORK.rglob('*') if p.is_file())
    files += sorted(p for p in ARCHIVE.rglob('*') if p.is_file())
    files += [ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp',
              ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll',
              ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',
              ROOT/'docs/fsrd_native_output_initialization.md',
              ROOT/'docs/evidence/.gitattributes',
              ROOT/'docs/evidence/fsrd_native_output_initialization_rgb_bit_proof.json',
              ROOT/'tools_tmp/native_output_initialization_stage_erratum_20260930.json',
              ROOT/'tools_tmp/native_output_initialization_staged_verification_v2_20260930.json']
    files = list(dict.fromkeys(files))
    registration = {
        'schema':'native-output-initialization-independent-read-only-audit-registration-v1',
        'utc':datetime.now(timezone.utc).isoformat(),
        'branch':git('branch','--show-current'), 'head':git('rev-parse','HEAD'),
        'scope':'Independent reconstruction and CPU recomputation of the completed twelve-context external output initialization diagnostic.',
        'write_scope':str(HERE),
        'new_native_contexts':0, 'new_native_RR_calls':0,
        'prohibited_actions':['native/GPU/game runs','builds','edits outside write_scope','producer report rewrites'],
        'checks':['Exact source insertion whitelist and absolute includes',
                  'Six modes: legacy, heap/barrier control, zero/sentinel first/all frames',
                  'Seven raw inputs, formats/upload counts, DLL/provider and 64x184 applied controls',
                  'Twelve owned-child guards, fresh process contexts, logs and lobe sizes',
                  'All 66 pairs: raw RGBA/RGB/alpha RMS, max, changed fractions, per-frame RMS and RGB uint16 bit equality',
                  'Six repeat pairs and new mode0 versus previous frozen wave P raw output',
                  'Per-frame component sentinel survival and finite values',
                  '131 copied archive files and 112 retained external payload/build binaries',
                  '136 committed files including the historical Git newline normalization erratum',
                  'SHA256/size freeze unchanged after audit'],
        'acceptance_limits':['One synthetic input and two repeats per mode; no population determinism or quality claim',
                             'Retained destination alpha does not distinguish no store from same-value store',
                             'RGB equality does not rule out transient reads/internal state issues or establish a universal contract',
                             'No inference of game stain/wave root cause or production acceptance'],
        'files': [identity(p) for p in files]
    }
    save(HERE/'preregistration.json',registration)
    save(HERE/'pre_audit_freeze.json', {'schema':'independent-audit-pre-freeze-v1','files':registration['files']})
    print(json.dumps({'registered_files':len(files),'preregistration':identity(HERE/'preregistration.json'),
                      'pre_audit_freeze':identity(HERE/'pre_audit_freeze.json')}))
