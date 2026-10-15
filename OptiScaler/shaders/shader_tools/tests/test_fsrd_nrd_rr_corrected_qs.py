"""V7 nonendpoint/full-matrix material oracle and packet RNE regression tests."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import numpy as np

import fsrd_nrd_rr_corrected_qs as qs
import fsrd_nrd_rr_material_quality as files


def run(output):
    checks = 0
    def need(condition, message):
        nonlocal checks
        checks += 1
        if not bool(condition):
            raise AssertionError(message)
    # Execute only the existing, independently authored production polynomial
    # definition. Importing that GPU driver would execute unrelated setup.
    source = Path(__file__).with_name('test_fsrd_nrd_conversion.py')
    tree = ast.parse(source.read_bytes())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'material_brdf_polynomials')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    production = scope['material_brdf_polynomials']
    rng = np.random.default_rng(0x15C7007)
    rows = []
    for r in (123/1023., 307/1023., .02, .8, 1.):
        for n in (0., .1, .25, .5, .75, .9, 1.):
            matrix = qs.polynomials(n, r*r)
            scalar = qs.scalar_polynomials(n, r*r)
            external = production(n, r*r)
            need(np.allclose(matrix, scalar, rtol=4e-15, atol=2e-14), 'independent scalar and full-four-power matrix polynomials')
            need(np.allclose(matrix, external, rtol=4e-15, atol=2e-14), 'separately authored production fixture polynomial agrees')
            for f0 in ((1.,1.,1.), (.04,.04,.04), (.6,.1,.05), (.003,.008,.012)):
                full = qs.reflectance(f0, r, n)
                need(np.allclose(full, qs.scalar_reflectance(f0,r,n), rtol=6e-15, atol=2e-14), 'colored/dielectric bias gate and scale independent scalar match')
                need(np.isfinite(full).all() and np.all(full >= 0), 'finite nonnegative guide over supported domain')
        n = rng.uniform(.12,.95,128)
        alpha = r*r
        correct = qs.polynomials(n,alpha)[3]
        wrong = 1+3.59685*n-1.36772*n**3+alpha*(9.04401-16.3174*n+9.22949*n**3)+alpha**3*(5.56589+19.7886*n-20.2123*n**3)
        need(np.count_nonzero(abs(correct-wrong)>1e-6) == len(n), 'nonendpoint cases reject frozen linear-NoV denominator defect')
    for r,n,expected in ((123/1023.,.5,1.0066746388677077), (123/1023.,.75,1.0269212145974087),
                         (307/1023.,.5,0.9551390804130458), (307/1023.,.75,0.9832094537710564)):
        value = float(qs.reflectance((1,1,1),r,n)[0])
        # Checkpoint values are separately recorded in the defect audit; the
        # three independent polynomial comparisons above use tighter bounds.
        need(abs(value-expected)<5e-14, 'recorded NoV^2 correction numeric checkpoint')
        rows.append(dict(roughness=r,no_v=n,qs=value))
    values = np.concatenate((np.linspace(0,1,65537,dtype=np.float32),
        np.array([0.,-0.,2**-25,np.nextafter(np.float32(2**-25),np.float32(1)),2**-24,2**-14],np.float32)))
    manual = qs.float32_to_half_rne(values)
    need(np.array_equal(manual.view('<u2'),values.astype('<f2').view('<u2')), 'integer packet RNE matches IEEE CPU reference including ties/subnormals/signedzero')
    need(manual[-4] == np.float16(0) and manual[-3] == np.float16(2**-24), 'half minimum tie rounds even and next representable rounds up')
    codes = np.stack((np.arange(1024),np.arange(1024)[::-1],np.arange(1024)),axis=-1)
    metal = (np.arange(1024)%256).astype('u1')
    packet = qs.captured_material(codes,metal)
    factor = qs.material_factors(packet,123/1023.,np.full(1024,.75))
    need(packet.dtype == np.dtype('<f2') and np.isfinite(packet).all(), 'captured RGB10^2/metalR8 packet explicitly IEEE half')
    need(np.all((factor['f0']>=0)&(factor['f0']<=1)) and np.all((factor['qd']>=0)&(factor['qd']<=1)), 'physical F0/Qd derive from actual half cues')
    need(np.array_equal(qs.unorm8(np.array([0.,.5,1.,1.1])),np.array([0,128,255,255],'u1')), 'guide direct-UNORM endpoints/tie/clamp without half intermediate')
    for bad in (-1.1,float('nan'),1.1):
        try:
            qs.reflectance((1,1,1),.12,bad)
        except ValueError:
            need(True,'invalid native guide domain rejected')
        else:
            need(False,'invalid native guide domain rejected')
    result = dict(schema='fsrd-corrected-qs-oracle-properties-v7',checks=checks,rows=rows,
        correction=qs.CORRECTION, production_hlsl_already_correct=True,
        independent_production_polynomial_sha256=files.file_sha(source),
        cpu_upload_quantization='FP64 rational -> clamp -> nearest-even directUNORM8; no half intermediate',
        hardware_quantization_verified=False, gpu_executed=False, compiler_executed=False)
    files.write_json(output,result)
    print(json.dumps(result,indent=2))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
