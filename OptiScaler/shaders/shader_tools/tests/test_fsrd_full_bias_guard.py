"""Actual production DXIL contracts for fully bias-routed current colour.

InputConv and every composition pipeline execute on D3D12. Explicit nonzero
RR lobes are adversarial composition inputs, not a denoiser/quality simulation.
A private control disables only the new guard; no historical package is needed.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as c
from fsrd_toolchain import dxc
from test_fsrd_composition_graph import GraphWorker


GUARD = 'biasWeight == 1.0f && !IsSet(FLAGS_DEBUG)'
INPUTS = ('FSRDInputConv', 'FSRDInputConvAdditive')
VARIANTS = ('FSRDOutputComp', 'FSRDOutputCompLight', 'FSRDOutputCompNoRecovery',
            'FSRDOutputCompTileLight', 'FSRDOutputCompTileAnchor')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compile_shader(directory, name, compiler):
    subprocess.run([str(compiler), '-T', 'cs_6_2', '-E', 'CSMain', '-enable-16bit-types',
                    '-O3', '-Qstrip_debug', '-Qstrip_reflect', str(directory/(name+'.hlsl')),
                    '-Fo', str(directory/(name+'_Shader.cso'))], check=True, capture_output=True)


def freeze(output):
    current, control = output/'current', output/'unguarded_control'
    current.mkdir(); control.mkdir()
    identity = {}
    for source in t.PRE.iterdir():
        if source.is_file() and source.suffix in ('.hlsl', '.hlsli', '.cso'):
            shutil.copyfile(source, current/source.name)
            shutil.copyfile(source, control/source.name)
            identity[source.name] = sha(source)
    text = (control/'FSRDInputConv.hlsl').read_text()
    if text.count(GUARD) != 1:
        raise ValueError('Expected one exact full-bias guard')
    (control/'FSRDInputConv.hlsl').write_text(text.replace(GUARD, 'false'))
    compiler = dxc()
    # Freshly compile the actual sources and authenticate checked-in production
    # bytecode before using it. The control changes only authority, not colour.
    for name in INPUTS:
        compile_shader(current, name, compiler)
        if sha(current/(name+'_Shader.cso')) != identity[name+'_Shader.cso']:
            raise ValueError('Production bytecode does not match current source: '+name)
        compile_shader(control, name, compiler)
    directories = {}
    for name in VARIANTS:
        directory = output/name
        directory.mkdir()
        shutil.copyfile(current/(name+'_Shader.cso'), directory/'FSRDOutputComp_Shader.cso')
        shutil.copyfile(current/'FSRDOutputComp.hlsl', directory/'FSRDOutputComp.hlsl')
        directories[name] = directory
    return current, control, directories, dict(production_files=identity,
        control_change='Only biasCurrentSource expression replaced with false',
        control_source_sha256=sha(control/'FSRDInputConv.hlsl'),
        control_bytecode={n:sha(control/(n+'_Shader.cso')) for n in INPUTS},
        compiler=str(compiler), compiler_sha256=sha(compiler))


def run():
    test_source_sha256=sha(__file__)
    output = t.OUT.parent/'full_bias_guard'
    output.mkdir(parents=True, exist_ok=True)
    current, control, directories, identity = freeze(output)
    records = []
    w, h = 41, 25
    y, x = np.indices((h, w))
    raw = t.rgba(w, h, (.37, .29, .61))
    raw[..., 0] += .11*np.sin(.23*x+.17*y)
    raw[..., 1] += .07*np.cos(.31*x-.19*y)
    raw[..., 2] += .09*np.sin(.43*x+.11*y)
    diffuse = t.rgba(w, h, (.46, .51, .39))
    specular = t.rgba(w, h, (.03, .05, .07))
    depth = np.full((h,w), 10, np.float32)
    zero = t.rgba(w, h, (0,0,0))
    floor = t.rgba(w, h, (.13,.12,.19), .02)
    invalid = raw.copy(); invalid[...,3] = -1
    mixed = np.choose((x//5)%4, [0., .5, np.nextafter(np.float32(1), np.float32(0)), 1.]).astype(np.float32)
    cases = [('absent', mixed, 1., False), ('zero', mixed*0, 1., True),
             ('partial', mixed*0+.5, 1., True), ('near_full', mixed*0+np.nextafter(np.float32(1),np.float32(0)), 1., True),
             ('reduced_strength', mixed*0+1, .5, True),
             ('unsaturated_strength', mixed*0+.4, 2., True),
             ('saturated_strength', mixed*0+.6, 2., True), ('mixed_boundary', mixed, 1., True)]

    def check(label, ok, **metrics):
        t.check(label, ok, **metrics)
        if not ok:
            raise AssertionError(label)

    def convert(worker, directory, kernel, image, mask, strength, enabled, floor_on,
                z=depth, reference=invalid, debug=False, alternates=False):
        worker.second_shader = ''
        flags = c.conversion_cb(w,h,floor=floor_on)['Flags'] | ((1<<15) if enabled else 0)
        if debug: flags |= (1<<16) | (34<<17)
        if alternates: flags |= 1<<28
        return c.convert(image,diffuse,specular,directory=directory,depth=z,
            floor=floor if floor_on else None,reference=reference,resources={8:mask},
            kernel=kernel,overrides=dict(Flags=flags,BiasMaskStrength=strength,RecoveryMask=7),
            strength=.75 if kernel=='additive' else 0,
            output_formats=[10,10,10,24,28,28,10,10,10,10])

    def composition(worker, packed, detail, kind, *, poison=0, history=None,
                    flags=8, selected=False, reference=None):
        rr_spec=t.rgba(w,h,(.8,.2,.6),3)
        rr_diff=t.rgba(w,h,(.1,.9,.3),10)
        if flags & (1<<5): rr_spec=packed[0].copy()
        else: rr_spec[packed[6][...,3]==-1,:3]+=poison
        if flags & (1<<4): rr_diff=packed[1].copy()
        else: rr_diff[packed[6][...,3]==-1,:3]+=poison*.7
        normal=packed[3].copy()
        if selected: normal[:,8:24,3]=1/3
        hist=t.rgba(w,h,(-1,-1,-1),-1) if history is None else history[1]
        meta=np.zeros((h,w,4),np.uint32) if history is None else history[2]
        values=dict(DstTexSize=[w,h,1/w,1/h],Flags=flags,DetailPreservation=detail,
            RecoveryMask=7,SpatialTemporalMask=7 if kind=='FSRDOutputCompLight' else 2,
            SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,FloorHandoverAnchorClamp=4,
            FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1,
            HistoryValid=int(history is not None),WriteHistory=int(detail>0),
            SourceUvScale=[1,1],SourceUvOffset=[0,0])
        if kind in ('split','split_reverse'):
            names=['FSRDOutputCompTileLight','FSRDOutputCompTileAnchor']
            if kind=='split_reverse': names.reverse()
            directory=directories[names[0]]
            worker.second_shader=directories[names[1]]/'FSRDOutputComp_Shader.cso'
        else:
            directory=directories[kind];worker.second_shader=''
        inputs=[rr_spec,packed[4],rr_diff,packed[5],packed[6],normal,
                packed[7] if reference is None else reference,depth,packed[2],hist,meta,
                zero,zero,np.zeros((h,w,2),np.float32),zero,packed[0],packed[1]]
        result=t._dispatch('FSRDOutputComp',values,inputs,[10,10,3],(w,h),directory)
        check('composition covers all pixels '+kind,not np.any(result[0]==-8192))
        return result

    try:
        with GraphWorker(output/'gpu') as worker:
            for kernel in ('original','additive'):
                for floor_on in (False,True):
                    for label,mask,strength,enabled in cases:
                        name=f'{kernel} Floor{int(floor_on)} {label}'
                        old=convert(worker,control,kernel,raw,mask,strength,enabled,floor_on)
                        new=convert(worker,current,kernel,raw,mask,strength,enabled,floor_on)
                        weight=np.clip(mask*strength,0,1) if enabled else np.zeros_like(mask)
                        full=weight==1
                        for slot in range(len(new)):
                            if slot==6:
                                check(name+' SkipRGB unchanged',np.array_equal(new[slot][...,:3],old[slot][...,:3]))
                                check(name+' partial/zero SkipA unchanged',np.array_equal(new[slot][~full],old[slot][~full]))
                            else:
                                check(name+f' output{slot} unchanged',np.array_equal(new[slot],old[slot]))
                        check(name+' exact authority selection',np.all((new[6][...,3]==-1)==full))
                        if full.any():
                            check(name+' full bias RR RGB zero',np.all(new[0][full,:3]==0)&np.all(new[1][full,:3]==0))
                            check(name+' full bias detail remains invalid',np.all(new[7][full,3]==-1))
                        for detail in (0.,1.):
                            kinds=['FSRDOutputComp','FSRDOutputCompLight','FSRDOutputCompNoRecovery'] if detail==0 else ['FSRDOutputComp','FSRDOutputCompLight','split','split_reverse']
                            for kind in kinds:
                                out=composition(worker,new,detail,kind)
                                if full.any():
                                    check(name+f' {kind} detail{detail} excludes stale RR',np.array_equal(out[0][full,:3],new[6][full,:3]))
                                    if detail>0:
                                        check(name+f' {kind} clears full-bias history',np.all(out[1][full]==-1)&np.all(out[2][full]==0))
                                if detail==0 and kind=='FSRDOutputComp':
                                    previous=composition(worker,old,detail,kind)
                                    check(name+' unmasked/partial composition bytes retained',np.array_equal(out[0][~full],previous[0][~full]))
                                    if full.any():check(name+' reproduces old extra-RR contribution',np.max(abs(previous[0][full,:3]-new[6][full,:3]))>.05)
                        records.append(dict(case=name,full_bias_pixels=int(full.sum()),partial_pixels=int(((weight>0)&(weight<1)).sum())))

            for kernel in ('original','additive'):
                for floor_on in (False,True):
                    old=convert(worker,control,kernel,raw,mixed,1,True,floor_on,alternates=True)
                    new=convert(worker,current,kernel,raw,mixed,1,True,floor_on,alternates=True)
                    check(f'{kernel} Floor{floor_on} optional RR feeds have nonzero control',
                          np.any(old[8][mixed==0,:3]>0)&np.any(old[9][mixed==0,:3]>0))
                    check(f'{kernel} Floor{floor_on} optional RR feeds exact',
                          np.array_equal(old[8],new[8])&np.array_equal(old[9],new[9]))

            # A scalar guard/luminance ternary once moved FP16 conversion and
            # changed dark, unmasked diagnostic alpha by one subnormal ULP.
            # Independent small radiances and partial routing exercise the
            # exact original store instead of hiding that drift in RGB bounds.
            for kernel in ('original','additive'):
                for exposure in (3e-5,1e-4,3e-4):
                    image=raw.copy();image[...,:3]*=exposure
                    ref=image.copy();ref[...,3]=-1
                    for amount in (0.,.5,np.nextafter(np.float32(1),np.float32(0))):
                        mask=mixed*0+amount
                        old=convert(worker,control,kernel,image,mask,1,True,False,reference=ref)
                        new=convert(worker,current,kernel,image,mask,1,True,False,reference=ref)
                        check(f'dark native16 byte parity {kernel} exposure{exposure} bias{amount}',
                              all(np.array_equal(a,b) for a,b in zip(old,new)))
                        if amount==.5:
                            check(f'dark fixture produces subnormal SkipA {kernel} exposure{exposure}',
                                  np.any((old[6][...,3]>0)&(old[6][...,3]<np.finfo(np.float16).tiny)))

            # Far-plane bypass and input inspection keep the same complete RGB,
            # empty signals/guides and invalid reference; only production full
            # bias gets authority. Diagnostics remain exact control outputs.
            for far in (False,True):
                for debug in (False,True):
                    z=np.full((h,w),12000 if far else 10,np.float32)
                    old=convert(worker,control,'original',raw,np.ones_like(mixed),1,True,False,z=z,debug=debug)
                    new=convert(worker,current,'original',raw,np.ones_like(mixed),1,True,False,z=z,debug=debug)
                    check(f'far{far} debug{debug} RGB/signal/guide/reference parity',all(
                        np.array_equal(a[...,:3],b[...,:3]) if i==6 else np.array_equal(a,b) for i,(a,b) in enumerate(zip(old,new))))
                    check(f'far{far} debug{debug} authority',np.all(new[6][...,3]==old[6][...,3]) if debug else np.all(new[6][...,3]==-1))

            # Invalid-reference certificate seams cannot lend RR colour or
            # decisions to neighbours. Exercise both tile owners, both orders,
            # and disabled-lobe bindings, independently of converter guide tags.
            p=convert(worker,current,'original',raw,mixed,1,True,True)
            full=p[6][...,3]==-1
            for flags in (8,8|(1<<4),8|(1<<5)):
                for kind in ('FSRDOutputComp','split','split_reverse'):
                    one=composition(worker,p,1,kind,flags=flags,selected=True)
                    two=composition(worker,p,1,kind,flags=flags,selected=True,poison=12)
                    check(f'invalid-reference boundary {kind} flags{flags}',all(np.array_equal(a,b) for a,b in zip(one,two)))

            # Routed certificates have invalid reference, while adjacent zero
            # bias retains a valid reference and actively exercises recovery.
            # A constant pedestal/current field also exercises constant-Skip
            # support; the spatial field exercises varying-Skip support.
            for pattern in ('constant','varying'):
                image=floor.copy() if pattern=='constant' else raw
                ref=image.copy();ref[...,3]=.02
                old=convert(worker,control,'original',image,mixed,1,True,True,reference=ref)
                new=convert(worker,current,'original',image,mixed,1,True,True,reference=ref)
                full=new[6][...,3]==-1
                neighbours=~full
                check(pattern+' boundary has valid zero-bias neighbours',np.any((mixed==0)&(new[7][...,3]>=0)))
                check(pattern+' full/partial boundary references remain invalid',np.all(new[7][mixed>0,3]==-1))
                for kind in ('FSRDOutputComp','FSRDOutputCompLight','split','split_reverse'):
                    one=composition(worker,old,1,kind,selected=True)
                    two=composition(worker,new,1,kind,selected=True)
                    check(pattern+' active unmasked/partial boundary bytes '+kind,
                          all(np.array_equal(a[neighbours],b[neighbours]) for a,b in zip(one,two)))
                    check(pattern+' active full-bias boundary source '+kind,np.array_equal(two[0][full,:3],new[6][full,:3]))
                    check(pattern+' active full-bias boundary history '+kind,np.all(two[1][full]==-1)&np.all(two[2][full]==0))

            # Enter, leave and revisit full bias with changing current colour and
            # real ping-pong history outputs. Valid unmasked reference creates
            # history; full/partial routing withdraws its permission.
            for kind in ('FSRDOutputComp','FSRDOutputCompLight','split','split_reverse'):
                history=None
                for frame,amount in enumerate((0.,1.,0.,.5,1.,0.)):
                    image=raw.copy();image[...,:3]*=1+.13*frame
                    ref=image.copy();ref[...,3]=.02
                    p=convert(worker,current,'original',image,mixed*0+amount,1,True,True,reference=ref)
                    out=composition(worker,p,1,kind,history=history)
                    if amount==1:
                        check(f'{kind} transition{frame} chooses current source',np.array_equal(out[0][...,:3],p[6][...,:3]))
                        check(f'{kind} transition{frame} invalidates history',np.all(out[1]==-1)&np.all(out[2]==0))
                    if frame in (2,5):
                        fresh=composition(worker,p,1,kind)
                        check(f'{kind} leaving full bias has no certified history',all(np.array_equal(a,b) for a,b in zip(out,fresh)))
                    history=out
    finally:
        (output/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,
            cases=records,identity=identity,test_source_sha256=test_source_sha256,
            scope='Full-bias composition safety only; explicit stale RR fixtures, no native quality/performance claim.'),indent=2))
    if sha(__file__)!=test_source_sha256:raise RuntimeError('Test source changed during execution')
    assert all(item['passed'] for item in t.checks),'full bias current-source regression'


if __name__=='__main__':run()
