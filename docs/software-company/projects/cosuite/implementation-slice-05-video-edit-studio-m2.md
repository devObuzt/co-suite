# Implementation Slice 05: Video Edit Studio

Date: 2026-06-09
Owner: Developers Manager
Source brief: `video-edit-studio-feature-brief-m2.md`
Target milestone: M2

## Slice Goal

Add a planned Video Edit Studio creation workflow that turns uploaded videos into queued montage/editing jobs and returns reviewable final videos.

This slice is planning-ready, not implementation-started. It should start after Product Bulk lifecycle gates and M1 stabilization tasks are closed or explicitly accepted as parallel M2 work.

## Task Breakdown

| ID | Owner | Status | Scope | Acceptance Criteria |
| --- | --- | --- | --- | --- |
| PROD-03 | Product Manager | ready_for_handoff | Video Edit Studio product brief | User promise, wizard steps, V1 scope, deferred scope, and open decisions are documented. |
| DESIGN-02 | Design | not_started | Video Edit Studio wizard design | Desktop/mobile wizard covers type selection, upload/Drive source, clip ordering, editing options, progress, and result review. |
| ARCH-03 | Architecture | not_started | Video processing architecture | Job model, state machine, storage model, provider adapters, retries, cancellation, provider-limit handling, and worker requirements are specified. |
| DEVOPS-03 | DevOps / Infra | not_started | Render worker readiness | ffmpeg/Remotion runtime, queue concurrency, storage cleanup, CPU/memory limits, and stuck-job alerts are defined. |
| DEVMGR-04 | Developers Manager | not_started | Engineering implementation plan | Backend/frontend tasks are sequenced with tests, fixtures, dependencies, and rollout gates. |
| DEV-J-01 | Developers | not_started | Backend contracts | APIs support source upload/link validation, job creation, progress polling, result asset serialization, and explicit failure states. |
| DEV-J-02 | Developers | not_started | Video processing worker | Worker processes a fixture video through analysis, optional transcription, dead-space removal, composition, render, and final storage. |
| DEV-J-03 | Developers | not_started | Frontend wizard | Creation UI opens Video Edit Studio wizard, supports multi-video ordering/preview, options, queue state, and result review. |
| QA-04 | QA | not_started | Video Edit Studio smoke matrix | QA fixtures and smoke rows cover successful render, inaccessible link, missing audio, multi-clip ordering, provider limit, failed render, preview, download, and regenerate/edit feedback. |

## Proposed V1 Technical Flow

1. Frontend creates a draft video-edit session.
2. User uploads local videos or provides a supported link.
3. Backend validates source metadata and stores raw files.
4. User confirms clip order and edit options.
5. Backend creates a durable generation job with `job_type = video_edit`.
6. Worker processes:
   - source probe;
   - thumbnail extraction;
   - transcript/caption extraction when talking-head;
   - silence/dead-space detection;
   - optional background removal;
   - manifest creation;
   - Remotion/ffmpeg render;
   - final MP4 storage.
7. Frontend polls job progress.
8. Final asset appears in Recent Content / Generated Assets.

## Backend Contracts To Design

Candidate endpoints:

- `POST /suites/{suite_id}/video-edit/sessions`
- `POST /suites/{suite_id}/video-edit/sessions/{session_id}/sources`
- `POST /suites/{suite_id}/video-edit/sessions/{session_id}/confirm`
- `GET /suites/{suite_id}/video-edit/sessions/{session_id}`
- `GET /suites/{suite_id}/video-edit/jobs/{job_id}`
- `POST /suites/{suite_id}/video-edit/assets/{asset_id}/regenerate`

Contracts must include:

- clip order;
- clip title;
- source type;
- source validation status;
- thumbnail URL;
- duration;
- audio presence;
- selected edit options;
- user notes;
- final media URL;
- job status and progress events.

## Processing States

Suggested states:

- `draft`
- `sources_uploaded`
- `sources_validated`
- `awaiting_confirmation`
- `queued`
- `analyzing`
- `transcribing`
- `cutting`
- `removing_background`
- `composing`
- `rendering`
- `finalizing`
- `completed`
- `failed`
- `canceled`

## Design Notes

The UI should avoid looking like professional timeline software. The user should make simple decisions and see what the system is doing.

Important screens:

- creation card for Video Edit / Montage;
- video type step;
- source upload/link step;
- clip ordering step;
- edit options step;
- processing/progress screen;
- final result review card.

## QA Fixtures

Minimum fixtures:

- one talking-head video with clear speech;
- one talking-head video with silence/dead spaces;
- two or three clips named in sortable order;
- product scene clips without speech;
- video without audio;
- inaccessible Google Drive link;
- oversized file;
- simulated provider-limit exception;
- simulated render failure.

## Risks

- Video processing is expensive and slow.
- Railway web process should not carry long render jobs.
- Raw/intermediate media can consume storage quickly.
- Background removal providers may have limits and inconsistent output.
- Captions and non-English text must be treated carefully, especially Arabic/Hebrew.
- Drive links can fail due to permissions even when they appear valid in browser.

## Gate Before Implementation

Do not start implementation until:

- `DESIGN-02` has a reviewed wizard design.
- `ARCH-03` has a durable worker/storage/job design.
- `DEVOPS-03` confirms render runtime feasibility.
- `QA-04` has fixture definitions.
- Product confirms max video duration, max file size, and V1 option defaults.
