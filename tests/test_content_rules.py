import pytest

from api.models.suite import Suite
from api.models.user import User
from api.routers import suites as suites_router
from api.services import content_rules as cr
from api.services import marketing_plan_generator as mpg


# ── Service: normalization ────────────────────────────────────────────────────

def test_normalize_content_rules_accepts_legacy_and_new_shapes():
    rules = cr.normalize_content_rules(
        [
            "لا تستخدم إيموجي",
            {"text": "اكتب بنبرة ودية", "source": "regenerate_feedback"},
            {"from": "شيقل", "to": "شيكل"},
            {"from": "  ", "to": "شيكل"},  # unusable
            {},  # unusable
        ]
    )

    assert len(rules) == 3
    assert rules[0] == {
        "type": "guideline",
        "text": "لا تستخدم إيموجي",
        "source": "manual",
        "id": rules[0]["id"],
    }
    assert rules[1]["source"] == "regenerate_feedback"
    assert rules[2]["type"] == "replace"
    assert rules[2]["from"] == "شيقل"
    assert rules[2]["to"] == "شيكل"
    assert all(rule["id"] for rule in rules)


def test_normalize_content_rules_dedupes_and_caps():
    rules = cr.normalize_content_rules(["نفس القاعدة", "نفس القاعدة"] + [f"قاعدة {i}" for i in range(cr.MAX_RULES + 10)])

    assert len(rules) == cr.MAX_RULES
    texts = [rule["text"] for rule in rules]
    assert len(texts) == len(set(texts))


def test_rule_ids_are_stable_across_normalizations():
    first = cr.normalize_content_rules([{"from": "شيقل", "to": "شيكل"}])[0]
    second = cr.normalize_content_rules([{"from": "شيقل", "to": "شيكل"}])[0]

    assert first["id"] == second["id"]


# ── Service: application ──────────────────────────────────────────────────────

def test_apply_replace_rules_substitutes_all_occurrences():
    rules = cr.normalize_content_rules([{"from": "شيقل", "to": "شيكل"}, "تعليمة أسلوبية"])

    assert cr.apply_replace_rules("دفع ٥٠٠٠ شيقل ورجع شيقل واحد", rules) == "دفع ٥٠٠٠ شيكل ورجع شيكل واحد"
    assert cr.apply_replace_rules(None, rules) is None


def test_apply_replace_rules_to_item_touches_only_requested_fields():
    rules = cr.normalize_content_rules([{"from": "شيقل", "to": "شيكل"}])
    item = {"title": "خسر شيقل", "script": "٥٠ شيقل", "provider": "شيقل-provider"}

    cr.apply_replace_rules_to_item(item, rules, ("title", "script"))

    assert item["title"] == "خسر شيكل"
    assert item["script"] == "٥٠ شيكل"
    assert item["provider"] == "شيقل-provider"


def test_format_content_rules_prompt_lists_both_kinds():
    rules = cr.normalize_content_rules([{"from": "شيقل", "to": "شيكل"}, "لا تستخدم إيموجي بالعناوين"])

    block = cr.format_content_rules_prompt(rules)

    assert "MUST follow" in block
    assert '"شيكل"' in block and '"شيقل"' in block
    assert "لا تستخدم إيموجي بالعناوين" in block
    assert cr.format_content_rules_prompt([]) == ""


# ── Wiring: work-plan generation ──────────────────────────────────────────────

def _payload_with_rules() -> dict:
    return {
        "suite": {"id": "s1", "name": "متجر"},
        "brand": {
            "name": "متجر",
            "services": ["خدمة"],
            "content_rules": [
                {"from": "شيقل", "to": "شيكل"},
                {"text": "لا تستخدم إيموجي"},
            ],
        },
        "strategy": {},
        "planning_inputs": {},
    }


def test_social_prompt_includes_content_rules():
    prompt = mpg.build_social_content_plan_prompt(_payload_with_rules(), "ar", 10, "anthropic")

    assert "MUST follow" in prompt
    assert "لا تستخدم إيموجي" in prompt


def test_paid_prompt_includes_content_rules():
    prompt = mpg.build_paid_content_plan_prompt(_payload_with_rules(), "ar", "anthropic")

    assert "MUST follow" in prompt
    assert "لا تستخدم إيموجي" in prompt


def test_normalize_social_content_plan_enforces_replace_rules():
    plan = mpg.normalize_social_content_plan(
        [
            {
                "type": "attraction",
                "title": "صاحب محل خسر ٥٠٠٠ شيقل",
                "idea": "قصة عن شيقل ضايع",
                "script": "دفع شيقل ورجع شيقل",
                "provider": "anthropic",
            }
        ],
        _payload_with_rules(),
        "ar",
        3,
    )

    joined = " ".join(
        item[field]
        for group in plan["candidates"].values()
        for item in group
        for field in ("title", "idea", "script")
    )
    assert "شيقل" not in joined


def test_normalize_paid_content_plan_enforces_replace_rules():
    plan = mpg.normalize_paid_content_plan(
        [
            {
                "stage": "awareness",
                "title": "إعلان عن شيقل",
                "hook": "وفر شيقل",
                "copy": "بـ ١٠ شيقل بس",
                "provider": "anthropic",
            }
        ],
        _payload_with_rules(),
        "ar",
    )

    joined = " ".join(
        " ".join(str(item.get(field) or "") for field in ("title", "hook", "copy"))
        for group in plan["candidates"].values()
        for item in group
    )
    assert "شيقل" not in joined


# ── Teach: AI suggestion parsing ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_rules_from_feedback_parses_ai_response(monkeypatch):
    async def fake_call_text_ai(**_kwargs):
        return '{"rules": [{"from": "شيقل", "to": "شيكل"}, {"text": "نبرة رسمية"}]}'

    monkeypatch.setattr(cr, "call_text_ai", fake_call_text_ai)

    suggestions = await cr.suggest_rules_from_feedback("بدل شيقل اكتب شيكل وخلي النبرة رسمية")

    assert len(suggestions) == 2
    assert suggestions[0]["type"] == "replace"
    assert suggestions[0]["source"] == "taught"
    assert suggestions[1]["type"] == "guideline"


@pytest.mark.asyncio
async def test_suggest_rules_falls_back_to_guideline_on_ai_failure(monkeypatch):
    async def failing_call_text_ai(**_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(cr, "call_text_ai", failing_call_text_ai)

    suggestions = await cr.suggest_rules_from_feedback("بدي اللغة أبسط")

    assert len(suggestions) == 1
    assert suggestions[0]["type"] == "guideline"
    assert suggestions[0]["text"] == "بدي اللغة أبسط"


# ── Router endpoints ──────────────────────────────────────────────────────────

class FakeDb:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


def _suite_and_user() -> tuple[Suite, User]:
    suite = Suite(
        id="suite-1",
        owner_id="user-1",
        name="متجر",
        slug="matjar",
        brand={"name": "متجر", "content_rules": [{"text": "قاعدة قديمة", "source": "profile_edit"}]},
        strategy={},
    )
    user = User(id="user-1", email="owner@example.com", hashed_password="hash", full_name="Owner")
    return suite, user


@pytest.mark.asyncio
async def test_content_rules_endpoints_add_list_delete(monkeypatch):
    suite, user = _suite_and_user()
    db = FakeDb()

    async def fake_get_owned_suite(_db, _suite_id, _user):
        return suite

    monkeypatch.setattr(suites_router, "_get_owned_suite", fake_get_owned_suite)

    added = await suites_router.add_content_rules(
        "suite-1",
        suites_router.AddContentRulesRequest(
            rules=[suites_router.ContentRuleInput(replace_from="شيقل", replace_to="شيكل")],
            source="taught",
        ),
        user,
        db,
    )
    assert db.committed is True
    assert len(added["rules"]) == 2
    replace_rule = added["rules"][1]
    assert replace_rule["type"] == "replace"
    assert replace_rule["source"] == "taught"

    listed = await suites_router.list_content_rules("suite-1", user, db)
    assert [rule["id"] for rule in listed["rules"]] == [rule["id"] for rule in added["rules"]]

    deleted = await suites_router.delete_content_rule("suite-1", replace_rule["id"], user, db)
    assert len(deleted["rules"]) == 1
    assert deleted["rules"][0]["text"] == "قاعدة قديمة"


@pytest.mark.asyncio
async def test_add_content_rules_rejects_empty_payload(monkeypatch):
    suite, user = _suite_and_user()

    async def fake_get_owned_suite(_db, _suite_id, _user):
        return suite

    monkeypatch.setattr(suites_router, "_get_owned_suite", fake_get_owned_suite)

    with pytest.raises(Exception) as exc:
        await suites_router.add_content_rules(
            "suite-1",
            suites_router.AddContentRulesRequest(rules=[suites_router.ContentRuleInput()]),
            user,
            FakeDb(),
        )
    assert getattr(exc.value, "status_code", None) == 422


# ── Suite deletion ────────────────────────────────────────────────────────────

class _DeleteResult:
    def __init__(self, suite):
        self._suite = suite

    def scalar_one_or_none(self):
        return self._suite


class _DeleteDb:
    def __init__(self, suite):
        self._suite = suite
        self.statements = []
        self.deleted = []
        self.committed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return _DeleteResult(self._suite)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_delete_suite_removes_suite_and_children():
    suite, user = _suite_and_user()
    db = _DeleteDb(suite)

    response = await suites_router.delete_suite("suite-1", user, db)

    assert response == {"ok": True, "deleted_suite_id": "suite-1"}
    assert db.deleted == [suite]
    assert db.committed is True
    # owned-suite select + child deletes/updates across all suite tables
    assert len(db.statements) >= 12


@pytest.mark.asyncio
async def test_delete_suite_rejects_non_owner():
    suite, _owner = _suite_and_user()
    intruder = User(id="user-2", email="other@example.com", hashed_password="hash", full_name="Other")
    db = _DeleteDb(suite)

    with pytest.raises(Exception) as exc:
        await suites_router.delete_suite("suite-1", intruder, db)

    assert getattr(exc.value, "status_code", None) == 404
    assert db.deleted == []
