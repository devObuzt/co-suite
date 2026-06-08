# Shotstack Chroma Key Experiment

This experiment verifies whether Shotstack can remove a green/chroma background and render the keyed subject over a replacement image.

## Setup

Create a Shotstack account, then copy the **stage** API key from the Shotstack dashboard.

Run:

```bash
SHOTSTACK_API_KEY=your_stage_key python3 scripts/experiments/shotstack_chromakey_demo.py
```

The script submits a render, polls the render status, and prints the final MP4 URL when Shotstack finishes.

## What It Tests

- A green-screen video clip is placed on the top track.
- A background image is placed on the lower track.
- The top video uses Shotstack's `chromaKey` asset property.
- The render output is a square MP4.

Default source assets come from the official Shotstack chroma-key documentation:

- Green-screen clip: `https://shotstack-assets.s3.amazonaws.com/footage/avatar-chromakey.mp4`
- Background image: `https://shotstack-assets.s3.amazonaws.com/images/waterfall-square.jpg`

## Tunable Values

You can override these variables:

```bash
SHOTSTACK_GREEN_SCREEN_VIDEO=https://example.com/green.mp4
SHOTSTACK_BACKGROUND_IMAGE=https://example.com/background.jpg
SHOTSTACK_CHROMA_COLOR="#00ff00"
SHOTSTACK_CHROMA_THRESHOLD=150
SHOTSTACK_CHROMA_HALO=100
SHOTSTACK_API_VERSION=stage
```

## Using A Google Drive Video

1. Upload the green-screen video to Google Drive.
2. Open sharing settings.
3. Set access to **Anyone with the link**.
4. Copy the sharing link.
5. Run the script with that link:

```bash
SHOTSTACK_API_KEY=your_stage_key \
SHOTSTACK_GREEN_SCREEN_VIDEO="https://drive.google.com/file/d/FILE_ID/view?usp=sharing" \
python3 scripts/experiments/shotstack_chromakey_demo.py
```

The script converts common Google Drive share URLs into this direct-download format:

```text
https://drive.google.com/uc?export=download&id=FILE_ID
```

Google Drive can still block some large files, files with download warnings, or files with restricted permissions. If that happens, upload the test video to Cloudinary, S3, R2, or another public file host and use that direct file URL instead.

## Notes

Shotstack chroma key is for videos with a controlled color background, such as green screen. It is not AI background removal for ordinary videos without a solid chroma backdrop.

Source: https://shotstack.io/docs/guide/architecting-an-application/chromakey/
