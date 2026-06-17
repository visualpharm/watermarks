# Home before/after slider — requirements (locked)

## Layout
- Picker bar ABOVE the image, single line on desktop.
- LEFT field = "Watermarked · version" → controls the LEFT (before) image.
- RIGHT field = "After AI removal · attack model" → **aligned to the right edge**
  of the bar (sits above the right/after half of the image it controls).
- Plain native `<select>` (no custom pill/chevron styling).

## Defaults
- Version: latest (v4).
- Attack model: most successful removal first (verdict rank, confidence tiebreak).

## The bug being fixed
- Attack `<select>` was populated from `attacks.filter(a => a.image)`.
  Models that refused (image:null) were dropped, so v1/v3/v4 collapsed to ONE option.
- Fix: list ALL attack models for the version. Each option shows model + outcome:
  - produced an image → "model · removed"  → right half = the cleaned result.
  - refused (no image) → "model · refused" → right half = the watermarked image
    itself (watermark survived; both halves identical), caption explains.
- Result: every version now shows multiple models AND multiple results.

## Data today (static/versions/versions.json)
- 2 attack models per version: Flux Kontext, nano-banana.
- v1: Kontext removed, nano refused
- v2: Kontext removed, nano removed
- v3: Kontext removed, nano refused
- v4: Kontext removed, nano refused   ← latest = default

## Verify headless
- Default = V4 + Flux Kontext; before wm-v4.jpg, after wm-v4-kontext.jpg.
- v4 attack dropdown has 2 options (not 1).
- Switch to v2 → both options removable; switch model swaps the right image.
- Pick a "refused" model → right image == left image, caption says refused.
- RIGHT field is right-aligned; bar is a single row on desktop.
