"""Value helpers for the Glassdoor parsers: numbers, text, dates. Pure
functions that tolerate None and junk. Same behaviour as
similarweb/shared.py's helpers of the same name, kept local so the
glassdoor package runs standalone (it is published as its own repo)."""
import html as html_lib
import re


def num(value):
    """int / float / numeric string -> float; bool, junk, NaN -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    try:
        out = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return out if out == out else None


def to_int(value):
    out = num(value)
    return int(round(out)) if out is not None else None


def rounded(value, digits=2):
    out = num(value)
    return round(out, digits) if out is not None else None


def text(value):
    """Whitespace-collapsed, HTML-unescaped string; '' -> None."""
    if value is None:
        return None
    out = " ".join(html_lib.unescape(str(value)).replace("\xa0", " ").split())
    return out or None


def iso_date(value):
    """'2026-08-01T00:00:00+00:00' / '2026-08-01' -> '2026-08-01'; the .NET
    zero date '0001-01-01…' -> None."""
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match or match.group(1) == "0001":
        return None
    return "-".join(match.groups())
