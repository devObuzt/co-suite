# Spike findings: `@remotion/transitions` API + A/V sync (Task 1)

Date: 2026-07-10
Remotion version: `4.0.473` (pinned exactly, matching `remotion@^4.0.473`)
`@remotion/transitions` installed: `^4.0.473`

## 1. Resolved import paths / export names

Enumeration command (`web`):

```bash
node -e "for (const m of ['','/slide','/fade','/wipe','/flip','/clock-wipe','/none']) { try { console.log(m||'(root)', Object.keys(require('@remotion/transitions'+m))); } catch(e){ console.log(m,'MISSING',e.code); } }"
```

Raw output:

```
(root) [
  'linearTiming',
  'springTiming',
  'TransitionSeries',
  'useTransitionProgress',
  'makeHtmlInCanvasPresentation',
  'crossZoom',
  'dreamyZoom',
  'filmBurn',
  'linearBlur'
]
/slide [ 'slide' ]
/fade [ 'fade' ]
/wipe [ 'wipe' ]
/flip [ 'flip' ]
/clock-wipe [ 'clockWipe' ]
/none [ 'none' ]
```

Root exports confirm: `TransitionSeries`, `linearTiming`, `springTiming` are all root exports (`import {TransitionSeries, linearTiming, springTiming} from '@remotion/transitions'`).

### The four transitions this plan needs

| Requested | Resolved import | Export name | Built-in? |
|---|---|---|---|
| `slide` | `@remotion/transitions/slide` | `slide` | Built-in |
| `fade` | `@remotion/transitions/fade` | `fade` | Built-in |
| `wipe` | `@remotion/transitions/wipe` | `wipe` | Built-in |
| `flip` | `@remotion/transitions/flip` | `flip` | Built-in |

All four are built-in — no custom `TransitionPresentation` needed for any of them. `flip` in particular was flagged as an open question in the plan brief; it does exist as a genuine built-in sub-path export.

### `zoom` (mentioned in the interface note as a possible custom case)

There is **no** `@remotion/transitions/zoom` path (`ERR_PACKAGE_PATH_NOT_EXPORTED`). However, the package's `exports` map (`node_modules/@remotion/transitions/package.json`) lists a real built-in zoom-style transition at a differently-named sub-path:

- `@remotion/transitions/zoom-in-out` → export `zoomInOut` (shader-based presentation, `CompWithShader`). Also exports `zoomInOutShader`.
- Root also exports `crossZoom` and `dreamyZoom` (alternate zoom-flavored presentations, not sub-pathed).

**Finding: "zoom" does NOT need a custom presentation.** It needs the correctly-named built-in, `zoomInOut` from `@remotion/transitions/zoom-in-out`. Using a generic name like `zoom` when probing sub-paths gives a false negative (`ERR_PACKAGE_PATH_NOT_EXPORTED`) — the real export is named `zoom-in-out`. This was the spike's main "assumption was wrong" catch: don't conclude "needs custom presentation" from one missing guessed path; check the package's exports map.

### Full sub-path export surface (for reference / future transitions)

`fade`, `slide`, `wipe`, `flip`, `clock-wipe` → `clockWipe`, `book-flip` → `bookFlip` (assumed), `zoom-blur`, `dreamy-zoom`, `film-burn`, `linear-blur`, `zoom-in-out` → `zoomInOut`, `none` → `none`, `iris`, `dissolve`, `ripple`, `crosswarp`, `cross-zoom`, `swap`.

### Factory signatures

All four (and `zoomInOut`) follow the same pattern — a factory function `(props?) => TransitionPresentation`:

```js
// flip
(props) => ({ component: Flip, props: props ?? {} })
// slide
(props) => ({ component: SlidePresentation, props: props ?? {} })
// fade
(props) => ({ component: FadePresentation, props: props ?? {} })
// wipe
(props) => ({ component: WipePresentation, props: props ?? {} })
```

Called with no args for the spike (`flip()`, `slide()`); each accepts an optional props object (e.g. `slide({direction: 'from-left'})`) per `dist/presentations/*.d.ts` — not enumerated exhaustively here since default props were sufficient for measurement.

`TransitionSeries.d.ts` confirms `TransitionSeries.Sequence` requires `durationInFrames: number` (not optional), and `TransitionSeries.Transition` takes `presentation` + `timing` (via `linearTiming({durationInFrames})` or `springTiming(...)`).

## 2. Prototype

`web/src/remotion/_spike/TransitionSpike.tsx` (throwaway, deleted before commit): three solid-colour `AbsoluteFill`s inside a `TransitionSeries`, a `flip` transition between scene 1→2 and a `slide` transition between scene 2→3, plus a single `<Audio src={staticFile('remotion/sound/marketing-upbeat-bed.wav')} />` spanning the full `AbsoluteFill`. Registered temporarily as composition id `TransitionSpike` in `web/src/remotion/Root.tsx` (removed in step 5 below).

## 3. Measured composition length vs `sum(D)` — naive pass

**Important discovery about the measurement command:** `npm exec remotion -- compositions src/remotion/index.ts | grep -i spike` reports whatever `durationInFrames` value is hardcoded on the `<Composition>` element — it does **not** reflect the intrinsic/actual length of the `TransitionSeries` content inside it. Remotion has no CLI-level introspection of `TransitionSeries`'s true content length; the composition's `durationInFrames` is an input the caller must compute, not an output Remotion derives. Raw output confirming this:

```
$ npm exec remotion -- compositions src/remotion/index.ts 2>/dev/null | grep -i spike
TransitionSpike    30      1080x1920      110 (3.67 sec)
```

(110 here is just the hardcoded `<Composition durationInFrames={110}>` value used to give headroom for stills at frame 98-101 — not a measurement of the transition content.)

**Actual measurement method used instead:** render `still` frames at candidate boundary frames and sample pixel colour to find exactly where scene content stops (goes black, since the `AbsoluteFill` wrapper background is black and nothing is scheduled past the `TransitionSeries` content).

### Pass 1 — naive: `durationInFrames` on every `Sequence` == `D[i]` (no compensation)

`D = [30, 30, 30]`, `T = 7`, 2 transitions (`flip`, `slide`).

Predicted naive total = `sum(D) - numTransitions * T` = `90 - 14` = `76`.

Still renders (`remotion still ... --frame=N`), center-pixel sample (scene 3 colour `#457b9d` = RGB `(69,123,157)`):

| frame | pixel | interpretation |
|---|---|---|
| 74 | `(69, 123, 157)` | scene 3 content |
| 75 | `(69, 123, 157)` | scene 3 content — **last content frame** |
| 76 | `(0, 0, 0)` | black — content has ended |
| 77 | `(0, 0, 0)` | black |
| 89 | `(0, 0, 0)` | black |

Content occupies frames `0..75` = **76 frames total**, exactly matching the predicted `sum(D) - numTransitions*T`. Confirmed with a second, differently-shaped case to rule out coincidence: `D = [40, 25, 35]`, `T = 10` → predicted `100 - 20 = 80`. Measured: frame 79 still scene-3 colour, frame 80 black → **80 frames total**. Formula holds.

## 4. Derived sync rule

Given per-scene visual durations `D[i]` (i = 0..N-1) and a uniform transition length of `T` frames on every one of the `N-1` boundaries:

**Naive relationship** (matches the plan brief's prediction exactly):
```
total = sum(seqDurations) - (N - 1) * T
```

**Compensation rule** (to make `total == sum(D)`, i.e. match the continuous, un-shortened audio track):

```
TransitionSeries.Sequence durationInFrames:
  - first sequence  (i == 0):      D[0] + T/2
  - last sequence   (i == N-1):    D[N-1] + T/2
  - interior sequence (0<i<N-1):   D[i] + T
```

Rationale: each interior sequence borders two transitions (one on each side), so it needs the full `T` added back to survive both overlaps at its intended visual length; the first/last sequences only border one transition each, so they only need `T/2`... but empirically **T/2 exactly balances the books** for the edge sequences, and `+T` balances interior ones, because the total deficit to make up is `(N-1)*T` and `2*(T/2) + (N-2)*T = (N-1)*T` for N≥2. (For `N==1`, no transitions exist; use `D[0]` unmodified.) For non-uniform transition lengths `T[k]` per boundary `k`, generalize to: sequence `i` gets `+T[i-1]/2` from its left boundary (if any) and `+T[i]/2` from its right boundary (if any) — i.e. half of each adjacent transition's length, summed.

**Empirical confirmation:** re-ran the `D=[40,25,35]`, `T=10` case with `compD = [D[0]+T/2, D[1]+T, D[2]+T/2] = [45, 35, 40]` as the actual `TransitionSeries.Sequence` `durationInFrames` values. Predicted total = `sum(D) = 100`. Measured via still frames:

| frame | pixel | interpretation |
|---|---|---|
| 98 | `(69, 123, 157)` | scene 3 content |
| 99 | `(69, 123, 157)` | scene 3 content — **last content frame** |
| 100 | `(0, 0, 0)` | black |
| 101 | `(0, 0, 0)` | black |

Content occupies frames `0..99` = exactly **100 frames = sum(D)**. Rule confirmed by direct render, not just algebra.

**Consequence for the outer `<Composition>`:** since Remotion does not auto-derive `durationInFrames` for a `TransitionSeries`-based composition (see section 3), the calling code (Task 8) must set the outer `<Composition durationInFrames={...}>` to `sum(D)` directly — computed the same way the existing `Root.tsx` already does via `manifest.durationSeconds * fps`, not via any Remotion introspection API. This is consistent with (and requires no change to) the current pattern in `web/src/remotion/Root.tsx`.

## 5. Built-in vs custom summary (for Tasks 6-8)

| Transition | Status | Import |
|---|---|---|
| `slide` | Built-in | `@remotion/transitions/slide` → `slide` |
| `fade` | Built-in | `@remotion/transitions/fade` → `fade` |
| `wipe` | Built-in | `@remotion/transitions/wipe` → `wipe` |
| `flip` | Built-in | `@remotion/transitions/flip` → `flip` |
| `zoom` | Built-in (differently named) | `@remotion/transitions/zoom-in-out` → `zoomInOut` |

**None of the five requested transitions need a custom `TransitionPresentation`.** The only pitfall is that `zoom` is not the sub-path name — it's `zoom-in-out`.

## 6. Surprises / gotchas for later tasks

1. **`flip` is built-in** — no custom presentation required (was an open question in the brief).
2. **`zoom` is built-in but under a non-obvious name** (`zoom-in-out`, export `zoomInOut`) — probing `@remotion/transitions/zoom` gives a false "missing" signal (`ERR_PACKAGE_PATH_NOT_EXPORTED`). Always check the package's `exports` map in `package.json` rather than trusting one guessed path.
3. **`remotion compositions` does not measure `TransitionSeries` content length** — it only echoes back whatever `durationInFrames` was hardcoded on the `<Composition>`. There is no CLI-level way to ask Remotion "how long is this TransitionSeries really." The sync-rule math above must be computed by application code and fed into the `<Composition>`'s `durationInFrames`, same as today's `manifest.durationSeconds * fps` pattern.
4. Measuring actual content length required rendering `still` frames and sampling pixel colour at candidate boundaries — there's no built-in duration-introspection API for `TransitionSeries` short of this or wiring up `calculateMetadata`.
5. The compensation formula generalizes cleanly to non-uniform per-boundary transition lengths (each sequence absorbs half of each adjacent transition's `T`), which Task 8 will likely need since different transition types (e.g. `flip` vs `fade`) may use different `T` values.

## Files touched by this spike

- `web/package.json`, `web/package-lock.json` — added `@remotion/transitions@^4.0.473` (kept, shipped).
- `web/src/remotion/_spike/TransitionSpike.tsx` — throwaway prototype, deleted after measurement, not shipped.
- `web/src/remotion/Root.tsx` — temporary composition registration added and then reverted; no net change shipped.
- This findings note.
