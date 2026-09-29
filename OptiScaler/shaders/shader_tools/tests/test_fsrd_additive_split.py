"""Targeted production DXIL contracts for the optional additive allocation.

Actual AMD quality has its own probe. This suite pins disabled compatibility to
the genuine base DXIL and independently evaluates accepted local RGB ridge fits.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_alpha_common import (GPUWorker, compose, convert, extract_baseline,
                               frozen_identity, rgba, save_json, shader_identity)


def quantized(a):
    return np.rint(np.clip(a.astype(np.float16).astype(np.float64), 0, 1)*255)/255


def fit_oracle(raw, diffuse, specular, center, strength):
    """Independent double-precision moments for a valid planar 7x7 fit."""
    y, x = center
    h, w = raw.shape[:2]
    box = (slice(max(y-3, 0), min(y+4, h)), slice(max(x-3, 0), min(x+4, w)))
    s, d = quantized(specular[..., :3]), quantized(diffuse[..., :3])
    a = (s+d)[box].reshape(-1, 3)
    c = raw[..., :3].astype(np.float16).astype(np.float64)[box].reshape(-1, 3)
    ma, mc = a.mean(0), c.mean(0)
    va, vc = np.var(a, axis=0), np.var(c, axis=0)
    ac = np.mean((a-ma)*(c-mc), axis=0)
    ridge = .02*ma**2+1e-6
    slope = (ac+ridge*mc/np.maximum(ma, 1e-3))/(va+ridge)
    intercept = np.clip(mc-slope*ma, 0, mc)
    variance = np.maximum(vc+slope*slope*va-2*slope*ac, 0)
    uncertainty = np.sqrt(variance*(1+ma*ma/np.maximum(va, 1e-6))/len(a))
    accepted = (len(a) >= 12) & (va >= .01*ma**2+1e-6)
    ss = s[box].reshape(-1, 3)
    accepted &= (ss.min(0) >= 4/255) & (ss.max(0)-ss.min(0) <= .10*ss.mean(0)+1e-6)
    accepted &= (intercept > np.maximum(.01*mc, 2*uncertainty)) & (slope >= 0)
    b = intercept*strength
    new_slope = (mc-b)/np.maximum(ma, 1e-3)
    model = (s[y, x]+d[y, x])*new_slope+b
    share = (s[y, x]*new_slope+b)/np.maximum(model, 1e-6)
    baseline = s[y, x]/np.maximum(s[y, x]+d[y, x], .008)
    return np.where(accepted, np.maximum(share, baseline), baseline), accepted


def run():
    # The generic lossless hook is for changes expected to be identical. Enabled
    # additive strengths intentionally differ and are checked by their own oracle.
    os.environ.pop('FSRD_LOSSLESS_BASELINE', None)
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', str(t.ROOT/'tools_tmp/fsrd_alpha_native')))
    output.mkdir(parents=True, exist_ok=True)
    baseline = Path(os.environ['FSRD_ALPHA_BASELINE']) if os.environ.get('FSRD_ALPHA_BASELINE') else extract_baseline(output)
    base_identity = frozen_identity(baseline)
    report = dict(baseline=base_identity, candidate_shaders=shader_identity(t.PRE),
                  production_shader_tests=True, actual_amd=False, checks=[],
                  source_hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ('test_fsrd_additive_split.py', 'fsrd_alpha_common.py',
                                              'fsrd_gpu_runner.cpp', 'run_fsrd_gpu_tests.py')})
    def check(name, condition, **metrics):
        report['checks'].append(dict(name=name, passed=bool(condition), **metrics))
        print(('PASS ' if condition else 'FAIL ')+name+' '+str(metrics), flush=True)
    w, h = 41, 31
    y, x = np.indices((h, w))
    pattern = ((x+2*y) % 7)/6
    d = rgba((.07+.40*pattern)[..., None]*np.array([.70, .85, 1], np.float32))
    s = t.rgba(w, h, (13/255, 16/255, 21/255))
    light = np.array([.45, .38, .32], np.float32)
    intercept = np.array([.08, .07, .055], np.float32)
    raw = rgba((d[..., :3]+s[..., :3])*light+intercept)
    depth = np.full((h, w), 10, np.float32)
    with GPUWorker(output):
        report['gpu_runner_sha256'] = hashlib.sha256(t.runner.read_bytes()).hexdigest()
        fields, size = t.mirror.hlsl_cbuffer_fields(t.mirror.brace_body(
            (t.PRE/'FSRDInputConv.hlsl').read_text(), 'cbuffer CB_Packing'), 'FSRDInputConv')
        field = next(f for f in fields if f[0]=='AdditiveLightSplit')
        check('CB uses existing final slot', field[2:] == (412, 4) and size == 416,
              offset=field[2], byte_size=size)
        check('disabled conversion DXIL is genuine base byte for byte',
              (t.PRE/'FSRDInputConv_Shader.cso').read_bytes() == (baseline/'FSRDInputConv_Shader.cso').read_bytes())
        check('enabled conversion has its own additive DXIL',
              (t.PRE/'FSRDInputConvAdditive_Shader.cso').read_bytes() != (baseline/'FSRDInputConv_Shader.cso').read_bytes())
        p0 = convert(raw, d, s, 0)
        frozen = convert(raw, d, s, 0, directory=baseline)
        check('disabled candidate exactly matches genuine base stored outputs',
              all(np.array_equal(a, b) for a, b in zip(p0, frozen)))
        baseline_comp = compose(frozen, directory=baseline, detail=0)
        check('disabled composition exactly matches base', np.array_equal(compose(p0, detail=0), baseline_comp))
        # Varied RGB guides expose arithmetic reassociation that an affine fit
        # fixture can miss. This independent fixture also covers guide values
        # around the divisor floor, without requiring an external capture.
        varied_rng = np.random.default_rng(29617)
        varied_raw = rgba(varied_rng.uniform(.04, .16, (63, 97, 3)))
        varied_d = rgba(varied_rng.uniform(0, .8, (63, 97, 3)))
        varied_s = rgba(varied_rng.uniform(0, .15, (63, 97, 3)))
        varied_base = convert(varied_raw, varied_d, varied_s, 0, directory=baseline)
        varied_current = convert(varied_raw, varied_d, varied_s, 0)
        differences = []
        for i, (a, b) in enumerate(zip(varied_base, varied_current)):
            if i == 4:
                a, b = a[..., :3], b[..., :3]
            if not np.array_equal(a, b):
                differences.append(dict(output=i, changed_channels=int(np.count_nonzero(a != b)),
                                        maximum_delta=float(np.max(abs(a-b)))))
        check('disabled varied RGB guides preserve every consumed output exactly',
              not differences, differences=differences)
        check('disabled varied-guide share alpha is also exactly original',
              np.array_equal(varied_base[4][..., 3], varied_current[4][..., 3]))
        for strength in (.5, 1):
            p = convert(raw, d, s, strength)
            check(f'strength{strength} retains source guides geometry motion and reference',
                  all(np.array_equal(p[i], p0[i]) for i in (2, 3, 5, 7)) and
                  np.array_equal(p[4][..., :3], p0[4][..., :3]))
            points = ((3, 3), (h//2, w//2), (h-4, w-4), (0, 0))
            errors, accepted_count = [], 0
            for center in points:
                share, accepted = fit_oracle(raw, d, s, center, strength)
                expected = (raw[center][:3].astype(np.float16).astype(float)*share /
                            np.maximum(p[4][center][:3], .008)).astype(np.float16).astype(np.float32)
                errors.append(float(np.max(abs(p[0][center][:3]-expected))))
                accepted_count += int(accepted.sum())
            check(f'strength{strength} matches independent RGB ridge at interior and edge',
                  accepted_count >= 9 and max(errors) <= .004, max_signal_error=max(errors), accepted_channels=accepted_count)
            changed = int(np.count_nonzero(p[0][..., :3] != p0[0][..., :3]))
            check(f'strength{strength} changes actual specular signal', changed > w*h, changed_channels=changed)
            identity = compose(p, detail=0)[..., :3]
            maximum = float(np.max(abs(identity-raw[..., :3].astype(np.float16).astype(float))))
            check(f'strength{strength} preserves identity without injecting Skip', maximum < .001,
                  max_error=maximum, skip_max=float(p[6][..., :3].max()))
            check(f'strength{strength} avoids added raw Skip energy',
                  float(p[6][..., :3].mean()) <= float(p0[6][..., :3].mean())+1e-7)
        for scale in (.02, 8, 200, 60000):
            c = raw.copy()
            c[..., :3] *= scale
            a, b = convert(c, d, s, 0), convert(c, d, s, 1)
            out = compose(b, detail=0)[..., :3]
            stored = c[..., :3].astype(np.float16).astype(float)
            error = float(np.max(abs(out-stored)))
            check(f'dark/HDR identity and finite storage scale{scale}',
                  np.isfinite(out).all() and error <= max(3e-5, float(stored.max())*.003), max_error=error)
            check(f'dark/HDR does not increase bypass energy scale{scale}',
                  float(b[6][..., :3].mean()) <= float(a[6][..., :3].mean())+max(1e-7, scale*1e-5))
            if scale != 60000:
                check(f'dark/HDR probe exercises an active fit scale{scale}', np.any(a[0][..., :3] != b[0][..., :3]))
        # All channels of these fixtures have insufficient or unsafe evidence.
        flat = t.rgba(w, h, (.2, .2, .2))
        pure = rgba((quantized(d[..., :3])+quantized(s[..., :3]))*light)
        cases = [('constant guide has no intercept evidence', raw, flat, s),
                 ('zero additive term', pure, d, s),
                 ('missing specular guide', raw, d, t.rgba(w, h, (0, 0, 0))),
                 ('small floored specular guide', raw, d, t.rgba(w, h, (1/255, 1/255, 1/255))),
                 ('textured specular rejects intercept allocation', raw, d,
                  rgba(np.where(((x+y)%2)[..., None], [.035, .045, .055], [.07, .085, .10]))),
                 ('rewritten overshoot is not fit evidence', raw, t.rgba(w, h, (.7, .7, .7)), t.rgba(w, h, (.7, .7, .7)))]
        for name, c, da, sa in cases:
            a = convert(c, da, sa, 0, kernel='additive')
            b = convert(c, da, sa, 1)
            check('enabled-kernel fallback: '+name, all(np.array_equal(q, r) for q, r in zip(a, b)))
        small_raw, small_d, small_s = raw[:3, :3].copy(), d[:3, :3].copy(), s[:3, :3].copy()
        check('small footprint does not duplicate taps to reach minimum evidence',
              all(np.array_equal(a, b) for a, b in zip(convert(small_raw, small_d, small_s, 0, kernel='additive'),
                                                      convert(small_raw, small_d, small_s, 1))))
        colored = s.copy()
        colored[..., 0] = 1/255
        a, b = convert(raw, d, colored, 0, kernel='additive'), convert(raw, d, colored, 1)
        check('enabled-kernel dark colored-metal channel retains exact fallback signal and Skip',
              np.array_equal(a[0][..., 0], b[0][..., 0]) and np.array_equal(a[6][..., 0], b[6][..., 0]))
        check('safe colored-metal channels fit independently', np.any(a[0][..., 1:3] != b[0][..., 1:3]))
        invalid_d = d.copy()
        invalid_d[..., 0] = np.nan
        invalid_n = t.rgba(w, h, (0, 0, 0))
        masks = [('invalid guide cannot create fit evidence', dict(diff=invalid_d)),
                 ('missing normal cannot create fit evidence', dict(normals=invalid_n)),
                 ('title bias bypass cannot create fit evidence',
                  dict(overrides={'Flags':(1 << 1)|(1 << 5)|(1 << 15)}, resources={8:t.rgba(w, h, (.6, .6, .6))})),
                 ('title responsivity bypass cannot create fit evidence',
                  dict(overrides={'Flags':(1 << 1)|(1 << 5)|(1 << 13), 'ResponsivityTrustThreshold':.5},
                       resources={15:t.rgba(w, h, (.1, .1, .1))})),
                 ('published emissive radiance excludes fit evidence',
                  dict(overrides={'Flags':(1 << 1)|(1 << 5)|(1 << 6)}, resources={11:t.rgba(w, h, (.1, .1, .1))}))]
        for name, opts in masks:
            da = opts.pop('diff', d)
            a, b = convert(raw, da, s, 0, kernel='additive', **opts), convert(raw, da, s, 1, **opts)
            check('enabled-kernel fallback: '+name, all(np.array_equal(q, r) for q, r in zip(a, b)))
        # Vary rejected geometry and its radiance across a boundary. The left
        # neighborhood has sufficient evidence, so no-bleed is not a global fallback.
        for boundary in ('depth', 'normal', 'roughness'):
            z = depth.copy()
            normal = t.rgba(w, h, (0, 0, -1))
            rough = np.full((h, w), .55, np.float32)
            if boundary == 'depth': z[:, w//2:] = 20
            if boundary == 'normal': normal[:, w//2:, :3] = (1, 0, 0)
            if boundary == 'roughness': rough[:, w//2:] = .9
            changed = raw.copy()
            changed[:, w//2:, :3] = [2, 1, .5]
            opts = dict(depth=z, normals=normal, roughness=rough)
            a = convert(raw, d, s, 1, **opts)
            b = convert(changed, d, s, 1, **opts)
            center = (h//2, w//2-1)
            check(boundary+' edge cannot lend additive fit radiance', np.array_equal(a[0][center], b[0][center]))
            off = convert(raw, d, s, 0, kernel='additive', **opts)
            check(boundary+' edge test exercises an active fit', np.any(a[0][center][:3] != off[0][center][:3]))
        # Distinct title-resource origins and logical partial groups exercise all
        # taps, rather than only checking the center pixel's source coordinates.
        origin_values = {'InputBase0':[2, 3, 0, 0], 'InputBase1':[4, 2, 3, 4],
                         'InputBase2':[0, 0, 5, 1], 'InputBase3':[1, 5, 0, 0]}
        def padded(a, ox, oy, fill):
            result = np.full((h+8, w+8, *a.shape[2:]), fill, np.float32)
            result[oy:oy+h, ox:ox+w] = a
            return result
        plain = convert(raw, d, s, 1)
        shifted = convert(padded(raw, 2, 3, 6), padded(d, 5, 1, .8), padded(s, 1, 5, .6), 1,
                          normals=padded(t.rgba(w, h, (0, 0, -1)), 4, 2, 1),
                          roughness=padded(np.full((h, w), .55, np.float32), 3, 4, .95),
                          depth=depth, reference=raw, size=(w, h), origins=origin_values)
        check('distinct color guide normal roughness origins match full logical window',
              all(np.array_equal(a, b) for a, b in zip(plain, shifted)))
        floor = rgba((d[..., :3]+s[..., :3])*light*.20)
        for sm, dm in ((1, 1), (.5, 1), (1, .5), (0, 0)):
            opts = dict(SpecularAlbedoDemodulation=sm, DiffuseAlbedoModulation=dm)
            pair = []
            for strength in (0, 1):
                p = convert(raw, d, s, strength, floor=floor, overrides=opts,
                            kernel='additive' if strength == 0 else 'auto')
                pair.append(p)
                out = compose(p, detail=0, spec_strength=sm, diff_strength=dm)[..., :3]
                error = float(np.max(abs(out-raw[..., :3].astype(np.float16).astype(float))))
                check(f'Floor and partial modulation identity sm{sm} dm{dm} strength{strength}', error < .001, max_error=error)
            check(f'Floor sm{sm} dm{dm} identity test exercises an active fit',
                  np.any(pair[0][0][..., :3] != pair[1][0][..., :3]))
        cfg = (t.ROOT/'OptiScaler/Config.cpp').read_text()
        hdr = (t.ROOT/'OptiScaler/Config.h').read_text()
        runtime = (t.ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text()
        check('INI key loads saves resets and stays optional by default',
              'FfxDenoiserAdditiveLightSplit.set_from_config(readFloat("FSR-RR", "AdditiveLightSplit"))' in cfg and
              'ini.SetValue("FSR-RR", "AdditiveLightSplit"' in cfg and
              'FfxDenoiserAdditiveLightSplit.reset()' in cfg and
              'FfxDenoiserAdditiveLightSplit{0.0f}' in hdr)
        check('applied sanitized strength participates in existing history reset',
              'unitValue(cfg.FfxDenoiserAdditiveLightSplit.value_or_default(), 0.0f)' in runtime and
              bool(re.search(r'_convDesc.AdditiveLightSplit\s*!=\s*additiveLightSplit', runtime)))
        preprocess = (t.ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text()
        selection = t.mirror.brace_body(preprocess,
            'bool DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)')
        check('runtime selects finite-positive additive PSO before history Floor or barriers',
              'std::isfinite(desc.AdditiveLightSplit) && desc.AdditiveLightSplit > 0.0f' in selection and
              'if (useAdditivePipeline && !EnsureAdditiveConversionPipeline())' in selection and
              '? m_additiveConvPso.Get() : m_convShader.m_pso.Get()' in selection and
              selection.index('EnsureAdditiveConversionPipeline()') < selection.index('sourceBases') < selection.index('DispatchFloorSeed'))
    report['dispatches'] = t.timings
    save_json(output/'results.json', report)
    assert all(c['passed'] for c in report['checks']), 'additive split contract regression'


if __name__ == '__main__':
    run()
