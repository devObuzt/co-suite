# Video Edit Studio Feature Brief

Date: 2026-06-09
Owner: Product Manager
Project: OneShare / co-Suite
Target milestone: M2, planned from M1 workbench evidence

## Purpose

Video Edit Studio brings the video editing and montage experiments into the main Creation experience.

The goal is to let a business owner or creator upload one or more videos, choose the type of edit, select production options, then receive a queued processed video with the same review/download/publish lifecycle used by generated content.

This feature should feel like a guided production assistant, not a raw editor. The user should not need to understand ffmpeg, Remotion, transcripts, alpha videos, or render pipelines.

## Entry Point

In `Create & Generate`, add a creation option:

- `Video Edit / Montage`

Clicking it opens a dedicated wizard. It should not be buried inside Quick Post, because it has its own upload, processing, queue, and review lifecycle.

## Wizard Flow

### Step 1: Video Type

Ask what kind of video needs editing:

1. Person or people speaking to camera.
2. Product clips or multiple business/product scenes.

This decision controls default options:

- talking-head videos enable transcript, captions, dead-space removal, background removal, and 3D behind-subject titles.
- product/scene videos enable ordering, transitions, text overlays, music, sound effects, and montage pacing.

### Step 2: Source Videos

The user can provide:

- one local video upload;
- multiple local video uploads;
- a Google Drive video link, only if the file is publicly accessible or permissioned for download.

Validation must happen before queueing:

- unsupported format;
- inaccessible Drive link;
- file too large;
- no video stream;
- no audio stream when talking-head features require transcription.

### Step 3: Clip Order and Preview

If there is more than one video:

- sort clips by filename by default;
- show each clip as a compact row or card with thumbnail, title, duration, and source;
- allow drag-and-drop reordering;
- clicking the thumbnail opens an inline preview/player;
- allow rename/title override for each clip.

The confirmed order becomes part of the job input and render manifest.

### Step 4: Editing Options

Available options:

- remove background;
- add sound effects;
- add visual transitions between clips;
- remove dead spaces / silence;
- add 3D titles between subject and background for talking-head videos;
- add captions for talking-head videos;
- add text overlays for product/scene videos;
- add music;
- user notes for the editor/AI.

Music and sound effects options must support:

- AI/default library later;
- user-uploaded local music files;
- user-uploaded local sound-effect files.

### Step 5: Queue and Processing

After confirmation, create a queued processing job.

The UI should show progress by stage:

- upload accepted;
- source analysis;
- transcript/caption extraction when relevant;
- silence/dead-space detection;
- background removal when selected;
- composition manifest creation;
- render;
- final delivery export;
- storage/public URL readiness.

Long-running work must not depend on request-local FastAPI background tasks for the final production version. It should use the same durable job direction already identified for AI generation and Product Bulk.

### Step 6: Result Review

The final video appears in Recent Content / Generated Assets with:

- video preview;
- open in new tab;
- download;
- approve;
- reject with feedback;
- regenerate/re-edit with notes;
- publish/schedule later when platform readiness exists.

Failure states must be explicit and actionable. Do not show a generic `Not Found`.

## Existing Evidence From Experiments

The current repo already contains POC work that should inform the feature:

- `docs/software-company/projects/cosuite/remotion-ai-montage-poc.md`
- `scripts/experiments/prepare_remotion_montage.py`
- `scripts/experiments/transcribe_video_openai.py`
- `scripts/experiments/generate_remotion_backgrounds_openai.py`
- `scripts/experiments/finalize_remotion_delivery.py`
- `scripts/experiments/video_bg_removal_compare.py`
- `web/src/remotion`

POC capabilities already explored:

- Remotion composition;
- transcript-driven captions;
- silence/dead-space detection;
- background/scene prompt generation;
- AI background generation;
- final MP4 delivery;
- background-removal provider comparison.

## Department Responsibilities

### Product Manager

- Own the Video Edit Studio user promise.
- Keep the first version focused on assisted montage, not a full timeline editor.
- Decide which options are V1, V1.5, and later.
- Define pricing/token implications for video processing.

### Design

- Design a calm wizard for long-running video tasks.
- Design multi-clip ordering and preview interactions.
- Design progress states that feel alive but not noisy.
- Design result review cards consistent with generated image/video content.

### Architecture

- Define the job model and video-processing state machine.
- Decide how raw uploads, intermediate files, and final renders are stored.
- Define provider abstraction for background removal, transcription, audio, and rendering.
- Define retry, cancellation, timeout, and provider-limit behavior.

### DevOps / Infra

- Define worker runtime requirements for ffmpeg, Remotion, and browser rendering.
- Define queue concurrency and CPU/memory limits.
- Define storage cleanup policies for raw/intermediate/final media.
- Define operational alerts for stuck jobs, failed renders, and provider-limit failures.

### Developers Manager

- Break implementation into slices:
  - contracts and models;
  - upload/source validation;
  - processing job worker;
  - frontend wizard;
  - result review integration;
  - QA fixtures and smoke gates.

### Developers

- Implement backend APIs for source intake, job creation, progress, and output assets.
- Implement frontend wizard and result review UI.
- Integrate Remotion/ffmpeg processing through a worker-safe interface.
- Keep provider-specific code behind service adapters.

### QA

- Build test fixtures:
  - one talking-head video;
  - multiple talking-head clips;
  - product clips;
  - inaccessible Drive link;
  - missing audio;
  - render failure;
  - provider-limit failure.
- Verify preview, queue progress, final download, rejection feedback, and regenerate flow.

## V1 Scope Recommendation

V1 should support:

- local upload of one or more videos;
- talking-head and product/scene choice;
- clip ordering;
- preview thumbnails;
- captions for talking-head videos;
- silence/dead-space removal;
- basic transitions;
- music upload;
- general editing notes;
- queued job progress;
- final MP4 preview/download/review.

V1 should defer:

- full manual timeline editing;
- public marketplace of music/effects;
- automatic publishing of edited videos;
- Drive import unless download permission validation is reliable;
- advanced 3D titles unless the subject/background pipeline is stable.

## Open Decisions

- Which background-removal provider becomes default: fal/BRIA, fal/VEED, or another provider.
- Whether V1 uses Remotion worker in Railway or a separate render service.
- Max file size and max duration for the first release.
- Whether video editing consumes tokens, separate video credits, or both.
