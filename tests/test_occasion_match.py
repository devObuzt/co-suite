from api.services.occasion_match import relevant_occasions


def test_relevant_occasions_ranks_and_caps():
    occ = [
        {"title": "المونديال", "type": "sports", "confidence": "medium"},
        {"title": "عيد الأضحى", "type": "religious", "confidence": "high"},
        {"title": "رجعة المدارس", "type": "school", "confidence": "high"},
    ]
    out = relevant_occasions(occ, {"industry": "retail"}, limit=2)
    assert len(out) == 2
    assert out[0]["title"] == "عيد الأضحى"  # high-confidence universal ranks first


def test_relevant_occasions_empty_safe():
    assert relevant_occasions([], {}) == []
    assert relevant_occasions(None, {}) == []


def test_relevant_occasions_skips_malformed():
    out = relevant_occasions([{"type": "religious"}, "notadict", {"title": "ok", "type": "national"}], {})
    assert [o["title"] for o in out] == ["ok"]
