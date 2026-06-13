#!/usr/bin/env python3
"""
Invisible (blind) watermark — a robust block-DCT coefficient-comparison mark that
hides a short serial in the luminance channel. Survives JPEG re-encode and mild
processing; it does NOT survive a full AI regeneration (nothing does — that's what
the forensic detector + registry are for). Its job is to catch the lazy thief who
just crops / recompresses, and to carry the verifiable serial.

Pure numpy + Pillow.
"""
import numpy as np
from PIL import Image

# 16-bit sync header (0xAC96) so we can tell "present" from noise
HEADER = [1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0]
MAXLEN = 16                      # serial up to 16 ASCII chars
FRAME = len(HEADER) + 8 + MAXLEN * 8     # 16 + 8 + 128 = 152 bits
C1, C2 = (3, 2), (2, 3)         # mid-frequency coefficient pair


def _dct_mat(n=8):
    k = np.arange(n)[:, None]; m = np.arange(n)[None, :]
    D = np.cos(np.pi * (2 * m + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    D[0] = 1.0 / np.sqrt(n)
    return D


_D = _dct_mat(8)


def _int_bits(v, n):
    return [(v >> (n - 1 - i)) & 1 for i in range(n)]


def _frame(serial):
    s = serial.encode("ascii", "ignore")[:MAXLEN]
    bits = list(HEADER) + _int_bits(len(s), 8)
    for byte in s:
        bits += _int_bits(byte, 8)
    bits += [0] * (FRAME - len(bits))      # pad
    return bits


def embed(pil, serial, delta=11):
    ycc = pil.convert("YCbCr")
    Y = np.asarray(ycc)[:, :, 0].astype(np.float32)
    Cb = np.asarray(ycc)[:, :, 1]; Cr = np.asarray(ycc)[:, :, 2]
    h, w = Y.shape
    frame = _frame(serial); bi = 0
    for by in range(0, h - 7, 8):
        for bx in range(0, w - 7, 8):
            blk = Y[by:by + 8, bx:bx + 8]
            C = _D @ blk @ _D.T
            bit = frame[bi % FRAME]
            a, b = C[C1], C[C2]
            if bit:                         # want a - b >= delta
                if a - b < delta:
                    mid = (a + b) / 2; C[C1] = mid + delta / 2; C[C2] = mid - delta / 2
            else:                           # want b - a >= delta
                if b - a < delta:
                    mid = (a + b) / 2; C[C2] = mid + delta / 2; C[C1] = mid - delta / 2
            Y[by:by + 8, bx:bx + 8] = _D.T @ C @ _D
            bi += 1
    Y = np.clip(Y, 0, 255).astype(np.uint8)
    out = np.dstack([Y, Cb, Cr])
    return Image.fromarray(out, "YCbCr").convert("RGB")


def extract(pil):
    Y = np.asarray(pil.convert("YCbCr"))[:, :, 0].astype(np.float32)
    h, w = Y.shape
    votes = np.zeros(FRAME); counts = np.zeros(FRAME); bi = 0
    for by in range(0, h - 7, 8):
        for bx in range(0, w - 7, 8):
            C = _D @ Y[by:by + 8, bx:bx + 8] @ _D.T
            votes[bi % FRAME] += 1.0 if C[C1] > C[C2] else -1.0
            counts[bi % FRAME] += 1
            bi += 1
    if counts.min() == 0:
        return {"found": False, "confidence": 0}
    bits = (votes > 0).astype(int)
    agree = float(np.mean(np.abs(votes) / counts))     # 0..1 consensus strength
    hdr_match = float(np.mean(bits[:16] == np.array(HEADER)))
    if hdr_match < 0.95:
        return {"found": False, "confidence": round(agree, 3), "header_match": round(hdr_match, 3)}
    ln = int("".join(map(str, bits[16:24])), 2)
    ln = max(0, min(MAXLEN, ln))
    chars = []
    for i in range(ln):
        byte = int("".join(map(str, bits[24 + i * 8:32 + i * 8])), 2)
        if 32 <= byte < 127:
            chars.append(chr(byte))
    return {"found": True, "serial": "".join(chars), "confidence": round(agree, 3),
            "header_match": round(hdr_match, 3)}


if __name__ == "__main__":
    import io, sys
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/wm2_master.png"
    serial = sys.argv[2] if len(sys.argv) > 2 else "WM-7F3A9C2B"
    base = Image.open(src).convert("RGB")
    wm = embed(base, serial)
    print("clean  ->", extract(base))
    print("marked ->", extract(wm))
    buf = io.BytesIO(); wm.save(buf, "JPEG", quality=85); buf.seek(0)
    print("jpeg85 ->", extract(Image.open(buf)))
    buf = io.BytesIO(); wm.save(buf, "JPEG", quality=60); buf.seek(0)
    print("jpeg60 ->", extract(Image.open(buf)))
    d = np.abs(np.asarray(wm).astype(int) - np.asarray(base).astype(int))
    print(f"visual delta: mean {d.mean():.2f} max {d.max()} (psnr-ish)")
