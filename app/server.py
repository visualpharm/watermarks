#!/usr/bin/env python3
"""
watermarks.brieflysites.com — two tools:
  /                      SPA: "In Search of an Unbreakable Watermark" + "Detector"
  /api/versions          watermark versions + AI removal attempts + forensic verdicts
  /api/example           the EDEM demo pair (data-urls)
  /api/forensic          original-vs-review forensic analysis (AI mode password-gated)
  /api/health            capabilities

Secrets come from the ENVIRONMENT in production (Coolify), with a local .env
fallback for dev. The advanced AI mode is gated by AI_MODE_PASSWORD.
"""
import base64, io, json, os, re, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont
import forensic, invisible, provenance, registry

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
STATIC = os.path.join(ROOT, "static")
PORT = int(os.environ.get("PORT", "8011"))

FAL_MODEL = os.environ.get("FAL_MODEL", "google/gemini-flash-1.5")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PROVIDER_ORDER = os.environ.get("AI_PROVIDERS", "fal,openai,gemini").split(",")
AI_PASSWORD = os.environ.get("AI_MODE_PASSWORD", "")

REMOVAL_PROMPT = (
    "Remove every watermark from this product photo. Delete all the repeated "
    "PREVIEW text, the SAMPLE and DO NOT COPY microtext, and any faint diagonal "
    "lettering on the box, the stickers, the green shipping label, the barcode, "
    "and the background. Reconstruct the clean cardboard texture, the original "
    "label text and barcode, and the plain studio background underneath. Output a "
    "clean, watermark-free product image, keeping the box, stickers and labels intact.")

MODEL_IDS = {"Flux Kontext": "fal-ai/flux-pro/kontext",
             "Flux Kontext Max": "fal-ai/flux-pro/kontext/max",
             "nano-banana": "fal-ai/nano-banana/edit  (Gemini 2.5 Flash Image)",
             "Nano Banana Pro": "fal-ai/nano-banana-pro/edit  (Gemini 3 Pro Image)",
             "Qwen Image Edit": "fal-ai/qwen-image-edit",
             "Seedream v4": "fal-ai/bytedance/seedream/v4/edit",
             "GPT Image 1": "openai /v1/images/edits  (gpt-image-1)",
             "GPT Image 2": "openai /v1/images/edits  (gpt-image-2)",
             "SeedEdit 3.0": "fal-ai/bytedance/seededit/v3/edit-image"}
GENERATED_ON = os.environ.get("VERSIONS_DATE", "2026-06-17")


# ----------------------------------------------------------------- keys ------
def _load_keys():
    keys = {k: os.environ[k] for k in
            ("FAL_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY") if os.environ.get(k)}
    if keys:
        return keys
    # dev fallback: read from local .env files
    home = os.path.expanduser("~")
    files = [f"{home}/projects/ilbuco-g2/.env.local",
             f"{home}/projects/lira/.env.local",
             f"{home}/projects/guide/.env.local"]
    want = ("OPENAI_API_KEY", "GEMINI_API_KEY", "FAL_KEY")
    for f in files:
        if not os.path.exists(f):
            continue
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k = k.replace("export ", "").strip(); v = v.strip().strip('"').strip("'")
                if k in want and k not in keys and v:
                    keys[k] = v
    return keys


KEYS = _load_keys()


# --------------------------------------------------------------- helpers -----
def _decode(data_url):
    if data_url.strip().startswith("data:") and "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return base64.b64decode(data_url)


def _flatten(pil, bg=(255, 255, 255)):
    if pil.mode in ("RGBA", "LA", "P"):
        pil = pil.convert("RGBA")
        base = Image.new("RGB", pil.size, bg); base.paste(pil, mask=pil.split()[-1])
        return base
    return pil.convert("RGB")


def _thumb(pil, mx=900, fmt="PNG"):
    im = pil.convert("RGBA") if fmt == "PNG" else _flatten(pil)
    if max(im.size) > mx:
        s = mx / max(im.size)
        im = im.resize((int(im.width*s), int(im.height*s)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format=fmt, quality=82)
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _rawurl(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "image/png" if ext == "png" else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def _font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try: return ImageFont.truetype(p, sz)
        except Exception: pass
    return ImageFont.load_default()


# --------------------------------------------------------------- AI ----------
def _composite(orig, review, heat, panel=440):
    def prep(p):
        im = _flatten(p, (245, 241, 234)); s = panel / max(im.size)
        return im.resize((max(1, int(im.width*s)), max(1, int(im.height*s))), Image.LANCZOS)
    imgs = [("ORIGINAL", prep(Image.open(io.BytesIO(orig)))),
            ("REVIEW", prep(Image.open(io.BytesIO(review))))]
    if heat:
        imgs.append(("DIFF HEAT-MAP", prep(Image.open(io.BytesIO(base64.b64decode(heat.split(',',1)[1]))))))
    pad, lab = 12, 26
    rowh = max(i.height for _, i in imgs)
    W = sum(i.width for _, i in imgs) + pad*(len(imgs)+1); Hh = rowh + lab + pad*2
    sh = Image.new("RGB", (W, Hh), (245, 241, 234)); d = ImageDraw.Draw(sh); f = _font(16)
    x = pad
    for name, im in imgs:
        d.text((x, pad-2), name, fill=(40, 38, 32), font=f); sh.paste(im, (x, pad+lab)); x += im.width+pad
    buf = io.BytesIO(); sh.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


SYS_PROMPT = (
    "You are an image-forensics examiner. You see a contact sheet: ORIGINAL, "
    "REVIEW, and a DIFF HEAT-MAP where red=edge error (normal resizing), "
    "yellow=smooth-area error (suspicious reconstruction), cyan=content ADDED, "
    "magenta=content REMOVED. Classify the REVIEW vs the ORIGINAL as: "
    "clean_rescale (faithful scaled copy), edited (subject intact but surroundings "
    "changed: background added/removed/cropped/stretched), manipulated (the "
    "subject's own pixels reconstructed: watermark removal / AI inpainting), or "
    "inconclusive. A new background alone is 'edited', NOT 'manipulated'. Reply "
    'ONLY JSON: {"verdict":...,"confidence":0-100,"watermark_removal_suspected":'
    'bool,"background_or_scene_added":bool,"reasoning":"<=60 words","artifacts":[]}')


def _extract_json(t):
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*", "", t).strip().rstrip("`").strip()
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return json.loads(t[i:j+1])
    raise ValueError("no JSON")


def _ask_fal(comp, user):
    body = {"model": FAL_MODEL, "system_prompt": SYS_PROMPT, "prompt": user, "image_url": comp}
    req = urllib.request.Request("https://fal.run/fal-ai/any-llm/vision",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Key {KEYS['FAL_KEY']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.loads(r.read())
    if j.get("error"): raise RuntimeError(str(j["error"])[:160])
    return j["output"], f"fal:{FAL_MODEL}"


def _ask_openai(comp, user):
    body = {"model": OPENAI_MODEL, "temperature": 0, "max_tokens": 400,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYS_PROMPT},
                         {"role": "user", "content": [{"type": "text", "text": user},
                          {"type": "image_url", "image_url": {"url": comp}}]}]}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEYS['OPENAI_API_KEY']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.loads(r.read())
    return j["choices"][0]["message"]["content"], f"openai:{OPENAI_MODEL}"


def _ask_gemini(comp, user):
    b64 = comp.split(",", 1)[1]
    body = {"contents": [{"parts": [{"text": SYS_PROMPT+"\n\n"+user},
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={KEYS['GEMINI_API_KEY']}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        j = json.loads(r.read())
    return j["candidates"][0]["content"]["parts"][0]["text"], f"gemini:{GEMINI_MODEL}"


PROVIDERS = {"fal": (_ask_fal, "FAL_KEY"), "openai": (_ask_openai, "OPENAI_API_KEY"),
             "gemini": (_ask_gemini, "GEMINI_API_KEY")}


def ai_opinion(orig, review, algo):
    m = algo.get("metrics", {})
    user = ("Algorithmic metrics:\n" + "\n".join(f"- {k}: {v}" for k, v in m.items()) +
            f"\n\nAlgorithmic verdict: {algo.get('verdict')} ({algo.get('confidence')}%).")
    comp = _composite(orig, review, algo.get("heatmap"))
    errs = []
    for name in PROVIDER_ORDER:
        name = name.strip()
        if name not in PROVIDERS or not KEYS.get(PROVIDERS[name][1]):
            continue
        try:
            txt, mid = PROVIDERS[name][0](comp, user)
            out = _extract_json(txt); out["_model"] = mid
            return out
        except urllib.error.HTTPError as e:
            errs.append(f"{name}: HTTP {e.code} {e.read().decode()[:100]}")
        except Exception as e:
            errs.append(f"{name}: {e}")
    return {"error": "AI providers failed. " + " | ".join(errs) if errs else "No AI key configured."}


def _ai_available():
    return any(KEYS.get(PROVIDERS[p.strip()][1]) for p in PROVIDER_ORDER if p.strip() in PROVIDERS)


# ----------------------------------------------------- forgery evidence ------
def build_evidence(orig_bytes, review_bytes, algo):
    """Harvest independent proofs that the REVIEW is a stolen/forged copy."""
    rev_inv = invisible.extract(Image.open(io.BytesIO(review_bytes)))
    orig_inv = invisible.extract(Image.open(io.BytesIO(orig_bytes)))
    prov = provenance.read_provenance(review_bytes)
    serial = rev_inv.get("serial", "") if rev_inv.get("found") else ""
    reg = registry.validate(serial)
    proofs = []

    # 1. registry serial / invisible watermark
    if reg["status"] == "valid":
        proofs.append({"sev": "ok", "label": "Registry serial", "detail": reg["message"]})
    elif rev_inv.get("found"):
        proofs.append({"sev": "bad", "label": "Registry serial", "detail": reg["message"]})
    elif orig_inv.get("found"):
        proofs.append({"sev": "bad", "label": "Invisible watermark stripped",
                       "detail": f"The original carries registered serial "
                                 f"{orig_inv.get('serial')}, but the review has none — "
                                 "the mark was scrubbed or the image was regenerated."})
    else:
        proofs.append({"sev": "warn", "label": "Invisible watermark",
                       "detail": "No registry serial found in either file."})

    # 2. forensic reconstruction
    fv = algo.get("verdict")
    sev = {"manipulated": "bad", "edited": "warn", "inconclusive": "warn"}.get(fv, "ok")
    proofs.append({"sev": sev, "label": "Forensic reconstruction", "detail": algo.get("summary", "")})

    # 3. embedded AI provenance (the thief's own tool)
    if prov["verdict"] in ("ai_generated", "ai_edited"):
        proofs.append({"sev": "bad", "label": "Embedded AI provenance (C2PA)", "detail": prov["summary"]})
    elif prov["verdict"] in ("has_provenance", "tool_trace"):
        proofs.append({"sev": "warn", "label": "Provenance trace", "detail": prov["summary"]})
    else:
        proofs.append({"sev": "ok", "label": "Provenance", "detail": prov["summary"]})

    signals = sum(1 for p in proofs if p["sev"] == "bad")
    if signals >= 2:
        head = f"Forgery confirmed — {signals} independent proofs"
    elif signals == 1:
        head = "Likely forgery — 1 proof"
    else:
        head = "No forgery signals"
    return {"headline": head, "signals": signals, "proofs": proofs,
            "serial_review": rev_inv, "serial_original": orig_inv}


# ----------------------------------------------------------------- http ------
CTYPE = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
         ".css": "text/css", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".json": "application/json",
         ".ico": "image/x-icon", ".webp": "image/webp"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, code=200, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send({"error": "not found"}, 404)
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CTYPE.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        if ext in (".html", ".js", ".css"):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _safe(self, base, rel):
        p = os.path.normpath(os.path.join(base, rel.lstrip("/")))
        return p if p.startswith(base) else None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(WEB, "index.html"))
        if path == "/api/health":
            return self._send({"ok": True, "ai": _ai_available(),
                               "ai_requires_password": bool(AI_PASSWORD)})
        if path == "/api/versions":
            return self._versions()
        if path == "/api/example":
            return self._example()
        if path == "/api/example-history":
            return self._file(os.path.join(STATIC, "example-history.json"))
        if path.startswith("/static/"):
            p = self._safe(STATIC, path[len("/static/"):])
            return self._file(p) if p else self._send({"error": "bad path"}, 400)
        if path.startswith("/web/"):
            p = self._safe(WEB, path[len("/web/"):])
            return self._file(p) if p else self._send({"error": "bad path"}, 400)
        self._send({"error": "not found"}, 404)

    def _versions(self):
        with open(os.path.join(STATIC, "versions", "versions.json")) as f:
            data = json.load(f)
        for v in data["versions"]:
            v["image"] = "/static/versions/" + v["image"]
            for a in v["attacks"]:
                a["model_id"] = MODEL_IDS.get(a["model"], "")
                if a.get("image"):
                    a["image"] = "/static/versions/" + a["image"]
        data["base"] = "/static/versions/" + data["base"]
        data["meta"] = {"generated_on": GENERATED_ON, "removal_prompt": REMOVAL_PROMPT,
                        "base_source": "studio composite of the clean master asset"}
        self._send(data)

    def _example(self):
        case = self.path.split("case=")[-1].split("&")[0] if "case=" in self.path else "theft"
        try:
            ex = self._example_history_case(case)
            if ex:                       # one of the pre-filled icons8 3D-Stickle tests
                o = _rawurl(os.path.join(STATIC, "examples", ex["fileA"]))
                r = _rawurl(os.path.join(STATIC, "examples", ex["fileB"]))
            elif case == "resize":
                o = _thumb(Image.open(os.path.join(STATIC, "example-master.png")), 900, "PNG")
                r = _thumb(Image.open(os.path.join(STATIC, "example-edem.png")), 900, "PNG")
            else:   # theft: full-res marked master (invisible serial intact) vs AI suspect
                o = _rawurl(os.path.join(STATIC, "versions", "wm-v7.png"))
                r = _rawurl(os.path.join(STATIC, "suspect-ai-edited.png"))
            self._send({"original": o, "review": r})
        except Exception as e:
            self._send({"error": str(e)}, 500)

    @staticmethod
    def _example_history_case(case):
        try:
            with open(os.path.join(STATIC, "example-history.json")) as f:
                for it in json.load(f).get("items", []):
                    if it.get("case") == case:
                        return it
        except Exception:
            pass
        return None

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/forensic":
            return self._send({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n))
            a = _decode(payload["original"]); b = _decode(payload["review"])
            mode = payload.get("mode", "algo")
        except Exception as e:
            return self._send({"error": f"bad request: {e}"}, 400)
        if mode == "ai" and AI_PASSWORD:
            if self.headers.get("X-AI-Password", "") != AI_PASSWORD:
                return self._send({"error": "Advanced AI mode requires the access password."}, 403)
        try:
            algo = forensic.analyze_bytes(a, b, want_heatmap=True)
        except Exception as e:
            return self._send({"error": f"analysis failed: {e}"}, 500)
        out = {"algo": algo}
        try:
            out["evidence"] = build_evidence(a, b, algo)
        except Exception as e:
            out["evidence"] = {"error": str(e)}
        if mode == "ai":
            out["ai"] = ai_opinion(a, b, algo)
        self._send(out)


if __name__ == "__main__":
    print(f"watermarks -> http://0.0.0.0:{PORT}/  ai={_ai_available()}  pw={'set' if AI_PASSWORD else 'none'}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
