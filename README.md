# Unbreakable — watermark research & image forensics

Public site: **https://watermarks.brieflysites.com**

Two tools served by one small Python (stdlib `http.server` + Pillow/numpy) backend:

1. **In Search of an Unbreakable Watermark** — four versions of a protected-preview
   watermark on the same box, each attacked with image-editing models
   (Flux Kontext, nano-banana). A `manipulated` forensic verdict on the cleaned
   result means the eraser had to damage the asset — the watermark held.
2. **Detector — Image Forensics** — upload an original and a copy; classifies it as
   clean rescale / edited (background added) / manipulated (watermark scrub).
   Algorithmic mode is free; the Advanced AI mode is password-gated.

## Run locally
    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
    PORT=8011 python app/server.py        # http://127.0.0.1:8011

## Environment (set in Coolify)
- `FAL_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` — AI removal/examiner providers (fal first)
- `AI_MODE_PASSWORD` — gates the Advanced AI detector mode

## Regenerate watermark versions (dev)
    python tools/watermark.py {clean|v1|v2|v3|v4} out.jpg src.png
    python tools/build_versions.py        # re-attacks + rewrites static/versions/versions.json
