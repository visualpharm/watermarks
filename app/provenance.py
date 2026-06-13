#!/usr/bin/env python3
"""
Provenance / AI-trace harvester. Reads a suspect file's own embedded evidence:
  - C2PA manifest (Content Credentials) — present on gpt-image-2, Firefly, etc.
  - the C2PA claim_generator + AI-generation assertion (trainedAlgorithmicMedia)
  - XMP / EXIF software + edit-history tags
  - known AI generator / editor names anywhere in the bytes
The thief's own tool tags the theft. No parsing of proprietary detectors needed.
Pure stdlib + Pillow.
"""
import io
import re
from PIL import Image

# (needle, human label) — generators/editors that betray AI editing
AI_TOOLS = [
    (b"trainedAlgorithmicMedia", "C2PA: declared AI-generated (trainedAlgorithmicMedia)"),
    (b"compositeWithTrainedAlgorithmicMedia", "C2PA: AI-composited"),
    (b"OpenAI", "OpenAI"), (b"DALL", "DALL-E / GPT Image"), (b"gpt-image", "GPT Image"),
    (b"Firefly", "Adobe Firefly"), (b"Adobe Photoshop", "Adobe Photoshop"),
    (b"Midjourney", "Midjourney"), (b"Gemini", "Google Gemini"), (b"Imagen", "Google Imagen"),
    (b"Stable Diffusion", "Stable Diffusion"), (b"Seedream", "Seedream"),
    (b"bytedance", "ByteDance"), (b"Grok", "xAI Grok"), (b"Qwen", "Qwen"),
    (b"black-forest", "Flux / Black Forest Labs"), (b"SynthID", "Google SynthID"),
    (b"Generative Fill", "Adobe Generative Fill"),
]
C2PA_MARKERS = [b"urn:c2pa", b"c2pa.assertions", b"jumbf", b"jumb", b"claim_generator",
                b"contentauth", b"c2pa.actions"]
EDIT_ACTIONS = [b"c2pa.edited", b"c2pa.placed", b"c2pa.cropped", b"c2pa.color_adjustments",
                b"c2pa.drawing", b"c2pa.filtered"]


def _printable_after(raw, needle, span=160):
    i = raw.find(needle)
    if i < 0:
        return ""
    chunk = raw[i + len(needle): i + len(needle) + span]
    runs = re.findall(rb"[\x20-\x7e]{4,}", chunk)
    return runs[0].decode("ascii", "ignore") if runs else ""


def read_provenance(image_bytes):
    raw = image_bytes
    out = {"has_c2pa": False, "ai_generated": False, "claim_generator": "",
           "tools": [], "edits": [], "xmp_software": "", "summary": "",
           "verdict": "no_provenance"}

    out["has_c2pa"] = any(m in raw for m in C2PA_MARKERS)
    if b"claim_generator" in raw:
        out["claim_generator"] = _printable_after(raw, b"claim_generator")
    if b"trainedAlgorithmicMedia" in raw or b"compositeWithTrainedAlgorithmicMedia" in raw:
        out["ai_generated"] = True

    seen = set()
    for needle, label in AI_TOOLS:
        if needle in raw and label not in seen:
            seen.add(label); out["tools"].append(label)
    for needle in EDIT_ACTIONS:
        if needle in raw:
            out["edits"].append(needle.decode())

    # XMP block
    try:
        im = Image.open(io.BytesIO(raw))
        xmp = im.info.get("XML:com.adobe.xmp") or im.info.get("xmp") or ""
        if isinstance(xmp, bytes):
            xmp = xmp.decode("utf-8", "replace")
        m = re.search(r"(?:CreatorTool|Software|creator)[^>]*>([^<]{2,80})", xmp)
        if m:
            out["xmp_software"] = m.group(1).strip()
        elif b"<x:xmpmeta" in raw:                     # XMP only in raw bytes
            x = raw[raw.find(b"<x:xmpmeta"): raw.find(b"</x:xmpmeta") + 12].decode("utf-8", "ignore")
            m = re.search(r"(?:CreatorTool|Software)[^>]*>([^<]{2,80})", x)
            if m:
                out["xmp_software"] = m.group(1).strip()
    except Exception:
        pass

    # verdict + summary
    if out["ai_generated"]:
        named = [t for t in out["tools"] if not t.startswith("C2PA:")]
        gen = named[0] if named else (out["claim_generator"] or "an AI model")
        out["verdict"] = "ai_generated"
        out["summary"] = (f"The file's own C2PA Content Credentials declare it AI-generated "
                          f"by {gen}. The thief's tool tagged the theft.")
    elif out["has_c2pa"] and out["edits"]:
        out["verdict"] = "ai_edited"
        out["summary"] = "C2PA manifest records AI/editor actions on this file."
    elif out["has_c2pa"]:
        out["verdict"] = "has_provenance"
        out["summary"] = ("A C2PA manifest is present" +
                          (f" (generator: {out['claim_generator']})" if out['claim_generator'] else "") + ".")
    elif out["tools"]:
        out["verdict"] = "tool_trace"
        out["summary"] = "Metadata names an AI/editing tool: " + ", ".join(out["tools"]) + "."
    else:
        out["summary"] = "No embedded provenance or AI-tool traces found."
    return out


if __name__ == "__main__":
    import json, sys
    for p in sys.argv[1:]:
        print(p)
        print(json.dumps(read_provenance(open(p, "rb").read()), indent=2))
        print()
