#!/usr/bin/env python3
"""Procedurally synthesise extra montage sound-effects and merge them into the
built-in creative-asset library manifest.

Why: the scene-boundary "transition" sound pool only had 3 usable sfx, so every
cut re-used the same handful. These pure-Python (no deps, no downloads, no
licensing) sounds cover whoosh/swoosh/impact transitions, in-scene pop/click/ding
beats, and risers/sub-drops. Running this is idempotent: it rewrites each WAV and
upserts its manifest entry by storage_url.

    python scripts/generate_sfx_library.py

On next API startup, ``seed_builtin_creative_assets`` picks up the new manifest
entries and inserts them into the DB (local + prod) automatically.
"""
from __future__ import annotations

import hashlib
import json
import math
import wave
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
STATIC_LIBRARY = ROOT / "api" / "static" / "creative_assets" / "library"
SFX_DIR = STATIC_LIBRARY / "sfx"
MANIFEST_PATH = STATIC_LIBRARY / "manifest.json"

SR = 48000
SFX_USE_CASES = ["attention_beat", "title_pop", "visual_accent"]


# ── tiny DSP helpers ──────────────────────────────────────────────────────────

def _bell(progress: float, power: float = 1.6) -> float:
    return math.sin(math.pi * max(0.0, min(1.0, progress))) ** power


def _tail_fade(progress: float, edge: float = 0.02) -> float:
    """Fade the last ``edge`` fraction to zero so sustained sounds don't click."""
    return 1.0 if progress < 1.0 - edge else max(0.0, (1.0 - progress) / edge)


def _write_wav(path: Path, samples: list[float]) -> float:
    """Peak+RMS normalise (mirrors write_mono_pcm_wav) and write mono 16-bit PCM."""
    peak = max(0.001, max(abs(s) for s in samples))
    rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
    target_rms = 10 ** (-16 / 20)
    gain = min(0.92 / peak, target_rms / max(0.001, rms))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        frames = bytearray()
        for s in samples:
            value = int(max(-0.92, min(0.92, s * gain)) * 32767)
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        handle.writeframes(bytes(frames))
    return round(len(samples) / SR, 3)


# ── sound generators (each returns a list of float samples ~[-1, 1]) ──────────

def whoosh(dur: float, f0: float, f1: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    prev = 0.0
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        noise = rng.uniform(-1, 1)
        high = noise - prev
        prev = noise
        sweep = math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * t)
        out.append((high * 0.6 + sweep * 0.3) * _bell(p, 1.8))
    return out


def swoosh_fast(dur: float, f0: float, f1: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    prev = 0.0
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        noise = rng.uniform(-1, 1)
        high = noise - prev
        prev = noise
        sweep = math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * t)
        env = (p / 0.12) if p < 0.12 else math.exp(-(p - 0.12) * 6.5)
        out.append((high * 0.65 + sweep * 0.3) * env)
    return out


def impact_boom(dur: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        body = math.sin(2 * math.pi * (70 - 35 * p) * t) * math.exp(-p * 5)
        click = rng.uniform(-1, 1) * math.exp(-p * 60) * 0.5
        out.append((body * 0.9 + click) * _tail_fade(p))
    return out


def impact_hit(dur: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    partials = [(180, 1.0), (402, 0.6), (690, 0.35), (1240, 0.2)]
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        s = sum(a * math.sin(2 * math.pi * f * t) for f, a in partials) * math.exp(-p * 9)
        click = rng.uniform(-1, 1) * math.exp(-p * 80) * 0.6
        out.append((s * 0.5 + click) * _tail_fade(p))
    return out


def pop_drop(dur: float, f0: float, f1: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        tone = math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * t) * math.exp(-p * 10)
        click = rng.uniform(-1, 1) * math.exp(-p * 120) * 0.3
        out.append(tone + click)
    return out


def pop_bubble(dur: float, f0: float, f1: float) -> list[float]:
    n = int(dur * SR)
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        out.append(math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * t) * _bell(p, 1.2))
    return out


def click_tick(dur: float, seed: int) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    prev = 0.0
    out: list[float] = []
    for i in range(n):
        p = i / n
        noise = rng.uniform(-1, 1)
        high = noise - prev
        prev = noise
        out.append(high * math.exp(-p * 30))
    return out


def ding(dur: float, base: float, seed: int) -> list[float]:
    n = int(dur * SR)
    partials = [(base, 1.0), (base * 2.0, 0.5), (base * 3.01, 0.25)]
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        attack = min(1.0, p / 0.004)
        s = sum(a * math.sin(2 * math.pi * f * t) for f, a in partials)
        out.append(s * math.exp(-p * 4) * attack)
    return out


def riser(dur: float, f0: float, f1: float, seed: int, *, noisy: bool) -> list[float]:
    n = int(dur * SR)
    rng = Random(seed)
    prev = 0.0
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        vib = 1 + 0.02 * math.sin(2 * math.pi * 6 * t)
        tone = math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * vib * t)
        amp = p ** 1.5
        if noisy:
            noise = rng.uniform(-1, 1)
            high = noise - prev
            prev = noise
            sample = (tone * 0.4 + high * 0.5) * amp
        else:
            sample = tone * amp
        out.append(sample * _tail_fade(p, 0.03))
    return out


def sub_drop(dur: float, f0: float, f1: float) -> list[float]:
    n = int(dur * SR)
    out: list[float] = []
    for i in range(n):
        t = i / SR
        p = i / n
        out.append(math.sin(2 * math.pi * (f0 + (f1 - f0) * p) * t) * _bell(p, 1.0))
    return out


# ── the sound set ─────────────────────────────────────────────────────────────

SOUNDS = [
    ("whoosh-up", "Whoosh Up", ["whoosh", "swoosh", "transition"], lambda: whoosh(0.5, 300, 3800, 101)),
    ("whoosh-down", "Whoosh Down", ["whoosh", "swoosh", "transition"], lambda: whoosh(0.5, 3800, 300, 102)),
    ("swoosh-fast", "Swoosh Fast", ["swoosh", "whoosh", "transition"], lambda: swoosh_fast(0.28, 500, 2600, 103)),
    ("swoosh-reverse", "Swoosh Reverse", ["swoosh", "whoosh", "transition"], lambda: swoosh_fast(0.30, 2600, 600, 104)),
    ("impact-boom", "Impact Boom", ["impact", "hit", "boom"], lambda: impact_boom(0.6, 105)),
    ("impact-hit", "Impact Hit", ["impact", "hit"], lambda: impact_hit(0.4, 106)),
    ("pop-soft", "Pop Soft", ["pop", "energy"], lambda: pop_drop(0.12, 900, 400, 107)),
    ("pop-bubble", "Pop Bubble", ["pop", "energy"], lambda: pop_bubble(0.14, 300, 820)),
    ("click-tick", "Click Tick", ["click", "tick"], lambda: click_tick(0.035, 108)),
    ("ding-bright", "Ding Bright", ["ding", "notification"], lambda: ding(0.6, 880, 109)),
    ("riser-tension", "Riser Tension", ["riser", "build", "transition", "energy"], lambda: riser(1.2, 200, 2800, 110, noisy=True)),
    ("riser-sweep", "Riser Sweep", ["riser", "build", "transition", "energy"], lambda: riser(1.0, 200, 3000, 111, noisy=False)),
    ("sub-drop", "Sub Drop", ["impact", "drop", "sub", "transition"], lambda: sub_drop(0.8, 120, 30)),
]


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.get("assets", [])
    by_url = {e.get("storage_url"): e for e in entries}

    added, updated = 0, 0
    for slug, title, tags, generator in SOUNDS:
        samples = generator()
        digest = hashlib.sha1(f"generated/sfx/{slug}".encode("utf-8")).hexdigest()[:10]
        filename = f"{slug}-{digest}.wav"
        storage_url = f"/static/creative_assets/library/sfx/{filename}"
        duration = _write_wav(SFX_DIR / filename, samples)
        entry = {
            "library_key": hashlib.sha1(storage_url.encode("utf-8")).hexdigest(),
            "kind": "sfx",
            "title": title,
            "storage_url": storage_url,
            "content_type": "audio/wav",
            "duration_seconds": duration,
            "tags": tags,
            "use_cases": SFX_USE_CASES,
            "classification": {
                "tags": tags,
                "use_cases": SFX_USE_CASES,
                "auto_classified": False,
                "source_folder": "generated/sfx",
            },
            "metadata": {
                "original_path": f"generated/sfx/{filename}",
                "orientation": None,
                "library": "Generated SFX",
                "generated": True,
            },
            "active": True,
        }
        if storage_url in by_url:
            by_url[storage_url].update(entry)
            updated += 1
        else:
            entries.append(entry)
            by_url[storage_url] = entry
            added += 1
        print(f"  {filename}  ({duration:.2f}s)  tags={tags}")

    entries.sort(key=lambda item: (item["kind"], item["metadata"].get("orientation") or "", item["title"]))
    manifest["assets"] = entries
    manifest["asset_count"] = len(entries)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAdded {added}, updated {updated}. Manifest now has {len(entries)} assets.")


if __name__ == "__main__":
    main()
