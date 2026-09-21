"""Which browsers may talk to this API.

A wrong answer here does not look like a CORS error to anybody — it looks like
"the app says I am not signed in", because every call dies at the preflight.
"""
import re

from api.main import MANZUMA_ORIGIN_REGEX

PATTERN = re.compile(MANZUMA_ORIGIN_REGEX)


def allowed(origin: str) -> bool:
    return bool(PATTERN.fullmatch(origin))


def test_our_own_apps_are_allowed():
    assert allowed("https://cosuite.manzuma.app")
    assert allowed("https://oneshare.manzuma.app")
    assert allowed("https://accounts.manzuma.app")
    assert allowed("https://manzuma.app")
    assert allowed("https://co-suite-web-production.up.railway.app")


def test_lookalikes_are_not():
    assert not allowed("https://manzuma.app.evil.com")
    assert not allowed("https://evil-manzuma.app")
    assert not allowed("http://cosuite.manzuma.app")   # plain http
    assert not allowed("https://cosuite.manzuma.app.evil.io")
