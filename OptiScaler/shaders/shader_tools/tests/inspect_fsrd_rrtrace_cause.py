"""Authenticate historical RRTrace inputs and isolate same-frame pipeline changes.

These observations have no clean truth. Differences to captured input/identity
are attribution measurements, never image-quality scores or alpha acceptance.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--captures',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Use a new output directory')
    a.output.mkdir(parents=True)
    report=dict(scope=__doc__,quality_accepted=False,source_root=str(a.captures.resolve()),rows=[],skipped=[])
    selected=None
    for path in sorted(a.captures.glob('*/capture.json')):
        m=json.loads(path.read_text());folder=path.parent.resolve();arrays={}
        if not m.get('complete',False):raise ValueError('Incomplete capture '+folder.name)
        authenticated='images' in m
        if not authenticated:
            if (m['schema_version']!=1 or m.get('source')!='live_gpu' or
                not m.get('gpu_completion_verified') or not m.get('completion_token') or
                m.get('format')!='rgba32f_le' or m.get('production_debug_mode')!='None' or
                m.get('active_radiance_signals')!=['diffuse','specular']):
                raise ValueError('Unsupported historical capture metadata')
            # Schema1 has dimensions/fence provenance but no capture-time hashes.
            # Hashing today cannot provide that missing attestation.
            m['images']=[dict(name=('raw_rgba' if v.stem=='raw_rgb' else v.stem),file=v.name,
                width=m['width'],height=m['height'],channels=4) for v in folder.glob('*.rgba32f')]
        hashes={}
        wanted={'raw_rgba','source_diffuse_albedo','source_specular_albedo','rr_guide_diffuse',
                'rr_guide_specular','diffuse_in','specular_in','diffuse_out','specular_out',
                'composition_production','identity_gpu','both_gpu','skip_rgb','joint_field_final'}
        for item in m['images']:
            payload=(folder/item['file']).resolve()
            if payload.parent!=folder:raise ValueError('Payload escapes capture')
            b=payload.read_bytes();sha=hashlib.sha256(b).hexdigest()
            if (authenticated and sha!=item['sha256']) or len(b)!=item['width']*item['height']*item['channels']*4:
                raise ValueError('Payload integrity failure '+str(payload))
            hashes[item['name']]=sha
            if item['name'] in wanted:
                arrays[item['name']]=np.frombuffer(b,'<f4').reshape(item['height'],item['width'],item['channels']).copy()
        for item in m.get('constant_buffers',[]):
            payload=(folder/item['file']).resolve()
            if payload.parent!=folder or hashlib.sha256(payload.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Constant buffer integrity failure')
        row=dict(capture=folder.name,frame=m.get('frame_index'),schema_version=m['schema_version'],
                 backend=m.get('backend','legacy'),settings=m.get('settings'),render_size=m.get('render_size'),
                 payload_attestation=('capture-time manifest SHA256 verified' if authenticated else
                     'schema1 structural/fence metadata verified; hashes computed now, capture-time hashes absent'),
                 origin_xy=m.get('origin_xy'),payload_sha256=hashes,measurements={})
        raw=arrays.get('raw_rgba');identity=arrays.get('identity_gpu');prod=arrays.get('composition_production')
        roi=(slice(25,85),slice(5,85),slice(0,3))
        if raw is not None:
            row['measurements']['source_range_rgb']=[raw[roi].min((0,1)).tolist(),raw[roi].max((0,1)).tolist()]
        def difference(name,x,y):
            if x is None or y is None:return
            e=x[roi].astype(float)-y[roi].astype(float)
            row['measurements'][name]=dict(signed_mean_rgb=e.mean((0,1)).tolist(),
                rms_difference_rgb=np.sqrt(np.mean(e*e,(0,1))).tolist(),max_abs_rgb=abs(e).max((0,1)).tolist(),
                exact_equal=bool(np.array_equal(x[roi],y[roi])))
        difference('identity_minus_source',identity,raw)
        difference('production_minus_identity',prod,identity)
        difference('production_minus_both_compare',prod,arrays.get('both_gpu'))
        if prod is None:difference('comparison_both_minus_identity',arrays.get('both_gpu'),identity)
        for name in ('source_diffuse_albedo','source_specular_albedo','rr_guide_diffuse','rr_guide_specular'):
            if name not in arrays:continue
            x=arrays[name][roi]
            row['measurements'][name]=dict(mean_rgb=x.mean((0,1)).tolist(),
                std_rgb=x.std((0,1)).tolist(),invalid_fraction=float(np.mean(~np.isfinite(x)|(x<0)|(x>1))))
        report['rows'].append(row)
        if m['schema_version']==6 and (selected is None or m['frame_index']>selected[0]['frame_index']):
            selected=(m,arrays)
    (a.output/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if selected:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        m,x=selected
        fig,axes=plt.subplots(2,3,figsize=(13,8),constrained_layout=True)
        panels=(('Raw source RGB','raw_rgba'),('Captured identity RGB','identity_gpu'),
                ('Captured production RGB','composition_production'),
                ('Source diffuse albedo','source_diffuse_albedo'),('Source specular albedo','source_specular_albedo'))
        for ax,(title,key) in zip(axes.flat,panels):
            # Same fixed mapping for all radiance panels; guides use [0,1].
            v=x[key][...,:3];display=np.sqrt(np.clip(v*4 if key in ('raw_rgba','identity_gpu','composition_production') else v,0,1))
            ax.imshow(display);ax.set_title(title);ax.set_xlabel('ROI x (pixels)');ax.set_ylabel('ROI y (pixels)')
        delta=(x['composition_production'][...,:3]-x['identity_gpu'][...,:3])@np.array([.2126,.7152,.0722])
        im=axes[1,2].imshow(delta,cmap='coolwarm',vmin=-.01,vmax=.01)
        axes[1,2].set_title('Production minus identity luma')
        axes[1,2].set_xlabel('ROI x (pixels)');axes[1,2].set_ylabel('ROI y (pixels)')
        fig.colorbar(im,ax=axes[1,2],label='Signed luma difference (linear RGB)')
        fig.suptitle(m['capture_id']+' · '+m['backend']+' · single frame, no clean reference',fontsize=13)
        fig.text(.01,.002,'Source: authenticated MO2 RRTrace · Radiance display sqrt(clamp(4 × RGB)); albedo sqrt(clamp(RGB)). Difference is attribution, not clean error.',fontsize=8)
        fig.savefig(a.output/'latest_stage6.png',dpi=150)
        plt.close(fig)
    print(f'Inspected {len(report["rows"])} historical captures; '+
          f'{sum("capture-time manifest" in r["payload_attestation"] for r in report["rows"])} with capture-time payload hash checks; no alpha/game quality claim.')


if __name__=='__main__':main()
