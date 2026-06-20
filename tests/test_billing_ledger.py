import pytest

from api.models.billing import (
    BillingEventType,
    LedgerAccountType,
    PlanTier,
    Subscription,
)
from api.services.billing import (
    GenerationGateStatus,
    apply_marketing_budget_top_up,
    apply_monthly_plan_token_grant,
    generation_gate_decision,
    apply_token_purchase,
    record_subscription_plan_set,
    record_generation_token_usage,
    record_marketing_budget_spend,
)


def test_billing_ledger_enum_values_are_stable():
    assert LedgerAccountType.subscription.value == "subscription"
    assert LedgerAccountType.generation_tokens.value == "generation_tokens"
    assert LedgerAccountType.marketing_budget.value == "marketing_budget"

    assert BillingEventType.subscription_plan_set.value == "subscription_plan_set"
    assert BillingEventType.subscription_token_grant.value == "subscription_token_grant"
    assert BillingEventType.token_purchase.value == "token_purchase"
    assert BillingEventType.generation_usage.value == "generation_usage"
    assert BillingEventType.marketing_budget_top_up.value == "marketing_budget_top_up"
    assert BillingEventType.marketing_budget_spend.value == "marketing_budget_spend"


def test_subscription_starts_with_separate_token_and_marketing_wallets():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo)

    assert sub.generation_token_balance == 0
    assert sub.marketing_budget_balance_usd == 0


def test_plan_grant_purchase_and_generation_usage_create_auditable_token_events():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo)

    grant = apply_monthly_plan_token_grant(
        sub,
        tokens=1000,
        reason="June solo allowance",
        idempotency_key="plan:suite-1:2026-06",
    )
    purchase = apply_token_purchase(
        sub,
        tokens=500,
        amount_usd=25.0,
        external_ref="morning_payment_123",
        metadata={"package": "starter"},
    )
    usage = record_generation_token_usage(
        sub,
        tokens=275,
        event_type="image_generation",
        metadata={"job_id": "job-1", "provider": "google"},
    )

    assert sub.generation_token_balance == 1225
    assert grant.ledger_account == LedgerAccountType.generation_tokens
    assert grant.billing_event_type == BillingEventType.subscription_token_grant
    assert grant.amount_tokens == 1000
    assert grant.balance_after_tokens == 1000
    assert grant.idempotency_key == "plan:suite-1:2026-06"

    assert purchase.billing_event_type == BillingEventType.token_purchase
    assert purchase.amount_tokens == 500
    assert purchase.amount_usd == 25.0
    assert purchase.balance_after_tokens == 1500
    assert purchase.external_ref == "morning_payment_123"

    assert usage.billing_event_type == BillingEventType.generation_usage
    assert usage.event_type == "image_generation"
    assert usage.amount_tokens == -275
    assert usage.balance_after_tokens == 1225
    assert usage.event_data == {"job_id": "job-1", "provider": "google"}


def test_subscription_plan_set_event_records_plan_and_seat_change():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo, seat_count=1)

    event = record_subscription_plan_set(
        sub,
        tier=PlanTier.team,
        seat_count=3,
        monthly_tokens=4500,
        external_ref="morning_subscription_123",
    )

    assert sub.tier == PlanTier.team
    assert sub.seat_count == 3
    assert sub.monthly_generation_token_grant == 4500
    assert event.ledger_account == LedgerAccountType.subscription
    assert event.billing_event_type == BillingEventType.subscription_plan_set
    assert event.amount_tokens == 0
    assert event.balance_after_tokens == sub.generation_token_balance
    assert event.external_ref == "morning_subscription_123"
    assert event.event_data == {
        "tier": "team",
        "seat_count": 3,
        "monthly_generation_token_grant": 4500,
    }


def test_marketing_budget_top_up_and_spend_use_separate_balance():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.team)
    sub.generation_token_balance = 300

    top_up = apply_marketing_budget_top_up(
        sub,
        amount_usd=200.0,
        external_ref="morning_ads_123",
    )
    spend = record_marketing_budget_spend(
        sub,
        amount_usd=47.25,
        event_type="meta_campaign_budget",
        metadata={"campaign_id": "cmp-1"},
    )

    assert sub.generation_token_balance == 300
    assert sub.marketing_budget_balance_usd == 152.75
    assert top_up.ledger_account == LedgerAccountType.marketing_budget
    assert top_up.amount_usd == 200.0
    assert top_up.balance_after_usd == 200.0
    assert spend.billing_event_type == BillingEventType.marketing_budget_spend
    assert spend.amount_usd == -47.25
    assert spend.balance_after_usd == 152.75
    assert spend.event_data == {"campaign_id": "cmp-1"}


def test_generation_usage_rejects_insufficient_tokens_without_mutating_balance():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo)
    sub.generation_token_balance = 10

    with pytest.raises(ValueError, match="Insufficient generation tokens"):
        record_generation_token_usage(sub, tokens=11, event_type="video_generation")

    assert sub.generation_token_balance == 10


def test_generation_gate_allows_limited_free_trial_then_returns_payment_actions():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo)
    sub.generation_token_balance = 0

    allowed = generation_gate_decision(
        sub,
        required_tokens=100,
        free_trial_units_used=2,
        requested_units=1,
        allow_free_trial=True,
    )
    exhausted = generation_gate_decision(
        sub,
        required_tokens=100,
        free_trial_units_used=3,
        requested_units=1,
        allow_free_trial=True,
    )

    assert allowed.status == GenerationGateStatus.free_trial
    assert allowed.free_trial_remaining == 0
    assert exhausted.status == GenerationGateStatus.blocked
    assert exhausted.payment_required is True
    assert exhausted.detail["code"] == "generation_tokens_exhausted"
    assert exhausted.detail["allowed_actions"] == ["upgrade_plan", "buy_generation_tokens"]


def test_generation_gate_blocks_expensive_actions_without_tokens_even_during_free_trial():
    sub = Subscription(id="sub-1", suite_id="suite-1", tier=PlanTier.solo)
    sub.generation_token_balance = 0

    decision = generation_gate_decision(
        sub,
        required_tokens=300,
        free_trial_units_used=0,
        requested_units=1,
        allow_free_trial=False,
    )

    assert decision.status == GenerationGateStatus.blocked
    assert decision.payment_required is True
    assert decision.detail["required_tokens"] == 300
    assert decision.detail["token_balance"] == 0
