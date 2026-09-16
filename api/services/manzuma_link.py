"""The rules that decide which local row a Manzuma session belongs to.

Pure on purpose: every branch here is a decision about somebody's account or
somebody's business, and those are the branches worth testing without a
database in the way.
"""
import re
from typing import Optional

from sqlalchemy import select

from ..models.user import User
from .manzuma_accounts import ManzumaOrg, ManzumaSession


def normalize_email(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().lower()
    return cleaned or None


def normalize_phone(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return None
    keep_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    return f"+{digits}" if keep_plus else digits


def approval_for(org: Optional[ManzumaOrg]) -> str:
    """A new person is approved when their business pays for co-Suite.

    The freeze rule does not change — its input does: a subscription instead of
    a manual decision.
    """
    return "approved" if org and org.subscribes_to("cosuite") else "frozen"


def suite_decision(
    linked_suite_id: Optional[str],
    unlinked_owned_suite_ids: list[str],
) -> tuple[str, Optional[str]]:
    """Which suite this business works with.

    Linking is never automatic when there is a choice to get wrong: one unlinked
    suite is an offer the person confirms, more than one is a decision only they
    can make.
    """
    if linked_suite_id:
        return ("use", linked_suite_id)
    if len(unlinked_owned_suite_ids) == 1:
        return ("offer_link", unlinked_owned_suite_ids[0])
    return ("create", None)


async def resolve_user(db, session: ManzumaSession, org: Optional[ManzumaOrg]) -> User:
    """The local row for this Manzuma person, adopting a legacy one if it is theirs.

    Order matters: the explicit link first, then email, then phone. Someone who
    signed up here years ago with the same email keeps their suites, their
    history and their approval status — they just stop having a password.
    """
    found = (
        await db.execute(select(User).where(User.manzuma_user_id == session.user_id))
    ).scalar_one_or_none()
    if found:
        return found

    # Only an identifier accounts itself proved may adopt an existing account.
    # Without this, anyone who signs up at accounts claiming someone else's
    # email walks into that person's suite, their brand and their connections.
    email = normalize_email(session.email)
    if email and session.email_verified:
        found = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if not found:
        phone = normalize_phone(session.phone)
        if phone and session.phone_verified:
            found = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()

    if found:
        found.manzuma_user_id = session.user_id
        await db.commit()
        await db.refresh(found)
        return found

    created = User(
        email=email or f"{session.user_id}@manzuma.local",
        hashed_password="",
        full_name=session.name or email or "Manzuma user",
        phone=normalize_phone(session.phone),
    )
    created.manzuma_user_id = session.user_id
    created.approval_status = approval_for(org)
    created.is_verified = bool(session.email_verified or session.phone_verified)
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created
