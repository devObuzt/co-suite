from api.services.manzuma_accounts import ManzumaOrg, ManzumaSub
from api.services.manzuma_link import approval_for, normalize_email, normalize_phone, suite_decision


def test_email_and_phone_normalize_for_matching():
    assert normalize_email("  W@Example.COM ") == "w@example.com"
    assert normalize_email(None) is None
    assert normalize_phone("050-123-4567") == "0501234567"
    assert normalize_phone("+972 50 123 4567") == "+972501234567"
    assert normalize_phone("") is None


def test_approval_follows_the_cosuite_subscription():
    live = ManzumaSub(module="cosuite", plan="pro", status="active")
    cancelled = ManzumaSub(module="cosuite", plan="pro", status="cancelled")
    elsewhere = ManzumaSub(module="oneshare", plan="starter", status="active")

    assert approval_for(ManzumaOrg("o1", "Afkar", "owner", (live,))) == "approved"
    assert approval_for(ManzumaOrg("o2", "Old", "owner", (cancelled,))) == "frozen"
    assert approval_for(ManzumaOrg("o3", "Other", "owner", (elsewhere,))) == "frozen"
    assert approval_for(None) == "frozen"


def test_suite_decision_prefers_the_linked_suite():
    assert suite_decision("s1", ["s2"]) == ("use", "s1")


def test_suite_decision_offers_a_single_unlinked_suite():
    assert suite_decision(None, ["s2"]) == ("offer_link", "s2")


def test_suite_decision_creates_when_there_is_nothing_or_too_much_to_choose():
    assert suite_decision(None, []) == ("create", None)
    assert suite_decision(None, ["s2", "s3"]) == ("create", None)
