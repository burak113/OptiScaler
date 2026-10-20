"""Non-destructive synchronized evidence frames, NumPy + Python stdlib only.

Writes lossless RGB PNGs and a local HTML viewer. No new image is presented as
ground truth. All stages use fixed BASE exposure and identical crop/aspect.
"""
from __future__ import annotations

import argparse
import html
import json
import struct
import zlib
from pathlib import Path

import numpy as np

import recorded_analysis as r
from support_tracer import trace_stages


def png_bytes(rgb):
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected RGB uint8 HxWx3")
    h, w = rgb.shape[:2]
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind+payload) & 0xffffffff)
    scan = b"".join(b"\0" + row.tobytes() for row in rgb)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(scan, 6)) + chunk(b"IEND", b"")


def display(rgb, exposure, valid=None):
    x = np.asarray(rgb, float)
    out = (np.power(np.clip(np.nan_to_num(x, nan=0) * exposure, 0, 1), 1/2.2) * 255 + .5).astype(np.uint8)
    if valid is not None:
        yy, xx = np.mgrid[:valid.shape[0], :valid.shape[1]]
        checker = np.where(((xx//5 + yy//5) % 2)[..., None] != 0, np.array([95, 25, 35]), np.array([35, 15, 20])).astype(np.uint8)
        out[~valid] = checker[~valid]
    return out


def outline(rgb, mask):
    out = rgb.copy()
    inner = mask.copy()
    inner[1:] &= mask[:-1]; inner[:-1] &= mask[1:]
    inner[:, 1:] &= mask[:, :-1]; inner[:, :-1] &= mask[:, 1:]
    out[mask & ~inner] = (60, 220, 255)
    return out


def recorded_frames(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    a, meta = r.loader.load_clip(r.PACKAGE / "fixtures/clips/bottle_track7.npz")
    masks, contract = r.freeze_contract(a, "bottle_track7")
    stages={"input_diffuse": a["input_diffuse"], "input_specular": a["input_specular"]}
    traces=list(trace_stages(stages,a["input_motion"],a["crop_origin_render"],a["render_extent"],a["frame_indices"],{k:.001 for k in stages},
                            comparison_breaks=(a["provider_controls"][:,45]&1)!=0))
    frames = []
    for t, frame in enumerate(a["frame_indices"]):
        h, w = a["input_depth"].shape[1:]
        sheet = np.full((2*h+4, 5*w+16, 3), 18, np.uint8)
        for row, lobe in enumerate(("diffuse", "specular")):
            current = a["input_"+lobe][t, ..., :3].astype(np.float32)
            if t:
                qx, qy, valid = r.loader.previous_coordinates(a, t)
                previous, _ = r.loader.sample_previous(a["input_"+lobe][t-1, ..., :3].astype(np.float32), qx, qy)
            else:
                previous = np.full_like(current, np.nan)
                valid = np.zeros((h, w), bool)
            exposure = contract["exposure"][lobe]
            raw = a["raw_rr_"+lobe][t, ..., :3].astype(np.float32)
            selected = a["selected_rr_"+lobe][t, ..., :3].astype(np.float32)
            traced=traces[t]["stages"]["input_"+lobe]
            current_support = traced["current_support"]
            previous_support = np.nan_to_num(traced["transported_previous_support"]) > .5
            valid = valid & traced["history_valid"]
            support = np.zeros_like(current, dtype=np.uint8) + 15
            support[current_support & valid] = (225, 70, 180)
            support[previous_support & valid] = (45, 220, 130)
            support[current_support & previous_support & valid] = (245, 220, 70)
            support[~valid] = (95, 25, 35)
            panels = [display(current, exposure), display(previous, exposure, valid), display(raw, exposure), display(selected, exposure), support]
            for col, panel in enumerate(panels):
                sheet[row*(h+4):row*(h+4)+h, col*(w+4):col*(w+4)+w] = outline(panel, masks[t])
        filename = f"bottle_f{int(frame)}.png"
        (out / filename).write_bytes(png_bytes(sheet))
        frames.append({"frame": int(frame), "image": filename, "origin": a["crop_origin_render"][t].tolist(),
                       "mask_pixels": int(masks[t].sum())})
    info = {"schema": "astra.job06.visual_evidence.v1", "frames": frames,
            "source_archive_sha256": meta["archive"]["sha256"], "display_gamma": 2.2,
            "source_frame_duration_seconds": None, "synchronized_by": "captured original frame index",
            "exposure": contract["exposure"], "threshold_native_luma": .001,
            "support_operator": "threshold prior radiance then bilinear transport binary coverage; majority >0.5, mixed coverage remains an uncertainty proxy",
            "row_order": ["diffuse", "specular"], "column_order": ["current input", "transported previous input", "raw RR", "selected output", "support overlap"],
            "not_displayed": "Final title composition/video is not available; no simulated final image is substituted.",
            "original_evidence_modified": False}
    (out / "visual_manifest.json").write_text(json.dumps(info, indent=2, allow_nan=False)+"\n")
    captions = ["Güncel girdi", "Taşınan önceki girdi", "Ham RR", "Seçilmiş çıktı", "Destek örtüşmesi"]
    names = "".join("<span>"+html.escape(x)+"</span>" for x in captions)
    page = """<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job 06 — Şişe destek izleyicisi</title><style>
body{background:#10141b;color:#e8eef6;font:16px/1.5 system-ui;margin:0 auto;padding:28px;max-width:1100px}h1{font-size:27px}.note{background:#1c2635;padding:14px;border-radius:8px}.labels{display:grid;grid-template-columns:repeat(5,1fr);text-align:center;font-size:14px;gap:4px;margin:10px 0}img{display:block;width:100%;height:auto;image-rendering:auto}button{padding:9px 18px;background:#263a52;color:white;border:1px solid #6485a7;border-radius:6px}input{width:50%;vertical-align:middle;margin:0 14px}.cyan{color:#3cdcff}.magenta{color:#e146b4}.green{color:#2ddc82}.yellow{color:#f5dc46}.small{font-size:14px;color:#bbc8d8}
</style><h1>Hareketli şişe: eşzamanlı destek izleyicisi</h1>
<p class="note">Üst sıra diffuse, alt sıra specular. Her aşama aynı kareyi, aynı kırpmayı ve kanal başına sabit pozlamayı kullanır. Görüntüler kayıtlı GPU tensörlerinden CPU üzerinde hazırlanmıştır. Yeni bir RR çalıştırması veya oyun çıktısı değildir.</p>
<div><button onclick="step(-1)">Önceki</button><input id="slider" aria-label="Kare" type="range" min="0" max="6" value="0"><button onclick="step(1)">Sonraki</button></div>
<h2 id="label"></h2><div class="labels">__CAPTIONS__</div><img id="frame" alt="Diffuse ve specular aşamalarının aynı karede karşılaştırması">
<p><span class="cyan">Camgöbeği sınır:</span> değişmeyen BASE hareket maskesi (şişe + el/kol). <span class="magenta">Pembe:</span> yalnız güncel parlak destek. <span class="green">Yeşil:</span> yalnız taşınmış önceki destek. <span class="yellow">Sarı:</span> her ikisi. Koyu kırmızı: önceki kırpmanın dışında veya ilk karede bilinmeyen geçmiş.</p>
<p class="small">Parlak destek eşiği: native pre-remod luma &gt; 0.001. Son sütunda önceki ikili destek bilineer taşınır; ağırlıklı kapsama &gt; 0.5 ise parlak sayılır. Bu işlem, ikinci sütundaki taşınmış radyansı eşiklemekle aynı değildir. Kısmi kapsama belirsizdir. Bu eşik bir nesne silueti tanımlamaz; seyrek örnek, değişen ışık ve specular özellikler de maskeyi etkiler. Rapor 0, 0.0001, 0.001 ve 0.01 eşiklerini ayrı verir. Kare süresi pakette bulunmadığı için otomatik oynatma yoktur. Final remod/oyun videosu mevcut değildir. Kaynak veriler değiştirilmemiştir.</p>
<script>const frames=__FRAMES__;const slider=document.getElementById('slider');function show(){const f=frames[+slider.value];document.getElementById('label').textContent=`Kare ${f.frame} · global kırpma (${f.origin}) · maske ${f.mask_pixels} piksel`;document.getElementById('frame').src=f.image}function step(x){slider.value=Math.max(0,Math.min(6,+slider.value+x));show()}slider.oninput=show;show();</script></html>"""
    (out / "index.html").write_text(page.replace("__FRAMES__", json.dumps(frames)).replace("__CAPTIONS__", names), encoding="utf-8")
    return info


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=r.HERE / "evidence/visuals")
    data = recorded_frames(ap.parse_args().out)
    print(json.dumps({"frames": len(data["frames"]), "source_frame_duration_seconds": None, "gpu_executed": False}))
