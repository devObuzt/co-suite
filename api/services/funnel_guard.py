"""Cost cap for startbyconnec: funnel users generate each stage exactly once."""
from fastapi import HTTPException

from ..models.user import User


def block_funnel_regeneration(user: User, *, already_generated: bool) -> None:
    if (user.approval_status or "frozen") == "funnel" and already_generated:
        raise HTTPException(status_code=403, detail="funnel_regeneration_blocked")
