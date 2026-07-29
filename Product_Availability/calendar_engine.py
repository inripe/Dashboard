"""Calendar engine — Inripe availability layer.

Pure functions. No Streamlit, no I/O, no globals.

Week buckets are day-of-month, not ISO:
    W1 = day 1-7, W2 = 8-14, W3 = 15-21, W4 = 22 to end of month.
W4 is 7-10 days long depending on the month.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterator

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)}
WEEKS = ["W1", "W2", "W3", "W4"]
_WEEK_FIRST_DAY = {"W1": 1, "W2": 8, "W3": 15, "W4": 22}


class CalendarError(ValueError):
    """Raised when a month or week token cannot be resolved."""


def month_number(month: str) -> int:
    """'March' -> 3. Case-insensitive, tolerates stray whitespace."""
    key = str(month).strip().title()
    if key not in MONTH_NO:
        raise CalendarError(f"unknown month {month!r}")
    return MONTH_NO[key]


def check_week(week: str) -> str:
    """'w2' -> 'W2'. Raises on anything outside W1-W4."""
    key = str(week).strip().upper()
    if key not in _WEEK_FIRST_DAY:
        raise CalendarError(f"unknown week token {week!r}")
    return key


def days_in_month(year: int, month: str) -> int:
    return calendar.monthrange(year, month_number(month))[1]


def bucket_start(year: int, month: str, week: str) -> date:
    """First calendar date of a month/week bucket."""
    return date(year, month_number(month), _WEEK_FIRST_DAY[check_week(week)])


def bucket_end(year: int, month: str, week: str) -> date:
    """Last calendar date of a month/week bucket. W4 runs to month end."""
    m = month_number(month)
    w = check_week(week)
    day = calendar.monthrange(year, m)[1] if w == "W4" else _WEEK_FIRST_DAY[w] + 6
    return date(year, m, day)


def bucket_of(d: date) -> tuple[str, str]:
    """Inverse of bucket_start: a date -> ('March', 'W3')."""
    return MONTHS[d.month - 1], WEEKS[min(3, (d.day - 1) // 7)]


def bucket_days(year: int, month: str, week: str) -> int:
    """Length of a bucket in days. 7 for W1-W3, 7-10 for W4."""
    return (bucket_end(year, month, week) - bucket_start(year, month, week)).days + 1


def iso_week(d: date) -> tuple[int, int]:
    """(iso_year, iso_week) — used for labelling only, never for windows."""
    y, w, _ = d.isocalendar()
    return y, w


def year_days(year: int) -> list[date]:
    """Every date in the year, in order."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def week_grid(year: int, week_len: int = 7) -> list[tuple[int, date, date]]:
    """Fixed reporting grid: (week_no, first_day, last_day) from 1 Jan.

    52 full weeks plus a 1-2 day remainder folded into the last week, so
    every date in the year belongs to exactly one bucket.
    """
    if week_len < 1:
        raise CalendarError("week_len must be positive")
    start, end = date(year, 1, 1), date(year, 12, 31)
    grid: list[tuple[int, date, date]] = []
    cursor, n = start, 1
    while cursor <= end:
        last = min(cursor + timedelta(days=week_len - 1), end)
        grid.append((n, cursor, last))
        cursor, n = last + timedelta(days=1), n + 1
    if len(grid) > 52:
        n_last, first_last, _ = grid[52]
        grid = grid[:52]
        wk, f, _ = grid[-1]
        grid[-1] = (wk, f, end)
    return grid


def week_of(d: date, grid: list[tuple[int, date, date]]) -> int:
    """Which reporting week a date falls in."""
    for n, first, last in grid:
        if first <= d <= last:
            return n
    raise CalendarError(f"{d} outside grid")


def month_spans(year: int) -> Iterator[tuple[str, date, date]]:
    """(month_name, first_day, last_day) for each month."""
    for m in MONTHS:
        n = month_number(m)
        yield m, date(year, n, 1), date(year, n, calendar.monthrange(year, n)[1])
