#!/usr/bin/env python3
"""Build pre-filled detector history from real icons8 3D-Stickle illustrations.

Creates A/B test pairs (clean rescale, AI manipulation, edit), forensic-scores
each, saves the full images to static/examples/ and writes
static/example-history.json (verdict + 64px thumbnails + reload filenames) so the
detector can seed its history and reload any test on click.

Run:  FAL_KEY=... .venv/bin/python tools/build_detector_examples.py
"""
import base64, io, json, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = "/tmp/stickle"
EXD = os.path.join(ROOT, "static", "examples")
os.makedirs(EXD, exist_ok=True)
sys.path.insert(0, os.path.join(ROOT, "app"))
import forensic                       # noqa: E402
from PIL import Image, ImageFilter    # noqa: E402
import numpy as np                    # noqa: E402

FAL_KEY = os.environ.get("FAL_KEY") or ""
if not FAL_KEY:
    f = os.path.expanduser("~/projects/lira/.env.local")
    if os.path.exists(f):
        for ln in open(f):
            if ln.startswith("FAL_KEY="):
                FAL_KEY = ln.split("=", 1)[1].strip()


def cutout(im):
    """Alpha-cut the colorful subject off the white studio background + soft
    shadow, so the foreground mask is stable across a uniform rescale."""
    a = np.asarray(im.convert("RGB")).astype(int)
    val = a.max(2); sat = a.max(2) - a.min(2)
    opaque = (sat > 28) | (val < 165)
    alpha = (Image.fromarray((opaque * 255).astype("uint8"))
             .filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5)))
    out = im.convert("RGBA"); out.putalpha(alpha); return out


def fal_edit(model, src_path, out_path, prompt):
    if os.path.exists(out_path):
        return True
    uri = "data:image/jpeg;base64," + base64.b64encode(open(src_path, "rb").read()).decode()
    pl = {"prompt": prompt, "image_urls": [uri], "num_images": 1}
    req = urllib.request.Request("https://fal.run/" + model, data=json.dumps(pl).encode(),
        headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"}, method="POST")
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=240).read())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"  FAL {e.code}: {e.read().decode()[:160]}\n"); return False
    imgs = res.get("images") or []
    if not imgs:
        return False
    u = imgs[0]["url"]
    raw = (base64.b64decode(u.split(",", 1)[1]) if u.startswith("data:")
           else urllib.request.urlopen(u, timeout=120).read())
    Image.open(io.BytesIO(raw)).convert("RGB").save(out_path, "JPEG", quality=92)
    return True


def thumb(path, mx=72):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (247, 244, 237, 255)); bg.alpha_composite(im)
    im = bg.convert("RGB")
    s = mx / max(im.size)
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=62)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    box = Image.open(f"{SRC}/box.jpg")
    suit = Image.open(f"{SRC}/suitcase.jpg").convert("RGB")
    robot = Image.open(f"{SRC}/robot.jpg").convert("RGB")
    pairs = []   # (case, title, label, fileA, fileB)

    # 1) CLEAN RESCALE — alpha cutout, uniform downscale, nothing else touched
    coA = cutout(box); coA.save(os.path.join(EXD, "box-orig.png"))
    coB = coA.resize((864, 864), Image.LANCZOS); coB.save(os.path.join(EXD, "box-rescale.png"))
    pairs.append(("box", "Box illustration · uniform downscale",
                  "Same asset, scaled down — nothing altered", "box-orig.png", "box-rescale.png"))

    # 2) MANIPULATED — a real AI editor reconstructs the object (sticker/logo removal)
    suit.save(os.path.join(EXD, "suitcase-orig.jpg"), "JPEG", quality=92)
    bp = os.path.join(EXD, "suitcase-ai.jpg")
    if not fal_edit("fal-ai/bytedance/seedream/v4/edit", os.path.join(EXD, "suitcase-orig.jpg"), bp,
                    "Remove every sticker, label, badge and logo from this suitcase and "
                    "reconstruct the clean surface underneath. Keep the suitcase shape, "
                    "color and the background otherwise identical."):
        fal_edit("fal-ai/flux-pro/kontext", os.path.join(EXD, "suitcase-orig.jpg"), bp,
                 "Remove all stickers and logos; reconstruct the clean suitcase surface.")
    pairs.append(("suitcase", "Suitcase illustration · AI sticker removal",
                  "An AI editor erased the stickers — surface reconstructed",
                  "suitcase-orig.jpg", "suitcase-ai.jpg"))

    # 3) EDITED — subject intact, but distorted (non-uniform stretch)
    robot.save(os.path.join(EXD, "robot-orig.jpg"), "JPEG", quality=92)
    robot.resize((1340, 980), Image.LANCZOS).save(os.path.join(EXD, "robot-edited.jpg"), "JPEG", quality=92)
    pairs.append(("robot", "Robot illustration · non-uniform stretch",
                  "Subject distorted — stretched, not uniformly scaled",
                  "robot-orig.jpg", "robot-edited.jpg"))

    hist = []
    ages = [12, 95, 1610]   # minutes ago
    for (case, title, label, fa, fb), age in zip(pairs, ages):
        res = forensic.analyze(Image.open(os.path.join(EXD, fa)),
                               Image.open(os.path.join(EXD, fb)), want_heatmap=False)
        print(f"  {case:9} -> {res['verdict']} ({res['confidence']}%)")
        hist.append({"case": case, "title": title, "label": label,
                     "verdict": res["verdict"], "conf": res["confidence"], "ageMin": age,
                     "fileA": fa, "fileB": fb,
                     "a": thumb(os.path.join(EXD, fa)), "b": thumb(os.path.join(EXD, fb))})

    with open(os.path.join(ROOT, "static", "example-history.json"), "w") as f:
        json.dump({"items": hist, "source": "icons8.com/illustrations/style--3d-stickle"}, f, indent=2)
    print(f"wrote example-history.json ({len(hist)} items)")


if __name__ == "__main__":
    main()
