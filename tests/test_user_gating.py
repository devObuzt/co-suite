import pytest

from api.models.user import User
from api.services import admin_audit


def test_new_user_defaults_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    # Column default applies on INSERT; the model-level default must also be frozen
    assert User.approval_status.default.arg == "frozen"


def test_serialize_user_public_includes_approval_and_phone():
    user = User(
        id="u1", email="a@b.com", full_name="A", hashed_password="h",
        approval_status="approved", phone="0501234567",
    )
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "approved"
    assert payload["phone"] == "0501234567"


def test_serialize_user_public_defaults_missing_status_to_frozen():
    user = User(id="u1", email="a@b.com", full_name="A", hashed_password="h")
    payload = admin_audit.serialize_user_public(user)
    assert payload["approval_status"] == "frozen"
