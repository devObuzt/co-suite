"""Guards the CORS origin list.

FRONTEND_URL held only https://www.cosuite.app while Railway served the app on
the apex as well, so every preflight from https://cosuite.app was answered
"Disallowed CORS origin" with a 400.
"""
from api.main import _with_www_variants


def test_apex_origin_gets_a_www_twin():
    out = _with_www_variants(["https://cosuite.app"])
    assert "https://cosuite.app" in out
    assert "https://www.cosuite.app" in out


def test_www_origin_gets_an_apex_twin():
    """The real production case: only the www form was configured."""
    out = _with_www_variants(["https://www.cosuite.app"])
    assert "https://cosuite.app" in out
    assert "https://www.cosuite.app" in out


def test_configured_origin_stays_first():
    """billing and funnel build links from frontend_url.split(",")[0], so the
    configured value must not be reordered underneath them."""
    out = _with_www_variants(["https://www.cosuite.app", "https://oneshare.app"])
    assert out[0] == "https://www.cosuite.app"


def test_no_duplicates_when_both_forms_are_configured():
    out = _with_www_variants(["https://cosuite.app", "https://www.cosuite.app"])
    assert len(out) == len(set(out)) == 2


def test_scheme_and_port_are_preserved():
    out = _with_www_variants(["http://localhost:3000"])
    assert out == ["http://localhost:3000", "http://www.localhost:3000"]


def test_garbage_entries_do_not_explode():
    out = _with_www_variants(["", "not-a-url", "https://cosuite.app"])
    assert "https://cosuite.app" in out
    assert "https://www.cosuite.app" in out
