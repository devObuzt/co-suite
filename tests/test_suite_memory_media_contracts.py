import pytest
from fastapi import BackgroundTasks, HTTPException
from api.models.content import ContentPost, PostFormat, PostStatus
from api.models.generation_job import GenerationJob, GenerationJobStatus, GenerationJobType
from api.models.suite import Suite
from api.models.user import User
from api.routers.content import (
    GenerateRequest,
    _apply_rejection_metadata,
    _append_content_learning_log,
    _account_options,
    _mark_regeneration_requested,
    _validate_quick_creative_brief,
    _normalize_rejection_reason,
    _publish_preflight,
    _record_publish_attempt,
    generate_account_content,
)
from api.services import publisher
from api.services.media_storage import media_readiness_for_post
from api.services.suite_memory import build_suite_memory_v0, merge_suite_brand


def test_suite_memory_v0_normalizes_legacy_brand_strategy_connections():
    memory = build_suite_memory_v0(
        brand={
            "name": "Acme Clinic",
            "industry": "Healthcare",
            "target_audience": "Parents",
            "audience_languages": ["en", "ar"],
            "tone": "calm",
            "colors": {"primary": "#123456"},
            "brand_logos": [{"url": "https://cdn.example/logo.png"}],
            "brand_personas": [{"name": "Maya"}],
            "services": ["Pediatrics"],
            "content_rules": [{"text": "Avoid fear-based copy"}],
            "usp_points": ["Same-day bookings"],
            "esp_points": ["Peace of mind"],
        },
        strategy={
            "marketing_plan": {"content_themes": ["Education"]},
            "audience_segments": ["New parents"],
        },
        connections={
            "facebook": {"page_id": "page_1", "page_access_token": "secret"},
            "instagram": {},
        },
    )

    assert memory["version"] == "suite_memory_v0"
    assert memory["business_profile"]["name"] == "Acme Clinic"
    assert memory["audience_profile"]["summary"] == "Parents"
    assert memory["language_profile"]["languages"] == ["en", "ar"]
    assert memory["brand_profile"]["tone"] == "calm"
    assert memory["visual_assets"]["logos"][0]["url"] == "https://cdn.example/logo.png"
    assert memory["personas"][0]["name"] == "Maya"
    assert memory["products_services"]["items"] == ["Pediatrics"]
    assert memory["content_rules"][0]["text"] == "Avoid fear-based copy"
    assert memory["platform_connections_summary"]["facebook"]["state"] == "connected"
    assert memory["platform_connections_summary"]["instagram"]["state"] == "not_connected"
    assert memory["platform_connections_summary"]["facebook"].get("page_access_token") is None
    assert memory["use_brand_default"] is True


def test_append_content_learning_log_keeps_recent_structured_events():
    brand = {"content_learning_logs": [{"type": f"old-{i}"} for i in range(60)]}

    updated = _append_content_learning_log(
        brand,
        event_type="text_edit",
        user_id="user-1",
        source="post_editor",
        payload={"from": "هلق", "to": "اسا"},
    )

    assert len(updated["content_learning_logs"]) == 50
    latest = updated["content_learning_logs"][-1]
    assert latest["type"] == "text_edit"
    assert latest["source"] == "post_editor"
    assert latest["payload"] == {"from": "هلق", "to": "اسا"}


def test_media_readiness_marks_public_media_ready():
    post = ContentPost(
        id="post_1",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.pending,
        media_urls=["https://cdn.example/post.png"],
        ai_metadata={},
    )

    readiness = media_readiness_for_post(post)

    assert readiness["state"] == "ready"
    assert readiness["publish_ready"] is True
    assert readiness["items"][0]["public"] is True
    assert readiness["items"][0]["backend"] == "remote"


def test_media_readiness_distinguishes_missing_local_and_not_required():
    missing = ContentPost(
        id="post_2",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.pending,
        media_urls=[],
        ai_metadata={"media_error": "image provider timeout"},
    )
    local = ContentPost(
        id="post_3",
        suite_id="suite_1",
        format=PostFormat.video,
        status=PostStatus.pending,
        media_urls=["/static/posts/video.mp4"],
        ai_metadata={},
    )
    text_only = ContentPost(
        id="post_4",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.pending,
        media_urls=[],
        ai_metadata={"content_type": "text", "requires_media": False},
    )

    assert media_readiness_for_post(missing)["state"] == "failed"
    assert media_readiness_for_post(missing)["reason"] == "Media generation failed. You can retry generation or publish as text only where supported."
    assert media_readiness_for_post(local)["state"] == "local-only"
    assert media_readiness_for_post(local)["publish_ready"] is False
    assert media_readiness_for_post(text_only)["state"] == "not_required"


def test_publish_preflight_blocks_media_posts_without_public_media():
    post = ContentPost(
        id="post_5",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        media_urls=["/static/posts/local.png"],
        ai_metadata={},
    )

    try:
        _publish_preflight(post, ["facebook", "instagram"])
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
        assert exc.detail["message"] == "Media is not ready for publishing."
        assert exc.detail["media_readiness"]["state"] == "local-only"
    else:
        raise AssertionError("Expected non-public media to block publishing")


def test_publish_preflight_allows_explicit_facebook_text_only():
    post = ContentPost(
        id="post_6",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        media_urls=["/static/posts/local.png"],
        ai_metadata={},
    )

    platforms, preflight = _publish_preflight(post, ["facebook"], allow_text_only=True)

    assert platforms == ["facebook"]
    assert preflight["publish_mode"] == "text_only"
    assert preflight["media_readiness"]["publish_ready"] is False


def test_publish_preflight_accepts_public_media():
    post = ContentPost(
        id="post_7",
        suite_id="suite_1",
        format=PostFormat.carousel,
        status=PostStatus.approved,
        media_urls=["https://cdn.example/1.png", "https://cdn.example/2.png"],
        ai_metadata={},
    )

    platforms, preflight = _publish_preflight(post, ["facebook", "instagram"])

    assert platforms == ["facebook", "instagram"]
    assert preflight["publish_mode"] == "media"
    assert preflight["media_readiness"]["state"] == "ready"


def test_publish_preflight_uses_platform_specific_media_before_generic_media():
    post = ContentPost(
        id="post_7_platform_media",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        media_urls=["https://cdn.example/generic.png"],
        ai_metadata={
            "platform_media": {
                "facebook": ["/static/posts/facebook-local.png"],
                "instagram": ["https://cdn.example/instagram.png"],
            }
        },
    )

    with pytest.raises(HTTPException) as exc:
        _publish_preflight(post, ["facebook", "instagram"])

    assert exc.value.status_code == 400
    assert exc.value.detail["media_readiness"]["platforms"]["facebook"]["state"] == "local-only"
    assert exc.value.detail["media_readiness"]["platforms"]["instagram"]["state"] == "ready"


def test_facebook_media_publish_does_not_fall_back_to_text_only(monkeypatch):
    post = ContentPost(
        id="post_7_fb_no_text_fallback",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        media_urls=["/static/posts/local.png"],
        ai_metadata={},
    )

    monkeypatch.setattr(publisher, "_fb_text", lambda *args: (_ for _ in ()).throw(AssertionError("unexpected text publish")))

    result = publisher.publish_post(
        post,
        {"facebook": {"page_id": "page_1", "page_access_token": "token_1"}},
        ["facebook"],
    )

    assert "facebook" not in result
    assert result["facebook_error"] == "Facebook media is not available as a public HTTPS URL."


def test_partial_publish_attempt_keeps_post_globally_unpublished():
    post = ContentPost(
        id="post_7_partial_publish",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        ai_metadata={"source": "ai"},
    )

    attempt = _record_publish_attempt(
        post,
        requested_platforms={"facebook", "instagram"},
        successful_platforms={"facebook"},
        fully_published=False,
        preflight={"publish_mode": "media", "media_readiness": {"state": "ready"}},
        publish_result={"facebook": "fb_123", "instagram_error": "permission denied"},
    )

    assert attempt["status"] == "partially_published"
    assert attempt["fully_published"] is False
    assert post.status == PostStatus.approved
    assert post.ai_metadata["last_publish_result"]["status"] == "partially_published"
    assert post.ai_metadata["last_publish_result"]["results"]["facebook"] == "fb_123"
    assert post.ai_metadata["last_publish_result"]["results"]["instagram_error"] == "permission denied"


def test_merge_suite_brand_preserves_unrelated_existing_fields():
    merged = merge_suite_brand(
        {
            "name": "Acme",
            "colors": {"primary": "#111111", "secondary": "#222222"},
            "brand_logos": [{"url": "https://cdn.example/logo.png"}],
            "content_rules": [{"text": "Do not use fear copy"}],
        },
        {
            "colors": {"primary": "#333333"},
            "audience_note": "Parents in Haifa",
        },
    )

    assert merged["name"] == "Acme"
    assert merged["colors"] == {"primary": "#333333", "secondary": "#222222"}
    assert merged["brand_logos"][0]["url"] == "https://cdn.example/logo.png"
    assert merged["content_rules"][0]["text"] == "Do not use fear copy"
    assert merged["audience_note"] == "Parents in Haifa"


def test_rejection_metadata_persists_reason_and_history():
    post = ContentPost(
        id="post_8",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.pending,
        ai_metadata={"source": "ai"},
    )

    _apply_rejection_metadata(post, "Make it more local", "user_1")

    assert post.ai_metadata["source"] == "ai"
    assert post.ai_metadata["last_rejection"]["reason"] == "Make it more local"
    assert post.ai_metadata["last_rejection"]["rejected_by"] == "user_1"
    assert post.ai_metadata["rejection_history"][0]["reason"] == "Make it more local"


def test_empty_rejection_reason_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _normalize_rejection_reason(None)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Rejection reason is required"


def test_regeneration_request_preserves_original_post_metadata():
    post = ContentPost(
        id="post_9",
        suite_id="suite_1",
        format=PostFormat.carousel,
        status=PostStatus.rejected,
        ai_metadata={"idea_id": "old_idea"},
    )

    _mark_regeneration_requested(post, "Use Hebrew, less text", "user_1")

    assert post.ai_metadata["idea_id"] == "old_idea"
    assert post.ai_metadata["regeneration_requested"]["feedback"] == "Use Hebrew, less text"
    assert post.ai_metadata["regeneration_requested"]["requested_by"] == "user_1"


def test_publish_attempt_metadata_is_recorded_even_when_all_platforms_fail():
    post = ContentPost(
        id="post_10",
        suite_id="suite_1",
        format=PostFormat.image,
        status=PostStatus.approved,
        ai_metadata={"source": "ai"},
    )

    attempt = _record_publish_attempt(
        post,
        requested_platforms={"facebook", "instagram"},
        successful_platforms=set(),
        fully_published=False,
        preflight={"publish_mode": "media", "media_readiness": {"state": "ready"}},
        publish_result={"errors": {"facebook": "permission denied", "instagram": "permission denied"}},
    )

    assert attempt["status"] == "failed"
    assert attempt["successful_platforms"] == []
    assert post.ai_metadata["source"] == "ai"
    assert post.ai_metadata["last_publish_result"]["status"] == "failed"
    assert post.ai_metadata["publish_attempts"][0]["results"]["errors"]["facebook"] == "permission denied"


def test_account_generation_options_force_brand_off_and_keep_language():
    options = _account_options(
        GenerateRequest(
            count=1,
            prompt="Create a post",
            mode="image",
            content_type="image",
            use_brand=True,
            language="he",
        )
    )

    assert options["use_brand"] is False
    assert options["account_level"] is True
    assert options["language"] == "he"
    assert options["content_type"] == "image"


@pytest.mark.asyncio
async def test_account_generation_route_forces_brand_off_and_enqueues_durable_job(monkeypatch):
    user = User(id="user-1", email="owner@example.com", hashed_password="x")
    suite = Suite(id="suite-1", owner_id=user.id, name="Quick Create", slug="quick-create")
    suite.brand = {"account_level_draft": True, "name": "Owner"}

    async def fake_get_or_create_account_draft_suite(_current_user, _db):
        return suite

    async def fake_get_active_job(_db, _suite_id):
        return None

    async def fake_enforce_generation_gate(*_args, **_kwargs):
        return None

    created_job_input = {}

    async def fake_create_job(_db, suite_id, job_type, user_id, input_data):
        created_job_input.update(input_data)
        return GenerationJob(
            id="job-1",
            suite_id=suite_id,
            type=job_type,
            status=GenerationJobStatus.queued,
            stage="queued",
            message="Generation queued.",
            progress=0,
            created_by=user_id,
            input=input_data,
        )

    class FakeDb:
        committed = False

        async def commit(self):
            self.committed = True

    monkeypatch.setattr("api.routers.content._get_or_create_account_draft_suite", fake_get_or_create_account_draft_suite)
    monkeypatch.setattr("api.routers.content.get_active_job", fake_get_active_job)
    monkeypatch.setattr("api.routers.content.enforce_generation_gate", fake_enforce_generation_gate)
    monkeypatch.setattr("api.routers.content.create_job", fake_create_job)

    background_tasks = BackgroundTasks()
    payload = await generate_account_content(
        GenerateRequest(
            count=12,
            prompt="Create a launch post",
            mode="image",
            content_type="image",
            use_brand=True,
            language="ar",
        ),
        background_tasks,
        user,
        FakeDb(),
    )

    assert payload["job_id"] == "job-1"
    assert payload["status"] == "queued"
    assert payload["type"] == GenerationJobType.content_generation.value
    assert payload["suite_id"] == "suite-1"
    assert payload["execution"]["mode"] == "durable_worker"
    assert background_tasks.tasks == []

    assert created_job_input["count"] == 3
    assert created_job_input["use_brand"] is False
    assert created_job_input["account_level"] is True
    assert created_job_input["language"] == "ar"
    assert suite.brand["account_level_draft"] is True
    assert suite.brand["audience_languages"] == ["ar"]


@pytest.mark.asyncio
async def test_account_generation_route_preserves_payment_gate_upgrade_actions(monkeypatch):
    user = User(id="user-1", email="owner@example.com", hashed_password="x")
    suite = Suite(id="suite-1", owner_id=user.id, name="Quick Create", slug="quick-create")
    suite.brand = {"account_level_draft": True}

    async def fake_get_or_create_account_draft_suite(_current_user, _db):
        return suite

    async def fake_get_active_job(_db, _suite_id):
        return None

    async def fake_enforce_generation_gate(*_args, **_kwargs):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "generation_tokens_exhausted",
                "message": "Generation tokens are exhausted.",
                "allowed_actions": ["upgrade_plan", "buy_generation_tokens"],
            },
        )

    class FakeDb:
        async def commit(self):
            return None

    monkeypatch.setattr("api.routers.content._get_or_create_account_draft_suite", fake_get_or_create_account_draft_suite)
    monkeypatch.setattr("api.routers.content.get_active_job", fake_get_active_job)
    monkeypatch.setattr("api.routers.content.enforce_generation_gate", fake_enforce_generation_gate)

    with pytest.raises(HTTPException) as exc:
        await generate_account_content(
            GenerateRequest(count=1, prompt="Create a launch post", content_type="image"),
            BackgroundTasks(),
            user,
            FakeDb(),
        )

    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "generation_tokens_exhausted"
    assert exc.value.detail["allowed_actions"] == ["upgrade_plan", "buy_generation_tokens"]


def test_quick_creative_brief_allows_uploaded_https_assets():
    _validate_quick_creative_brief(
        GenerateRequest(
            count=1,
            mode="quick",
            content_type="image",
            creative_brief={
                "logo": {"enabled": True, "source": "uploaded", "url": "https://cdn.example/logo.png"},
                "required_sizes": {"ids": ["instagram_post_4_5"], "aspect_ratios": ["4:5"]},
                "reference_assets": [
                    {
                        "kind": "product",
                        "names": ["product.png"],
                        "urls": ["https://cdn.example/product.png"],
                        "count": 1,
                        "instruction": "Preserve product identity.",
                    }
                ],
                "hook": "Launch now",
            },
        )
    )


def test_quick_creative_brief_rejects_unuploaded_reference_assets():
    with pytest.raises(HTTPException) as exc:
        _validate_quick_creative_brief(
            GenerateRequest(
                count=1,
                mode="quick",
                content_type="image",
                creative_brief={
                    "reference_assets": [
                        {"kind": "product", "names": ["local.png"], "urls": [], "count": 1}
                    ]
                },
            )
        )

    assert exc.value.status_code == 422
    assert "uploaded" in str(exc.value.detail)


def test_quick_creative_brief_rejects_invalid_required_size():
    with pytest.raises(HTTPException) as exc:
        _validate_quick_creative_brief(
            GenerateRequest(
                count=1,
                mode="quick",
                content_type="image",
                creative_brief={"required_sizes": {"ids": ["poster_7_3"]}},
            )
        )

    assert exc.value.status_code == 422
    assert "required size" in str(exc.value.detail)
