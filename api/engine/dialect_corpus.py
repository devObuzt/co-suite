"""Dialect learning corpus — stores Claude's voiceover output + your corrections.

Every time you reply to a Telegram voiceover-approval message with corrected
text, that pair gets appended to `data/dialect_corpus.jsonl`. Claude then
receives the latest entries as in-context examples when generating new
voiceovers, so the system progressively learns YOUR exact pronunciation of
1948-Palestinian dialect over time.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

log = logging.getLogger(__name__)

CORPUS_PATH = DATA_DIR / "dialect_corpus.jsonl"
MAX_PROMPT_EXAMPLES = 30


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def add_correction(
    original: str,
    corrected: str,
    post_id: str | None = None,
    notes: str | None = None,
) -> None:
    """Append one (Claude-output → user-corrected) pair to the corpus."""
    if not corrected.strip():
        return
    entry = {
        "timestamp": _now_iso(),
        "original": original.strip(),
        "corrected": corrected.strip(),
        "post_id": post_id,
        "notes": notes,
    }
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log.info("Added dialect correction to corpus (post=%s)", post_id or "?")


def load_corrections(limit: int = MAX_PROMPT_EXAMPLES) -> list[dict]:
    """Read the most-recent `limit` corrections (newest first)."""
    if not CORPUS_PATH.exists():
        return []
    out: list[dict] = []
    with CORPUS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Newest first, capped
    return list(reversed(out))[:limit]


def format_for_prompt(limit: int = MAX_PROMPT_EXAMPLES) -> str:
    """Return a markdown-ish block to inject into Claude's system prompt.

    Empty string if the corpus is empty.
    """
    items = load_corrections(limit=limit)
    if not items:
        return ""
    lines = [
        "",
        "— تصحيحات سابقة من المستخدم (تعلّم منها بدقّة):",
        "هذه أمثلة من حالات Claude كتب فيها التشكيل غلط والمستخدم صحّحه. النمط الذي صحّحه هو القاعدة الصحيحة:",
        "",
    ]
    for it in items:
        orig = it.get("original", "").strip()
        corr = it.get("corrected", "").strip()
        if not corr:
            continue
        if orig:
            lines.append(f"❌ {orig}")
            lines.append(f"✅ {corr}")
        else:
            lines.append(f"✅ {corr}  (تشكيل مرجعي صحيح)")
        if it.get("notes"):
            lines.append(f"   ملاحظة: {it['notes']}")
        lines.append("")
    lines.append("طبّق هذه التصحيحات على كل voiceover_ar_tashkeel من الآن فصاعداً.")
    return "\n".join(lines)
