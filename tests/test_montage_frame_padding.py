"""Regression: Remotion 404s on the last subject frame when ffmpeg's fps filter
yields a couple fewer frames than the composition requests (round(sourceEnd*fps)
vs the extracted tail). That failure drops the whole render to the basic
ffmpeg_local_fallback engine. pad_subject_frames holds the final frame so the
composition never requests a missing index.
"""
from pathlib import Path

from api.services.video_montage import pad_subject_frames


def _make_frames(dir_path: Path, count: int) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        # distinct bytes per frame so we can prove which frame got duplicated
        (dir_path / f"frame_{index:05d}.png").write_bytes(f"frame-{index}".encode())


def test_pads_missing_tail_frames_by_holding_the_last(tmp_path):
    frames = tmp_path / "subject-frames"
    _make_frames(frames, 1124)  # indices 0..1123, like the 404'd render

    padded = pad_subject_frames(frames, 1128)

    assert padded == 4
    for index in range(1124, 1128):
        target = frames / f"frame_{index:05d}.png"
        assert target.exists()
        assert target.read_bytes() == b"frame-1123"  # held the real last frame
    # the exact frame Remotion 404'd on now resolves
    assert (frames / "frame_01124.png").exists()


def test_noop_when_enough_frames_already_exist(tmp_path):
    frames = tmp_path / "subject-frames"
    _make_frames(frames, 100)
    assert pad_subject_frames(frames, 100) == 0
    assert pad_subject_frames(frames, 40) == 0
    assert len(list(frames.glob("frame_*.png"))) == 100


def test_noop_on_empty_dir(tmp_path):
    frames = tmp_path / "subject-frames"
    frames.mkdir()
    assert pad_subject_frames(frames, 10) == 0
    assert list(frames.glob("frame_*.png")) == []


def test_pads_from_actual_last_index_not_count(tmp_path):
    # Guard against a gap making the count-based bound under-pad.
    frames = tmp_path / "subject-frames"
    frames.mkdir()
    (frames / "frame_00000.png").write_bytes(b"a")
    (frames / "frame_00005.png").write_bytes(b"last")  # highest index is 5
    padded = pad_subject_frames(frames, 8)
    for index in range(6, 8):
        assert (frames / f"frame_{index:05d}.png").read_bytes() == b"last"
    assert padded == 2
