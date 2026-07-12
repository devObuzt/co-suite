"""Phone normalization for the startbyconnec funnel (Israeli-default).

The same person must map to the same lead whether they type 052-1234567,
0521234567, +972521234567 or 972521234567.
"""
import re

_DIGITS = re.compile(r"\d+")


def normalize_phone(raw: str | None) -> str | None:
    """Return a canonical +<countrycode><number> form, or None if unusable.

    Rules (owner decision — Israeli default):
    - strip everything but digits (a leading + is remembered)
    - 05Xxxxxxxx (10 digits)  -> +9725Xxxxxxxx
    - 9725... / 009725...     -> +9725...
    - other international with explicit + and >= 9 digits -> +digits
    - anything with fewer than 9 digits -> None
    """
    if not raw:
        return None
    raw = raw.strip()
    had_plus = raw.startswith("+")
    digits = "".join(_DIGITS.findall(raw))
    if digits.startswith("00"):
        digits = digits[2:]
        had_plus = True
    if not digits or len(digits) < 9:
        return None
    if digits.startswith("972"):
        rest = digits[3:].lstrip("0") if digits[3:4] == "0" else digits[3:]
        return f"+972{rest}" if len(rest) >= 8 else None
    if digits.startswith("0") and len(digits) == 10:
        return f"+972{digits[1:]}"
    if had_plus:
        return f"+{digits}"
    # 9-digit local without leading 0 (e.g. 521234567)
    if len(digits) == 9 and digits.startswith("5"):
        return f"+972{digits}"
    return None
