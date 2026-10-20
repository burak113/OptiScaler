"""Portable captured-glass policy fixture. Python stdlib + NumPy; no GPU or RR Lab."""
from pathlib import Path
import argparse, hashlib, json
import numpy as np

HERE = Path(__file__).resolve().parent
LUMA = np.array([.2126, .7152, .0722], np.float32)
UUID = '87ee1fba-b8bc-4660-aa3f-d06db7bf863f'
FRAMES = list(range(46, 64))
REFERENCE = 54

def sha(data): return hashlib.sha256(data).hexdigest()

def gaussian(a, sigma):
    radius = int(3*sigma+.5)
    kernel = np.exp(-.5*(np.arange(-radius, radius+1)/sigma)**2)
    kernel /= kernel.sum()
    def conv(x, axis):
        pad = [(0,0)]*x.ndim; pad[axis] = (radius,radius)
        padded = np.pad(x,pad,mode='edge')
        result = np.zeros_like(x,dtype=np.float32)
        for i,weight in enumerate(kernel):
            take = [slice(None)]*x.ndim; take[axis] = slice(i,i+x.shape[axis])
            result += weight*padded[tuple(take)]
        return result
    return conv(conv(a.astype(np.float32),a.ndim-2),a.ndim-1)

def policy_variants(raw, selected):
    return {'Glass Off (captured NZR)':selected,'Glass RR':raw,
            'Glass Blend 0.5':raw+np.float32(.5)*(selected-raw),
            'Glass Blend 0.75':raw+np.float32(.75)*(selected-raw)}

def metrics(raw, selected, mask):
    rows = {}
    assert mask.any()
    for name,rgb in policy_variants(raw,selected).items():
        lum = rgb@LUMA; low = gaussian(lum,2); high = lum-low
        average = lum.mean(0)
        rows[name] = {'fine_temporal_cv_p50':float(np.median(lum.std(0)[mask]/np.maximum(average[mask],1e-6))),
            'hp_temporal_cv_p50':float(np.median(high.std(0)[mask]/np.maximum(low.mean(0)[mask],1e-6))),
            'detail':float(abs(average-gaussian(average,1.5))[mask].mean()),
            'level':float(average[mask].mean())}
    return rows

def decode_nz(packed):
    xy = np.stack([(packed&1023)/1023.,((packed>>10)&1023)/1023.],-1).astype(np.float32)*2-1
    z = 1-abs(xy[...,0])-abs(xy[...,1]); t = np.maximum(-z,0)
    xy += np.where(xy>=0,-t[...,None],t[...,None])
    return abs(z)/np.sqrt((xy*xy).sum(-1)+z*z)

class SourceCapture:
    def __init__(self,path):
        self.path = Path(path)
        self.manifest_bytes = (self.path/'capture.json').read_bytes()
        self.manifest = json.loads(self.manifest_bytes)
        self.frames = self.manifest['frames']
        self.published = int(self.manifest.get('manifest_published_frames',len(self.frames)))
        self.width,self.height = self.manifest['roi']['extent']
        self.x,self.y = self.manifest['roi']['origin']
        self.rw,self.rh = self.manifest['render_extent']
        assert self.manifest['capture_uuid']==UUID and max(FRAMES)<self.published
        self.hashes = {}
    def read(self,f,name,dtype='<f2',channels=4):
        image = {x['name']:x for x in self.frames[f]['images']}[name]
        relative = image['file']
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        data = (self.path/relative).read_bytes()
        self.hashes[f'{f}/{name}'] = {'file':relative,'sha256':sha(data),'bytes':len(data),
                                    'dtype':dtype,'channels':channels}
        shape = (self.height,self.width,channels) if channels>1 else (self.height,self.width)
        return np.frombuffer(data,np.dtype(dtype)).reshape(shape).copy()
    def camera(self,f):
        camera = self.frames[f]['frame_parameters']['camera']
        return tuple(np.array(camera[key],'<u4').view('<f4').reshape(4,4) for key in ('view','projection'))
    def coordinates(self,f,reference_depth):
        va,pa = self.camera(REFERENCE); view,projection = self.camera(f)
        yy,xx = np.mgrid[:self.height,:self.width].astype(np.float64)
        nx = (xx+self.x+.5)/self.rw*2-1; ny = 1-(yy+self.y+.5)/self.rh*2
        z = reference_depth.astype(np.float64)
        direction = np.stack([nx*z/pa[0,0],ny*z/pa[1,1],z],-1)
        inv = np.linalg.inv(va.astype(np.float64))
        world = direction@inv[:3,:3].T+inv[:3,3]
        current = world@view[:3,:3].T.astype(np.float64)+view[:3,3]
        qx = (projection[0,0]*current[...,0]/current[...,2]+1)/2*self.rw-self.x-.5
        qy = (1-projection[1,1]*current[...,1]/current[...,2])/2*self.rh-self.y-.5
        return qx,qy
    def sample(self,image,qx,qy):
        x = np.floor(qx).astype(int); y = np.floor(qy).astype(int); fx = qx-x; fy = qy-y
        valid = (x>=0)&(y>=0)&(x<self.width-1)&(y<self.height-1)
        x = np.clip(x,0,self.width-2); y = np.clip(y,0,self.height-2)
        weights = [(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy]
        values = [image[y,x],image[y,x+1],image[y+1,x],image[y+1,x+1]]
        if image.ndim==3: weights = [w[...,None] for w in weights]
        return sum(w*v for w,v in zip(weights,values)),valid

def best_crop(mask,width,height):
    # Choose by valid-mask coverage only, before looking at any quality metric.
    inner_w,inner_h = width-12,height-12
    integral = np.pad(mask.astype(np.int64),((1,0),(1,0))).cumsum(0).cumsum(1)
    scores = integral[inner_h:,inner_w:]-integral[:-inner_h,inner_w:]-integral[inner_h:,:-inner_w]+integral[:-inner_h,:-inner_w]
    scores = scores[6:mask.shape[0]-height+7,6:mask.shape[1]-width+7]
    y,x = np.unravel_index(np.argmax(scores),scores.shape)
    return [int(x),int(y),int(x+width),int(y+height)]

def export(source_path,out=HERE):
    out = Path(out).resolve(); out.mkdir(parents=True,exist_ok=True)
    source = SourceCapture(source_path)
    reference_depth = source.read(REFERENCE,'input_depth','<f4',1)
    raw_spec=[]; selected_spec=[]; diffuse=[]; old_masks=[]; eligible_masks=[]; valid_masks=[]
    normal_original=[]; depth_original=[]; motion_original=[]; view_words=[]; projection_words=[]
    full_raw=[]; full_selected=[]; diffuse_proof=[]; exposure=None
    for f in FRAMES:
        rs = source.read(f,'raw_rr_specular'); ss = source.read(f,'selected_rr_specular')
        rd = source.read(f,'raw_rr_diffuse'); sd = source.read(f,'selected_rr_diffuse')
        different = int(np.count_nonzero(rd.view('<u2')!=sd.view('<u2')))
        assert different==0
        diffuse_proof.append({'frame':f,'words':rd.size,'differing_words':different,
            'raw_sha256':source.hashes[f'{f}/raw_rr_diffuse']['sha256'],
            'selected_sha256':source.hashes[f'{f}/selected_rr_diffuse']['sha256']})
        packed = source.read(f,'input_normal_roughness','<u4',1)
        depth = source.read(f,'input_depth','<f4',1)
        motion = source.read(f,'input_motion','<f2',4)
        original_eligible = (((packed>>20)&1023)<=2)&np.isfinite(depth)&(abs(depth)>1e-5)&(abs(depth)<500)
        original_probe_mask = np.any(rs[...,:3]!=ss[...,:3],-1)&(decode_nz(packed)<=.5)&(abs(depth)<500)
        normal_original.append(packed); depth_original.append(depth); motion_original.append(motion)
        camera = source.frames[f]['frame_parameters']['camera']
        view_words.append(np.array(camera['view'],'<u4')); projection_words.append(np.array(camera['projection'],'<u4'))
        raw = rs[...,:3].astype(np.float32); selected = ss[...,:3].astype(np.float32); diff = rd[...,:3].astype(np.float32)
        # Full-ROI evidence uses the exact prior order: compose before camera sampling.
        cr,cs = raw+diff,selected+diff
        if f==55: exposure=float(.8/max(np.percentile(cs@LUMA,97),1e-6))
        if f==REFERENCE:
            valid = np.ones(depth.shape,bool); mask = original_probe_mask; eligible=original_eligible
        else:
            qx,qy = source.coordinates(f,reference_depth)
            raw,valid = source.sample(raw,qx,qy); selected,v2=source.sample(selected,qx,qy)
            diff,v3=source.sample(diff,qx,qy); cr,v4=source.sample(cr,qx,qy); cs,v5=source.sample(cs,qx,qy)
            mask,mv=source.sample(original_probe_mask.astype(np.float32),qx,qy);mask=mask>.999
            eligible,ev=source.sample(original_eligible.astype(np.float32),qx,qy);eligible=eligible>.999
            valid &= v2&v3&v4&v5&mv&ev
        raw_spec.append(raw.astype(np.float32));selected_spec.append(selected.astype(np.float32));diffuse.append(diff.astype(np.float32))
        full_raw.append(cr.astype(np.float32));full_selected.append(cs.astype(np.float32))
        old_masks.append(mask);eligible_masks.append(eligible);valid_masks.append(valid)
    common = np.logical_and.reduce(old_masks)&np.logical_and.reduce(valid_masks)
    assert int(common.sum())==8048,('prior full-ROI mask calibration failed',int(common.sum()))
    full_statistics = metrics(np.stack(full_raw),np.stack(full_selected),common)
    known = {'Glass Off (captured NZR)':(.08864346891641617,.03574063628911972,.0006428358610719442,.004292116034775972),
             'Glass RR':(.058001432567834854,.025560304522514343,.0003532776318024844,.00456627132371068),
             'Glass Blend 0.5':(.0649728775024414,.029156632721424103,.00048163923202082515,.004429193213582039),
             'Glass Blend 0.75':(.07472296804189682,.03192280977964401,.0005598214920610189,.004360654857009649)}
    for name,expected in known.items(): assert np.allclose(list(full_statistics[name].values()),expected,rtol=3e-6,atol=2e-9),(name,full_statistics[name])
    full_evidence={'scope':'FULL ORIGINAL 512x512 ROI, not the bundled small crop','common_mask_pixels':8048,
        'frames':FRAMES,'reference':REFERENCE,'metrics':full_statistics,'calibration_against_prior_measured_numbers':True,
        'composition_order':'sum FP16-decoded specular+diffuse as float32 before bilinear sampling; then cast float32',
        'source_capture_manifest_sha256':sha(source.manifest_bytes),
        'recompute':'export --source-capture PATH; source data is required for full-ROI reproduction'}
    (out/'full_roi_evidence.json').write_text(json.dumps(full_evidence,indent=2),encoding='utf8')
    all_raw=np.stack(raw_spec);all_sel=np.stack(selected_spec);all_diff=np.stack(diffuse)
    width,height=192,160
    while True:
        crop=best_crop(common,width,height);x0,y0,x1,y1=crop
        def cut(a):return np.ascontiguousarray(np.asarray(a)[:,y0:y1,x0:x1])
        frozen=common[y0:y1,x0:x1].copy();frozen[:6]=False;frozen[-6:]=False;frozen[:,:6]=False;frozen[:,-6:]=False
        raw=cut(all_raw);selected=cut(all_sel);diff=cut(all_diff)
        path=out/'glass_crop.npz'
        np.savez_compressed(path,aligned_raw_spec_rgb=raw,
            aligned_selected_spec_rgb_xor=np.bitwise_xor(raw.view('<u4'),selected.view('<u4')),
            aligned_equal_diffuse_rgb=diff,common_mask=frozen,
            original_normal_roughness_u32=cut(normal_original),original_depth_f32=cut(depth_original),
            original_motion_rgba_f16=cut(motion_original),aligned_original_eligibility=cut(eligible_masks),
            aligned_prior_glass_mask=cut(old_masks),alignment_valid=cut(valid_masks),
            camera_view_words_u32=np.stack(view_words),camera_projection_words_u32=np.stack(projection_words))
        if path.stat().st_size<19_500_000:break
        width-=32;height-=32
        assert width>=96 and height>=96,'export exceeds compact-fixture budget'
    statistics=metrics(raw+diff,selected+diff,frozen)
    manifest={'schema':'captured-glass-cpu-fixture-v1','capture_uuid':UUID,
        'capture_status':{'published_frames':source.published,'complete':source.manifest.get('complete'),
                          'only_published_frames_read':True},
        'source_capture_manifest_sha256':sha(source.manifest_bytes),'frames':FRAMES,'reference_frame':REFERENCE,
        'original_roi':{'origin':[source.x,source.y],'extent':[source.width,source.height]},
        'render_extent':[source.rw,source.rh],'fixture_crop_in_original_roi_xyxy':crop,
        'crop_selection':'maximum original common-mask coverage for 192x160 initial crop, before reading quality metrics; 6px metric halo excluded',
        'fixture_common_mask_pixels':int(frozen.sum()),'full_roi_common_mask_pixels_separate_evidence':8048,
        'fixture_metrics':statistics,'data_file':path.name,'data_sha256':sha(path.read_bytes()),'data_bytes':path.stat().st_size,
        'display_exposure':exposure,'exposure_origin':'0.8 / p97(luma(selected specular+diffuse)), original full ROI frame55',
        'display_tonemap':'uint8(255 * (max(rgb,0)*exposure/(1+max(rgb,0)*exposure))**(1/2.2))',
        'policy':'raw + float32(k)*(selected-raw), k=.5 or .75; common full vertical gate |nz|<=.5; no output FP16 re-quantization',
        'fixture_composition_order':'aligned float32 specular + aligned float32 equal diffuse; differs in rounding order from separate prior full-ROI evidence',
        'alignment':'reference-depth camera-only reprojection, P00/P11 convention, bilinear source sampling; no source-depth occlusion or dynamic-motion compensation',
        'geometry_provenance':'original_* arrays are UNWARPED source-frame crop values in exact stored dtype; aligned eligibility/masks are separate booleans',
        'eligibility':'original roughness code<=2, finite abs(depth)>1e-5 and<500; independent of modified variants',
        'prior_glass_mask':'original captured raw-vs-selected spec RGB difference AND decoded abs(nz)<=.5 AND abs(depth)<500, warped >.999; frozen before all policy variants',
        'reference_warning':'Game capture has NO ground truth. Captured selected is OLD NZR output, not a reference for a new algorithm.',
        'diffuse_equality':{'full_roi_fp16_words':sum(x['words'] for x in diffuse_proof),'differing_words':0,'frames':diffuse_proof},
        'source_payloads':source.hashes,
        'export_code_sha256':sha(Path(__file__).read_bytes()),'dependencies':['Python standard library','NumPy']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps({'crop':crop,'common_pixels':int(frozen.sum()),'data_bytes':path.stat().st_size,'metrics':statistics},indent=2))

def analyze(folder=HERE):
    folder=Path(folder); manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    path=folder/manifest['data_file'];assert sha(path.read_bytes())==manifest['data_sha256'],'fixture hash mismatch'
    with np.load(path,allow_pickle=False) as f:
        raw=f['aligned_raw_spec_rgb']; selected=np.bitwise_xor(raw.view('<u4'),f['aligned_selected_spec_rgb_xor']).view('<f4')
        diff=f['aligned_equal_diffuse_rgb']; mask=f['common_mask']
        assert raw.dtype==np.float32 and selected.dtype==np.float32
        assert f['original_normal_roughness_u32'].dtype==np.uint32
        assert f['original_depth_f32'].dtype==np.float32 and f['original_motion_rgba_f16'].dtype==np.float16
        assert mask.sum()==manifest['fixture_common_mask_pixels']
        assert np.all(~mask|np.logical_and.reduce(f['aligned_prior_glass_mask']&f['alignment_valid']))
        rows=metrics(raw+diff,selected+diff,mask)
    return rows,manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('export');p.add_argument('--source-capture',required=True,type=Path);p.add_argument('--out',type=Path,default=HERE)
    p=sub.add_parser('analyze');p.add_argument('--fixture',type=Path,default=HERE)
    args=parser.parse_args()
    if args.mode=='export':export(args.source_capture,args.out)
    else:print(json.dumps(analyze(args.fixture)[0],indent=2))
if __name__=='__main__':main()
