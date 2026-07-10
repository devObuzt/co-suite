# Geometric scene transitions + dead-air-aware cuts — design

**Date:** 2026-07-10
**Status:** Approved (design), pending implementation plan
**Area:** Video montage — `api/services/video_montage.py`, `web/src/remotion/AiMontage.tsx`

## Problem

The montage currently marks scene boundaries with three **overlay** transition
layers stacked over the cut:

1. `visualTransitions` — library clip overlays (fed by `transition_video`
   creative assets), `mixBlendMode: screen`.
2. `TransitionEffects` — a per-scene exit light sweep.
3. `BoundaryTransition` — a between-scene light band / veil.

The owner considers the overlay look unprofessional ("كش"). Separately, the
owner uploaded a DaVinci Resolve pack (`.drfx` = 320 Fusion `.setting` macros +
PNG thumbnails, **zero video clips**) hoping to add its transitions. That pack
cannot be consumed: `.setting` files only render inside DaVinci Resolve/Fusion,
while OneShare renders via **Remotion** (React/Chromium) + ffmpeg on Railway.
The uploaded ZIP was also stored as an `active` `transition_video` asset with
`content_type: application/zip`, which would have broken renders that picked it;
it has been **deactivated** in the production DB
(`creative_assets.id = 1eada323-35f1-4748-a6c8-7377b4848ca8`).

Additionally, dead-air removal (`dead_spaces` option) physically cuts silent
gaps from the source and `concat`s the pieces, but the **join positions are
lost**, so transitions cannot be placed at those jump-cuts.

## Goal

Replace the overlay transitions with **real geometric transitions** (the family
the `.drfx` pack represents — flip / zoom / slide / fade), applied to the
**whole frame** (person + background) at **every cut** in the final video —
both dead-air removal joins and narrative scene changes — with the transition
**type chosen by scene energy**. The `.drfx` pack is used only as a visual
reference for which transitions to build, never consumed.

## Decisions (locked)

- **Scope of motion:** whole frame (person + background). Fast, Reels-style.
- **Transition set:** four — `slide`, `flip`, `zoom`, `fade`.
- **Selection:** by scene energy (`beatType` + scene duration), not random.
- **Boundaries:** every cut gets a transition — dead-air joins **and** scene
  changes.
- **Implementation approach:** `@remotion/transitions` `TransitionSeries`;
  Python decides per-boundary transition and writes it into the manifest;
  Remotion renders. (Alternatives — hand-rolled overlapping sequences, or an
  ffmpeg `xfade` post-pass — were rejected: more bug surface / breaks the
  single-composition audio+caption continuity.)

## Architecture / data flow

Same pattern as today: **Python decides, Remotion renders.**

```
source (talking-head)
  └─ cut_dead_spaces()  →  tightened video + [dead-air join times]   ← NEW: return joins
       └─ build scenes (shot-list)  →  split scenes at join times     ← NEW
            └─ per boundary: pick transition by energy  →  manifest.sceneTransitions[]  ← NEW
                 └─ Remotion: <TransitionSeries> + one continuous audio track  ← CHANGED
```

Model: **the final timeline is a list of source-segments separated by cuts;
every cut (silence or scene) carries a transition.** Background / palette /
caption follow the parent scene each segment belongs to.

## Python changes (`api/services/video_montage.py`)

- **`cut_dead_spaces()`** additionally returns `join_times`: the cumulative
  timestamps (in the *tightened* timeline) where silence was removed, derived
  from the summed durations of the retained non-silent segments.
- **Scene splitting:** any `join_time` that falls inside a scene splits that
  scene into two sub-scenes at that point. Sub-scenes inherit
  background/palette/caption from the parent but get their own
  `sourceStart`/`sourceEnd`. Result: every adjacent scene pair is a real cut.
- **`pick_scene_transition(from_scene, to_scene, seed)`** → transition type by
  energy:
  - `enumeration` beat, or scene shorter than ~1.5 s → high energy → `zoom` / `flip`
  - `cta` → `zoom` (emphasis)
  - `narrative` / calm → `fade` / `slide`
  - within a tier, a per-boundary seed (job/suite + index) distributes between
    the two choices and prevents the same transition twice in a row.
- **Manifest:** add `sceneTransitions: [{type, durationInFrames, direction?}]`
  of length `len(scenes) - 1`. Remove `visualTransitions`. `transition_video`
  assets stop being consumed but remain in the DB (kind is not removed).

## Remotion changes (`web/src/remotion/AiMontage.tsx`)

- Add dependency **`@remotion/transitions`**.
- Replace the flat `timedScenes.map(<Sequence>)` **and** the `BoundaryTransition`
  loop with a single **`<TransitionSeries>`**: one `TransitionSeries.Sequence`
  per scene, one `TransitionSeries.Transition` per boundary driven by
  `manifest.sceneTransitions[i]`.
- **Presentations:** `slide` / `fade` / `wipe` from the library; **`flip`**
  (CSS 3D `rotateY`) and **`zoom`** (springy `scale`) as custom presentations.
  Exact built-in names verified against the installed version at build time.
- **Remove** the three overlay layers: `visualTransitions`, `TransitionEffects`,
  `BoundaryTransition`.
- **Audio:** a single composition-level `<Audio>` of the tightened source
  (not per-scene), continuous and independent of the visual transitions, so
  transition overlaps never double up speech.

## Transition catalog + energy map

| Transition | Source | Energy | `.drfx` family |
|---|---|---|---|
| `slide` | library | calm/medium | Push / Pan |
| `flip`  | custom (rotateY) | high | Card Flip |
| `zoom`  | custom (springy scale) | high / cta | Zoom |
| `fade`  | library | calm | Fade |

Speed: **~6–8 frames** (fast, Reels-style).

## Edge cases & risks

- **⚠️ Top risk — A/V sync:** `TransitionSeries.Transition` overlaps its two
  neighbours, shortening the visual timeline by the sum of transition
  durations. Visual length must be compensated (extend scene durations by the
  overlap) so it equals the continuous audio length. **Verify with a
  single-`flip` prototype render before rolling out all four.**
- No silence / single segment → no joins → transitions only at scene
  boundaries (normal).
- Single scene → no transitions at all.
- `dead_spaces` off → no silence joins; scene boundaries still get transitions.
- Prevent identical consecutive transitions via the per-boundary seed.

## Testing

- **Python unit:** `pick_scene_transition` energy mapping; scene-splitting at
  join times; `sceneTransitions` manifest shape (with/without silence, single
  scene).
- **Remotion:** single-`flip` prototype render to validate A/V sync visually,
  then all four.
- **Integration:** confirm `transition_video` / `visualTransitions` removal does
  not break the rest of the render.

## Out of scope

- Consuming `.drfx` / `.setting` files (requires DaVinci Resolve; not viable in
  a Remotion/ffmpeg cloud pipeline).
- Deleting the uploaded ZIP asset from R2 (only deactivated).
- New transitions beyond the four; per-scene manual transition overrides.
