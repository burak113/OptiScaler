"""Independent GPU closure and RR participation for fitted Floor lighting.

Known current samples and independently constructed stochastic colour prevent a
quiet model from passing by replacing RR's input. Chromatic dark-tail and actual
partial-model producer measurements are reported alongside the strict controls.
"""
import json
import re
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c


def declared_floor_reserve_kind(source):
    """Identify supported energy-accounting contracts, never quality truth.

    A raw-source consumer is not enough to identify its pedestal arithmetic.
    Unknown arithmetic fails closed; historical pinned contracts stay explicit.
    """
    code = re.sub(r'\s+', '', re.sub(r'//[^\n]*|/\*[\s\S]*?\*/', '', source))
    required = ('constfloat3residualSource=rawColor;',
                'float3denoiserColor=(1.0f-biasWeight)*max(residualSource-spatialFloor,0.0f);')
    if not all(expression in code for expression in required):
        raise ValueError('Unknown current-raw residual arithmetic')
    carrier = (
        'constfloatrelativeModelNoise=max(detailReference.a,0.0f)/max(GetLuminance(spatialFloor),1e-5f);',
        'constfloatmodelNoisePlateau=smoothstep(0.005f,0.025f,relativeModelNoise);',
        'constboolmodelHeadroomEligible=ordinaryNoiseModel&&detailReference.a>=0.0f&&!FloorCoherentLighting(floorModel)&&!FloorLocalLightingProjection(floorModel);',
        'constfloat3carrierAlbedo=splitSpecWeight+splitDiffWeight;',
        'constfloat3carrierBudget=spatialFloor/max(carrierAlbedo,1e-5f);',
        'constfloatcarrierIrradiance=0.25f*modelNoisePlateau*min(carrierBudget.r,min(carrierBudget.g,carrierBudget.b));',
        'constfloat3carrierReserve=carrierIrradiance*carrierAlbedo;',
        'spatialFloor-=modelHeadroomEligible?carrierReserve:0.0f;',
    )
    if all(expression in code for expression in carrier):
        return 'quarter_albedo_carrier'
    if 'carrierReserve' in code:
        raise ValueError('Unknown albedo carrier arithmetic; zero-Q repair is not the selected contract')
    bounded = (
        'constfloatmodelHeadroomRatio=2.0f*max(detailReference.a,0.0f)/max(GetLuminance(spatialFloor),1e-5f);',
        'constfloatboundedModelHeadroom=0.5f*modelHeadroomRatio/(0.5f+modelHeadroomRatio);',
        'constfloatmodelPedestalConfidence=any(materialSlope>0.0f)?1.0f:planeConfidence;',
        'constfloatmodelHeadroom=ordinaryNoiseModel&&detailReference.a>=0.0f?boundedModelHeadroom*modelPedestalConfidence:0.0f;',
        'spatialFloor*=1.0f-modelHeadroom;',
    )
    if all(expression in code for expression in bounded):
        return 'bounded_scalar_headroom'
    continuous = (
        'constfloatrelativeReferenceNoise=max(detailReference.a,0.0f)/max(GetLuminance(FloorRadiance(detailReference.rgb)),1e-5f);',
        'constfloatmodelPedestalConfidence=any(materialSlope>0.0f)?1.0f:planeConfidence;',
        'constfloatmodelHeadroom=ordinaryNoiseModel&&detailReference.a>=0.0f?saturate(2.0f*relativeReferenceNoise)*modelPedestalConfidence:0.0f;',
        'spatialFloor*=1.0f-modelHeadroom;',
    )
    if all(expression in code for expression in continuous):
        return 'continuous_scalar_headroom'
    raise ValueError('Unknown current-raw pedestal accounting contract')


def declared_floor_reserve(spatial, sigma, albedo, confidence, eligible, kind, reference_luma=None):
    """Declared split energy only; callers still score independent clean truth."""
    spatial = np.asarray(spatial, np.float64)
    sigma = np.maximum(np.asarray(sigma, np.float64), 0.)
    eligible = np.asarray(eligible, bool)
    if kind == 'quarter_albedo_carrier':
        q = np.asarray(albedo, np.float64)
        ratio = sigma / np.maximum(spatial @ c.LUMA, 1e-5)
        plateau = np.clip((ratio - .005) / .020, 0., 1.)
        plateau = plateau * plateau * (3. - 2. * plateau)
        # Original selected Min includes every channel. An exactly zero Floor
        # channel can collapse the common budget even when its guide is zero.
        budget = np.min(spatial / np.maximum(q, 1e-5), axis=-1)
        reserve = (.25 * plateau * budget * eligible)[..., None] * q
    else:
        luma = spatial @ c.LUMA if kind == 'bounded_scalar_headroom' else reference_luma
        if luma is None:
            raise ValueError('Historical scalar headroom requires its declared reference luminance')
        ratio = 2. * sigma / np.maximum(luma, 1e-5)
        headroom = .5 * ratio / (.5 + ratio) if kind == 'bounded_scalar_headroom' else np.clip(ratio, 0., 1.)
        reserve = spatial * (headroom * confidence * eligible)[..., None]
    return spatial - reserve


def noise_residual_contract(directory=None):
    directory = t.PRE if directory is None else directory
    w, h = 65, 49
    diffuse = t.rgba(w, h, (.5, .5, .5))
    specular = t.rgba(w, h, (.04, .04, .04))
    models = (
        ('full material', t.rgba(w, h, (0, 0, 0), 1)),
        ('partial material', t.rgba(w, h, (0, -100, -100), 1)),
        ('lighting plane', t.rgba(w, h, (-100, -100, -100), 3)),
    )
    records = []
    for mean in ((.4, .4, .4), (.5, .08, .01)):
        sigma = .02
        truth = t.rgba(w, h, mean)
        raw = truth.copy()
        raw[..., :3] = np.maximum(raw[..., :3] + np.random.default_rng(29137).normal(0, sigma, (h, w, 3)), 0)
        floor = truth.copy(); floor[..., 3] = sigma
        reference = truth.copy(); reference[..., 3] = sigma
        observation = raw[..., :3].astype(np.float16).astype(np.float32)
        for label, model in models:
            packed = c.convert(raw, diffuse, specular, floor=floor, reference=reference,
                               resources={17: model}, directory=directory)
            recovered = c.compose(packed, detail=0, directory=directory)[..., :3]
            submitted = packed[0][..., :3] * packed[4][..., :3] + packed[1][..., :3] * packed[5][..., :3]
            raw_std = np.std(observation, axis=(0, 1))
            residual_std = np.std(submitted, axis=(0, 1))
            row = dict(case='independent RGB ray noise', model=label, mean_rgb=list(mean), sigma=sigma,
                       residual_std_fraction_rgb=(residual_std / raw_std).tolist(),
                       zero_residual_fraction_rgb=np.mean(submitted <= 1e-5, axis=(0, 1)).tolist(),
                       raw_zero_fraction_rgb=np.mean(observation <= 0, axis=(0, 1)).tolist(),
                       identity_bias_rgb=np.mean(recovered - observation, axis=(0, 1)).tolist(),
                       ordinary_fraction=float(np.mean(packed[3][..., 3] == 0)))
            records.append(row)
            print(json.dumps(row), flush=True)
            t.check(f'{label} keeps stochastic RGB residual for RR mean={mean}',
                    float(np.min(residual_std / raw_std)) > .3, **row)
            if mean == (.4, .4, .4):
                t.check(f'{label} grey noise largely reaches RR',
                        float(np.min(residual_std / raw_std)) > .85 and
                        float(np.max(np.mean(submitted <= 1e-5, axis=(0, 1)))) < .08, **row)
            flags = c.conversion_cb(w, h, floor=True)['Flags']
            bleed = c.convert(raw, diffuse, specular, floor=floor, reference=reference,
                              resources={17: model}, directory=directory,
                              overrides={'Flags': flags | (1 << 28)})
            t.check(f'{label} Bleed toggle cannot change main RR colour mean={mean}',
                    all(np.array_equal(a, b) for a, b in zip(packed[:8], bleed[:8])))

    # Actual Seed supplies the partial-channel payload and uncertainty. A clean
    # red material model is intentionally unrelated to independently noisy G/B.
    y, x = np.indices((h, w))
    albedo = diffuse.copy()
    albedo[..., 0] = .45 + .17*np.sin(.83*x + .21*y) + .09*np.cos(.71*y - .17*x)
    truth = t.rgba(w, h, (0, .15, .08))
    truth[..., 0] = .8 * albedo[..., 0] + .06
    raw = truth.copy()
    raw[..., 1:3] = np.maximum(raw[..., 1:3] + np.random.default_rng(71511).normal(0, .04, (h, w, 2)), 0)
    depth = np.full((h, w), 10, np.float32)
    normals = t.rgba(w, h, (0, 0, -1))
    floor, linear, reference = c.seed_frame(raw, albedo, depth, normals, directory)
    model = getattr(floor, '_floor_model', None)
    if model is None:
        raise ValueError('Partial producer probe requires actual Floor model readback')
    decoded = model[..., :3] > -99
    partial = decoded[..., 0] & ~decoded[..., 1] & ~decoded[..., 2] & (model[..., 3] >= .5)
    interior = np.zeros((h, w), bool); interior[7:-7, 7:-7] = True
    partial &= interior
    packed = c.convert(raw, albedo, specular, floor=floor, reference=reference, directory=directory)
    submitted = packed[0][..., :3] * packed[4][..., :3] + packed[1][..., :3] * packed[5][..., :3]
    reconstructed = c.compose(packed, detail=0, directory=directory)[..., :3]
    observed = raw[..., :3].astype(np.float16).astype(np.float32)
    mask = partial if partial.any() else interior
    row = dict(case='actual Seed red-only model with independent GB noise',
               partial_pixels=int(partial.sum()),
               reference_sigma_percentiles=np.percentile(reference[..., 3][mask], [10, 50, 90]).tolist(),
               raw_noise_rms_rgb=np.sqrt(np.mean((observed[mask] - truth[..., :3][mask])**2, axis=0)).tolist(),
               zero_residual_fraction_rgb=np.mean(submitted[mask] <= 1e-5, axis=0).tolist(),
               residual_std_rgb=np.std(submitted[mask], axis=0).tolist(),
               identity_bias_rgb=np.mean(reconstructed[mask] - observed[mask], axis=0).tolist(),
               selected_fraction=float(np.mean(packed[3][..., 3][mask] != 0)))
    records.append(row)
    print(json.dumps(row), flush=True)
    t.check('actual Seed fixture exercises a partial RGB model', int(partial.sum()) >= 32, **row)
    incoming_rms = float(np.sqrt(np.mean((observed[mask] - truth[..., :3][mask])**2)))
    sigma = float(np.median(reference[..., 3][mask]))
    t.check('partial Seed uncertainty covers incoming noise in unmodeled RGB channels',
            .5 * incoming_rms <= sigma <= 1.5 * incoming_rms,
            reference_sigma_median=sigma, incoming_rgb_noise_rms=incoming_rms)

    # Deterministic G/B lighting is unrelated to the modeled red material.
    # All-RGB unexplained variance would incorrectly call this known truth noise.
    clean = truth.copy()
    clean[..., 1] = .42 + .09*np.sin(.95*x + .27*y)
    clean[..., 2] = .36 + .08*np.cos(.34*x + .83*y)
    clean_floor, _, clean_reference = c.seed_frame(clean, albedo, depth, normals, directory)
    clean_model = clean_floor._floor_model
    accepted = clean_model[..., :3] > -99
    clean_partial = accepted[..., 0] & ~accepted[..., 1] & ~accepted[..., 2]
    clean_partial &= interior & (clean_reference[..., 3] >= 0)
    clean_sigma = float(np.median(clean_reference[..., 3][clean_partial])) if clean_partial.any() else float('inf')
    t.check('clean unmodeled colour fixture exercises a partial RGB model', int(clean_partial.sum()) >= 32)
    t.check('partial Seed does not relabel clean independent RGB lighting as noise',
            clean_sigma < .0015, reference_sigma_median=clean_sigma, maximum_sigma=.0015)
    records.append(dict(case='actual Seed red-only model with clean independent GB lighting',
                        partial_pixels=int(clean_partial.sum()), reference_sigma_median=clean_sigma))
    return records


def pedestal_headroom_contract(directory=None):
    directory = t.PRE if directory is None else directory
    w, h = 19, 13
    raw = t.rgba(w, h, (.4, .4, .4))
    diffuse = t.rgba(w, h, (.5, .5, .5))
    specular = t.rgba(w, h, (.04, .04, .04))
    records = []
    for value in (.4, 1e-5):
        # Match the incoming level to the pedestal. A much brighter source has
        # its own FP16 demodulation loss legitimately returned through Skip.
        raw = t.rgba(w, h, (value, value, value))
        floor = t.rgba(w, h, (value, value, value), .04)
        stored = floor[..., :3].astype(np.float16).astype(np.float32)
        tolerance = .002 * stored + 6e-8
        pedestals = []
        for sigma in (0., .004, .04, .4, 10000.):
            reference = t.rgba(w, h, (value, value, value), sigma)
            model = t.rgba(w, h, (0, 0, 0), 1)
            packed = c.convert(raw, diffuse, specular, floor=floor, reference=reference,
                               resources={17: model}, directory=directory)
            pedestal = packed[6][..., :3]
            pedestals.append(pedestal)
            t.check(f'bounded model headroom retains a finite half pedestal value={value} sigma={sigma}',
                    all(np.isfinite(p).all() for p in packed) and
                    np.all(pedestal >= .5 * stored - tolerance) and
                    np.all(pedestal <= stored + tolerance))
            if sigma == 0:
                t.check(f'quiet fitted mean retains its complete pedestal value={value}',
                        np.all(abs(pedestal - stored) <= tolerance))
            records.append(dict(case='bounded noisy pedestal', floor_level=value, reference_sigma=sigma,
                                minimum_retained_fraction=float(np.min(pedestal / stored))))
        t.check(f'pedestal reservation is monotone in measured uncertainty value={value}',
                all(np.all(a >= b) for a, b in zip(pedestals, pedestals[1:])))
    return records


def material_acceptance_diagnostic(directory=None):
    """Measure actual producer acceptance on fixed truth with increasing noise.

    Acceptance transitions are reported, without treating a particular model
    mask or source weight as the quality objective. The independent energy
    bound includes the existing maximum five-percent flat clipping correction.
    """
    directory = t.PRE if directory is None else directory
    w, h = 65, 49
    y, x = np.indices((h, w))
    albedo = t.rgba(w, h, (.5, .5, .5))
    albedo[..., 0] = .45 + .17*np.sin(.83*x + .21*y) + .09*np.cos(.71*y - .17*x)
    truth = t.rgba(w, h, (0, .15, .08))
    truth[..., 0] = .8*albedo[..., 0] + .06
    field = np.random.default_rng(175113).normal(0, 1, (h, w))
    depth = np.full((h, w), 10, np.float32)
    normals = t.rgba(w, h, (0, 0, -1))
    specular = t.rgba(w, h, (.04, .04, .04))
    roi = (slice(7, -7), slice(7, -7), slice(0, 3))
    previous = None
    records = []
    for sigma in (0., .01, .03, .06, .12, .24):
        raw = truth.copy()
        raw[..., 0] = np.maximum(raw[..., 0] + sigma*field, 0)
        floor, _, reference = c.seed_frame(raw, albedo, depth, normals, directory)
        model = floor._floor_model
        packed = c.convert(raw, albedo, specular, floor=floor, reference=reference, directory=directory)
        result = c.compose(packed, detail=0, directory=directory)[..., :3]
        observed = raw[..., :3].astype(np.float16).astype(np.float32)
        spatial = floor[..., :3]
        residual = packed[0][..., :3]*packed[4][..., :3] + packed[1][..., :3]*packed[5][..., :3]
        tolerance = .002*np.maximum(observed, spatial) + .00002
        lower = np.maximum(observed - .05*spatial, 0)
        upper = np.maximum(observed, spatial)
        accepted = (model[..., 0] > -99) & (model[..., 3] >= .5)
        row = dict(case='actual material model acceptance under fixed stochastic field',
                   input_red_noise_sigma=sigma, diagnostic_only=True,
                   accepted_red_fraction=float(accepted[7:-7, 7:-7].mean()),
                   reference_sigma_median=float(np.median(reference[7:-7, 7:-7, 3])),
                   residual_rms_rgb=np.sqrt(np.mean(residual[roi]**2, (0, 1))).tolist(),
                   skip_mean_rgb=packed[6][roi].mean((0, 1)).tolist(),
                   composed_minus_current_rms_rgb=np.sqrt(np.mean((result[roi]-observed[roi])**2, (0, 1))).tolist())
        if previous is not None:
            row['acceptance_changed_fraction'] = float(np.mean(accepted[7:-7, 7:-7] != previous[7:-7, 7:-7]))
        previous = accepted
        records.append(row)
        print(json.dumps(row), flush=True)
        t.check(f'producer confidence sweep keeps finite current energy sigma={sigma}',
                all(np.isfinite(signal).all() for signal in packed) and
                np.all(result[roi] >= (lower-tolerance)[roi]) and
                np.all(result[roi] <= (upper+tolerance)[roi]), **row)
    return records


def plane_authority_contract(directory=None):
    directory = t.PRE if directory is None else directory
    w, h = 19, 13
    raw = t.rgba(w, h, (.4, .4, .4))
    floor = t.rgba(w, h, (.4, .4, .4), .04)
    reference = floor.copy()
    diffuse = t.rgba(w, h, (.5, .5, .5))
    specular = t.rgba(w, h, (.04, .04, .04))
    tiny = float(np.nextafter(np.float16(2), np.float16(np.inf)))
    records, pedestals = [], []
    for authority in (2., tiny, 2.25, 3.):
        model = t.rgba(w, h, (-100, -100, -100), authority)
        packed = c.convert(raw, diffuse, specular, floor=floor, reference=reference,
                           resources={17: model}, directory=directory)
        pedestal = packed[6][..., :3]
        pedestals.append(pedestal)
        records.append(dict(case='continuous plane authority', model_alpha=authority,
                            skip_mean_rgb=np.mean(pedestal, axis=(0, 1)).tolist()))
    first_step = float(np.max(abs(pedestals[1] - pedestals[0])))
    t.check('one FP16 plane-confidence step cannot reallocate a full noisy pedestal',
            first_step < .001, maximum_skip_step=first_step, next_plane_alpha=tiny)
    kind = declared_floor_reserve_kind((directory / 'FSRDInputConv.hlsl').read_text(encoding='utf-8'))
    if kind == 'quarter_albedo_carrier':
        t.check('fixed authorized Floor does not receive a second plane-confidence multiplier',
                all(np.array_equal(pedestals[0], p) for p in pedestals[1:]))
    else:
        t.check('plane confidence changes the pedestal continuously and monotonically',
                all(np.all(a >= b) for a, b in zip(pedestals, pedestals[1:])) and
                float(np.mean(pedestals[0] - pedestals[-1])) > .05)
    return records


def carrier_stability_contract(directory=None):
    """Fixed stored guides/Floor cannot inherit above-plateau sigma jitter."""
    directory = t.PRE if directory is None else directory
    kind = declared_floor_reserve_kind((directory / 'FSRDInputConv.hlsl').read_text(encoding='utf-8'))
    if kind != 'quarter_albedo_carrier':
        return []  # Historical diagnostics retain their own declared contract.
    w, h = 19, 13
    floor = t.rgba(w, h, (.4, .1, .04), .04)
    raw = floor.copy()
    raw[..., :3] = np.maximum(raw[..., :3] + np.random.default_rng(91317).normal(0, .02, (h, w, 3)), 0)
    diffuse = t.rgba(w, h, (.5, .5, .5))
    specular = t.rgba(w, h, (.04, .04, .04))
    model = t.rgba(w, h, (0, 0, 0), 1)
    outputs, rows = [], []
    stored = floor[..., :3].astype(np.float16).astype(np.float32)
    tolerance = .002 * stored + 2e-5
    for sigma in (.04, .08, .12):
        reference = floor.copy(); reference[..., 3] = sigma
        packed = c.convert(raw, diffuse, specular, floor=floor, reference=reference,
                           resources={17: model}, directory=directory)
        outputs.append(packed)
        t.check(f'albedo reserve retains finite three-quarter pedestal sigma={sigma}',
                all(np.isfinite(p).all() for p in packed) and
                np.all(packed[6][..., :3] >= .75 * stored - tolerance))
        rows.append(dict(case='fixed-Floor above-plateau sigma jitter', reference_sigma=sigma,
                         skip_mean_rgb=packed[6][..., :3].mean((0, 1)).tolist()))
    t.check('above-plateau sigma jitter cannot modulate main RR colour or Skip',
            all(np.array_equal(outputs[0][index][..., :3], packed[index][..., :3])
                for packed in outputs[1:] for index in (0, 1, 6)))
    # Record the known selected-contract limitation, not a quality objective.
    cyan = t.rgba(w, h, (0, .4, .4), .04)
    cyan_guide = t.rgba(w, h, (0, .5, .5))
    cyan_packed = c.convert(cyan, cyan_guide, t.rgba(w, h, (0, 0, 0)), floor=cyan,
                            reference=cyan, resources={17: model}, directory=directory)
    rows.append(dict(case='known zero-Floor/zero-guide common-budget collapse', diagnostic_only=True,
                     skip_mean_rgb=cyan_packed[6][..., :3].mean((0, 1)).tolist(),
                     limitation='No guarantee of nonzero reserve in this degenerate channel layout; separate zero-Q repair rejected on actual-native64/96 transitions.'))
    return rows


def run():
    t.OUT = t.OUT.parent / 'floor_split_contract'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w, h = 19, 13
    raw = t.rgba(w,h,(.4,.4,.4))
    floor = t.rgba(w,h,(.35,.5,.3),.04)
    diffuse = t.rgba(w,h,(.5,.5,.5))
    specular = t.rgba(w,h,(.04,.04,.04))
    absent = t.rgba(w,h,(0,0,0))
    material = t.rgba(w,h,(0,0,0),1)
    red_material = t.rgba(w,h,(0,-100,-100),1)
    plane = t.rgba(w,h,(-100,-100,-100),3)
    luma = np.array([.2126,.7152,.0722], np.float64)

    def convert(model, reference, **kwargs):
        resources = {17:model, **kwargs.pop('resources',{})}
        return c.convert(raw, kwargs.pop('diffuse',diffuse), kwargs.pop('specular',specular),
                         floor=kwargs.pop('floor',floor), reference=reference,
                         resources=resources, **kwargs)

    for sigma in (0.,.006,.04,.2):
        reference = t.rgba(w,h,(.4,.4,.4),sigma)
        observation = raw[...,:3].astype(np.float16).astype(np.float64)
        pedestal = floor[...,:3].astype(np.float16).astype(np.float64)
        # A material/plane model can reserve residual headroom, but its quiet
        # mean has no authority to replace the known current colour sample.
        for name, model in (('material',material),
                            ('red-only material',red_material),
                            ('flat lighting plane',plane)):
            packed = convert(model,reference)
            result = c.compose(packed,detail=0)[...,:3]
            bound = .002 * np.maximum(observation, pedestal) + .00002
            t.check(f'{name} retains current sample energy sigma {sigma}',
                    np.all(result >= observation - bound) and
                    np.all(result <= np.maximum(observation, pedestal) + bound))
            t.check(f'{name} retains at least half the eligible Floor pedestal sigma {sigma}',
                    np.all(packed[6][..., :3] >= .5 * pedestal - bound))
            t.check(f'{name} remains an ordinary surface sigma {sigma}',
                    np.all(packed[3][...,3]==0))

    reference = t.rgba(w,h,(.4,.4,.4),.04)
    flags = c.conversion_cb(w,h,floor=True)['Flags']
    excluded = [
        ('Floor disabled',dict(overrides={'Flags':flags & ~(1<<7)})),
        ('zero roughness',dict(roughness=np.zeros((h,w),np.float32))),
        ('fractional bias',dict(overrides={'Flags':flags|(1<<15)},resources={8:np.full((h,w),.35,np.float32)})),
        ('responsivity low',dict(overrides={'Flags':flags|(1<<13),'ResponsivityTrustThreshold':.5},resources={15:np.zeros((h,w),np.float32)})),
        ('responsivity inverted high',dict(overrides={'Flags':flags|(1<<13),'ResponsivityTrustThreshold':.5,'ResponsivityInvert':1},resources={15:np.ones((h,w),np.float32)})),
        ('partial diffuse',dict(overrides={'DiffuseAlbedoModulation':.5})),
        ('partial specular',dict(overrides={'SpecularAlbedoDemodulation':.5})),
        ('half diffuse layout',dict(overrides={'Flags':flags|(1<<24)})),
        ('half specular layout',dict(overrides={'Flags':flags|(1<<25)})),
        ('unsupported original albedo',dict(diffuse=t.rgba(w,h,(0,0,0)))),
        ('specular dominant',dict(diffuse=t.rgba(w,h,(.02,.02,.02)),specular=t.rgba(w,h,(.7,.7,.7)))),
        ('albedo overshoot',dict(diffuse=t.rgba(w,h,(.8,.8,.8)),specular=t.rgba(w,h,(.4,.4,.4)))),
        ('emissive reinterpretation',dict(diffuse=t.rgba(w,h,(2,2,2)),specular=t.rgba(w,h,(2,2,2)))),
    ]
    for name, arguments in excluded:
        active = convert(material,reference,**arguments)
        disabled = convert(absent,reference,**arguments)
        t.check(name+' excludes model headroom',
                all(np.array_equal(a,b) for a,b in zip(active[:7],disabled[:7])))
    for name, invalid_reference in (
        ('negative reference validity',t.rgba(w,h,(.4,.4,.4),-1)),
        ('nonfinite reference uncertainty',t.rgba(w,h,(.4,.4,.4),np.nan)),
    ):
        active=convert(material,invalid_reference)
        disabled=convert(absent,invalid_reference)
        t.check(name+' excludes model headroom',
                all(np.array_equal(a,b) for a,b in zip(active[:7],disabled[:7])))
    for reference_sigma in (0.,-1.):
        flat_model=t.rgba(w,h,(-100,-100,-100),1.2)
        flat_reference=t.rgba(w,h,(.4,.4,.4),reference_sigma)
        packed=convert(flat_model,flat_reference)
        result=c.compose(packed,detail=0)[...,:3]
        observed=raw[...,:3].astype(np.float16).astype(np.float64)
        pedestal=floor[...,:3].astype(np.float16).astype(np.float64)
        stored_alpha=float(np.float16(1.2))
        bias=.15*(stored_alpha-1)*(pedestal@luma)
        correction=np.minimum(bias[...,None],.05*pedestal) if reference_sigma>=0 else 0
        expected=np.maximum(observed,pedestal)-correction
        error=float(np.max(np.abs(result-expected)/(.002*np.abs(expected)+.00002)))
        t.check(f'flat common RGB correction requires valid reference {reference_sigma}',
                error<=1,maximum_tolerance_fraction=error)
    active = convert(material,reference,overrides={'FloorDetailPreservation':0})
    for detail in (.35,1.):
        other=convert(material,reference,overrides={'FloorDetailPreservation':detail})
        t.check(f'ordinary packed lighting independent of detail slider {detail}',
                all(np.array_equal(a,b) for a,b in zip(active[:7],other[:7])))
    records = noise_residual_contract()
    records.extend(plane_authority_contract())
    records.extend(pedestal_headroom_contract())
    records.extend(material_acceptance_diagnostic())
    records.extend(carrier_stability_contract())
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    assert all(check['passed'] for check in t.checks),'Floor current-source closure/routing failed'


if __name__=='__main__':
    run()
