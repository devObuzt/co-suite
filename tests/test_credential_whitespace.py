"""A pasted key keeps the newline the clipboard brought with it.

`ANTHROPIC_API_KEY` on production ended with a literal "\n" (found 2026-11-23,
109 characters stored for a 108-character key). The Anthropic path survived it
only because `ai_client.py` scrubs the key on every call; the OpenAI path puts
`settings.openai_api_key` straight into an `Authorization` header, where a
newline is not a valid header value at all.

So the scrub belongs at the source. An environment variable has no meaningful
leading or trailing whitespace — a stray one is always a paste artefact.
"""
from api.core.config import Settings


def test_api_keys_lose_a_pasted_newline():
    s = Settings(anthropic_api_key="sk-ant-abc\n", openai_api_key="sk-proj-xyz\n")
    assert s.anthropic_api_key == "sk-ant-abc"
    assert s.openai_api_key == "sk-proj-xyz"


def test_surrounding_whitespace_goes_too():
    s = Settings(openai_api_key="  sk-proj-xyz \t\r\n")
    assert s.openai_api_key == "sk-proj-xyz"


def test_every_string_setting_is_stripped():
    """The rule is the whole class of bug, not the two keys that hit us."""
    s = Settings(
        manzuma_service_key="mk\n",
        meta_app_secret="ms\n",
        serpapi_api_key="sk\n",
        telegram_bot_token="tt\n",
        google_ads_refresh_token="rt\n",
        whatsapp_access_token="wa\n",
        r2_secret_access_key="r2\n",
        fal_key="fal\n",
    )
    for field in (
        "manzuma_service_key", "meta_app_secret", "serpapi_api_key",
        "telegram_bot_token", "google_ads_refresh_token",
        "whatsapp_access_token", "r2_secret_access_key", "fal_key",
    ):
        value = getattr(s, field)
        assert "\n" not in value, field
        assert value == value.strip(), field


def test_no_control_characters_survive_into_an_authorization_header():
    """The exact shape of the production failure, as a header value."""
    s = Settings(openai_api_key="sk-proj-xyz\n")
    header = f"Bearer {s.openai_api_key}"
    assert all(ord(c) >= 32 for c in header), repr(header)


def test_database_url_still_gets_its_asyncpg_scheme():
    """A wildcard validator must not disturb the one that was already here."""
    s = Settings(database_url="postgresql://u:p@h:5432/db\n")
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"
