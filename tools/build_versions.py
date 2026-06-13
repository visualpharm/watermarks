#!/usr/bin/env python3
"""Attack each watermark version with AI removers + forensic-score the result,
then emit versions.json for the UI. Run from the img-forensic dir."""
import json, os, subprocess, sys
import forensic
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "watermark-demo")
PY = os.path.join(HERE, ".venv/bin/python")
PROMPT = "/tmp/wm_remove_prompt.txt"

ATTACKERS = [("Flux Kontext", "fal-ai/flux-pro/kontext", "kontext"),
             ("nano-banana", "fal-ai/nano-banana/edit", "nano")]

META = {
 "v1": dict(title="Initial", visibility="High", protection="Low",
   commit="feat(wm): v1 initial — fused multiply preview + behind-edge occlusion "
          "+ loud diagonal PREVIEW/SAMPLE decoy",
   approach="A fused multiply pass over the whole object plus a behind-the-edges "
            "layer and a loud full-canvas PREVIEW/SAMPLE decoy. Reads as protected "
            "but the decoy is a separable overlay — easy for a model to strip."),
 "v2": dict(title="Kontext-patch", visibility="High", protection="High",
   commit="feat(wm): v2 kontext-patch — bake PREVIEW into cardboard (per-face "
          "perspective), green label + barcode, FRAGILE sticker, cast-shadow "
          "dither; entangled so removal is destructive",
   approach="PREVIEW is multiplied INTO the cardboard per box face (perspective "
            "shear + lighting), woven into the green label and its barcodes, "
            "printed into the FRAGILE sticker, and dithered into the cast shadow. "
            "Removing it means rebuilding the asset."),
 "v3": dict(title="Low-visibility", visibility="Low", protection="High (~95%)",
   commit="perf(wm): v3 low-visibility — drop the loud removable decoy + dense "
          "grid + behind layer; keep only the entangled object-local marks "
          "(~95% protection at a fraction of the visual noise)",
   approach="Drops the methods that are invasive AND easily removed (the loud "
            "decoy, the SAMPLE grid, the background layer) and keeps only the "
            "entangled, hard-to-remove marks baked into cardboard, label, "
            "barcode and sticker. Much cleaner preview, nearly the same protection."),
 "v4": dict(title="Poison", visibility="Low", protection="Maximum",
   commit="feat(wm): v4 poison — v3 + irreversible mosaic/scramble of the "
          "hard-to-redraw regions (FRAGILE sticker + green-label barcodes) so a "
          "remover can't restore them",
   approach="On top of v3, the hardest-to-redraw regions (the FRAGILE sticker and "
            "the green-label barcodes) are mosaicked and channel-scrambled "
            "irreversibly. Even a perfect watermark remover cannot recover the "
            "original detail — the information is gone."),
}
ORDER = ["v1", "v2", "v3", "v4"]


def attack(src, out, model):
    env = dict(os.environ)
    r = subprocess.run([PY, "/tmp/fal_edit2.py", src, out, model, PROMPT],
                       env=env, capture_output=True, text=True, timeout=400)
    return r.returncode == 0 and os.path.exists(out)


def main():
    clean = os.path.join(DEMO, "wm-clean.png")
    versions = []
    for vid in ORDER:
        img = os.path.join(DEMO, f"wm-{vid}.png")
        entry = dict(id=vid, image=f"wm-{vid}.png", **META[vid], attacks=[])
        for name, model, slug in ATTACKERS:
            out = os.path.join(DEMO, f"wm-{vid}-{slug}.png")
            ok = attack(img, out, model)
            a = dict(model=name)
            if not ok:
                a.update(image=None, verdict="refused",
                         summary="The model refused or failed to remove the watermark.")
            else:
                res = forensic.analyze(Image.open(clean), Image.open(out),
                                       want_heatmap=False)
                a.update(image=f"wm-{vid}-{slug}.png", verdict=res["verdict"],
                         confidence=res["confidence"], summary=res["summary"])
            entry["attacks"].append(a)
            print(f"  {vid} / {name}: {a['verdict']}")
        versions.append(entry)
    with open(os.path.join(DEMO, "versions.json"), "w") as f:
        json.dump({"base": "wm-clean.png", "versions": versions}, f, indent=2)
    print("wrote versions.json")


if __name__ == "__main__":
    main()
