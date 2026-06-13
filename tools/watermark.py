#!/usr/bin/env python3
"""
Versioned 'protected preview' watermarking, all rendered on one shared base so
the versions are directly comparable.

  v1  initial      — fused multiply preview + loud diagonal decoy (easy to strip)
  v2  kontext-patch— bake PREVIEW into cardboard/label/barcode/sticker + shadow,
                     per-face perspective (entangled; removal is destructive)
  v3  low-visibility— drop the loud removable decoy, keep only the entangled
                     object-local marks (~95% of the protection, far cleaner)
  v4  poison       — v3 + irreversible mosaic/scramble of hard-to-redraw regions
                     (FRAGILE sticker, barcodes) so removal can't restore them

CLI:  watermark.py {clean|v1|v2|v3|v4} OUT.png [SRC.png]
Pure Pillow + numpy.
"""
import io, math, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/Helvetica.ttc"]
def font(sz):
    for p in FONTS:
        try: return ImageFont.truetype(p, sz)
        except Exception: pass
    return ImageFont.load_default()


def build_base(src):
    random.seed(11); np.random.seed(11)
    box = Image.open(src).convert("RGBA")
    W, H = box.size
    A = np.asarray(box).astype(int)
    a = A[:, :, 3]; obj = a > 30
    r, g, b = A[:, :, 0], A[:, :, 1], A[:, :, 2]
    # studio bg + cast shadow
    gx = np.linspace(-1, 1, W); gy = np.linspace(-1, 1, H)
    gv = np.sqrt(gx[None, :]**2 + gy[:, None]**2)
    shade = np.clip(235 - np.clip(gv, 0, 1.4) * 26, 0, 255).astype(np.uint8)
    bg = Image.merge("RGBA", [Image.fromarray(shade)]*3 + [Image.new("L", (W, H), 255)])
    shadow = Image.new("L", (W, H), 0)
    shadow.paste(Image.fromarray((obj * 150).astype(np.uint8)), (int(W*0.02), int(H*0.04)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    sh = np.asarray(shadow).astype(np.float32) / 255.0
    bgA = np.asarray(bg).astype(np.float32); bgA[:, :, :3] *= (1 - 0.55 * sh[:, :, None])
    canvas = Image.alpha_composite(Image.fromarray(bgA.astype(np.uint8), "RGBA"), box)
    green = obj & (g > 110) & (g > r + 25) & (g > b + 25)
    blue  = obj & (b > 120) & (b > r + 30) & (b > g + 10)
    pink  = obj & (r > 180) & (b > 110) & (g < 130)
    satred = obj & (r > 175) & (g < 80) & (b < 80)
    dark  = obj & (r < 75) & (g < 75) & (b < 75)
    stickers = green | blue | pink | satred
    cardboard = obj & ~stickers & ~dark
    lum = np.asarray(canvas.convert("L")).astype(np.float32) / 255.0
    return dict(W=W, H=H, obj=obj, green=green, blue=blue, pink=pink, satred=satred,
                dark=dark, cardboard=cardboard, shadow_mask=(sh > 0.12) & ~obj,
                canvas=canvas, lum=lum, box=box)


# ---- low-level helpers --------------------------------------------------------
def tiled_text(W, H, text, fsize, fill, sx, sy, angle, jitter=0):
    over = int(1.7 * max(W, H))
    tile = Image.new("RGBA", (over, over), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile); f = font(fsize); row = 0
    for y in range(0, over, sy):
        off = (sx // 2) if row % 2 else 0
        for x in range(-sx, over, sx):
            jx = random.randint(-jitter, jitter) if jitter else 0
            jy = random.randint(-jitter, jitter) if jitter else 0
            al = max(0, min(255, fill[3] + (random.randint(-18, 18) if jitter else 0)))
            d.text((x+off+jx, y+jy), text, font=f, fill=(fill[0], fill[1], fill[2], al))
        row += 1
    tile = tile.rotate(angle, resample=Image.BICUBIC)
    l, t = (over-W)//2, (over-H)//2
    return tile.crop((l, t, l+W, t+H))

def shear(layer, k):
    return layer.transform(layer.size, Image.AFFINE,
                           (1, k, -k*layer.height/2, 0, 1, 0), resample=Image.BICUBIC)

def aA(layer): return np.asarray(layer).astype(np.float32)[:, :, 3] / 255.0
def soft(mask, rad=1.0):
    return np.asarray(Image.fromarray((mask*255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(rad))).astype(np.float32) / 255.0

def mbake(cn, ink_a, mask01, ink=(34, 30, 30), strength=1.0):
    f = np.clip(ink_a * mask01 * strength, 0, 1)[:, :, None]
    return cn * (1 - f) + (cn * (np.array(ink, np.float32) / 255.0)) * f


def cardboard_bake(cn, B, big_alpha=205, micro=True):
    """Per-face sheared PREVIEW multiplied into cardboard + faint micro grain."""
    W, H, obj, card, lum = B["W"], B["H"], B["obj"], B["cardboard"], B["lum"]
    ox = np.where(obj.any(0))[0]; oy = np.where(obj.any(1))[0]
    ox0, ox1, oy0, oy1 = ox.min(), ox.max(), oy.min(), oy.max()
    xseam = int(ox0 + 0.47*(ox1-ox0)); ytop = int(oy0 + 0.40*(oy1-oy0))
    yy, xx = np.mgrid[0:H, 0:W]
    regs = [(card & (yy < ytop), -8, -0.55),
            (card & (yy >= ytop) & (xx < xseam), 22, 0.28),
            (card & (yy >= ytop) & (xx >= xseam), -20, -0.30)]
    lmod = np.clip(0.5 + (1-lum)*0.9, 0.3, 1.4)
    for reg, ang, k in regs:
        lay = shear(tiled_text(W, H, "PREVIEW ", int(H*0.052), (28, 26, 28, big_alpha),
                               int(W*0.30), int(H*0.115), ang, 5), k)
        cn = mbake(cn, aA(lay)*lmod, soft(reg, 1.0), ink=(30, 28, 30), strength=0.95)
    if micro:
        m = tiled_text(W, H, "PREVIEW ", int(H*0.012), (40, 38, 40, 120),
                       int(W*0.10), int(H*0.026), -7, 2)
        cn = mbake(cn, aA(m)*lmod, soft(card, 0.6), ink=(46, 42, 40), strength=0.6)
    return cn

def label_barcode_bake(cn, B):
    W, H, green, dark = B["W"], B["H"], B["green"], B["dark"]
    g = tiled_text(W, H, "PREVIEW ", int(H*0.011), (10, 40, 10, 150),
                   int(W*0.07), int(H*0.020), -3, 1)
    cn = mbake(cn, aA(g), soft(green, 0.5), ink=(8, 52, 8), strength=0.8)
    if green.any():
        gx0, gx1 = np.where(green.any(0))[0][[0, -1]]
        gy0, gy1 = np.where(green.any(1))[0][[0, -1]]
        ld = np.zeros_like(green); ld[gy0:gy1, gx0:gx1] = dark[gy0:gy1, gx0:gx1]
        bc = tiled_text(W, H, "PREVIEW", int(H*0.010), (255, 255, 255, 170),
                        int(W*0.05), int(H*0.013), 0, 0)
        fa = (aA(bc)*soft(ld, 0.4))[:, :, None]
        cn = cn*(1-fa*0.8) + np.array([60, 90, 60], np.float32)*fa*0.8
    return cn

def fragile_bake(cn, B):
    W, H = B["W"], B["H"]
    f = tiled_text(W, H, "PREVIEW ", int(H*0.018), (90, 0, 0, 200),
                   int(W*0.10), int(H*0.030), 14, 2)
    return mbake(cn, aA(f), soft(B["satred"], 0.6), ink=(120, 10, 10), strength=0.85)

def shadow_dither(cn, B):
    W, H = B["W"], B["H"]
    s = tiled_text(W, H, "PREVIEW ", int(H*0.030), (120, 116, 110, 140),
                   int(W*0.16), int(H*0.05), -18, 3)
    fa = (aA(s)*soft(B["shadow_mask"], 1.0))[:, :, None]
    return cn*(1-fa*0.5) + np.array([150, 146, 140], np.float32)*fa*0.5

def behind_edges(canvasRGBA, B, alpha=90):
    W, H = B["W"], B["H"]
    lay = tiled_text(W, H, "PREVIEW ", int(H*0.07), (70, 70, 80, alpha),
                     int(W*0.34), int(H*0.16), -26, 6)
    ba = (aA(lay)*(1-B["obj"].astype(np.float32)))
    over = np.dstack([np.asarray(lay)[:, :, :3], (ba*255).astype(np.uint8)]).astype(np.uint8)
    return Image.alpha_composite(canvasRGBA, Image.fromarray(over, "RGBA"))

def decoy(canvasRGBA, B, big_alpha=70, grid=True):
    W, H = B["W"], B["H"]
    d1 = tiled_text(W, H, "PREVIEW ", int(H*0.075), (255, 255, 255, big_alpha),
                    int(W*0.40), int(H*0.18), 18, 8)
    canvasRGBA = Image.alpha_composite(canvasRGBA, d1)
    if grid:
        d2 = tiled_text(W, H, "SAMPLE  DO NOT COPY  ", int(H*0.016), (30, 30, 40, 70),
                        int(W*0.16), int(H*0.03), -8, 3)
        canvasRGBA = Image.alpha_composite(canvasRGBA, d2)
    return canvasRGBA

def finish(arr, W, H, jpeg=36, grain=6):
    ht = Image.new("L", (W, H), 0); dh = ImageDraw.Draw(ht)
    for y in range(0, H, 9):
        for x in range(0, W, 9):
            rr = random.uniform(0.5, 1.8); dh.ellipse([x-rr, y-rr, x+rr, y+rr], fill=18)
    arr = arr - np.asarray(ht).astype(np.float32)[:, :, None]*0.22
    rr = np.roll(arr[:, :, 0], 2, 1); bb = np.roll(arr[:, :, 2], -2, 1)
    arr[:, :, 0] = 0.6*arr[:, :, 0]+0.4*rr; arr[:, :, 2] = 0.6*arr[:, :, 2]+0.4*bb
    arr = np.clip(arr + np.random.normal(0, grain, arr.shape), 0, 255).astype(np.uint8)
    out = Image.fromarray(arr, "RGB")
    buf = io.BytesIO(); out.save(buf, "JPEG", quality=jpeg); buf.seek(0)
    return Image.open(buf).convert("RGB")


def poison_region(cn, mask, block):
    """Irreversible mosaic + per-block channel scramble inside mask."""
    H, W = mask.shape
    ys, xs = np.where(mask)
    if len(xs) == 0: return cn
    out = cn.copy()
    rng = np.random.default_rng(7)
    for y in range(ys.min(), ys.max(), block):
        for x in range(xs.min(), xs.max(), block):
            blk = mask[y:y+block, x:x+block]
            if blk.mean() < 0.35: continue
            region = out[y:y+block, x:x+block]
            avg = region.reshape(-1, 3).mean(0)
            # mosaic to the block average, then jitter channels + add noise
            jit = rng.normal(0, 26, 3)
            val = np.clip(avg + jit, 0, 255)
            noise = rng.normal(0, 30, region.shape)
            filled = np.clip(val[None, None, :] + noise, 0, 255)
            m = blk[:, :, None]
            out[y:y+block, x:x+block] = region*(1-m) + filled*m
    return out


# ---- versions -----------------------------------------------------------------
def render_clean(B):
    return B["canvas"].convert("RGB")

def render_v1(B):
    W, H = B["W"], B["H"]
    cn = np.asarray(B["canvas"].convert("RGB")).astype(np.float32)
    # simple object multiply (one orientation) + behind + loud decoy
    lay = tiled_text(W, H, "PREVIEW ", int(H*0.07), (30, 28, 30, 150),
                     int(W*0.33), int(H*0.15), -26, 6)
    lmod = np.clip(0.5 + (1-B["lum"])*0.8, 0.3, 1.3)
    cn = mbake(cn, aA(lay)*lmod, soft(B["obj"], 1.0), ink=(34, 32, 34), strength=0.7)
    c = Image.fromarray(np.clip(cn, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    c = behind_edges(c, B, alpha=120)
    c = decoy(c, B, big_alpha=95, grid=True)
    return finish(np.asarray(c.convert("RGB")).astype(np.float32), W, H)

def render_v2(B):
    W, H = B["W"], B["H"]
    cn = np.asarray(B["canvas"].convert("RGB")).astype(np.float32)
    cn = cardboard_bake(cn, B, big_alpha=205, micro=True)
    cn = label_barcode_bake(cn, B)
    cn = fragile_bake(cn, B)
    cn = shadow_dither(cn, B)
    c = Image.fromarray(np.clip(cn, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    c = behind_edges(c, B, alpha=90)
    c = decoy(c, B, big_alpha=70, grid=True)
    return finish(np.asarray(c.convert("RGB")).astype(np.float32), W, H)

def render_v3(B):
    """Drop the loud removable decoy + dense grid + behind layer. Keep the
    entangled object-local marks (slightly strengthened) -> low visibility."""
    W, H = B["W"], B["H"]
    cn = np.asarray(B["canvas"].convert("RGB")).astype(np.float32)
    cn = cardboard_bake(cn, B, big_alpha=120, micro=True)   # softer big print
    cn = label_barcode_bake(cn, B)                          # keep label/barcode
    cn = fragile_bake(cn, B)                                # keep sticker entangle
    # one small, honest visible tag in a corner (not a full-canvas decoy)
    c = Image.fromarray(np.clip(cn, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    tag = tiled_text(W, H, "PREVIEW ", int(H*0.030), (255, 255, 255, 55),
                     int(W*0.55), int(H*0.5), 18, 4)
    c = Image.alpha_composite(c, tag)
    return finish(np.asarray(c.convert("RGB")).astype(np.float32), W, H, grain=5)

def render_v4(B):
    """v3 + irreversibly poison the hard-to-redraw regions."""
    W, H = B["W"], B["H"]
    cn = np.asarray(B["canvas"].convert("RGB")).astype(np.float32)
    cn = cardboard_bake(cn, B, big_alpha=120, micro=True)
    cn = label_barcode_bake(cn, B)
    cn = fragile_bake(cn, B)
    # poison: FRAGILE sticker + the green-label barcodes (high-detail, hard to fake)
    block = max(6, int(H*0.012))
    cn = poison_region(cn, B["satred"], block)
    if B["green"].any():
        gx0, gx1 = np.where(B["green"].any(0))[0][[0, -1]]
        gy0, gy1 = np.where(B["green"].any(1))[0][[0, -1]]
        bcmask = np.zeros_like(B["green"]); bcmask[gy0:gy1, gx0:gx1] = B["dark"][gy0:gy1, gx0:gx1]
        bcmask = soft(bcmask, 1.0) > 0.2
        cn = poison_region(cn, bcmask, max(5, int(H*0.009)))
    c = Image.fromarray(np.clip(cn, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    tag = tiled_text(W, H, "PREVIEW ", int(H*0.030), (255, 255, 255, 55),
                     int(W*0.55), int(H*0.5), 18, 4)
    c = Image.alpha_composite(c, tag)
    return finish(np.asarray(c.convert("RGB")).astype(np.float32), W, H, grain=5)


RENDER = {"clean": render_clean, "v1": render_v1, "v2": render_v2,
          "v3": render_v3, "v4": render_v4}

if __name__ == "__main__":
    ver = sys.argv[1]; out = sys.argv[2]
    src = sys.argv[3] if len(sys.argv) > 3 else "/tmp/wm2_master.png"
    B = build_base(src)
    RENDER[ver](B).save(out)
    print("OK", ver, "->", out, RENDER[ver](B).size if False else "")
