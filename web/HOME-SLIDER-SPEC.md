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
- 7 attack models per version: Flux Kontext, Flux Kontext Max, nano-banana,
  Nano Banana Pro, Qwen Image Edit, Seedream v4, GPT image (OpenAI gpt-image-1).
- Every model removes the mark by regenerating the asset EXCEPT Nano Banana Pro,
  which refuses on all four versions.
- GPT image regenerates the whole frame from scratch (fresh 1024² composition) —
  the watermark is gone but so is the original asset; it carries a damage score
  like the others.
- Dropdown is sorted heaviest-rebuild first (verdict rank, then damage score);
  the most successful removal is the default option.

## Verify headless
- Default version = latest (v4); default model = the heaviest successful removal.
- Each version's attack dropdown lists ALL 7 models (refused ones included).
- Switch model → swaps the right (after) image; caption shows the damage score.
- Pick the "refused" model (Nano Banana Pro) → right image == left image, caption
  says refused.
- RIGHT field is right-aligned; bar is a single row on desktop.
