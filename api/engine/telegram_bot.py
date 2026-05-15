"""Telegram approval bot.

Two roles:
1. `send_for_approval(post_id)` — called by the orchestrator after a post is generated.
   Pushes the media + caption with inline approve/reject buttons to the configured chat.
2. `run_bot()` — long-running listener that responds to button presses, moves posts
   between pending/approved/rejected, and handles caption edits via /edit command.
"""
import asyncio
import html
import json
import logging
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import dialect_corpus, posts_bank, scheduler
from .config import (
    BRAND,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sending posts for approval
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape user-supplied text for Telegram HTML parse mode."""
    return html.escape(text or "", quote=False)


def _format_caption_for_telegram(post: dict) -> str:
    division = BRAND["divisions"].get(post["division"], {}).get("name_ar", post["division"])
    hashtags = json.loads(post.get("hashtags") or "[]")
    hashtag_str = " ".join(hashtags) if hashtags else ""

    caption_body = _esc(post.get("caption", ""))
    # Telegram caption hard limit is 1024 chars — trim safely.
    if len(caption_body) > 700:
        caption_body = caption_body[:697] + "..."

    format_labels = {
        "video": "ريل 🎬",
        "carousel": "كاروسيل 🎠",
        "image": "صورة 🖼",
    }
    fmt_label = format_labels.get(post["format"], "صورة 🖼")

    lines = [
        "🆕 <b>بوست جديد للموافقة</b>",
        "",
        f"🏷 <b>القسم:</b> {_esc(division)}",
        f"🎯 <b>الهدف:</b> {_esc(post.get('goal', ''))}",
        f"📱 <b>الشكل:</b> {fmt_label}",
        "",
        "📝 <b>الكابشن:</b>",
        caption_body,
    ]
    if hashtag_str:
        lines += ["", _esc(hashtag_str)]
    lines += ["", f"<i>ID: <code>{_esc(post['id'])}</code></i>"]
    return "\n".join(lines)


def _approval_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ موافق", callback_data=f"approve:{post_id}"),
                InlineKeyboardButton("❌ ارفض", callback_data=f"reject:{post_id}"),
            ],
            [
                InlineKeyboardButton("🔄 أعد التوليد", callback_data=f"regen:{post_id}"),
            ],
        ]
    )


async def _send_for_approval_async(post_id: str) -> int | None:
    """Send the post media + caption + buttons to the configured Telegram chat.

    Returns the Telegram message_id of the message carrying the buttons.
    For carousels: sends all photos as a media group (no buttons), then a
    separate message with caption + buttons."""
    post = posts_bank.get_post(post_id)
    if not post:
        log.error("send_for_approval: post %s not found", post_id)
        return None

    media_paths = posts_bank.get_media_paths(post)
    if not media_paths or not all(p.exists() for p in media_paths):
        log.error("send_for_approval: missing media for post %s", post_id)
        return None

    bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build().bot
    caption = _format_caption_for_telegram(post)
    keyboard = _approval_keyboard(post_id)
    fmt = post["format"]

    if fmt == "video":
        with open(media_paths[0], "rb") as f:
            msg = await bot.send_video(
                chat_id=TELEGRAM_CHAT_ID,
                video=InputFile(f),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                supports_streaming=True,
            )
    elif fmt == "carousel":
        # Telegram media groups don't support inline keyboards on individual items.
        # Strategy: send the slides as a media group, then a follow-up message
        # carrying the caption + approve/reject buttons.
        # Reading bytes up-front avoids file-handle / multipart issues with PTB.
        media_group = []
        for p in media_paths[:10]:
            with open(p, "rb") as f:
                media_group.append(InputMediaPhoto(media=f.read()))
        log.info("Sending media group of %d slides for post %s…", len(media_group), post_id)
        try:
            await bot.send_media_group(chat_id=TELEGRAM_CHAT_ID, media=media_group)
        except Exception as e:
            log.exception("send_media_group failed for post %s: %s", post_id, e)
            raise
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:  # single image
        with open(media_paths[0], "rb") as f:
            msg = await bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=InputFile(f),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    posts_bank.update_post(post_id, telegram_message_id=msg.message_id)
    log.info("Sent post %s for approval (telegram msg %s)", post_id, msg.message_id)
    return msg.message_id


def send_for_approval(post_id: str) -> int | None:
    """Sync wrapper around the async sender."""
    return asyncio.run(_send_for_approval_async(post_id))


# ---------------------------------------------------------------------------
# Voiceover (text-only) approval — runs BEFORE Veo 3 is invoked
# ---------------------------------------------------------------------------

def _vo_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ موافق — ولّد الفيديو", callback_data=f"vo_approve:{post_id}"),
            ],
            [
                InlineKeyboardButton("❌ ارفض الفكرة", callback_data=f"vo_reject:{post_id}"),
            ],
        ]
    )


def _format_vo_message(post: dict, idea: dict) -> str:
    division = BRAND["divisions"].get(post["division"], {}).get("name_ar", post["division"])
    topic = post.get("topic", "")
    vo_plain = idea.get("voiceover_ar", "")
    vo_tashkeel = idea.get("voiceover_ar_tashkeel", "")
    vo_phonetic = idea.get("voiceover_phonetic_en", "")
    music = idea.get("music_style", "")
    sfx = idea.get("sfx_notes", "")

    lines = [
        "🎙 <b>موافقة على نص الـ Voiceover</b>",
        "",
        f"🏷 <b>القسم:</b> {_esc(division)}",
        f"💡 <b>الفكرة:</b> {_esc(topic)}",
        "",
        "<b>النص بتشكيل (هاد اللي رح ينطقه Veo):</b>",
        f"<code>{_esc(vo_tashkeel or vo_plain)}</code>",
    ]
    if vo_phonetic:
        lines += ["", f"<b>النطق اللاتيني:</b>", f"<i>{_esc(vo_phonetic)}</i>"]
    if music or sfx:
        lines.append("")
        if music:
            lines.append(f"🎵 <b>موسيقى:</b> {_esc(music)}")
        if sfx:
            lines.append(f"🔊 <b>مؤثرات:</b> {_esc(sfx)}")
    lines += [
        "",
        "─────",
        "💬 <b>للتعديل:</b> رد على هذه الرسالة بالنص الصحيح (مع التشكيل المظبوط) — رح أتعلم منه وأبعتلك نسخة جديدة.",
        "",
        f"<i>ID: <code>{_esc(post['id'])}</code></i>",
    ]
    return "\n".join(lines)


async def _send_voiceover_for_approval_async(post_id: str) -> int | None:
    post = posts_bank.get_post(post_id)
    if not post:
        log.error("send_voiceover_for_approval: post %s not found", post_id)
        return None
    meta_path = Path(post["folder"]) / "meta.json"
    if not meta_path.exists():
        log.error("meta.json not found for %s", post_id)
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        idea = json.load(f)

    bot = Application.builder().token(TELEGRAM_BOT_TOKEN).build().bot
    msg = await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=_format_vo_message(post, idea),
        parse_mode=ParseMode.HTML,
        reply_markup=_vo_keyboard(post_id),
    )
    posts_bank.update_post(post_id, telegram_message_id=msg.message_id)
    log.info("Sent voiceover %s for approval (telegram msg %s)", post_id, msg.message_id)
    return msg.message_id


def send_voiceover_for_approval(post_id: str) -> int | None:
    """Sync wrapper — fires off a Telegram message asking to approve the VO."""
    return asyncio.run(_send_voiceover_for_approval_async(post_id))


# ---------------------------------------------------------------------------
# Bot listener (run as a long-lived process)
# ---------------------------------------------------------------------------

async def _generate_video_in_background(post_id: str, application: Application) -> None:
    """Run the (synchronous) Veo 3 generator in a thread + send result on completion."""
    from .video_generator import generate_video
    post = posts_bank.get_post(post_id)
    if not post:
        return
    folder = Path(post["folder"])
    meta_path = folder / "meta.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        idea = json.load(f)

    bot = application.bot
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                f"🎬 جاري توليد الفيديو… <code>{_esc(post_id)}</code>\n"
                f"<i>ياخد عادة 1-3 دقايق. رح أبعتلك الفيديو لما يجهز.</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        media_path, cost = await asyncio.to_thread(generate_video, idea, folder)
        posts_bank.set_media_path(post_id, media_path)
        posts_bank.add_cost(post_id, cost)
        posts_bank.update_post(post_id, status="PENDING", format="video")
        await _send_for_approval_async(post_id)
    except Exception as e:
        log.exception("Background Veo 3 generation failed for %s: %s", post_id, e)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"❌ فشل توليد الفيديو لـ <code>{_esc(post_id)}</code>\n{_esc(str(e)[:300])}",
            parse_mode=ParseMode.HTML,
        )
        posts_bank.update_post(post_id, status="FAILED", notes=str(e)[:500])


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    action, _, post_id = data.partition(":")
    post = posts_bank.get_post(post_id)
    if not post:
        try:
            await query.edit_message_text(text="⚠️ هذا البوست لم يعد موجوداً.")
        except Exception:
            await query.message.reply_text("⚠️ هذا البوست لم يعد موجوداً.")
        return

    # --- Voiceover approval flow (text-only, BEFORE Veo 3) ---
    if action == "vo_approve":
        posts_bank.update_post(post_id, status="VO_APPROVED")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"✅ تمت الموافقة على الـ voiceover. جاري توليد الفيديو…\n<code>{_esc(post_id)}</code>",
            parse_mode=ParseMode.HTML,
        )
        # Schedule the Veo 3 call without blocking the bot loop
        asyncio.create_task(_generate_video_in_background(post_id, context.application))
        return
    if action == "vo_reject":
        posts_bank.reject(post_id, reason="voiceover rejected via telegram")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            f"❌ تم رفض الفكرة (قبل توليد أي فيديو).\n<code>{_esc(post_id)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "approve":
        posts_bank.approve(post_id)
        # Assign next available publishing slot
        try:
            slot = scheduler.schedule_post(post_id)
            when = scheduler.format_local(slot)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"✅ <b>تمت الموافقة</b>\n"
                f"📅 <b>سيُنشر:</b> {_esc(when)}\n"
                f"<code>{_esc(post_id)}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.exception("Scheduling failed for %s: %s", post_id, e)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"✅ تمت الموافقة لكن فشل الجدولة:\n{_esc(str(e))}\n<code>{_esc(post_id)}</code>",
                parse_mode=ParseMode.HTML,
            )
    elif action == "reject":
        posts_bank.reject(post_id, reason="rejected via telegram")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"❌ تم الرفض.\n<code>{_esc(post_id)}</code>",
            parse_mode=ParseMode.HTML,
        )
    elif action == "regen":
        # Mark for regeneration — the orchestrator will pick this up on next run.
        posts_bank.update_post(post_id, status="REGEN_REQUESTED")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"🔄 سيتم إعادة توليد هذا البوست في الجولة القادمة.\n<code>{_esc(post_id)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def _on_edit_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/edit <post_id> <new caption>"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "الاستخدام: <code>/edit POST_ID النص الجديد</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    post_id = context.args[0]
    new_caption = " ".join(context.args[1:])
    post = posts_bank.get_post(post_id)
    if not post:
        await update.message.reply_text(
            f"⚠️ ما لقيت البوست <code>{_esc(post_id)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    posts_bank.update_post(post_id, caption=new_caption)
    await update.message.reply_text(
        f"✏️ تم تعديل الكابشن للبوست <code>{_esc(post_id)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def _on_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = posts_bank.list_pending()
    approved = posts_bank.list_approved()
    scheduled = posts_bank.list_scheduled()
    cost = posts_bank.todays_video_cost()

    lines = [
        "📊 <b>حالة النظام</b>",
        "",
        f"⏳ بانتظار الموافقة: {len(pending)}",
        f"📅 مجدولة للنشر: {len(scheduled)}",
        f"✅ في البنك (موافق عليها): {len(approved)}",
        f"💰 تكلفة الفيديو اليوم: ${cost:.2f}",
    ]

    if scheduled:
        lines += ["", "<b>أقرب 5 بوستات مجدولة:</b>"]
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .config import TIMEZONE
        tz = ZoneInfo(TIMEZONE)
        for p in scheduled[:5]:
            try:
                dt = datetime.fromisoformat(p["scheduled_publish_at"].replace("Z", "+00:00")).astimezone(tz)
                lines.append(f"  • {scheduler.format_local(dt)}  ({p['format']})")
            except Exception:
                pass

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 <b>Connec Content Engine</b>\n\n"
        "أنا هون عشان أبعتلك البوستات قبل ما تنتشر.\n\n"
        "<b>الأوامر:</b>\n"
        "/status — حالة البوستات\n"
        "/edit POST_ID النص الجديد — تعديل كابشن\n"
        "/whoami — معرفة chat_id تبعك",
        parse_mode=ParseMode.HTML,
    )


async def _on_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"chat_id: <code>{update.effective_chat.id}</code>\n"
        f"user_id: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def _on_reply_to_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text replies to bot messages — used for voiceover corrections.

    If the user replies to a voiceover-approval message with corrected Arabic
    text, we treat that as a dialect correction:
      1. Save (original Claude output → user correction) into the dialect corpus.
      2. Update the post's meta.json with the new voiceover_ar_tashkeel.
      3. Re-send the voiceover for approval (with the corrected text).
    """
    msg = update.message
    if not msg or not msg.reply_to_message:
        return
    parent_id = msg.reply_to_message.message_id
    post = posts_bank.find_by_telegram_message_id(parent_id)
    if not post:
        return
    if post.get("status") != "PENDING_VO":
        # Reply was to something other than a VO message — ignore silently.
        return

    correction = (msg.text or "").strip()
    if not correction:
        return

    # Load the idea to capture what Claude originally produced (for the corpus).
    meta_path = Path(post["folder"]) / "meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            idea = json.load(f)
    except Exception:
        idea = {}
    original = idea.get("voiceover_ar_tashkeel") or idea.get("voiceover_ar") or ""

    dialect_corpus.add_correction(
        original=original,
        corrected=correction,
        post_id=post["id"],
        notes="via Telegram reply",
    )
    posts_bank.update_idea_field(post["id"], "voiceover_ar_tashkeel", correction)
    # Also overwrite the plain version so phonetic gets ignored downstream
    posts_bank.update_idea_field(post["id"], "voiceover_ar", correction)
    # Clear the now-stale auto-generated phonetic — better to omit than to mislead
    posts_bank.update_idea_field(post["id"], "voiceover_phonetic_en", "")

    await msg.reply_text(
        "✏️ سجّلت التصحيح في الـ corpus التعليمي. هاي النسخة الجديدة للموافقة:",
        parse_mode=ParseMode.HTML,
    )
    await _send_voiceover_for_approval_async(post["id"])


def run_bot() -> None:
    """Start the long-lived Telegram listener."""
    posts_bank.init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CommandHandler("status", _on_status))
    app.add_handler(CommandHandler("edit", _on_edit_caption))
    app.add_handler(CommandHandler("whoami", _on_whoami))
    app.add_handler(CallbackQueryHandler(_on_callback))
    # Replies to bot messages — used for voiceover corrections
    app.add_handler(
        MessageHandler(
            filters.REPLY & filters.TEXT & ~filters.COMMAND,
            _on_reply_to_message,
        )
    )
    log.info("Telegram bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
