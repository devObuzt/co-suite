"""Early-warning capacity monitoring for the generation pipeline.

Runs inside the dedicated worker: every few minutes it computes leading
indicators from generation_jobs and pings the owner on Telegram BEFORE users
feel the pain (long queue waits, slowing renders, provider failures). A calm
day produces zero messages except the morning digest.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.database import AsyncSessionLocal
from ..core.observability import log_event, send_telegram_alert

log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 600
ALERT_COOLDOWN_SECONDS = 3600
DIGEST_HOUR_UTC = 5  # ~08:00 local (UTC+3)

MAX_OLDEST_QUEUED_SECONDS = 180
MAX_QUEUE_DEPTH = 5
MAX_RENDER_P95_MINUTES = 25.0
MAX_FAILURE_RATE = 0.2
MIN_JOBS_FOR_FAILURE_RATE = 3


async def collect_capacity_metrics(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM generation_jobs WHERE status = 'queued') AS queue_depth,
                  (SELECT count(*) FROM generation_jobs WHERE status = 'running') AS running,
                  (SELECT extract(epoch FROM (now() - min(created_at)))
                     FROM generation_jobs WHERE status = 'queued') AS oldest_queued_seconds,
                  (SELECT percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (finished_at - started_at)))
                     FROM generation_jobs
                     WHERE type = 'video_montage' AND status = 'completed'
                       AND finished_at > now() - interval '24 hours'
                       AND started_at IS NOT NULL AND finished_at IS NOT NULL
                  ) AS render_p95_seconds,
                  (SELECT count(*) FROM generation_jobs
                     WHERE status = 'failed' AND updated_at > now() - interval '1 hour') AS failed_last_hour,
                  (SELECT count(*) FROM generation_jobs
                     WHERE status = 'completed' AND finished_at > now() - interval '1 hour') AS completed_last_hour,
                  (SELECT count(*) FROM generation_jobs
                     WHERE status IN ('retrying', 'waiting_provider_limit')) AS waiting_retry
                """
            )
        )
    ).one()
    return {
        "queue_depth": int(row.queue_depth or 0),
        "running": int(row.running or 0),
        "oldest_queued_seconds": float(row.oldest_queued_seconds or 0),
        "render_p95_seconds": float(row.render_p95_seconds or 0),
        "failed_last_hour": int(row.failed_last_hour or 0),
        "completed_last_hour": int(row.completed_last_hour or 0),
        "waiting_retry": int(row.waiting_retry or 0),
    }


def evaluate_capacity_alerts(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (code, message) pairs for every crossed threshold."""
    alerts: list[tuple[str, str]] = []
    oldest = metrics.get("oldest_queued_seconds") or 0
    if oldest > MAX_OLDEST_QUEUED_SECONDS:
        alerts.append(
            (
                "queue_wait",
                f"⏳ أقدم مهمة مستنية بالطابور من {int(oldest / 60)} دقيقة "
                f"(الحد {int(MAX_OLDEST_QUEUED_SECONDS / 60)} د) — الوقت المناسب لزيادة replicas للـ worker.",
            )
        )
    depth = metrics.get("queue_depth") or 0
    if depth > MAX_QUEUE_DEPTH:
        alerts.append(
            (
                "queue_depth",
                f"📥 {depth} مهمة واقفة بالطابور (الحد {MAX_QUEUE_DEPTH}) و{metrics.get('running', 0)} قيد التنفيذ — ازدحام فعلي.",
            )
        )
    p95 = (metrics.get("render_p95_seconds") or 0) / 60
    if p95 > MAX_RENDER_P95_MINUTES:
        alerts.append(
            (
                "render_p95",
                f"🐢 رندر المونتاج تباطأ: p95 آخر 24 ساعة = {p95:.0f} دقيقة (الحد {MAX_RENDER_P95_MINUTES:.0f} د) — "
                "فكّر بذاكرة أكبر للـ worker أو الانتقال لـ Lambda.",
            )
        )
    failed = metrics.get("failed_last_hour") or 0
    completed = metrics.get("completed_last_hour") or 0
    total = failed + completed
    if total >= MIN_JOBS_FOR_FAILURE_RATE and failed / total > MAX_FAILURE_RATE:
        alerts.append(
            (
                "failure_rate",
                f"🔥 {failed} من أصل {total} مهمة فشلت بآخر ساعة — افحص المزوّدين (fal/Veo/Whisper) واللوغز.",
            )
        )
    waiting = metrics.get("waiting_retry") or 0
    if waiting >= 3:
        alerts.append(
            (
                "provider_limits",
                f"🚦 {waiting} مهمة بحالة إعادة محاولة/انتظار حدود مزوّد — حصة مزوّد قربت تخلص.",
            )
        )
    return alerts


async def collect_daily_digest(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM generation_jobs
                     WHERE type = 'video_montage' AND status = 'completed'
                       AND finished_at > now() - interval '24 hours') AS montages,
                  (SELECT count(*) FROM generation_jobs
                     WHERE status = 'completed' AND finished_at > now() - interval '24 hours') AS completed,
                  (SELECT count(*) FROM generation_jobs
                     WHERE status = 'failed' AND updated_at > now() - interval '24 hours') AS failed,
                  (SELECT avg(extract(epoch FROM (started_at - created_at)))
                     FROM generation_jobs
                     WHERE started_at IS NOT NULL AND created_at > now() - interval '24 hours') AS avg_wait_seconds,
                  (SELECT percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (finished_at - started_at)))
                     FROM generation_jobs
                     WHERE type = 'video_montage' AND status = 'completed'
                       AND finished_at > now() - interval '24 hours'
                       AND started_at IS NOT NULL) AS render_p95_seconds
                """
            )
        )
    ).one()
    return {
        "montages": int(row.montages or 0),
        "completed": int(row.completed or 0),
        "failed": int(row.failed or 0),
        "avg_wait_seconds": float(row.avg_wait_seconds or 0),
        "render_p95_seconds": float(row.render_p95_seconds or 0),
    }


def format_daily_digest(digest: dict[str, Any]) -> str:
    wait = digest.get("avg_wait_seconds") or 0
    p95 = (digest.get("render_p95_seconds") or 0) / 60
    return (
        "📊 ملخص آخر 24 ساعة\n"
        f"🎬 مونتاجات مكتملة: {digest.get('montages', 0)} (إجمالي المهام: {digest.get('completed', 0)})\n"
        f"⏱️ متوسط انتظار بدء المهمة: {wait:.0f} ثانية\n"
        f"🎞️ p95 لمدة الرندر: {p95:.0f} دقيقة\n"
        f"❌ فشل: {digest.get('failed', 0)}"
    )


async def run_capacity_watchdog(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> None:
    last_alert_at: dict[str, datetime] = {}
    last_digest_date: Optional[str] = None
    while True:
        try:
            async with session_factory() as db:
                metrics = await collect_capacity_metrics(db)
            now = datetime.now(timezone.utc)
            due = [
                (code, message)
                for code, message in evaluate_capacity_alerts(metrics)
                if (now - last_alert_at.get(code, datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
                > ALERT_COOLDOWN_SECONDS
            ]
            if due:
                await send_telegram_alert("⚠️ إنذار سعة مبكر\n\n" + "\n\n".join(message for _, message in due))
                for code, _ in due:
                    last_alert_at[code] = now
                log_event(
                    log,
                    logging.WARNING,
                    "Capacity watchdog alerts sent.",
                    event="capacity_alert",
                    codes=",".join(code for code, _ in due),
                    queue_depth=metrics.get("queue_depth"),
                    oldest_queued_seconds=int(metrics.get("oldest_queued_seconds") or 0),
                )
            digest_date = now.strftime("%Y-%m-%d")
            if now.hour == DIGEST_HOUR_UTC and digest_date != last_digest_date:
                async with session_factory() as db:
                    digest = await collect_daily_digest(db)
                await send_telegram_alert(format_daily_digest(digest))
                last_digest_date = digest_date
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Capacity watchdog tick failed; continuing.")
        await asyncio.sleep(interval_seconds)
