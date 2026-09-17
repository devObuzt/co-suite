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

    # The email is looked up either way: whether we may ADOPT that row depends
    # on accounts vouching for the address, but whether the address is already
    # taken decides what we can insert — `users.email` is unique, and creating
    # a second row with it crashes the sign-in.
    email = normalize_email(session.email)
    taken_by = None
    if email:
        taken_by = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        # Only an identifier accounts itself proved may adopt an existing
        # account. Without this, anyone who signs up at accounts claiming
        # somebody's email walks into their suite, brand and connections.
        if session.email_verified:
            found = taken_by

    if not found:
        phone = normalize_phone(session.phone)
        if phone and session.phone_verified:
            found = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()

    if found:
        found.manzuma_user_id = session.user_id
        await db.commit()
        await db.refresh(found)
        return found

    # An address we may not adopt is also an address we may not reuse: the new
    # account gets a placeholder, and the person keeps a way in while the
    # verified identifier is still theirs to prove.
    new_email = email if (email and taken_by is None) else f"{session.user_id}@manzuma.local"

    created = User(
        email=new_email,
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
