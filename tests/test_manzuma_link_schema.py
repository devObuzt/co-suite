from api.core.config import settings
from api.models.suite import Suite
from api.models.user import User


def test_settings_carry_the_manzuma_link_configuration():
    assert settings.manzuma_accounts_url == "https://accounts.manzuma.app"
    assert settings.manzuma_sso is False  # ships dark
    assert settings.manzuma_service_key == ""
    assert settings.internal_service_keys == ""


def test_link_columns_exist_and_are_unique():
    user_column = User.__table__.columns["manzuma_user_id"]
    suite_column = Suite.__table__.columns["organization_id"]

    assert user_column.unique is True
    assert user_column.nullable is True
    assert suite_column.unique is True
    assert suite_column.nullable is True
