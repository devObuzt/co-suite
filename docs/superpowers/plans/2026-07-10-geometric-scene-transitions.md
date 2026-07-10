# Geometric Scene Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three overlay transition layers with real geometric transitions (flip/zoom/slide/fade) applied to the whole frame at every cut — dead-air joins and scene changes — with the transition type chosen by scene energy.

**Architecture:** Python decides, Remotion renders. `cut_dead_spaces()` returns the dead-air join timestamps; the manifest builder splits scenes at those joins and writes a `sceneTransitions[]` array chosen by `beatType`+duration; `AiMontage.tsx` renders a `@remotion/transitions` `TransitionSeries` and removes the overlay layers. Audio becomes one continuous composition-level track so transition overlaps never double speech.

**Tech Stack:** Python (FastAPI service, `api/services/video_montage.py`), Remotion 4.0.x (`web/src/remotion/AiMontage.tsx`), `@remotion/transitions`, pytest, ffmpeg.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-10-geometric-scene-transitions-design.md`.
- Transition set is exactly four: `slide`, `flip`, `zoom`, `fade`. No others.
- Transition speed: 6–8 frames. Default `TRANSITION_FRAMES = 7`.
- `@remotion/transitions` version MUST match the installed `remotion` version (`^4.0.473`) — pin the same major.minor.
- Web workspace is a modified Next.js/Remotion: read `node_modules/next/dist/docs/` before writing any Next code; for Remotion, confirm the installed `@remotion/transitions` API surface before using it (see Task 1).
- `transition_video` creative-asset kind is NOT removed from the DB or `ALL_KINDS`; it simply stops being consumed by the montage.
- Preserve existing behaviour when `dead_spaces` is off and when there is a single scene (no transitions).
- Load env before any manual render/test that touches the service: `set -a; source api/.env; set +a`.
- **`web/` is an embedded git repo** (gitlink `160000`, no `.gitmodules`): its `web/src/**` changes commit INSIDE `web/` (`cd web && git commit`), then the outer repo records the pointer bump (`cd .. && git add web && git commit`). The web working tree already carries unrelated pre-existing dirty files (a prior feature) — web tasks MUST `git add` only their own named files, NEVER `git add -A`/`git add .`.

---

## Task 1: Spike — verify `@remotion/transitions` API and A/V sync

**Goal:** De-risk the two unknowns before writing production code: (a) which of the four transitions are built-in vs need a custom presentation, and (b) the exact frame math that keeps the visual `TransitionSeries` length equal to the continuous audio length. This task produces a throwaway prototype and a short findings note; no production files change.

**Files:**
- Create (throwaway): `web/src/remotion/_spike/TransitionSpike.tsx`
- Create: `docs/superpowers/plans/2026-07-10-spike-findings.md`

**Interfaces:**
- Produces (findings consumed by Tasks 6–8): the import path + factory signature for each of `slide`/`fade`/`wipe`/`flip`; whether `zoom` needs a custom `TransitionPresentation`; and the sync rule — given scene durations `D[i]` (frames) and a transition of `T` frames on every boundary, the exact `TransitionSeries.Sequence` `durationInFrames` to use so the composition's total equals `sum(D)`.

- [ ] **Step 1: Install the transitions package pinned to the remotion version**

Run:
```bash
cd web && npm install @remotion/transitions@$(node -p "require('./package.json').dependencies.remotion.replace('^','')")
```
Expected: `@remotion/transitions` added to `web/package.json` `dependencies` at the same version as `remotion`.

- [ ] **Step 2: Enumerate the built-in presentations and timings**

Run:
```bash
cd web && node -e "for (const m of ['','/slide','/fade','/wipe','/flip','/clock-wipe','/none']) { try { console.log(m||'(root)', Object.keys(require('@remotion/transitions'+m))); } catch(e){ console.log(m,'MISSING',e.code); } }"
```
Record, in the findings note, the exact export names and sub-paths that resolve (e.g. whether `flip` exists at `@remotion/transitions/flip`, and whether the root exports `TransitionSeries`, `linearTiming`, `springTiming`). Mark any of the four that has no built-in as "needs custom presentation".

- [ ] **Step 3: Build a minimal 3-sequence prototype**

Create `web/src/remotion/_spike/TransitionSpike.tsx` with three solid-colour `AbsoluteFill`s of known frame lengths (e.g. 30/30/30) wrapped in a `TransitionSeries`, a `flip` transition and a `slide` transition of `T=7` frames between them, and a single `<Audio>` (any bundled wav) spanning the full intended length. Register it as a temporary composition in `web/src/remotion/Root.tsx`.

- [ ] **Step 4: Measure the real composition length vs the intended length**

Run:
```bash
cd web && npm exec remotion -- compositions src/remotion/index.ts 2>/dev/null | grep -i spike
```
Compare the reported `durationInFrames` to `sum(D)`. Derive the compensation rule: with `TransitionSeries.Transition` overlapping its neighbours by `T`, total `= sum(seqDurations) - (numTransitions * T)`. Write the concrete rule to keep total `== sum(D)` (e.g. "set each interior sequence's `durationInFrames = D[i] + T`, first/last `+ T/2`", or the exact variant that the measurement confirms). This rule is consumed verbatim by Task 8.

- [ ] **Step 5: Record findings and remove the spike composition**

Write `docs/superpowers/plans/2026-07-10-spike-findings.md` with: the resolved import paths, the list of built-in vs custom transitions, and the confirmed sync rule. Delete the temporary composition registration from `Root.tsx` (leave `TransitionSpike.tsx` untracked or delete it — it must not ship).

- [ ] **Step 6: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web/package.json web/package-lock.json docs/superpowers/plans/2026-07-10-spike-findings.md
git commit -m "chore: add @remotion/transitions and record transition spike findings"
```

---

## Task 2: `cut_dead_spaces()` returns dead-air join timestamps

**Files:**
- Modify: `api/services/video_montage.py:2108` (`cut_dead_spaces`)
- Test: `tests/test_video_montage_transitions.py` (create)

**Interfaces:**
- Consumes: `non_silent_segments(path, duration) -> list[tuple[float,float]]` (existing).
- Produces: `cut_dead_spaces(source_path, output_path, duration) -> tuple[Path, bool, str | None, list[float]]` — the new 4th element `join_times` is the cumulative offsets (seconds, in the tightened timeline) at each internal segment boundary; empty when no cut is applied.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_video_montage_transitions.py`:
```python
from api.services.video_montage import dead_air_join_times


def test_join_times_are_cumulative_segment_ends():
    # Two silences removed from a 10s clip leave three speech chunks whose
    # tightened durations are 2.0, 3.0, 1.5 -> joins at 2.0 and 5.0.
    segments = [(0.0, 2.0), (4.0, 7.0), (8.5, 10.0)]
    assert dead_air_join_times(segments) == [2.0, 5.0]


def test_join_times_empty_for_single_segment():
    assert dead_air_join_times([(0.0, 10.0)]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: FAIL with `ImportError: cannot import name 'dead_air_join_times'`.

- [ ] **Step 3: Add the helper and extend `cut_dead_spaces`**

Add near `non_silent_segments` (after line 968):
```python
def dead_air_join_times(segments: list[tuple[float, float]]) -> list[float]:
    """Cumulative tightened-timeline offsets at each internal segment join.

    After concatenating the retained non-silent segments, the k-th internal
    boundary sits at the sum of the first k segment durations. The final
    segment's end is the clip end, not a join, so it is excluded.
    """
    if len(segments) <= 1:
        return []
    joins: list[float] = []
    cursor = 0.0
    for start, end in segments[:-1]:
        cursor += max(0.0, end - start)
        joins.append(round(cursor, 3))
    return joins
```
Change the two `return source_path, False, ...` lines in `cut_dead_spaces` to append `, []`, the final success `return output_path, True, None` to `return output_path, True, None, dead_air_join_times(segments)`, and compute `segments` once at the top (already present at line 2111). The failure returns become:
```python
        return source_path, False, "No audio stream was found, so silence cutting was skipped.", []
    segments = non_silent_segments(source_path, duration)
    if len(segments) <= 1:
        return source_path, False, None, []
```
and the exception path:
```python
    except subprocess.CalledProcessError as exc:
        return source_path, False, (exc.stderr or exc.stdout or str(exc))[-500:], []
    return output_path, True, None, dead_air_join_times(segments)
```

- [ ] **Step 4: Update the single caller to unpack four values**

At `api/services/video_montage.py:2734`, change:
```python
            tight_path, cut_applied, cut_warning = await asyncio.to_thread(
                cut_dead_spaces,
                normalized_for_cut,
                output_dir / "tight-source.mp4",
                pre_cut_duration,
            )
```
to unpack `tight_path, cut_applied, cut_warning, dead_air_joins = await asyncio.to_thread(...)` and initialise `dead_air_joins: list[float] = []` next to `dead_space_seconds_cut` at line 2728.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add api/services/video_montage.py tests/test_video_montage_transitions.py
git commit -m "feat(montage): cut_dead_spaces returns dead-air join timestamps"
```

---

## Task 3: `pick_scene_transition()` — energy → transition type

**Files:**
- Modify: `api/services/video_montage.py` (add helper near the other scene helpers, after `beat_scene_segments`)
- Test: `tests/test_video_montage_transitions.py`

**Interfaces:**
- Consumes: scene dicts with `beatType: str | None`, `sourceStart: float`, `sourceEnd: float`.
- Produces: `pick_scene_transition(from_scene, to_scene, seed: int) -> dict` returning `{"type": "slide"|"flip"|"zoom"|"fade", "durationInFrames": int, "direction": str | None}`; and module constant `TRANSITION_FRAMES = 7`.

- [ ] **Step 1: Write the failing test**

Add:
```python
from api.services.video_montage import pick_scene_transition, TRANSITION_FRAMES


def _scene(beat_type=None, start=0.0, end=3.0):
    return {"beatType": beat_type, "sourceStart": start, "sourceEnd": end}


def test_cta_incoming_scene_gets_zoom():
    t = pick_scene_transition(_scene("narrative"), _scene("cta"), seed=0)
    assert t["type"] == "zoom"
    assert t["durationInFrames"] == TRANSITION_FRAMES


def test_enumeration_is_high_energy_flip_or_zoom():
    t = pick_scene_transition(_scene(), _scene("enumeration"), seed=0)
    assert t["type"] in {"flip", "zoom"}


def test_short_incoming_scene_is_high_energy():
    t = pick_scene_transition(_scene(), _scene("narrative", 0.0, 1.0), seed=1)
    assert t["type"] in {"flip", "zoom"}


def test_calm_narrative_is_fade_or_slide():
    t = pick_scene_transition(_scene("narrative", 0, 5), _scene("narrative", 5, 11), seed=0)
    assert t["type"] in {"fade", "slide"}


def test_seed_parity_alternates_within_tier():
    a = pick_scene_transition(_scene(), _scene("enumeration"), seed=0)
    b = pick_scene_transition(_scene(), _scene("enumeration"), seed=1)
    assert a["type"] != b["type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: FAIL with `ImportError: cannot import name 'pick_scene_transition'`.

- [ ] **Step 3: Implement the helper**

Add module constant near the other constants (after `MAX_MONTAGE_SCENES = 24`):
```python
TRANSITION_FRAMES = 7
```
Add after `beat_scene_segments`:
```python
def _scene_is_high_energy(scene: dict[str, Any]) -> bool:
    beat_type = str(scene.get("beatType") or "").lower()
    duration = float(scene.get("sourceEnd") or 0) - float(scene.get("sourceStart") or 0)
    return beat_type == "enumeration" or duration < 1.5


def pick_scene_transition(
    from_scene: dict[str, Any],
    to_scene: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Choose a geometric transition for one scene boundary by energy.

    High-energy boundaries (fast enumeration beats or a short incoming scene)
    get flip/zoom; a closing cta gets zoom for emphasis; calm narrative
    boundaries get fade/slide. Within a tier the seed parity alternates the two
    choices so the same transition never repeats back-to-back.
    """
    incoming_beat = str(to_scene.get("beatType") or "").lower()
    parity = seed % 2
    if incoming_beat == "cta":
        transition_type = "zoom"
    elif _scene_is_high_energy(to_scene) or _scene_is_high_energy(from_scene):
        transition_type = ("flip", "zoom")[parity]
    else:
        transition_type = ("fade", "slide")[parity]
    direction = "from-left" if parity == 0 else "from-right"
    return {
        "type": transition_type,
        "durationInFrames": TRANSITION_FRAMES,
        "direction": direction if transition_type == "slide" else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add api/services/video_montage.py tests/test_video_montage_transitions.py
git commit -m "feat(montage): pick_scene_transition selects transition by scene energy"
```

---

## Task 4: `split_scenes_at_joins()` — insert a boundary at each dead-air join

**Files:**
- Modify: `api/services/video_montage.py` (add helper; used inside `build_remotion_scene_manifest`)
- Test: `tests/test_video_montage_transitions.py`

**Interfaces:**
- Consumes: the `scenes` list (each dict has `id`, `sourceStart`, `sourceEnd`, `caption`, `captionChunks`, `palette`, `beatType`, plus other fields) and `dead_air_joins: list[float]` in tightened-timeline seconds.
- Produces: `split_scenes_at_joins(scenes, joins, fps) -> list[dict]` — the same scenes with any scene that strictly contains a join split into two at that time; `id`s re-sequenced `scene-01..`; all non-timing fields copied; `captionChunks` recomputed per half via `build_caption_chunks`.

- [ ] **Step 1: Write the failing test**

Add:
```python
from api.services.video_montage import split_scenes_at_joins


def _full_scene(idx, start, end, caption="hello world"):
    return {
        "id": f"scene-{idx:02d}",
        "sourceStart": start,
        "sourceEnd": end,
        "caption": caption,
        "captionChunks": [],
        "palette": ["#111", "#222", "#333"],
        "beatType": "narrative",
    }


def test_join_inside_scene_splits_it():
    scenes = [_full_scene(1, 0.0, 4.0)]
    out = split_scenes_at_joins(scenes, [2.0], fps=30)
    assert len(out) == 2
    assert out[0]["sourceStart"] == 0.0 and out[0]["sourceEnd"] == 2.0
    assert out[1]["sourceStart"] == 2.0 and out[1]["sourceEnd"] == 4.0
    assert [s["id"] for s in out] == ["scene-01", "scene-02"]
    assert out[0]["palette"] == out[1]["palette"] == ["#111", "#222", "#333"]


def test_join_at_existing_boundary_is_ignored():
    scenes = [_full_scene(1, 0.0, 2.0), _full_scene(2, 2.0, 4.0)]
    out = split_scenes_at_joins(scenes, [2.0], fps=30)
    assert len(out) == 2


def test_no_joins_returns_scenes_unchanged():
    scenes = [_full_scene(1, 0.0, 4.0)]
    out = split_scenes_at_joins(scenes, [], fps=30)
    assert out == scenes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: FAIL with `ImportError: cannot import name 'split_scenes_at_joins'`.

- [ ] **Step 3: Implement the helper**

Add after `pick_scene_transition`:
```python
def split_scenes_at_joins(
    scenes: list[dict[str, Any]],
    joins: list[float],
    fps: int,
) -> list[dict[str, Any]]:
    """Split any scene that strictly contains a dead-air join into two scenes.

    Sub-scenes inherit every non-timing field (palette, caption, beatType,
    background) from the parent; only sourceStart/sourceEnd change and
    captionChunks are recomputed for each half's time window. Joins that land
    on an existing scene boundary (within one frame) are ignored. Ids are
    re-sequenced scene-01.. after all splits.
    """
    if not joins:
        return scenes
    epsilon = 1.0 / max(1, fps)
    result: list[dict[str, Any]] = []
    for scene in scenes:
        start = float(scene["sourceStart"])
        end = float(scene["sourceEnd"])
        inner = sorted(t for t in joins if start + epsilon < t < end - epsilon)
        if not inner:
            result.append(scene)
            continue
        cut_points = [start, *inner, end]
        for lo, hi in zip(cut_points, cut_points[1:]):
            piece = dict(scene)
            piece["sourceStart"] = round(lo, 3)
            piece["sourceEnd"] = round(hi, 3)
            piece["captionChunks"] = build_caption_chunks(
                scene.get("caption") or "", lo, hi, None
            )
            result.append(piece)
    for index, scene in enumerate(result):
        scene["id"] = f"scene-{index + 1:02d}"
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add api/services/video_montage.py tests/test_video_montage_transitions.py
git commit -m "feat(montage): split scenes at dead-air joins"
```

---

## Task 5: Thread joins into the manifest builder and emit `sceneTransitions`

**Files:**
- Modify: `api/services/video_montage.py` — `build_remotion_scene_manifest` (1405), `_render_remotion_montage_impl` (1979) call at 2011, `render_remotion_montage` (1940), and the `_generate_video_montage_impl` render dispatch.
- Test: `tests/test_video_montage_transitions.py`

**Interfaces:**
- Consumes: `split_scenes_at_joins`, `pick_scene_transition`, `dead_air_joins` from Task 2.
- Produces: `build_remotion_scene_manifest(..., dead_air_joins: list[float] | None = None)`; manifest gains `"sceneTransitions": list[dict]` (length `len(scenes) - 1`, empty for a single scene) and drops `"visualTransitions"`.

- [ ] **Step 1: Write the failing test for the transition array shape**

Add a test that calls the pure assembly of transitions (extract the per-boundary loop into a tiny helper so it is unit-testable):
```python
from api.services.video_montage import build_scene_transitions


def test_build_scene_transitions_length_is_boundaries():
    scenes = [_full_scene(1, 0, 2), _full_scene(2, 2, 4), _full_scene(3, 4, 6)]
    out = build_scene_transitions(scenes, seed=0)
    assert len(out) == 2
    assert all(set(t) == {"type", "durationInFrames", "direction"} for t in out)


def test_build_scene_transitions_single_scene_is_empty():
    assert build_scene_transitions([_full_scene(1, 0, 2)], seed=0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_scene_transitions'`.

- [ ] **Step 3: Add `build_scene_transitions` and wire it into the manifest**

Add after `split_scenes_at_joins`:
```python
def build_scene_transitions(scenes: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """One transition per interior boundary, chosen by energy (seeded)."""
    return [
        pick_scene_transition(scenes[i], scenes[i + 1], seed=seed + i)
        for i in range(len(scenes) - 1)
    ]
```
In `build_remotion_scene_manifest`:
1. Add `dead_air_joins: list[float] | None = None` to the signature (after `shot_list_beats`).
2. After the `scenes` list is fully built (immediately before `edited_duration = ...` at line 1745), insert:
```python
    scenes = split_scenes_at_joins(scenes, dead_air_joins or [], fps)
```
3. Delete the `transition_video_assets` selection block (lines ~1754–1764) and the `visual_transitions` construction inside the boundary loop (the `visual_transition_added` / `visual_asset` branch, ~1788–1806); keep the whoosh/`transition` SFX branch by making the loop always fall through to it. The reduced loop body is:
```python
    for index, start in enumerate(starts[1:]):
        if not music_enabled:
            continue
        asset = transition_assets[index % len(transition_assets)] if transition_assets else None
        if asset:
            public_path = remotion_public_asset_path(asset.storage_url, work_dir, asset.id)
            if public_path:
                selected_asset_ids.append(asset.id)
                sound_effects.append({"publicPath": public_path, "at": round(start, 3), "volume": 0.3, "assetId": asset.id, "kind": "transition"})
        elif whoosh_path.exists():
            sound_effects.append({"publicPath": "/remotion/sound/soft-whoosh.wav", "at": round(start, 3), "volume": 0.3, "kind": "transition"})
```
4. Remove `transition_video` from `wanted_kinds` seeding is NOT needed (kind stays valid); just stop referencing `transition_video_assets`.
5. Replace `"visualTransitions": visual_transitions,` in the manifest dict (line 1896) with:
```python
        "sceneTransitions": build_scene_transitions(scenes, seed=render_shuffle_seed),
```
`render_shuffle_seed` is already computed at line 1760 — keep that line even though the shuffle list is deleted, since the seed is reused here.

- [ ] **Step 4: Pass joins through the two intermediate callers**

In `_render_remotion_montage_impl` (line 1979) add a parameter `dead_air_joins: list[float] | None = None` and forward it in the `build_remotion_scene_manifest(...)` call at 2011 as `dead_air_joins=dead_air_joins`. In `render_remotion_montage` (1940) add the same parameter and forward it to `_render_remotion_montage_impl`. In `_generate_video_montage_impl`, pass `dead_air_joins=dead_air_joins` (from Task 2 Step 4) into whichever `render_remotion_montage(...)` call drives the Remotion render.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: PASS (12 passed).

- [ ] **Step 6: Sanity-check the module imports and no stale `visualTransitions` refs remain in Python**

Run:
```bash
python -c "import api.services.video_montage"
grep -n "visual_transitions\|visualTransitions\|transition_video_assets" api/services/video_montage.py || echo "clean"
```
Expected: import succeeds; grep prints only comments/none for the deleted names (no active assignments).

- [ ] **Step 7: Commit**

```bash
git add api/services/video_montage.py tests/test_video_montage_transitions.py
git commit -m "feat(montage): emit sceneTransitions, drop visualTransitions, thread dead-air joins"
```

---

## Task 6: SKIPPED — `zoom` is a built-in transition

**Status: dropped after the Task 1 spike.** The spike
(`docs/superpowers/plans/2026-07-10-spike-findings.md`) found that all five
transitions this plan uses are built into `@remotion/transitions` — no custom
`TransitionPresentation` is needed. In particular `zoom` ships as **`zoomInOut`**
from `@remotion/transitions/zoom-in-out` (the sub-path is `zoom-in-out`, not
`zoom`). Task 8 imports the built-in directly; there is no `zoom.tsx` to create.
No work in this task.

---

## Task 7: Remotion — move audio to a single continuous composition track

**Files:**
- Modify: `web/src/remotion/AiMontage.tsx` — `SceneLayer` (601) and `AiMontage` (698)

**Interfaces:**
- Consumes: `manifest.source` (`publicPath`), `sourceAudioPath` (existing module value used at line 668).
- Produces: `SceneLayer` no longer renders its own `<Audio>`; `AiMontage` renders exactly one top-level `<Audio src={publicAsset(sourceAudioPath)} />` spanning the whole composition.

- [ ] **Step 1: Remove the per-scene Audio from `SceneLayer`**

In `SceneLayer` delete the line at 668:
```tsx
      <Audio src={publicAsset(sourceAudioPath)} startFrom={startFrom} endAt={endAt} />
```

- [ ] **Step 2: Add one composition-level Audio in `AiMontage`**

In `AiMontage`'s returned tree, directly after the `backgroundMusic` `<Audio>` block (line 728), add:
```tsx
      <Audio src={publicAsset(sourceAudioPath)} />
```
(The tightened source's audio is already continuous, so no `startFrom`/`endAt` is needed; it plays for the whole composition.)

- [ ] **Step 3: Type-check**

Run: `cd web && npm exec tsc -- --noEmit`
Expected: no errors; `startFrom`/`endAt` no longer referenced only by the removed line (they remain used by the video `OffthreadVideo` in `SceneLayer`).

- [ ] **Step 4: Commit**

```bash
git add web/src/remotion/AiMontage.tsx
git commit -m "feat(remotion): single continuous audio track independent of transitions"
```

---

## Task 8: Remotion — render scenes through `TransitionSeries`, remove overlay layers

**Files:**
- Modify: `web/src/remotion/AiMontage.tsx` — imports, `AiMontage` (698); delete `TransitionEffects` (398) usage and `BoundaryTransition` (555).

**Interfaces:**
- Consumes: `manifest.sceneTransitions` (from Task 5), `zoom` (Task 6), built-in presentations (Task 1), `SceneLayer`.
- Produces: the montage renders each scene as a `TransitionSeries.Sequence` with a `TransitionSeries.Transition` per boundary; the three overlay layers are gone.

- [ ] **Step 1: Add imports (confirmed built-in by the Task 1 spike)**

At the top of `AiMontage.tsx` (all five are built-in — the spike verified `flip`
is built-in and `zoom` ships as `zoomInOut` at sub-path `zoom-in-out`):
```tsx
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {slide} from '@remotion/transitions/slide';
import {fade} from '@remotion/transitions/fade';
import {flip} from '@remotion/transitions/flip';
import {zoomInOut} from '@remotion/transitions/zoom-in-out';
```

- [ ] **Step 2: Add the presentation + timing resolver**

Inside `AiMontage`, before the return, add:
```tsx
  const sceneTransitions =
    'sceneTransitions' in manifest && Array.isArray(manifest.sceneTransitions)
      ? (manifest.sceneTransitions as Array<{
          type: 'slide' | 'flip' | 'zoom' | 'fade';
          durationInFrames: number;
          direction?: string | null;
        }>)
      : [];

  const presentationFor = (t: (typeof sceneTransitions)[number]) => {
    if (t.type === 'slide')
      return slide({direction: t.direction === 'from-right' ? 'from-right' : 'from-left'});
    if (t.type === 'flip') return flip();
    if (t.type === 'zoom') return zoomInOut();
    return fade();
  };
```

- [ ] **Step 3: Replace the scene + bridge render blocks with a `TransitionSeries`**

Replace the two blocks at lines 760–778 (`timedScenes.map(<Sequence>)` and the `timedScenes.slice(0,-1).map(BoundaryTransition)`) with:
```tsx
      <TransitionSeries>
        {timedScenes.flatMap(({duration, scene}, index) => {
          // Compensation rule from spike findings: keep the visual timeline
          // length equal to sum(scene durations) despite transition overlap.
          const seqFrames = duration + (index === 0 || index === timedScenes.length - 1
            ? Math.ceil(TRANSITION_FRAMES / 2)
            : TRANSITION_FRAMES);
          const nodes = [
            <TransitionSeries.Sequence key={scene.id} durationInFrames={seqFrames}>
              <SceneLayer scene={scene} durationInFrames={duration} />
            </TransitionSeries.Sequence>,
          ];
          const t = sceneTransitions[index];
          if (index < timedScenes.length - 1 && t) {
            nodes.push(
              <TransitionSeries.Transition
                key={`${scene.id}-t`}
                presentation={presentationFor(t)}
                timing={linearTiming({durationInFrames: t.durationInFrames})}
              />,
            );
          }
          return nodes;
        })}
      </TransitionSeries>
```
Add `const TRANSITION_FRAMES = 7;` near the top constants (mirror the Python default). **Replace the `seqFrames` formula with the exact rule recorded in Task 1 Step 4 if it differs** — that measured rule is authoritative for A/V sync.

- [ ] **Step 4: Delete the now-unused overlay code**

Remove the `visualTransitions` block (lines 738–759), the `TransitionEffects` element inside `SceneLayer` (line 694), the `TransitionEffects` component (398–452) and the `BoundaryTransition` component (555–599). Remove now-unused imports (`OffthreadVideo` stays; drop `BRIDGE_FRAMES` if only the deleted code used it).

- [ ] **Step 5: Type-check and lint**

Run: `cd web && npm exec tsc -- --noEmit`
Expected: no errors; no references to `TransitionEffects`, `BoundaryTransition`, `visualTransitions`, or `BRIDGE_FRAMES` remain.

- [ ] **Step 6: Commit**

```bash
git add web/src/remotion/AiMontage.tsx
git commit -m "feat(remotion): geometric TransitionSeries transitions, remove overlay layers"
```

---

## Task 9: End-to-end render verification

**Files:** none (verification only)

- [ ] **Step 1: Render a short montage with dead-air removal on**

Use an existing montage QA path/fixture (e.g. the source under `api/static/video_montage/local-remotion-qa/`). Trigger a render with options including `dead_spaces` and confirm the manifest written under the work dir contains a non-empty `sceneTransitions` array and no `visualTransitions` key:
```bash
set -a; source api/.env; set +a
# run the project's montage QA/render entrypoint, then:
find api/static/video_montage -name "*.json" -newermt "-5 min" -exec sh -c 'echo "== {} =="; python -c "import json,sys; m=json.load(open(sys.argv[1])); print(\"sceneTransitions:\", len(m.get(\"sceneTransitions\",[])), \"visualTransitions?\", \"visualTransitions\" in m)" {}' \;
```
Expected: `sceneTransitions: N` (N ≥ 1) and `visualTransitions? False`.

- [ ] **Step 2: Confirm A/V stays in sync in the output**

Probe the rendered mp4 duration and compare to the tightened audio/source duration (they should match within ~1 frame):
```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 <rendered_output>.mp4
```
Expected: within ±0.05 s of the tightened source duration. If off by ~`numTransitions * TRANSITION_FRAMES/fps`, the Task 8 compensation formula is wrong — revisit against the spike rule.

- [ ] **Step 3: Eyeball the transitions**

Open the output and confirm: a geometric transition (flip/zoom/slide/fade) plays at each cut, no light-sweep overlay remains, audio is continuous and lip-synced across cuts.

- [ ] **Step 4: Run the full Python test module once more**

Run: `python -m pytest tests/test_video_montage_transitions.py -q`
Expected: PASS (12 passed).

---

## Self-Review notes

- **Spec coverage:** dead-air join return (Task 2), scene split at joins (Task 4), energy selection (Task 3), all-cuts transitions (Task 5 builds one per boundary after splitting), whole-frame TransitionSeries (Task 8), continuous audio (Task 7), custom zoom / built-in slide-fade-flip (Tasks 1/6/8), overlay removal (Task 8), A/V-sync risk (Task 1 spike + Task 9 verify), `transition_video` kept in DB (Task 5 note). All covered.
- **`transition_video` asset kind:** intentionally not removed from `ALL_KINDS`/DB.
- **Types:** `dead_air_joins: list[float]`, `sceneTransitions[i]` keys `{type,durationInFrames,direction}` consistent across Tasks 3/5/8; `TRANSITION_FRAMES=7` mirrored in Python (Task 3) and TS (Task 8).
