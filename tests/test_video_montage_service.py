import shutil
import subprocess

import pytest

from api.models.suite import Suite
from api.services.video_montage import render_v1_video


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg is required")
def test_render_v1_video_applies_rtl_overlays_and_green_screen_removal(tmp_path):
    source = tmp_path / "green-source.mp4"
    output = tmp_path / "render.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x00b050:s=720x1280:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك", "colors": {"primary": "#2f80ff"}},
    )

    result = render_v1_video(
        source_path=source,
        output_path=output,
        suite=suite,
        input_data={
            "options": ["captions", "background", "titles", "music", "voice_cleanup"],
            "notes": "فيديو سريع مع كابتشن عربي واضح وخلفية جديدة.",
        },
    )

    assert result["rendered"] is True
    assert output.exists()
    assert "rtl_text_overlay" in result["capabilities_applied"]
    assert "green_screen_background_removal" in result["capabilities_applied"]
    assert "audio_cleanup" in result["capabilities_applied"]
