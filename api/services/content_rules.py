"""User-taught content rules: deterministic replacements + prompt guidelines.

Rules live in ``brand.content_rules`` as a list of dicts. Two shapes:
- Replace rule:   {"from": "شيقل", "to": "شيكل", ...}       — enforced in code after generation
- Guideline rule: {"text": "لا تستخدم إيموجي بالعناوين", ...} — injected into generation prompts

Legacy entries (plain strings or {text} dicts from regenerate feedback /
profile edits) are treated as guidelines.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..core.config import settings
from ..core.llm_client import call_text_ai

log = logging.getLogger(__name__)

MAX_RULES = 50
MAX_RULE_TEXT_CHARS = 300

RULE_TYPE_REPLACE = "replace"
RULE_TYPE_GUIDELINE = "guideline"


def _clean(value: Any, limit: int = MAX_RULE_TEXT_CHARS) -> str:
    return str(value or "").strip()[:limit]


def rule_id(rule: dict[str, Any]) -> str:
    """Stable id derived from rule content, so legacy rules without ids stay addressable."""
    explicit = _clean(rule.get("id"), 40)
    if explicit:
        return explicit
    payload = json.dumps(
        {"text": rule.get("text") or "", "from": rule.get("from") or "", "to": rule.get("to") or ""},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def normalize_content_rule(raw: Any) -> dict[str, Any] | None:
    """Coerce a stored/incoming rule into canonical shape; None when unusable."""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    replace_from = _clean(raw.get("from"))
    replace_to = _clean(raw.get("to"))
    text = _clean(raw.get("text"))
    if replace_from and replace_from != replace_to:
        rule: dict[str, Any] = {
            "type": RULE_TYPE_REPLACE,
            "from": replace_from,
            "to": replace_to,
            "text": text or f'اكتب "{replace_to}" وليس "{replace_from}"',
        }
    elif text:
        rule = {"type": RULE_TYPE_GUIDELINE, "text": text}
    else:
        return None
    rule["source"] = _clean(raw.get("source"), 60) or "manual"
    created_at = _clean(raw.get("created_at"), 60)
    if created_at:
        rule["created_at"] = created_at
    for key in ("post_id",):
        value = _clean(raw.get(key), 80)
        if value:
            rule[key] = value
    rule["id"] = rule_id(raw if raw.get("id") else rule)
    return rule


def normalize_content_rules(raw_rules: Any) -> list[dict[str, Any]]:
    """Normalize + dedupe a rules list, keeping insertion order, capped at MAX_RULES."""
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rules if isinstance(raw_rules, list) else []:
        rule = normalize_content_rule(raw)
        if not rule:
            continue
        marker = rule["id"]
        if marker in seen:
            continue
        seen.add(marker)
        rules.append(rule)
    return rules[-MAX_RULES:]


def brand_content_rules(brand: Any) -> list[dict[str, Any]]:
    if not isinstance(brand, dict):
        return []
    return normalize_content_rules(brand.get("content_rules"))


def replace_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rule for rule in rules if rule.get("type") == RULE_TYPE_REPLACE]


def guideline_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [rule for rule in rules if rule.get("type") == RULE_TYPE_GUIDELINE]


def apply_replace_rules(text: Any, rules: list[dict[str, Any]]) -> Any:
    """Apply deterministic substitutions to a string; non-strings pass through."""
    if not isinstance(text, str) or not text:
        return text
    for rule in replace_rules(rules):
        text = text.replace(rule["from"], rule["to"])
    return text


def apply_replace_rules_to_item(
    item: dict[str, Any],
    rules: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Apply replace rules in-place to the given text fields of a dict."""
    if not replace_rules(rules):
        return item
    for field in fields:
        if isinstance(item.get(field), str):
            item[field] = apply_replace_rules(item[field], rules)
    return item


def format_content_rules_prompt(rules: list[dict[str, Any]], limit: int = 15) -> str:
    """Prompt block listing the user's rules; empty string when there are none.

    Replace rules are included too so the model complies upfront — the code-level
    substitution afterwards is the guarantee, not the only line of defense.
    """
    lines: list[str] = []
    for rule in rules[-limit:]:
        if rule.get("type") == RULE_TYPE_REPLACE:
            lines.append(f'- اكتب دائمًا "{rule["to"]}" وليس "{rule["from"]}".')
        else:
            lines.append(f"- {rule['text']}")
    if not lines:
        return ""
    header = "User content rules (MUST follow in every text you write):"
    return header + "\n" + "\n".join(lines)


def new_rule(
    *,
    text: str = "",
    replace_from: str = "",
    replace_to: str = "",
    source: str = "manual",
) -> dict[str, Any] | None:
    """Build a normalized rule stamped with creation time."""
    return normalize_content_rule(
        {
            "text": text,
            "from": replace_from,
            "to": replace_to,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


# ── Teaching: turn free-text feedback into structured rule suggestions ────────

TEACH_MAX_TOKENS = 1000
TEACH_TIMEOUT_SECONDS = 30

_TEACH_PROMPT = """You convert user feedback about generated marketing content into persistent content rules.

Rule kinds:
- Replace rule: an exact wording/spelling correction that can be applied as find-and-replace.
  Example feedback: "بدل شيقل اكتب شيكل" -> {{"from": "شيقل", "to": "شيكل"}}
- Guideline rule: a style/tone/content instruction that cannot be a simple replacement.
  Example feedback: "بدي النبرة أرسمي وبلا إيموجي" -> {{"text": "استخدم نبرة رسمية ولا تستخدم الإيموجي"}}

Rules:
- Keep each rule short, general, and reusable for all future content (not tied to one post).
- Write guideline text in the same language as the feedback.
- Extract at most 3 rules. If the feedback is a one-off edit with nothing generalizable, return an empty list.
- Return STRICT JSON only: {{"rules": [{{"from": "...", "to": "..."}} or {{"text": "..."}}]}}

User feedback:
{feedback}
{diff_block}"""


def _parse_teach_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


async def suggest_rules_from_feedback(
    feedback: str,
    original: str = "",
    edited: str = "",
) -> list[dict[str, Any]]:
    """Use the fast model to convert feedback (or a before/after edit) into rule suggestions."""
    feedback = _clean(feedback, 1000)
    original = _clean(original, 2000)
    edited = _clean(edited, 2000)
    if not feedback and not (original and edited):
        return []
    diff_block = ""
    if original and edited:
        diff_block = f"\nOriginal text:\n{original}\n\nUser-edited text:\n{edited}\n"
    prompt = _TEACH_PROMPT.format(feedback=feedback or "(none — infer from the edit)", diff_block=diff_block)
    try:
        raw = await call_text_ai(
            provider="anthropic",
            model=settings.anthropic_fast_model,
            max_tokens=TEACH_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            system="Return valid JSON only.",
            timeout=TEACH_TIMEOUT_SECONDS,
        )
        parsed = _parse_teach_json(raw)
        raw_rules = parsed.get("rules") if isinstance(parsed.get("rules"), list) else []
    except Exception as exc:
        log.warning("Content rule suggestion failed: %s", exc)
        raw_rules = []
    if not raw_rules and feedback:
        # Fall back to saving the raw feedback as a guideline so teaching never dead-ends.
        raw_rules = [{"text": feedback}]
    stamped = []
    now = datetime.now(timezone.utc).isoformat()
    for raw_rule in raw_rules[:3]:
        if isinstance(raw_rule, dict):
            raw_rule = {**raw_rule, "source": "taught", "created_at": now}
        stamped.append(raw_rule)
    return normalize_content_rules(stamped)
