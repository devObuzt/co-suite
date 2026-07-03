import shutil
import subprocess
from pathlib import Path

import pytest

from api.models.suite import Suite
from api.services import video_montage
from api.services.video_montage import foreground_filter_chain, render_v1_video


def test_foreground_filter_preserves_subject_quality():
    chain = foreground_filter_chain(include_despill=True)

    assert "chromakey=0x00b050:0.18:0.03" in chain
    assert "scale=w='iw*" not in chain
    assert "flags=lanczos" in chain


def test_veed_fal_background_removal_requests_transparent_person_video(tmp_path, monkeypatch):
    calls: list[tuple[str, dict | None]] = []

    class FakeResponse:
        def __init__(self, payload: dict | None = None, content: bytes = b""):
            self._payload = payload or {}
            self.content = content

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_post(url: str, *, headers: dict, json: dict, timeout: int):
        calls.append((url, json))
        assert headers["Authorization"] == "Key test-fal-key"
        return FakeResponse({"request_id": "req-123"})

    def fake_get(url: str, *, headers: dict | None = None, timeout: int):
        calls.append((url, None))
        if url.endswith("/status"):
            return FakeResponse({"status": "COMPLETED"})
        if url.endswith("req-123"):
            return FakeResponse({"video": [{"url": "https://cdn.example/transparent.webm"}]})
        return FakeResponse(content=b"transparent-video")

    monkeypatch.setattr(video_montage.requests, "post", fake_post)
    monkeypatch.setattr(video_montage.requests, "get", fake_get)
    monkeypatch.setattr(video_montage.time, "sleep", lambda _seconds: None)

    result = video_montage.remove_background_with_veed_fal(
        source_url="https://drive.google.com/uc?export=download&id=abc",
        output_path=tmp_path / "subject.webm",
        fal_key="test-fal-key",
        poll_seconds=0,
        max_wait_seconds=20,
    )

    assert result["ok"] is True
    assert result["provider"] == "veed-fal"
    assert result["output_path"] == str(tmp_path / "subject.webm")
    assert (tmp_path / "subject.webm").read_bytes() == b"transparent-video"
    submit_url, payload = calls[0]
    assert submit_url == "https://queue.fal.run/veed/video-background-removal"
    assert payload == {
        "video_url": "https://drive.google.com/uc?export=download&id=abc",
        "output_codec": "vp9",
        "refine_foreground_edges": True,
        "subject_is_person": True,
    }


def test_render_remotion_pipeline_uses_transparent_subject_layers(tmp_path, monkeypatch):
    source = tmp_path / "transparent.webm"
    output = tmp_path / "render.mp4"
    source.write_bytes(b"webm")

    monkeypatch.setattr(video_montage, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(video_montage, "probe_duration_seconds", lambda _path: 6.0)
    monkeypatch.setattr(video_montage, "ffprobe_has_audio", lambda _path: True)
    monkeypatch.setattr(video_montage, "transcribe_video_segments", lambda _path, _dir: ([{"start": 0.0, "end": 2.8, "text": "هيك فيك تجيب ليدز جداد"}, {"start": 2.9, "end": 5.8, "text": "ونزيد المبيعات بسرعة"}], None))

    def fake_run_command(command: list[str]):
        command_text = " ".join(command)
        if "frame_%05d.png" in command_text:
            frames_dir = Path(command[-1]).parent
            frames_dir.mkdir(parents=True, exist_ok=True)
            (frames_dir / "frame_00000.png").write_bytes(b"png")
        elif command[:2] == ["npm", "exec"]:
            output.write_bytes(b"mp4")
        elif "-c:a" in command:
            Path(command[-1]).write_bytes(b"audio")

        class Result:
            stdout = "6.0"
            stderr = ""

        return Result()

    monkeypatch.setattr(video_montage, "run_command", fake_run_command)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك", "colors": {"primary": "#2f80ff"}},
    )

    result = video_montage.render_remotion_montage(
        transparent_source_path=source,
        output_path=output,
        suite=suite,
        input_data={"options": ["captions", "titles", "music"], "notes": "فيديو تسويقي"},
    )

    assert result["rendered"] is True
    assert "api_background_removal" in result["capabilities_applied"]
    assert "remotion_layered_render" in result["capabilities_applied"]
    assert "behind_person_3d_title" in result["capabilities_applied"]
    assert "sound_effect_transitions" in result["capabilities_applied"]
    manifest = (output.parent / "remotion-work" / "src" / "remotion" / "manifest.generated.json")
    assert manifest.exists()
    assert '"hasAlpha": true' in manifest.read_text(encoding="utf-8")


def test_remotion_component_renders_background_music_and_sound_effects():
    source = Path("web/src/remotion/AiMontage.tsx").read_text(encoding="utf-8")

    assert "manifest.audio.backgroundMusic" in source
    assert "manifest.audio.soundEffects" in source
    assert "key={`sfx-" in source


def test_remotion_manifest_generates_silent_audio_when_source_has_no_audio(tmp_path, monkeypatch):
    source = tmp_path / "transparent.webm"
    source.write_bytes(b"webm")
    work_dir = tmp_path / "work"
    commands: list[list[str]] = []

    monkeypatch.setattr(video_montage, "ffprobe_has_audio", lambda _path: False)

    def fake_run_command(command: list[str]):
        commands.append(command)
        command_text = " ".join(command)
        if "frame_%05d.png" in command_text:
            frames_dir = Path(command[-1]).parent
            frames_dir.mkdir(parents=True, exist_ok=True)
            (frames_dir / "frame_00000.png").write_bytes(b"png")
        elif "anullsrc=channel_layout=stereo" in command_text:
            Path(command[-1]).write_bytes(b"silent-audio")
        elif "-c:a" in command:
            Path(command[-1]).write_bytes(b"audio")

        class Result:
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(video_montage, "run_command", fake_run_command)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك"},
    )

    manifest_path, _scenes = video_montage.build_remotion_scene_manifest(
        transparent_source_path=source,
        work_dir=work_dir,
        suite=suite,
        input_data={"notes": "نص عربي"},
        duration=3.0,
        transcript_segments=[],
    )

    assert any("anullsrc=channel_layout=stereo" in " ".join(command) for command in commands)
    assert (work_dir / "public" / "remotion" / "inputs" / "transparent-audio.m4a").read_bytes() == b"silent-audio"
    assert '"/remotion/inputs/transparent-audio.m4a"' in manifest_path.read_text(encoding="utf-8")


def test_remotion_manifest_splits_single_transcript_into_multiple_scenes(tmp_path, monkeypatch):
    source = tmp_path / "transparent.webm"
    source.write_bytes(b"webm")
    work_dir = tmp_path / "work"

    monkeypatch.setattr(video_montage, "ffprobe_has_audio", lambda _path: True)
    monkeypatch.setattr(video_montage, "non_silent_segments", lambda _path, _duration: [(0.0, 3.0), (3.4, 6.2), (6.8, 9.0)])

    def fake_run_command(command: list[str]):
        command_text = " ".join(command)
        if "frame_%05d.png" in command_text:
            frames_dir = Path(command[-1]).parent
            frames_dir.mkdir(parents=True, exist_ok=True)
            (frames_dir / "frame_00000.png").write_bytes(b"png")
        elif "-c:a" in command:
            Path(command[-1]).write_bytes(b"audio")

        class Result:
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(video_montage, "run_command", fake_run_command)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك"},
    )

    manifest_path, scenes = video_montage.build_remotion_scene_manifest(
        transparent_source_path=source,
        work_dir=work_dir,
        suite=suite,
        input_data={"options": ["dead_spaces"], "notes": "عنوان أول. عنوان ثاني. عنوان ثالث"},
        duration=9.0,
        transcript_segments=[{"start": 0.0, "end": 9.0, "text": "عنوان أول عنوان ثاني عنوان ثالث عنوان رابع"}],
    )

    manifest = manifest_path.read_text(encoding="utf-8")
    assert len(scenes) == 3
    assert '"sceneCount": 3' in manifest
    assert '"soundEffectCount": 2' in manifest
    assert manifest.count('"publicPath": "/remotion/sound/soft-whoosh.wav"') == 2


def test_remotion_manifest_uses_manual_caption_and_title_overrides(tmp_path, monkeypatch):
    source = tmp_path / "transparent.webm"
    source.write_bytes(b"webm")
    work_dir = tmp_path / "work"

    monkeypatch.setattr(video_montage, "ffprobe_has_audio", lambda _path: True)

    def fake_run_command(command: list[str]):
        command_text = " ".join(command)
        if "frame_%05d.png" in command_text:
            frames_dir = Path(command[-1]).parent
            frames_dir.mkdir(parents=True, exist_ok=True)
            (frames_dir / "frame_00000.png").write_bytes(b"png")
        elif "-c:a" in command:
            Path(command[-1]).write_bytes(b"audio")

        class Result:
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(video_montage, "run_command", fake_run_command)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك"},
    )

    manifest_path, scenes = video_montage.build_remotion_scene_manifest(
        transparent_source_path=source,
        work_dir=work_dir,
        suite=suite,
        input_data={
            "caption_overrides": ["كابشن معدل يدويا"],
            "title_overrides": ["عنوان آمن"],
            "notes": "نص افتراضي",
        },
        duration=3.0,
        transcript_segments=[{"start": 0.0, "end": 2.5, "text": "كابشن من التفريغ"}],
    )

    manifest = manifest_path.read_text(encoding="utf-8")
    assert scenes[0]["caption"] == "كابشن معدل يدويا"
    assert scenes[0]["behindText"] == "عنوان آمن"
    assert scenes[0]["generatedCaption"] == "كابشن من التفريغ"
    assert "كابشن معدل يدويا" in manifest
    assert "عنوان آمن" in manifest


@pytest.mark.asyncio
async def test_generate_video_montage_prefers_veed_remotion_pipeline(tmp_path, monkeypatch):
    from api.core.config import settings

    monkeypatch.setattr(video_montage, "job_dir", lambda _job_id: tmp_path)
    monkeypatch.setattr(settings, "fal_key", "test-fal-key")

    def fake_remove_background(**kwargs):
        transparent = Path(kwargs["output_path"])
        transparent.write_bytes(b"transparent-webm")
        return {"ok": True, "provider": "veed-fal", "output_path": str(transparent)}

    def fake_render_remotion(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"mp4")
        return {
            "rendered": True,
            "output_url": "/static/video_montage/job-1/render.mp4",
            "capabilities_applied": ["api_background_removal", "remotion_layered_render"],
            "warnings": [],
        }

    def fail_legacy_render(**_kwargs):
        raise AssertionError("legacy chromakey render should not run when VEED/Remotion succeeds")

    monkeypatch.setattr(video_montage, "remove_background_with_veed_fal", fake_remove_background)
    monkeypatch.setattr(video_montage, "render_remotion_montage", fake_render_remotion)
    monkeypatch.setattr(video_montage, "render_v1_video", fail_legacy_render)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك", "colors": {"primary": "#2f80ff"}},
    )

    result = await video_montage.generate_video_montage_for_suite(
        suite=suite,
        job_id="job-1",
        input_data={
            "source_url": "https://drive.google.com/file/d/abc/view",
            "options": ["background", "captions", "titles", "music"],
            "notes": "كابشن عربي",
        },
    )

    assert result["rendered"] is True
    render = result["video_montage"]["render"]
    assert render["engine"] == "remotion_veed_fal"
    assert "api_background_removal" in render["capabilities_applied"]
    assert result["output_url"] == "/static/video_montage/job-1/render.mp4"


@pytest.mark.asyncio
async def test_generate_video_montage_uses_remotion_for_uploaded_green_screen_source(tmp_path, monkeypatch):
    from api.core.config import settings

    source = tmp_path / "uploaded.mp4"
    source.write_bytes(b"green-screen-source")

    monkeypatch.setattr(video_montage, "job_dir", lambda _job_id: tmp_path)
    monkeypatch.setattr(settings, "fal_key", "")
    monkeypatch.setattr(video_montage, "ffmpeg_filter_available", lambda name: name == "chromakey")
    monkeypatch.setattr(video_montage, "probe_duration_seconds", lambda _path: 8.0)

    def fake_local_chromakey(**kwargs):
        transparent = Path(kwargs["output_path"])
        transparent.write_bytes(b"transparent-local-webm")
        return {"ok": True, "provider": "local-chromakey", "output_path": str(transparent)}

    def fake_render_remotion(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"mp4")
        return {
            "rendered": True,
            "output_url": "/static/video_montage/job-upload/render.mp4",
            "capabilities_applied": [
                "remotion_layered_render",
                "behind_person_3d_title",
                "sound_effect_transitions",
                "music_bed",
            ],
            "warnings": [],
            "scene_count": 3,
        }

    def fail_legacy_render(**_kwargs):
        raise AssertionError("legacy chromakey render should not run for uploaded green-screen source")

    monkeypatch.setattr(video_montage, "create_local_transparent_subject", fake_local_chromakey)
    monkeypatch.setattr(video_montage, "render_remotion_montage", fake_render_remotion)
    monkeypatch.setattr(video_montage, "render_v1_video", fail_legacy_render)

    suite = Suite(
        id="suite-video-test",
        owner_id="user-1",
        name="كونيك",
        slug="connec",
        brand={"name": "كونيك", "colors": {"primary": "#2f80ff"}},
    )

    result = await video_montage.generate_video_montage_for_suite(
        suite=suite,
        job_id="job-upload",
        input_data={
            "source_file_path": str(source),
            "options": ["background", "captions", "titles", "music"],
            "notes": "كابشن عربي",
        },
    )

    render = result["video_montage"]["render"]
    assert result["rendered"] is True
    assert render["engine"] == "remotion_local_chromakey"
    assert render["scene_count"] == 3
    assert "behind_person_3d_title" in render["capabilities_applied"]
    assert "sound_effect_transitions" in render["capabilities_applied"]
    assert result["source_warning"] is None
    assert result["video_montage"]["source_warning"] is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg is required")
def test_render_v1_video_applies_rtl_overlays_and_green_screen_removal(tmp_path, monkeypatch):
    from api.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")

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
            "notes": "فيديو سريع مع كابتشن عربي واضح وخلفية جديدة. انتقال ثاني واضح.",
        },
    )

    assert result["rendered"] is True
    assert output.exists()
    assert "rtl_text_overlay" in result["capabilities_applied"]
    assert "green_screen_background_removal" in result["capabilities_applied"]
    assert "audio_cleanup" in result["capabilities_applied"]
    assert "behind_person_title" in result["capabilities_applied"]
    assert "animated_background" in result["capabilities_applied"]
    assert "person_camera_motion" in result["capabilities_applied"]
    assert "sound_effect_transitions" in result["capabilities_applied"]
    assert "visual_transitions" in result["capabilities_applied"]
