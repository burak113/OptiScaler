"""Isolate stored native reconstruction from Floor composition corrections.

No new native RR is run. NoRecovery is sampled at selected frames because it
has no history; optional oldRecovery preserves full-sequence history commits.
Exact saved trust votes are reused in all variants of one fixed native plan.
"""
from pathlib import Path
import argparse
import copy
import json
import os
import shutil

import numpy as np
from PIL import Image, ImageDraw

import fsrd_real_capture_compare as compare
import fsrd_real_capture_contact_sheet as contact
import fsrd_real_capture_replay as capture


def load(path):
    with np.load(capture.safe_path(path),allow_pickle=False) as archive:return {k:archive[k] for k in archive.files}


def sample(cap,packed,rr,frames):
    c={k:(v[frames] if isinstance(v,np.ndarray) else v) for k,v in cap.items()}
    c['frame_metadata']=[cap['frame_metadata'][i] for i in frames]
    p={k:v[frames] for k,v in packed.items()}
    r={k:v[frames] for k,v in rr.items() if k!='metadata'}
    r['metadata']=copy.deepcopy(rr['metadata']);r['metadata']['reset_frames']=[]
    return c,p,r


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--comparison-dir',type=Path,required=True)
    parser.add_argument('--baseline-packed-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,nargs='+',default=[8,63,72,127])
    parser.add_argument('--water-y',type=int,default=80,help='Manual ROI band; no semantic segmentation claim')
    parser.add_argument('--old-recovery',action='store_true',help='Also run oldRecovery with full history; default is sampled noRecovery only')
    args=parser.parse_args()
    root=capture.safe_path(args.comparison_dir);out=capture.safe_path(args.output);out.mkdir(parents=True,exist_ok=True)
    report=json.loads((root/'comparison.json').read_text())
    baseline=capture.safe_path(report['baseline_directory']);candidate=capture.safe_path(report['candidate_directory'])
    expected_frames=report['capture']['frames']
    for case in ('1:0','1:1'):
        if case not in report['cases'] or report['cases'][case]['protocol']!='one_native_context_two_captured_sequence_segments_reset_at_boundary':
            raise ValueError('attribution requires joint native comparison cases1:0 and1:1; exact-readback-reuse is unsupported')
        if report['cases'][case]['frames_per_segment']!=expected_frames:
            raise ValueError('comparison case frame extent differs from capture prefix')
        metadata=json.loads((root/f'floor1_bleed{case[-1]}'/'rr_joint/metadata.json').read_text())
        if metadata['frames']!=2*expected_frames or metadata['counters']['dispatches']!=2*expected_frames:
            raise ValueError('joint native frame/dispatch count differs from comparison prefix')
        resets=report['cases'][case]['metrics']['baseline']['resets']
        reset_frames={0,*resets['captured'],*resets['injected']}
        if not (root/f'floor1_bleed{case[-1]}'/'baseline_packed.npz').is_file() and reset_frames.intersection(args.frames):
            raise ValueError('baseline reset-frame attribution requires recorded normalized baseline_packed.npz')
    provenance,cap=capture.inspect_capture(args.capture,True,expected_frames)
    if provenance['frames']!=expected_frames:raise ValueError('capture prefix is shorter than recorded comparison')
    if provenance['capture_manifest_sha256']!=report['capture']['capture_manifest_sha256']:
        raise ValueError('attribution capture differs from stored comparison')
    if compare.identities(baseline)!=report['baseline_shader_hashes'] or compare.identities(candidate)!=report['candidate_shader_hashes']:
        raise ValueError('stored comparison shader snapshot differs')
    if any(not 0<=f<provenance['frames'] for f in args.frames):parser.error('selected frame outside capture')
    # Only the composition shader changes in this mixed snapshot. Trust is fixed
    # to the original candidate readback, including the committed full witness.
    old=out/'candidate_old_recovery'
    if args.old_recovery:
        old.mkdir(exist_ok=True)
        for path in candidate.iterdir():
            if path.suffix in ('.hlsl','.hlsli','.cso'):shutil.copyfile(path,old/path.name)
        for path in baseline.iterdir():
            if path.name.startswith('FSRDOutputComp') and path.suffix in ('.hlsl','.cso'):shutil.copyfile(path,old/path.name)
    os.environ.setdefault('FSRD_VS_ROOT','F:/VisualStudio')
    exe=root/'build/fsrd_gpu_runner.exe'
    sources={str(root/'comparison.json'):capture.digest(root/'comparison.json')}
    results={}
    for bleed in (0,1):
        case=f'1:{bleed}';folder=root/f'floor1_bleed{bleed}';work=out/folder.name;work.mkdir(exist_ok=True)
        a_path=folder/'baseline_packed.npz'
        if a_path.is_file():
            identity=report['cases'][case].get('packed_artifacts',{}).get('baseline',{})
            if capture.digest(a_path)!=identity.get('sha256'):raise ValueError('normalized baseline packed digest differs')
            a=load(a_path)
        else:
            a=compare.cached_preprocessing(args.baseline_packed_dir,provenance,report['baseline_shader_hashes'],True,bool(bleed))
        b=load(folder/'candidate_packed.npz')
        rr_path=folder/'rr_joint/readback.npz';rr=load(rr_path)
        meta=json.loads((folder/'rr_joint/metadata.json').read_text())
        if capture.digest(rr_path)!=meta['logical_readback_npz']['sha256'] or meta['status']!='passed':
            raise ValueError('native readback provenance mismatch')
        rr['metadata']=meta;n=provenance['frames']
        rr_a,rr_b=compare.slice_readback(rr,0,n),compare.slice_readback(rr,n,n)
        saved_a,saved_b=load(folder/'baseline_final.npz'),load(folder/'candidate_final.npz')
        old_image=None
        if args.old_recovery:
            gpu=capture.Gpu(work/'old_recovery128',old,exe)
            try:
                old_image,_=capture.compose(cap,b,rr_b,gpu,bool(bleed),True,floor=True,cached_trust=saved_b['trust'])
            finally:gpu.close()
        no_recovery=[]
        for label,packed,native,shaders,trust in (
                ('baseline',a,rr_a,baseline,saved_a['trust']),('candidate',b,rr_b,candidate,saved_b['trust'])):
            sc,sp,sr=sample(cap,packed,native,args.frames)
            gpu=capture.Gpu(work/(label+'_no_recovery'),shaders,exe)
            try:
                image,_=capture.compose(sc,sp,sr,gpu,bool(bleed),label=='candidate',recovery=0,floor=True,
                    composition_shader='FSRDOutputCompNoRecovery',cached_trust=trust[args.frames])
            finally:gpu.close()
            no_recovery.append(image)
        baseline_final=saved_a['image'][args.frames];v2=saved_b['image'][args.frames]
        raw=cap['raw_color'][args.frames];proxy=cap['raw_color'][n//2:].astype(np.float32).mean(0)
        arrays=dict(frames=np.asarray(args.frames,np.uint32),baseline_no_recovery=no_recovery[0],candidate_no_recovery=no_recovery[1],
            baseline_final=baseline_final,candidate_recovery=v2,
            raw=raw,reference=b['reference'][args.frames],model=b['model'][args.frames],skip=b['skip'][args.frames],
            recovery_delta=v2.astype(np.float32)-no_recovery[1])
        bl,vl,nl=[capture.luminance(value) for value in (baseline_final,v2,no_recovery[1])]
        old_selected=old_image[args.frames] if old_image is not None else None
        ol=capture.luminance(old_selected) if old_selected is not None else None
        if old_selected is not None:
            arrays.update(candidate_old_recovery=old_selected,recovery_delta_old=old_selected.astype(np.float32)-no_recovery[1])
        pl=capture.luminance(proxy)
        mask=np.zeros(pl.shape,bool);mask[8:-8,8:-8]=True
        water=mask.copy();water[:args.water_y]=False
        new_dark=(vl<.5*bl)&(vl<.25*pl)&(bl>.01)
        recovery_dark=(vl<.5*nl)&(vl<.25*pl)&(nl>.01)
        arrays['new_dark_mask']=new_dark;arrays['recovery_dark_mask']=recovery_dark
        if old_image is not None:np.savez_compressed(work/'candidate_old_recovery128.npz',image=old_image)
        maps=work/'pixelmaps.npz';np.savez_compressed(maps,**arrays)
        metrics={}
        for name,region in (('interior',mask),('manual_water_band',water)):
            selected=new_dark&region
            metrics[name]=dict(pixels_per_frame=int(region.sum()),new_dark_count_per_frame=selected.sum((1,2)).tolist(),
                recovery_added_dark_count_per_frame=(recovery_dark&region).sum((1,2)).tolist(),
                candidate_no_recovery_dark_count_per_frame=((nl<.25*pl)&region).sum((1,2)).tolist(),
                old_recovery_dark_count_per_frame=((ol<.25*pl)&region).sum((1,2)).tolist() if ol is not None else None,
                candidate_recovery_dark_count_per_frame=((vl<.25*pl)&region).sum((1,2)).tolist(),
                new_dark_mean_luma=dict(baseline=float(bl[selected].mean()) if selected.any() else None,
                    candidate_no_recovery=float(nl[selected].mean()) if selected.any() else None,
                    candidate_old_recovery=float(ol[selected].mean()) if ol is not None and selected.any() else None,
                    candidate_recovery=float(vl[selected].mean()) if selected.any() else None))
        points=[]
        for row,frame in enumerate(args.frames):
            indices=np.flatnonzero((new_dark[row]&water).ravel())
            indices=sorted(indices,key=lambda i:float((bl[row]-vl[row]).ravel()[i]),reverse=True)[:16]
            for index in indices:
                y,x=divmod(int(index),pl.shape[1])
                points.append(dict(frame=frame,x=x,y=y,baseline=float(bl[row,y,x]),
                    candidate_no_recovery=float(nl[row,y,x]),candidate_old_recovery=float(ol[row,y,x]) if ol is not None else None,candidate_recovery=float(vl[row,y,x])))
        metrics['largest_new_water_dark_points']=points
        # One common mapping for radiance panels. Last panel is an explicit mask,
        # with red marking recovery darkening and yellow marking all new dark.
        w,h=cap['roi']['extent'];pw,ph=2*w,2*h;top=44;cell=ph+24
        labels=['Baseline final','Baseline noRecovery','Candidate noRecovery']+(['Candidate oldRecovery'] if old_selected is not None else [])+['Candidate recovery','New dark / recovery darkening']
        sheet=Image.new('RGB',(len(labels)*pw,top+cell*len(args.frames)),(22,22,22));draw=ImageDraw.Draw(sheet)
        for column,label in enumerate(labels):draw.text((column*pw+6,24),label,fill='white')
        draw.text((6,6),f'Fixed native readbacks / cached trust | Floor=1 Bleed={bleed} | exposure 1 for all radiance panels',fill='white')
        for row,frame in enumerate(args.frames):
            panels=[baseline_final[row],no_recovery[0][row],no_recovery[1][row]]+([old_selected[row]] if old_selected is not None else [])+[v2[row]]
            diagnostic=np.zeros((h,w,3),np.uint8);diagnostic[new_dark[row]]=(255,220,0);diagnostic[recovery_dark[row]]=(255,0,0)
            for column in range(len(labels)):
                draw.text((column*pw+6,top+row*cell+3),f'frame {frame}',fill='white')
                pixels=contact.display(panels[column],1) if column<len(panels) else diagnostic
                sheet.paste(Image.fromarray(pixels).resize((pw,ph),Image.Resampling.NEAREST),(column*pw,top+row*cell+22))
        sheet.save(work/'attribution_contact_sheet.png')
        metrics['pixelmaps_sha256']=capture.digest(maps)
        results[case]=metrics
        for path in (folder/'candidate_packed.npz',folder/'baseline_final.npz',folder/'candidate_final.npz',rr_path):sources[str(path)]=capture.digest(path)
        (out/'attribution.json').write_text(json.dumps(dict(frames=args.frames,water_band_start=args.water_y,
            limitation='Stationary crop and injected resets; no clean truth. New-dark mask is relative to baseline and late noisy raw mean.',
            native_rr_replayed=False,trust_votes_reused=True,old_recovery_full_history_frames=n if args.old_recovery else 0,
            baseline_hashes=report['baseline_shader_hashes'],candidate_hashes=report['candidate_shader_hashes'],
            mixed_old_recovery_hashes=compare.identities(old) if args.old_recovery else None,sources=sources,cases=results),indent=2)+'\n')
        print(case,metrics['manual_water_band'],flush=True)
    print(out/'attribution.json')


if __name__=='__main__':main()
