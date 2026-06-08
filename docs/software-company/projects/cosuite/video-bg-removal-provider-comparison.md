# Video Background Removal Provider Comparison

This experiment compares the same source video across three providers:

- `bria-fal`: BRIA video background removal through fal.ai.
- `veed-fal`: VEED video background removal through fal.ai.
- `cutout-pro`: Cutout.Pro video background removal API.

## Run All Providers

```bash
VIDEO_URL="https://drive.google.com/file/d/FILE_ID/view?usp=sharing" \
FAL_KEY="your_fal_key" \
CUTOUT_PRO_API_KEY="your_cutout_key" \
python3 scripts/experiments/video_bg_removal_compare.py
```

Results are written to:

```text
reports/video-bg-removal/<timestamp>/results.json
```

## Run Only fal Providers

```bash
VIDEO_URL="https://drive.google.com/file/d/FILE_ID/view?usp=sharing" \
FAL_KEY="your_fal_key" \
PROVIDERS="bria-fal,veed-fal" \
python3 scripts/experiments/video_bg_removal_compare.py
```

## Run Only Cutout.Pro

```bash
VIDEO_URL="https://drive.google.com/file/d/FILE_ID/view?usp=sharing" \
CUTOUT_PRO_API_KEY="your_cutout_key" \
PROVIDERS="cutout-pro" \
python3 scripts/experiments/video_bg_removal_compare.py
```

## Useful Options

```bash
VEED_OUTPUT_CODEC=vp9        # vp9 or h264
VEED_REFINE_EDGES=true       # true or false
VEED_SUBJECT_IS_PERSON=true  # false for product/object videos
BRIA_BACKGROUND_COLOR=Transparent
BRIA_OUTPUT_CODEC=webm_vp9
CUTOUT_OUTPUT_FORMAT=mov     # mov or webm
MAX_WAIT_SECONDS=900
POLL_SECONDS=10
```

Google Drive share links are converted to direct-download URLs automatically, but the file must be public: **Anyone with the link**.

## What To Judge Manually

- Edge quality around hair, hands, and motion blur.
- Flicker between frames.
- Whether the output has a usable alpha channel.
- Processing time.
- Output format fit for the editing pipeline.
- Cost and API reliability.

Sources:

- https://fal.ai/models/bria/video/background-removal/api
- https://fal.ai/models/veed/video-background-removal/api
- https://www.cutout.pro/api-document/video-background-removal/
