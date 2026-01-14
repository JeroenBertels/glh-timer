from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def parse_duration_to_seconds(value: str) -> int:
    value = value.strip()
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError("Duration must be MM:SS or HH:MM:SS")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def format_seconds(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_time_or_now(
    value: str, race_date: date, race_timezone: str, server_now: datetime
) -> datetime:
    value = value.strip().upper()
    tz = ZoneInfo(race_timezone)
    if value == "NOW":
        return server_now.astimezone(tz)
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Time must be HH:MM:SS or NOW")
    hour, minute, second = (int(part) for part in parts)
    local_dt = datetime.combine(race_date, time(hour=hour, minute=minute, second=second))
    return local_dt.replace(tzinfo=tz)


def compute_best_duration_seconds(
    duration_values: list[int], start_times: list[datetime], end_times: list[datetime]
) -> int | None:
    candidates: list[int] = [value for value in duration_values if value is not None]
    for start in start_times:
        for end in end_times:
            if end >= start:
                candidates.append(int((end - start).total_seconds()))
    if not candidates:
        return None
    return min(candidates)


def classify_race_status(race_date: date, today: date) -> str:
    if race_date < today:
        return "past"
    if race_date > today:
        return "future"
    return "ongoing"

