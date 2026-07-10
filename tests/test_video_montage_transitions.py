from api.services.video_montage import dead_air_join_times


def test_join_times_are_cumulative_segment_ends():
    # Two silences removed from a 10s clip leave three speech chunks whose
    # tightened durations are 2.0, 3.0, 1.5 -> joins at 2.0 and 5.0.
    segments = [(0.0, 2.0), (4.0, 7.0), (8.5, 10.0)]
    assert dead_air_join_times(segments) == [2.0, 5.0]


def test_join_times_empty_for_single_segment():
    assert dead_air_join_times([(0.0, 10.0)]) == []
