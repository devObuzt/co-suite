from api.services.video_montage import dead_air_join_times, pick_scene_transition, TRANSITION_FRAMES


def test_join_times_are_cumulative_segment_ends():
    # Two silences removed from a 10s clip leave three speech chunks whose
    # tightened durations are 2.0, 3.0, 1.5 -> joins at 2.0 and 5.0.
    segments = [(0.0, 2.0), (4.0, 7.0), (8.5, 10.0)]
    assert dead_air_join_times(segments) == [2.0, 5.0]


def test_join_times_empty_for_single_segment():
    assert dead_air_join_times([(0.0, 10.0)]) == []


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
