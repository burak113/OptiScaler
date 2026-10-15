"""Paired MSE scoring; oracle arrays never enter a recovery operator.

Intervals are an empirical within-sequence block-bootstrap diagnostic, not a
population/game-quality confidence claim. Full-crop eight-frame blocks retain
spatial covariance instead of treating every pixel as independent evidence.
Independent many-sample reference replicas must agree on the direction.
"""
import numpy as np


class PairedMSE:
    def __init__(self,crop,temporal_block=8,replicas=2000,seed=22945830):
        self.crop = tuple(crop)
        self.temporal_block = temporal_block
        self.replicas = replicas
        self.seed = seed
        self.frames = 0
        self.blocks = {}
        self.disagreement_sum = 0.
        self.disagreement_count = 0

    def update(self,index,baseline,candidate,references):
        if index!=self.frames:
            raise ValueError('paired uncertainty requires each complete sequential frame exactly once')
        if 'mean' not in references:
            raise ValueError('explicit mean reference is required')
        x,y,w,h = self.crop
        cut = np.s_[y:y+h,x:x+w,:3]
        base,recovered = np.asarray(baseline,np.float64)[cut],np.asarray(candidate,np.float64)[cut]
        if base.shape!=(h,w,3) or recovered.shape!=base.shape or not np.isfinite(recovered).all():
            raise ValueError('finite paired RGB in the original fixed crop is required')
        block = index//self.temporal_block
        for name,reference in references.items():
            ref = np.asarray(reference,np.float64)[cut]
            if ref.shape!=base.shape or not np.isfinite(ref).all():
                raise ValueError('independent reference shape/finite mismatch')
            a,b = (base-ref)**2,(recovered-ref)**2
            values = self.blocks.setdefault(name,{})
            sums = values.setdefault(block,np.zeros(3,np.float64))
            sums += float(a.sum()),float(b.sum()),a.size
        if 'a' in references and 'b' in references:
            delta = np.asarray(references['a'],np.float64)[cut]-np.asarray(references['b'],np.float64)[cut]
            self.disagreement_sum += float(np.sum(delta*delta))
            self.disagreement_count += delta.size
        self.frames += 1

    def summarize(self):
        if not self.frames:
            raise ValueError('no paired samples')
        output = {}
        rng = np.random.default_rng(self.seed)
        for name,by_block in self.blocks.items():
            rows = np.stack([by_block[key] for key in sorted(by_block)])
            total = rows.sum(0)
            delta = (total[1]-total[0])/total[2]
            selections = rng.integers(0,len(rows),(self.replicas,len(rows)))
            boot = rows[selections].sum(1)
            distribution = (boot[:,1]-boot[:,0])/boot[:,2]
            interval = np.quantile(distribution,(.025,.975))
            output[name] = dict(baseline_mse=float(total[0]/total[2]),candidate_mse=float(total[1]/total[2]),
                candidate_minus_baseline_mse=float(delta),
                relative_mse_change=float((total[1]-total[0])/total[0]) if total[0] else None,
                paired_temporal_block_95=[float(v) for v in interval],
                temporal_blocks=len(rows),rgb_components=int(total[2]),
                blocks_with_negative_delta=int(np.sum(rows[:,1]<rows[:,0])))
        replicas = [output[name] for name in ('a','b') if name in output]
        return dict(references=output,frames=self.frames,temporal_block_frames=self.temporal_block,
            spatial_block='entire original fixed crop',bootstrap_draws=self.replicas,bootstrap_seed=self.seed,
            independent_reference_replicas_present=len(replicas)==2,
            both_replicas_improve=(all(v['candidate_minus_baseline_mse']<0 for v in replicas) if len(replicas)==2 else None),
            both_replica_block_upper_below_zero=(all(v['paired_temporal_block_95'][1]<0 for v in replicas) if len(replicas)==2 else None),
            reference_replica_disagreement_rmse=(float(np.sqrt(self.disagreement_sum/self.disagreement_count)) if self.disagreement_count else None),
            mean_reference_independent_mc_noise_rmse_estimate=(float(.5*np.sqrt(self.disagreement_sum/self.disagreement_count)) if self.disagreement_count else None),
            scope='paired empirical fixed-history intervals only; eight independent temporal blocks are not a game-quality or across-noise-seed guarantee')
