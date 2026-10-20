"""Reproducible evidence figures; no generated art and no claimed GPU candidate.

Optional rendering dependencies are in requirements-figures.txt. CPU tests and
numerical experiments need only the baseline NumPy requirement.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir())/"job07-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE/"src"))
import analyze_captures as captures
from foliage_guides import GuideFrame, observe_guides

OUT = HERE/"evidence/figures"


def display_rgb(rgb, exposure):
    # Display mapping only, identically applied to BASE and its identity copy.
    x = np.maximum(rgb.astype(np.float64)*exposure, 0)
    return np.power(x/(1+x), 1/2.2)


def save(fig, name):
    path=OUT/name
    fig.savefig(path,dpi=150,facecolor="white",bbox_inches="tight")
    plt.close(fig)
    return {"file":path.relative_to(HERE).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}


def captured_plates():
    result=[]
    for name in captures.CLIPS:
        a,meta=captures.LOADER.load_clip(captures.PACKAGE/"fixtures/clips"/(name+".npz"))
        masks,_=captures.freeze_or_check_masks(name,a,meta,HERE/"evidence")
        baseline=a["selected_rr_diffuse"][...,:3].astype(np.float32)+a["selected_rr_specular"][...,:3].astype(np.float32)
        # Single immutable BASE exposure, common to every frame and comparison.
        exposure=.8/max(float(np.percentile(baseline[masks["core"]],99)),1e-12)
        t=len(a["frame_indices"])//2
        def frame(i):
            return GuideFrame(a["recovery_original_normal_roughness"][i],a["input_depth"][i],a["input_motion"][i],
                              int(a["frame_indices"][i]),tuple(a["crop_origin_render"][i]),tuple(a["render_extent"]),True)
        observation=observe_guides(frame(t),frame(t-1),enabled=True)
        identity=baseline[t].copy()
        assert np.array_equal(identity.view(np.uint32),baseline[t].view(np.uint32))
        h,w=baseline[t].shape[:2]
        fig,axes=plt.subplots(1,3,figsize=(12, max(2.8,min(7.5,4*h/w+1.1))))
        axes[0].imshow(display_rgb(baseline[t],exposure),interpolation="nearest")
        axes[1].imshow(display_rgb(identity,exposure),interpolation="nearest")
        field=np.ma.masked_where(~observation.temporal_supported,observation.temporal_innovation)
        cmap=plt.get_cmap("magma").copy();cmap.set_bad("#b5b7be")
        im=axes[2].imshow(field,cmap=cmap,vmin=0,vmax=2,interpolation="nearest")
        titles=["BASE: recorded selected D + S", "Diagnostic ON: same recorded RGB", "CPU normal innovation (1 - dot)"]
        for ax,title in zip(axes,titles):
            ax.set_title(title,fontsize=10,pad=9);ax.set_xticks([]);ax.set_yticks([])
        fig.colorbar(im,ax=axes[2],fraction=.047,pad=.035,label="Gray = unsupported")
        fig.suptitle(f"{name}  |  capture frame {int(a['frame_indices'][t])}  |  {w} x {h}",fontsize=13,y=1.04)
        fig.text(.5,-.035,"Identity illustration only; no new RR execution. Same crop/aspect/exposure; displayed D+S is not the final game composite.",ha="center",fontsize=9)
        info=save(fig,name+"_identity_diagnostic.png")
        info.update({"source_archive_sha256":meta["archive"]["sha256"],"frame":int(a["frame_indices"][t]),
                     "exposure":exposure,"display_mapping":"(exposure*max(rgb,0)/(1+exposure*max(rgb,0)))**(1/2.2)",
                     "stage":"recorded selected-RR sum and CPU diagnostic; identical recorded RGB on both sides, not new candidate RR output"})
        result.append(info)
    return result


def bad_control():
    spec=importlib.util.spec_from_file_location("blind_control_plot",HERE/"review/blind_calibration.py")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    truth,normals,masks=mod.fixture()
    seed=mod.SEEDS[0]
    rng=np.random.default_rng(seed)
    noise=rng.normal(0,.09,(mod.FRAMES,)+truth.shape)
    noise+=.7*((rng.random(noise.shape)<.015).astype(np.float64)-.015)
    observed=truth[None]+noise
    exact=mod.guided_spatial(observed,normals)
    flat=mod.guided_spatial(observed,np.broadcast_to([0.,0.,1.],normals.shape))
    fig,axes=plt.subplots(1,3,figsize=(12,3.0))
    for ax,value,title in zip(axes,[truth,exact.mean(0),flat.mean(0)],
                             ["Analytic facade / window / text truth","CPU exact-normal surrogate","CPU flattened-normal control"]):
        ax.imshow(value,cmap="gray",vmin=.1,vmax=.8,interpolation="nearest")
        ax.set_title(title,fontsize=10);ax.set_xticks([]);ax.set_yticks([])
    fig.suptitle("Blind negative control: a lower flicker score can hide destroyed detail",fontsize=13,y=1.01)
    fig.text(.5,-.02,"Shared range .1-.8, same crop, 24-frame mean, seed17041. CPU surrogate only; historical AMD NormalEMA loss was not rerun.",ha="center",fontsize=9)
    return save(fig,"blind_facade_negative_control.png")


def captured_numeric():
    d=json.loads((HERE/"evidence/captured_with_candidate.json").read_text())
    names=[c["fixture"] for c in d["clips"]]
    x=np.arange(len(names));width=.32
    fig,axes=plt.subplots(1,3,figsize=(12,3.2))
    for j,role in enumerate(["input_diffuse","input_specular"]):
        y=[100*c["signals"][role]["exact_zero_rgb_fraction"] for c in d["clips"]]
        z=[100*c["signals"][role]["top_one_percent_positive_luma_energy_fraction"] for c in d["clips"]]
        label="Diffuse" if j==0 else "Specular"
        axes[0].bar(x+(j-.5)*width,y,width,label=label,color=["#276a9d","#da8330"][j])
        axes[1].bar(x+(j-.5)*width,z,width,color=["#276a9d","#da8330"][j])
    support=[100*c["candidate_diagnostic"]["temporal_supported"]["pair_fraction"] for c in d["clips"]]
    axes[2].bar(x,support,.6,color="#587d62")
    titles=["Exactly zero input RGB (%)","Energy carried by brightest1% (%)","Comparable guide pairs (%)"]
    for ax,title in zip(axes,titles):
        ax.set_title(title,fontsize=10);ax.set_xticks(x,names,rotation=16);ax.set_ylim(0,100);ax.grid(axis="y",alpha=.2);ax.set_axisbelow(True)
    axes[0].legend(frameon=False,fontsize=9)
    fig.suptitle("Captured inputs: sparse lighting and incomplete guide correspondence",fontsize=13,y=1.05)
    fig.text(.5,-.12,"Fixed BASE masks and denominators. Guide comparability is not semantic coverage or certified physical history; no GPU improvement measured.",ha="center",fontsize=9)
    return save(fig,"captured_evidence_summary.png")


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records=captured_plates()+[bad_control(),captured_numeric()]
    (OUT/"manifest.json").write_text(json.dumps({"executor":"root CPU rendering", "matplotlib":matplotlib.__version__,
        "numpy":np.__version__,"images":records},indent=2,allow_nan=False)+"\n")
    print("Rendered",len(records),"evidence figures")


if __name__=="__main__":
    main()
