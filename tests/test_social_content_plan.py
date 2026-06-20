from api.routers.suites import SocialLoopRequest, _build_content_plan, _normalize_social_loop


def test_build_content_plan_uses_suite_context_and_launch_fields():
    plan = _build_content_plan(
        {
            "name": "Acme Clinic",
            "services": ["Pediatrics", "Nutrition"],
            "audience_languages": ["en", "ar"],
        },
        {
            "marketing_plan": {
                "content_themes": ["Parent education", "Same-day bookings"],
            }
        },
        {
            "facebook": {"page_id": "page_1"},
            "instagram": {"ig_user_id": "ig_1"},
        },
    )

    assert plan["name"] == "Acme Clinic social content plan"
    assert [pillar["name"] for pillar in plan["content_pillars"]][:2] == ["Parent education", "Same-day bookings"]
    assert plan["cadence"]["posts_per_week"] == 3
    assert plan["platforms"] == ["facebook", "instagram"]
    assert {"type": "carousel", "enabled": True} in plan["formats"]
    assert plan["languages"] == ["en", "ar"]
    assert plan["approval_flow"]["required"] is True
    assert plan["scheduling_handoff"]["status"] == "ready_for_calendar"


def test_normalize_social_loop_preserves_editable_content_plan_fields():
    loop = _normalize_social_loop(
        SocialLoopRequest(
            name="Q3 launch",
            status="active",
            content_pillars=[{"name": "Proof", "percentage": 40, "notes": "Case studies"}],
            cadence={"posts_per_week": 4, "preferred_days": ["Monday"]},
            platforms=["instagram", "linkedin"],
            formats=[{"type": "reel", "enabled": True}],
            languages=["he"],
            approval_flow={"required": True, "steps": ["owner_review", "schedule"]},
            scheduling_handoff={"status": "needs_scheduler", "owner": "Marketing"},
            notes="Push local proof.",
        ),
        existing_count=0,
    )

    assert loop["id"] == "q3-launch"
    assert loop["content_pillars"][0]["name"] == "Proof"
    assert loop["cadence"]["posts_per_week"] == 4
    assert loop["platforms"] == ["instagram", "linkedin"]
    assert loop["formats"] == [{"type": "reel", "enabled": True}]
    assert loop["languages"] == ["he"]
    assert loop["approval_flow"]["steps"] == ["owner_review", "schedule"]
    assert loop["scheduling_handoff"]["owner"] == "Marketing"
