"""Execute the production DirectXMath camera resolver and check its runtime wiring."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT / 'tools_tmp/fsrd_camera_matrices/tests'))
    exe = out / 'fsrd_camera_matrices_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_camera_matrices_test.cpp'), exe,
                include_dirs=(ROOT / 'external/streamline',))
    subprocess.run([str(exe)], check=True)
    feature = (ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text(encoding='utf-8-sig')
    body = feature[feature.index('bool FSRDFeatureDx12::ResolveCameraMatrices('):]
    body = body[:body.index('// Derives the RR signal plan')]
    assert 'FSRDCamera::Resolve(' in body
    assert 'canUseStreamline ? &slData : nullptr' in body
    assert '_isRightHanded = camera.isRightHanded' in body
    assert '_viewMatrix = camera.view' in body and '_projMatrix = camera.projection' in body
    print('PASS: runtime uses tested resolver and gates Streamline to current constants')


if __name__ == '__main__':
    run()
