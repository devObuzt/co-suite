"""Text-to-Speech via ElevenLabs.

Used to generate the Arabic voiceover separately from Veo 3 so we control
pronunciation/dialect precisely. The voiceover is then muxed into Veo 3's
silent (or music-only) video by `audio_mixer.py`.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import httpx

from ..core.external_calls import external_call
from .config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL,
    ELEVENLABS_SPEED,
    ELEVENLABS_VOICE_ID,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"  # 44.1kHz / 128kbps, compatible with ffmpeg
HTTP_TIMEOUT = 120
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _headers() -> dict:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is missing in .env")
    return {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }


def list_voices() -> list[dict]:
    """Fetch all voices available on the account (built-in + custom clones)."""
    with external_call("elevenlabs", "list_voices") as call:
        r = httpx.get(
            f"{API_BASE}/voices",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=HTTP_TIMEOUT,
        )
        call.note(status_code=r.status_code)
        r.raise_for_status()
        return r.json().get("voices", [])


def _adjust_speed(input_path: Path, output_path: Path, speed: float) -> Path:
    """Apply `atempo` filter to change playback speed without changing pitch.

    ffmpeg's atempo accepts 0.5-2.0 per filter; we chain if outside that range,
    but for our 0.7-1.4 use case a single filter is enough.
    """
    if speed == 1.0:
        if input_path != output_path:
            shutil.move(str(input_path), str(output_path))
        return output_path
    cmd = [
        FFMPEG, "-y", "-i", str(input_path),
        "-filter:a", f"atempo={speed}",
        "-vn", str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg atempo failed: {proc.stderr[-400:]}")
    return output_path


def synthesize(
    text: str,
    out_path: Path | str,
    voice_id: str | None = None,
    model: str | None = None,
    voice_settings: dict | None = None,
    speed: float | None = None,
) -> Path:
    """Synthesize `text` (Arabic) to an MP3 at out_path. Returns the path.

    If `speed` is not 1.0, the audio is post-processed with ffmpeg's atempo
    filter, which changes the tempo without altering pitch.
    """
    if not text or not text.strip():
        raise ValueError("Empty text passed to TTS")

    voice_id = voice_id or ELEVENLABS_VOICE_ID
    model = model or ELEVENLABS_MODEL
    if speed is None:
        speed = ELEVENLABS_SPEED
    if not voice_id:
        raise RuntimeError(
            "ELEVENLABS_VOICE_ID is empty. Run scripts/list_voices.py to pick one."
        )

    payload: dict = {
        "text": text,
        "model_id": model,
        "voice_settings": voice_settings
        or {
            "stability": 0.55,        # 0=variable/expressive, 1=monotone
            "similarity_boost": 0.80,  # how close to original voice
            "style": 0.20,             # natural style emphasis (multilingual_v2)
            "use_speaker_boost": True,
        },
    }

    log.info(
        "ElevenLabs TTS — voice=%s model=%s chars=%d speed=%s",
        voice_id, model, len(text), speed,
    )

    with external_call(
        "elevenlabs", "tts_synthesize", voice_id=voice_id, model=model, chars=len(text)
    ) as call:
        r = httpx.post(
            f"{API_BASE}/text-to-speech/{voice_id}",
            headers=_headers(),
            json=payload,
            params={"output_format": DEFAULT_OUTPUT_FORMAT},
            timeout=HTTP_TIMEOUT,
        )
        call.note(status_code=r.status_code)
        if r.status_code >= 400:
            raise RuntimeError(f"ElevenLabs TTS failed [{r.status_code}]: {r.text}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if speed == 1.0:
        out_path.write_bytes(r.content)
    else:
        # Write raw to a temp file then run atempo into the final output
        raw_path = out_path.with_suffix(".raw.mp3")
        raw_path.write_bytes(r.content)
        _adjust_speed(raw_path, out_path, speed)
        try:
            raw_path.unlink()
        except OSError:
            pass

    log.info("Saved voiceover to %s (speed=%s)", out_path, speed)
    return out_path


# Rough cost estimate — ElevenLabs charges in "credits"; ~1 credit per character
# for Multilingual v2, and the Starter plan converts to roughly $0.18 per 1k chars.
COST_PER_1K_CHARS_USD = 0.18


def estimate_cost(text: str) -> float:
    return (len(text) / 1000.0) * COST_PER_1K_CHARS_USD
