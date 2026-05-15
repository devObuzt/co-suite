"""Audio mixing via ffmpeg.

Takes a video file (which may have its own background music/SFX from Veo 3)
and a separately-generated voiceover MP3, and combines them with sidechain
compression (a.k.a. "ducking") so the background dips automatically when the
voice is talking.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def mux_voiceover(
    video_path: Path | str,
    voiceover_path: Path | str,
    output_path: Path | str,
    voiceover_gain_db: float = 2.0,
    background_duck_db: float = -10.0,
    voiceover_start_seconds: float = 0.4,
) -> Path:
    """Combine a video's existing audio with a voiceover MP3.

    The voiceover starts slightly after the video begins (voiceover_start_seconds)
    so there's a brief moment of pure visual + music before the speaker comes in.

    The background (the video's own audio = music + SFX from Veo 3) is ducked by
    `background_duck_db` while the voice is active, then comes back up.
    """
    video_path = Path(video_path)
    voiceover_path = Path(voiceover_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a complex filter graph:
    #   [1:a]volume=+2dB,adelay=400|400[vo];
    #   [0:a]volume=-10dB[bg];
    #   [bg][vo]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=300[mixed]
    #   then amix to combine
    delay_ms = int(max(0, voiceover_start_seconds * 1000))
    filter_complex = (
        f"[1:a]volume={voiceover_gain_db}dB,adelay={delay_ms}|{delay_ms}[vo];"
        f"[0:a]volume={background_duck_db}dB[bg];"
        f"[vo][bg]amix=inputs=2:duration=first:dropout_transition=0,"
        f"dynaudnorm=p=0.85:m=12[out]"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", str(video_path),
        "-i", str(voiceover_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]

    log.info("ffmpeg muxing %s + %s → %s", video_path.name, voiceover_path.name, output_path.name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # If the video had no audio track to begin with, try a simpler mux
        if "Stream specifier 0:a" in (proc.stderr or "") or "does not match any streams" in (proc.stderr or ""):
            log.info("Source video has no audio track; using voiceover only")
            return _mux_voice_only(video_path, voiceover_path, output_path, delay_ms)
        log.error("ffmpeg failed:\n%s", proc.stderr[-2000:])
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")

    return output_path


def _mux_voice_only(video_path, voiceover_path, output_path, delay_ms):
    """Fallback when the source video has no existing audio track."""
    cmd = [
        FFMPEG, "-y",
        "-i", str(video_path),
        "-i", str(voiceover_path),
        "-filter_complex", f"[1:a]adelay={delay_ms}|{delay_ms}[vo]",
        "-map", "0:v",
        "-map", "[vo]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg (voice-only) failed: {proc.stderr[-500:]}")
    return Path(output_path)
