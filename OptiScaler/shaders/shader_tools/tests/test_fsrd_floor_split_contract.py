"""Independent GPU closure and routing checks for fitted Floor lighting sources."""
import json
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c


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

    for sigma in (0.,.006,.04):
        reference = t.rgba(w,h,(.4,.4,.4),sigma)
        observation = raw[...,:3].astype(np.float16).astype(np.float64)
        pedestal = floor[...,:3].astype(np.float16).astype(np.float64)
        stored_reference = reference.astype(np.float16).astype(np.float64)
        ratio = stored_reference[...,3] / np.maximum(stored_reference[...,:3] @ luma,1e-5)
        ramp = np.clip((ratio-.005)/.020,0,1)
        weight = ramp*ramp*(3-2*ramp)
        # One source decision for all channels: a model explaining only some
        # channels keeps every channel on the raw route, so RR never receives
        # noise in a subset of channels (coloured grain).
        for name, model, channels in (('material',material,[1,1,1]),
                                      ('red-only material',red_material,[0,0,0]),
                                      ('flat lighting plane',plane,[1,1,1])):
            packed = convert(model,reference)
            result = c.compose(packed,detail=0)[...,:3]
            source = observation + (pedestal-observation)*weight[...,None]*channels
            expected = np.maximum(source,pedestal)
            normalized = float(np.max(np.abs(result-expected)/(.002*np.abs(expected)+.00002)))
            t.check(f'{name} source/pedestal closure sigma {sigma}',normalized <= 1,
                    maximum_tolerance_fraction=normalized)
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
        t.check(name+' excludes the fitted source',
                all(np.array_equal(a,b) for a,b in zip(active[:7],disabled[:7])))
    for name, invalid_reference in (
        ('negative reference validity',t.rgba(w,h,(.4,.4,.4),-1)),
        ('nonfinite reference uncertainty',t.rgba(w,h,(.4,.4,.4),np.nan)),
    ):
        active=convert(material,invalid_reference)
        disabled=convert(absent,invalid_reference)
        t.check(name+' excludes fitted source',
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
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(check['passed'] for check in t.checks),'Floor fitted-source closure/routing failed'


if __name__=='__main__':
    run()
