"""Which browsers may talk to this API.

A wrong answer here does not look like a CORS error to anybody — it looks like
"the app says I am not signed in", because every call dies at the preflight.
And a too-generous one is worse: an origin we allow may read answers meant for
our customer, with the customer's cookies attached.
"""
import re

from api.main import MANZUMA_ORIGIN_REGEX, _origins

PATTERN = re.compile(MANZUMA_ORIGIN_REGEX)


def allowed(origin: str) -> bool:
    return bool(PATTERN.fullmatch(origin)) or origin in _origins


def test_our_own_apps_are_allowed():
    assert allowed("https://cosuite.manzuma.app")
    assert allowed("https://oneshare.manzuma.app")
    assert allowed("https://accounts.manzuma.app")
    assert allowed("https://manzuma.app")


def test_the_marketing_domain_is_allowed_by_name_not_by_pattern():
    assert allowed("https://cosuite.app")
    assert allowed("https://www.cosuite.app")
    assert not PATTERN.fullmatch("https://cosuite.app")


def test_lookalikes_are_not():
    assert not allowed("https://manzuma.app.evil.com")
    assert not allowed("https://evil-manzuma.app")
    assert not allowed("http://cosuite.manzuma.app")   # plain http
    assert not allowed("https://cosuite.manzuma.app.evil.io")


def test_the_shared_railway_domain_is_not_ours_to_trust():
    assert not allowed("https://attacker.up.railway.app")
    assert not allowed("https://co-suite-evil.up.railway.app")
