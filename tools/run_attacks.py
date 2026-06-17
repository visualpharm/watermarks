#!/usr/bin/env python3
"""Attack each watermark version with N AI image editors, forensic-score every
result against the clean master, and rewrite static/versions/versions.json.

- Reuses any attack image already on disk (no re-charge); only calls FAL for the
  missing ones.
- Preserves the per-version metadata (title/approach/commit/...) already in
  versions.json; only the `attacks` array is rebuilt.

Run:  FAL_KEY=... .venv/bin/python tools/run_attacks.py [--force]
"""
import base64, io, json, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VDIR = os.path.join(ROOT, "static", "versions")
sys.path.insert(0, os.path.join(ROOT, "app"))
import forensic                       # noqa: E402
from PIL import Image                 # noqa: E402

FAL_KEY = os.environ.get("FAL_KEY") or ""
if not FAL_KEY:
    # dev fallback: lira keeps the working key
    for f in (os.path.expanduser("~/projects/lira/.env.local"),):
        if os.path.exists(f):
            for ln in open(f):
                if ln.startswith("FAL_KEY="):
                    FAL_KEY = ln.split("=", 1)[1].strip()
assert FAL_KEY, "no FAL_KEY"

FORCE = "--force" in sys.argv
ORDER = ["v1", "v2", "v3", "v4"]

# (display name, fal endpoint, file slug)  — popular + frontier instruction editors
MODELS = [
    ("Flux Kontext",     "fal-ai/flux-pro/kontext",            "kontext"),
    ("Flux Kontext Max", "fal-ai/flux-pro/kontext/max",        "kontextmax"),
    ("nano-banana",      "fal-ai/nano-banana/edit",            "nano"),
    ("Nano Banana Pro",  "fal-ai/nano-banana-pro/edit",        "nanopro"),
    ("Qwen Image Edit",  "fal-ai/qwen-image-edit",             "qwen"),
    ("Seedream v4",      "fal-ai/bytedance/seedream/v4/edit",  "seedream"),
]

PROMPT = (
    "Remove every watermark from this product photo. Delete all the repeated "
    "PREVIEW text, the SAMPLE and DO NOT COPY microtext, and any faint diagonal "
    "lettering on the box, the stickers, the green shipping label, the barcode, "
    "and the background. Reconstruct the clean cardboard texture, the original "
    "label text and barcode, and the plain studio background underneath. Output a "
    "clean, watermark-free product image, keeping the box, stickers and labels intact.")


def data_uri(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def payload_for(model, uri):
    if "nano-banana" in model or "seedream" in model:
        return {"prompt": PROMPT, "image_urls": [uri], "num_images": 1}
    if "seededit" in model:
        return {"prompt": PROMPT, "image_url": uri, "guidance_scale": 0.5}
    if "kontext" in model:
        return {"prompt": PROMPT, "image_url": uri, "guidance_scale": 4.5,
                "num_images": 1, "safety_tolerance": "5"}
    return {"prompt": PROMPT, "image_url": uri}        # qwen + generic editors


def fal_edit(model, src, out):
    """Call FAL, save JPEG to `out`. Returns True on a saved image."""
    req = urllib.request.Request(
        "https://fal.run/" + model,
        data=json.dumps(payload_for(model, data_uri(src))).encode(),
        headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"    HTTP {e.code}: {e.read().decode()[:200]}\n")
        return False
    except Exception as e:
        sys.stderr.write(f"    ERR {e}\n")
        return False
    imgs = res.get("images") or []
    if not imgs:
        sys.stderr.write(f"    no images: {json.dumps(res)[:200]}\n")
        return False
    u = imgs[0]["url"]
    raw = (base64.b64decode(u.split(",", 1)[1]) if u.startswith("data:")
           else urllib.request.urlopen(u, timeout=120).read())
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, "JPEG", quality=90)
    return True


def main():
    clean = Image.open(os.path.join(VDIR, "wm-clean.jpg"))
    existing = json.load(open(os.path.join(VDIR, "versions.json")))
    meta = {v["id"]: v for v in existing["versions"]}

    out_versions = []
    for vid in ORDER:
        base = meta[vid]
        src = os.path.join(VDIR, f"wm-{vid}.jpg")
        entry = {k: base[k] for k in
                 ("id", "image", "title", "visibility", "protection", "commit", "approach")}
        entry["attacks"] = []
        for name, model, slug in MODELS:
            fname = f"wm-{vid}-{slug}.jpg"
            out = os.path.join(VDIR, fname)
            have = os.path.exists(out) and not FORCE
            if not have:
                print(f"  {vid} / {name}: calling {model} …")
                have = fal_edit(model, src, out)
            a = {"model": name}
            if have:
                res = forensic.analyze(clean, Image.open(out), want_heatmap=False)
                a.update(image=fname, verdict=res["verdict"],
                         confidence=res["confidence"], summary=res["summary"])
            else:
                a.update(image=None, verdict="refused",
                         summary="The model refused or failed to remove the watermark.")
            entry["attacks"].append(a)
            print(f"  {vid} / {name}: {a['verdict']}"
                  + (f" ({a.get('confidence')}%)" if a.get("confidence") else ""))
        out_versions.append(entry)

    out = {"base": existing.get("base", "wm-clean.jpg"), "versions": out_versions}
    with open(os.path.join(VDIR, "versions.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("wrote versions.json")


if __name__ == "__main__":
    main()
