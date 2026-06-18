#!/usr/bin/env python3
"""
Image-forensics: compare an ORIGINAL with a file UNDER REVIEW and classify it as

  clean_rescale  — a faithful, uniformly scaled copy; nothing touched
  edited         — the SUBJECT is intact, but its surroundings changed
                   (background added / removed / replaced, cropped, extended)
  manipulated    — the SUBJECT's own pixels were reconstructed
                   (watermark removal / AI inpainting / cloning)
  inconclusive   — can't align them, or signals conflict

How it works:
  1. Isolate the textured SUBJECT in each image (so a flat added background
     doesn't move the registration).
  2. Map the original onto the review frame on that subject.
  3. On the subject overlap, split error into EDGE error (normal resampling)
     vs FLAT error (the smoking gun for removal/inpainting), measured against
     each image's own baseline.
  4. Outside the subject, measure ADDED / REMOVED area (the edit signal).

Pure Pillow + numpy. Importable (analyze_bytes) and runnable as a CLI.
"""
import base64
import io
import json
import sys

import numpy as np
from PIL import Image, ImageFilter

MAX_DIM = 1500  # cap analysis resolution for speed

# ---------------------------------------------------------------- metadata ---
EDITOR_TELLS = {
    "photoshop": "Adobe Photoshop", "generative": "generative fill / AI",
    "firefly": "Adobe Firefly (AI)", "neural": "neural filter (AI)",
    "inpaint": "inpainting tool", "cleanup": "object/watermark cleanup",
    "watermarkremover": "watermark remover", "dewatermark": "watermark remover",
    "lama": "LaMa inpainting (AI)", "stable diffusion": "Stable Diffusion (AI)",
    "topaz": "Topaz (AI)", "gigapixel": "Topaz Gigapixel (AI upscaler)",
    "remini": "Remini (AI)", "midjourney": "Midjourney (AI)",
    "dall": "DALL-E (AI)", "gimp": "GIMP", "affinity": "Affinity Photo",
}
NEUTRAL_TELLS = ["canva", "figma", "sketch", "preview", "screenshot",
                 "imagemagick", "lightroom", "pixelmator"]


def _meta_text(im):
    bits = [f"{k}={v}" for k, v in (im.info or {}).items()]
    try:
        for k, v in im.getexif().items():
            bits.append(f"exif{k}={v}")
    except Exception:
        pass
    return " ".join(str(b) for b in bits)


def detect_software(im):
    t = _meta_text(im).lower()
    editors = sorted({lab for key, lab in EDITOR_TELLS.items() if key in t})
    neutral = sorted({key for key in NEUTRAL_TELLS if key in t})
    return editors, neutral


# --------------------------------------------------------------- geometry ---
def _foreground_mask(arr):
    h, w = arr.shape[:2]
    if arr.shape[2] == 4 and arr[:, :, 3].min() < 250:
        return arr[:, :, 3] > 24
    rgb = arr[:, :, :3].astype(np.int16)
    border = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    if np.std(border, axis=0).mean() > 40:
        return np.ones((h, w), bool)
    return np.abs(rgb - bg).max(axis=2) > 18


def _bbox(mask):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _morph(mask, size, grow=True):
    f = ImageFilter.MaxFilter(size) if grow else ImageFilter.MinFilter(size)
    return np.asarray(
        Image.fromarray((mask * 255).astype(np.uint8)).filter(f)) > 0


def _texture_mask(arr):
    """High-frequency (textured) regions — the real subject, not flat fills."""
    g = arr[:, :, :3].mean(2)
    e = (np.abs(np.diff(g, axis=1, prepend=g[:, :1])) +
         np.abs(np.diff(g, axis=0, prepend=g[:1, :])))
    dens = Image.fromarray(np.clip(e, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(5))
    return np.asarray(dens) > 9


def _subject_bbox(arr, fg):
    tex = _texture_mask(arr) & fg
    tex = _morph(tex, 7, grow=False)           # erode: drop thin flat-fill edges
    bb = _bbox(tex)
    if bb is None or (bb[2] - bb[0]) < 8 or (bb[3] - bb[1]) < 8:
        bb = _bbox(fg) or (0, 0, arr.shape[1], arr.shape[0])
    return bb


def _phase_shift(a, b, lim=0.12):
    a = a - a.mean(); b = b - b.mean()
    fa = np.fft.rfft2(a); fb = np.fft.rfft2(b)
    r = fa * np.conj(fb); r /= np.abs(r) + 1e-8
    c = np.fft.irfft2(r, s=a.shape)
    dy, dx = np.unravel_index(np.argmax(c), c.shape)
    if dy > a.shape[0] // 2:
        dy -= a.shape[0]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    if abs(dy) > lim * a.shape[0] or abs(dx) > lim * a.shape[1]:
        return 0, 0
    return int(dy), int(dx)


def _cap(im):
    if max(im.size) > MAX_DIM:
        s = MAX_DIM / max(im.size)
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                       Image.LANCZOS)
    return im


# --------------------------------------------------------------- analysis ---
def _align(A, B, ba_arr, fg_b, bxa, bxb):
    """Map original A onto B's frame aligning subject bbox bxa->bxb. None on fail."""
    aw, ah = bxa[2] - bxa[0], bxa[3] - bxa[1]
    bw, bh = bxb[2] - bxb[0], bxb[3] - bxb[1]
    if aw < 4 or ah < 4 or bw < 4 or bh < 4:
        return None
    sx, sy = bw / aw, bh / ah
    newA = A.resize((max(1, round(A.width * sx)), max(1, round(A.height * sy))),
                    Image.LANCZOS)
    canvasA = Image.new("RGBA", B.size, (0, 0, 0, 0))
    canvasA.paste(newA, (round(bxb[0] - bxa[0] * sx),
                         round(bxb[1] - bxa[1] * sy)))
    aa2 = np.asarray(canvasA).astype(np.int16)
    fg_a2 = aa2[:, :, 3] > 24
    both = fg_a2 & fg_b
    if both.sum() > 256:
        dy, dx = _phase_shift(aa2[:, :, :3].mean(2) * both,
                              ba_arr[:, :, :3].astype(np.int16).mean(2) * both)
        if dy or dx:
            aa2 = np.roll(aa2, (dy, dx, 0), axis=(0, 1, 2))
            fg_a2 = aa2[:, :, 3] > 24
    overlap = fg_a2 & fg_b
    if overlap.sum() < 64:
        return None
    diff = np.abs(aa2[:, :, :3] - ba_arr[:, :, :3]).max(axis=2)
    return {"aa2": aa2, "fg_a2": fg_a2, "overlap": overlap, "diff": diff,
            "median": float(np.median(diff[overlap])), "sx": sx,
            "aspect_a": aw / ah, "aspect_b": bw / bh}


def analyze(img_a, img_b, want_heatmap=True):
    soft_editors, soft_neutral = detect_software(img_b)
    A = _cap(img_a.convert("RGBA"))
    B = _cap(img_b.convert("RGBA"))
    aa, ba = np.asarray(A), np.asarray(B)
    fg_a, fg_b = _foreground_mask(aa), _foreground_mask(ba)

    # Try two registrations and keep whichever aligns the subject best:
    #  - exact foreground bbox (precise for a plain rescale)
    #  - textured-subject bbox (isolates the object when a flat background was
    #    added/replaced, which would otherwise blow up the foreground bbox)
    fa, fb = (_bbox(fg_a) or (0, 0, A.width, A.height)), \
             (_bbox(fg_b) or (0, 0, B.width, B.height))
    ta, tb = _subject_bbox(aa, fg_a), _subject_bbox(ba, fg_b)
    cands = [c for c in (_align(A, B, ba, fg_b, fa, fb),
                         _align(A, B, ba, fg_b, ta, tb)) if c]
    if not cands:
        return _inconclusive("No common subject found — the two files do not "
                             "look like the same image.", 20)
    R = min(cands, key=lambda c: c["median"])
    aa2, fg_a2, overlap, diff = R["aa2"], R["fg_a2"], R["overlap"], R["diff"]
    aspect_a, aspect_b = R["aspect_a"], R["aspect_b"]
    anisotropy = abs(aspect_a - aspect_b) / aspect_a
    sx = R["sx"]

    d = diff[overlap].astype(np.float32)
    median_all = float(np.median(d)); mean_all = float(d.mean())
    p95 = float(np.percentile(d, 95)); p99 = float(np.percentile(d, 99))

    if median_all > 50:
        return _inconclusive(
            f"The subjects differ too much to be the same image "
            f"(median diff {median_all:.0f}). Put the SAME object in both slots.",
            35, {"median_diff": median_all, "anisotropy_pct": anisotropy * 100})

    # Split the subject into TEXTURED vs truly SMOOTH areas by local texture
    # density (not per-pixel edges) — so sub-pixel scaling halos around stickers
    # /labels are excluded, and only genuinely flat surfaces feed removal
    # detection. Also stay in the deep interior (a new background recolors edges).
    textured = _morph(_texture_mask(aa2), 9)
    interior = _morph(fg_a2, 9, grow=False)
    flat = overlap & ~textured & interior
    edge_overlap = overlap & textured
    edge_err = float(diff[edge_overlap].mean()) if edge_overlap.sum() else 0.0
    flat_err = float(diff[flat].mean()) if flat.sum() else 0.0
    flat_hi_frac = float((diff[flat] > 42).mean()) if flat.sum() else 0.0

    # self-calibrating local anomaly (localized inpainting / removal)
    B_ = 16; h, w = diff.shape; bms = []
    for y in range(0, h - B_, B_):
        for x in range(0, w - B_, B_):
            fb = flat[y:y + B_, x:x + B_]
            if fb.sum() > B_ * B_ * 0.5:
                bms.append(diff[y:y + B_, x:x + B_][fb].mean())
    bms = np.array(bms) if bms else np.array([0.0])
    base_block = float(np.median(bms))
    mad = float(np.median(np.abs(bms - base_block))) * 1.4826 + 1e-6
    zb = (bms - base_block) / mad
    anom = (zb > 6.0) & (bms > 9.0)
    n_anom = int(anom.sum())
    anom_frac = float(n_anom / len(bms))
    max_excess = float((bms[anom] - base_block).max()) if n_anom else 0.0
    max_z = float(zb.max())

    # ---- surroundings: added / removed content (the EDIT signal) ----------
    box_a = _morph(fg_a2, 5)                    # original subject, a touch grown
    box_b = _morph(fg_b, 5)
    added = _morph(fg_b & ~box_a, 5, grow=False)    # open: drop AA specks
    removed = _morph(fg_a2 & ~box_b, 5, grow=False)
    added_frac = float(added.sum() / max(fg_b.sum(), 1))
    removed_frac = float(removed.sum() / max(fg_a2.sum(), 1))

    # ---- scoring ----------------------------------------------------------
    reasons = []
    removal_score = 0.0

    if n_anom >= 1:
        s = 14 + min(24, (n_anom - 1) * 5) + min(30, max_excess * 0.8)
        if n_anom == 1:
            s = min(s, 36)
        removal_score += s
        reasons.append(("warn",
                        f"{n_anom} smooth-area block(s) on the subject were "
                        f"reconstructed wrong (local diff up to "
                        f"{base_block + max_excess:.0f} vs a {base_block:.0f} "
                        f"baseline) — watermark removal / AI inpainting signature."))
    elif flat_hi_frac > 0.015:
        removal_score += min(40, flat_hi_frac * 1500)
        reasons.append(("warn",
                        f"{flat_hi_frac*100:.2f}% of the subject's smooth pixels "
                        "diverge from the original — diffuse reconstruction."))
    else:
        reasons.append(("ok",
                        "The subject's smooth surfaces match the original almost "
                        f"exactly (flat error {flat_err:.1f} vs edge {edge_err:.1f})"
                        " — error is only on contours, normal resampling."))
    removal_score = min(100.0, removal_score)

    edited = []
    if added_frac > 0.03:
        edited.append(("warn",
                       f"{added_frac*100:.0f}% of the review is NEW content "
                       "around the subject (background added / extended / composited)."))
    if removed_frac > 0.05:
        edited.append(("warn",
                       f"{removed_frac*100:.0f}% of the original subject area is "
                       "missing in the review (cropped / erased / occluded)."))
    if anisotropy > 0.06:
        edited.append(("warn",
                       f"The subject's aspect changed by {anisotropy*100:.0f}% "
                       "— stretched, not uniformly scaled."))
    elif anisotropy <= 0.04:
        reasons.append(("ok", f"Subject scaled uniformly "
                              f"(aspect within {anisotropy*100:.1f}%)."))

    if soft_editors:
        reasons.append(("warn", "Metadata names a pixel/AI editor: "
                                + ", ".join(soft_editors) + "."))
    elif soft_neutral:
        reasons.append(("ok", "Metadata only names a layout/export tool ("
                              + ", ".join(soft_neutral) + ")."))

    # ---- verdict ----------------------------------------------------------
    # A large added background recolors the subject boundary and leaves a few
    # contamination blocks; only a STRONG removal signal overrides "edited".
    strong_removal = removal_score >= 52 and (added_frac < 0.08
                                              or removal_score >= 78)
    if strong_removal:
        verdict = "manipulated"
        conf = int(min(97, 60 + (removal_score - 52) * 0.9))
        summary = (
            f"The subject's own pixels were reconstructed (watermark removal / "
            f"AI inpainting), not just resized — {n_anom} smooth-area block(s) "
            f"rebuilt, mean pixel delta {mean_all:.0f} (peak {p99:.0f}).")
        reasons = edited + reasons
    elif edited:
        verdict = "edited"
        conf = int(min(95, 68 + added_frac * 80 + removed_frac * 60
                       + anisotropy * 120))
        bits = []
        if added_frac > 0.03:
            bits.append("a background/extra content was added")
        if removed_frac > 0.05:
            bits.append("part of the original was removed")
        if anisotropy > 0.06:
            bits.append("the subject was stretched")
        summary = ("The subject itself is unchanged, but the image was edited: "
                   + "; ".join(bits) + ".")
        if removal_score >= 40:
            edited.append(("warn", "There is also some reconstruction signal on "
                                   "the subject — inspect the heat-map to rule "
                                   "out watermark removal under the new background."))
        reasons = edited + reasons
    elif removal_score >= 24:
        verdict = "inconclusive"; conf = 50
        summary = ("Mixed signals — some reconstruction error on the subject, "
                   "but not conclusive. Inspect the heat-map by eye.")
    else:
        verdict = "clean_rescale"
        conf = int(min(97, 72 + (24 - removal_score) * 1.0))
        summary = ("A clean, uniformly scaled copy of the original. No "
                   "watermark-removal, inpainting, or surrounding edits.")
        if aa.shape[2] == 4 and ba.shape[2] == 4 and \
                fg_a.mean() < 0.97 and fg_b.mean() < 0.97:
            reasons.append(("ok", "Both keep a clean transparent cut-out; a "
                                  "flattened watermarked preview could not."))

    metrics = _round({
        "subject_aspect_original": aspect_a, "subject_aspect_review": aspect_b,
        "anisotropy_pct": anisotropy * 100, "subject_scale_factor": sx,
        "median_diff": median_all, "mean_diff": mean_all,
        "p95_diff": p95, "p99_diff": p99,
        "edge_error": edge_err, "flat_error": flat_err,
        "flat_pixels_wrong_pct": flat_hi_frac * 100,
        "flat_baseline_diff": base_block, "anomalous_flat_blocks": n_anom,
        "max_block_excess": max_excess, "max_block_z": max_z,
        "added_content_pct": added_frac * 100,
        "removed_content_pct": removed_frac * 100,
        "removal_score": removal_score,
        "overlap_pixels": int(overlap.sum()),
    })
    heat = _heatmap(diff, flat, overlap, added, removed) if want_heatmap else None
    return {"verdict": verdict, "confidence": conf, "summary": summary,
            "reasons": reasons, "metrics": metrics,
            "software_editors": soft_editors, "heatmap": heat}


def _inconclusive(msg, conf, metrics=None):
    return {"verdict": "inconclusive", "confidence": conf, "summary": msg,
            "reasons": [], "metrics": _round(metrics or {}), "heatmap": None}


def _round(d):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


# ----------------------------------------------------- per-attack scoring ---
# The verdict ("manipulated") tells you THAT the asset was reconstructed; the
# damage score tells you HOW HARD the editor had to work. `analyze`'s internal
# removal_score saturates (~68 for every successful removal), so it can't rank
# editors against each other. This blends four independent intensity signals —
# how many smooth blocks were rebuilt, how far pixels moved on average, the
# worst-case shift, and the contour error — into a spread-out 0-100 number.
import math as _math


def damage_score(metrics):
    """0-100 reconstruction-intensity score. Higher = more aggressive rebuild.
    Varies a lot across editors (unlike the saturated verdict confidence)."""
    if not metrics:
        return None
    n = metrics.get("anomalous_flat_blocks", 0) or 0
    mn = metrics.get("mean_diff", 0) or 0
    p99 = metrics.get("p99_diff", 0) or 0
    ee = metrics.get("edge_error", 0) or 0
    # block count spans >1 decade (18..400) -> log; the rest are linear-capped
    n_c = min(1.0, _math.log10(1 + n) / _math.log10(1 + 400))
    mn_c = min(1.0, mn / 50.0)
    p99_c = min(1.0, p99 / 210.0)
    ee_c = min(1.0, ee / 72.0)
    raw = 0.34 * n_c + 0.30 * mn_c + 0.22 * p99_c + 0.14 * ee_c
    return int(round(5 + raw * 94))         # ~5..99, nothing reads as a flat 0


def _intensity_word(score):
    if score >= 85:
        return "the most aggressive"
    if score >= 72:
        return "a heavy"
    if score >= 55:
        return "a moderate"
    if score >= 42:
        return "a light"
    return "the lightest"


def describe_attack(metrics, verdict, model=None, rank=None, total=None):
    """One sentence built from THIS attack's own numbers, so no two read alike.
    `rank` (1 = heaviest) and `total` add relative wording when supplied."""
    if verdict == "refused" or not metrics:
        return ("The model declined or failed to remove the watermark — the "
                "mark survives intact.")
    n = int(metrics.get("anomalous_flat_blocks", 0) or 0)
    mn = metrics.get("mean_diff", 0) or 0
    p99 = metrics.get("p99_diff", 0) or 0
    ee = metrics.get("edge_error", 0) or 0
    sc = damage_score(metrics)
    word = _intensity_word(sc)
    rel = ""
    if rank and total:
        if rank == 1:
            rel = " — the most aggressive reconstruction of the set"
        elif rank == total:
            rel = " — the lightest touch of the set"
    name = (model + " ran ") if model else "This was "
    return (f"{name}{word} reconstruction: {n} smooth-area blocks rebuilt, "
            f"mean pixel delta {mn:.0f} (peak {p99:.0f}), contour error "
            f"{ee:.0f}{rel}.")


def _heatmap(diff, flat, overlap, added, removed):
    h, w = diff.shape
    hm = np.zeros((h, w, 3), np.uint8)
    hm[overlap] = (20, 20, 28)
    dd = np.clip(diff, 0, 120) / 120.0
    hm[..., 0] = np.maximum(hm[..., 0], (dd * 200).astype(np.uint8))  # red edges
    hm[flat & (diff > 42)] = (255, 230, 40)     # yellow = suspicious flat error
    hm[added] = (0, 200, 255)                    # cyan = added content
    hm[removed] = (255, 60, 200)                 # magenta = removed content
    out = Image.fromarray(hm)
    if max(h, w) < 700:
        out = out.resize((w * 2, h * 2), Image.NEAREST)
    buf = io.BytesIO(); out.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def analyze_bytes(a_bytes, b_bytes, want_heatmap=True):
    return analyze(Image.open(io.BytesIO(a_bytes)),
                   Image.open(io.BytesIO(b_bytes)), want_heatmap)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: forensic.py ORIGINAL REVIEW [--json]", file=sys.stderr)
        sys.exit(2)
    res = analyze(Image.open(sys.argv[1]), Image.open(sys.argv[2]),
                  want_heatmap="--json" not in sys.argv)
    if "--json" in sys.argv:
        res.pop("heatmap", None)
        print(json.dumps(res, indent=2))
    else:
        print(f"\n  VERDICT: {res['verdict'].upper()}  ({res['confidence']}% conf)")
        print(f"  {res['summary']}\n")
        for kind, msg in res["reasons"]:
            print(f"   [{'!' if kind == 'warn' else '+'}] {msg}")
        print("\n  metrics:")
        for k, v in res["metrics"].items():
            print(f"     {k:26} {v}")
