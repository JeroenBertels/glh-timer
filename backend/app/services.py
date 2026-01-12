from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from . import models
from .settings import settings
from .schemas import RaceCreate, RacePartCreate, ParticipantCreate, TimingEventCreate, StartTimeUpsert

OVERALL_PART_ID = "OVERALL"
OVERALL_PART_NAME = "Overall"

# ---------------------------
# Users / auth
# ---------------------------

_PBKDF2_ITERS = 200_000

def _hash_password(password: str) -> str:
    import os, hashlib, base64
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        _PBKDF2_ITERS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )

def _verify_password(password: str, stored: str) -> bool:
    import hashlib, base64, hmac
    try:
        algo, iters_s, salt_b64, dk_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        dk_expected = base64.b64decode(dk_b64.encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, dk_expected)
    except Exception:
        return False

def ensure_admin_user(session: Session) -> None:
    """Ensure the single admin account (from settings) exists in DB."""
    existing = session.execute(
        select(models.User).where(models.User.username == settings.GLH_ADMIN_USERNAME)
    ).scalar_one_or_none()

    if existing:
        changed = False

        if existing.role != "admin":
            existing.role = "admin"
            existing.race_id = None
            changed = True

        # DEV FRIENDLY: always sync admin password from settings
        existing.password_hash = _hash_password(settings.GLH_ADMIN_PASSWORD)
        changed = True

        if not existing.is_active:
            existing.is_active = 1
            changed = True

        if changed:
            session.commit()
        return

    u = models.User(
        username=settings.GLH_ADMIN_USERNAME,
        password_hash=_hash_password(settings.GLH_ADMIN_PASSWORD),
        role="admin",
        race_id=None,
        is_active=1,
    )
    session.add(u)
    session.commit()

def authenticate_user(session: Session, username: str, password: str) -> Optional[models.User]:
    u = session.execute(select(models.User).where(models.User.username == username)).scalar_one_or_none()
    if not u or not u.is_active:
        return None
    if _verify_password(password, u.password_hash):
        return u
    return None

def create_organizer_user(session: Session, username: str, password: str, race_id: str) -> None:
    if session.execute(select(models.User).where(models.User.username == username)).scalar_one_or_none():
        raise ValueError("Username already exists")
    if not session.get(models.Race, race_id):
        raise ValueError("Race not found")
    u = models.User(
        username=username,
        password_hash=_hash_password(password),
        role="organizer",
        race_id=race_id,
        is_active=1,
    )
    session.add(u)
    session.commit()

def list_users(session: Session) -> list[models.User]:
    return session.execute(select(models.User).order_by(models.User.role.asc(), models.User.username.asc())).scalars().all()


def _parse_date_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def _parse_hms_to_seconds(s: str) -> int:
    s = s.strip()
    if not s:
        raise ValueError("Empty duration")
    # allow "SS", "MM:SS", "HH:MM:SS"
    if re.fullmatch(r"\d+", s):
        return int(s)
    parts = s.split(":")
    if len(parts) == 2:
        mm, ss = parts
        return int(mm) * 60 + int(ss)
    if len(parts) == 3:
        hh, mm, ss = parts
        return int(hh) * 3600 + int(mm) * 60 + int(ss)
    raise ValueError("Invalid duration format. Use seconds, MM:SS, or HH:MM:SS")


def parse_duration(s: str) -> int:
    return _parse_hms_to_seconds(s)

def _format_seconds(sec: Optional[int]) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    hh = sec // 3600
    mm = (sec % 3600) // 60
    ss = sec % 60
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"

def create_race(session: Session, payload: RaceCreate) -> None:
    if session.get(models.Race, payload.race_id):
        raise ValueError("Race already exists")
    race = models.Race(
        race_id=payload.race_id,
        race_date=_parse_date_yyyy_mm_dd(payload.race_date),
        race_timezone=payload.race_timezone,
    )
    session.add(race)
    session.flush()
    # auto create overall part
    overall = models.RacePart(
        race_id=payload.race_id,
        race_part_id=OVERALL_PART_ID,
        name=OVERALL_PART_NAME,
        time_event_type="overall",
    )
    session.add(overall)
    session.commit()

def list_races(session: Session):
    return session.execute(select(models.Race).order_by(models.Race.race_date.desc())).scalars().all()

def get_race(session: Session, race_id: str):
    return session.get(models.Race, race_id)

def create_race_part(session: Session, payload: RacePartCreate) -> None:
    if payload.time_event_type not in ("duration", "end_time"):
        raise ValueError("time_event_type must be duration or end_time")
    # prevent overriding OVERALL
    if payload.race_part_id == OVERALL_PART_ID:
        raise ValueError("Reserved race_part_id")
    # uniqueness
    existing = session.execute(
        select(models.RacePart).where(
            and_(
                models.RacePart.race_id == payload.race_id,
                models.RacePart.race_part_id == payload.race_part_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError("Race part already exists")
    rp = models.RacePart(
        race_id=payload.race_id,
        race_part_id=payload.race_part_id,
        name=payload.name,
        time_event_type=payload.time_event_type,
    )
    session.add(rp)
    session.commit()


def list_race_parts(session: Session, race_id: str):
    return session.execute(
        select(models.RacePart).where(models.RacePart.race_id == race_id).order_by(models.RacePart.id.asc())
    ).scalars().all()

def get_race_part(session: Session, race_id: str, race_part_id: str):
    return session.execute(
        select(models.RacePart).where(and_(models.RacePart.race_id == race_id, models.RacePart.race_part_id == race_part_id))
    ).scalar_one_or_none()

def create_participant(session: Session, payload: ParticipantCreate) -> None:
    existing = session.execute(
        select(models.Participant).where(and_(models.Participant.race_id == payload.race_id, models.Participant.participant_id == payload.participant_id))
    ).scalar_one_or_none()
    if existing:
        raise ValueError("Participant already exists for this race")
    p = models.Participant(
        race_id=payload.race_id,
        participant_id=payload.participant_id,
        firstname=payload.firstname,
        lastname=payload.lastname,
        sex=payload.sex,
        group_name=payload.group_name,
        club_name=payload.club_name,
    )
    session.add(p)
    session.commit()

def list_participants(session: Session, race_id: str):
    return session.execute(
        select(models.Participant).where(models.Participant.race_id == race_id).order_by(models.Participant.participant_id.asc())
    ).scalars().all()

def create_timing_event(session: Session, payload: TimingEventCreate) -> None:
    race = get_race(session, payload.race_id)
    if not race:
        raise ValueError("Race not found")

    part = get_race_part(session, payload.race_id, payload.race_part_id)
    if not part:
        raise ValueError("Race part not found")

    participant = session.execute(
        select(models.Participant).where(
            and_(
                models.Participant.race_id == payload.race_id,
                models.Participant.participant_id == payload.participant_id,
            )
        )
    ).scalar_one_or_none()

    # Auto-create placeholder participant if needed
    if not participant:
        participant = models.Participant(
            race_id=payload.race_id,
            participant_id=payload.participant_id,
            firstname="Unknown",
            lastname=f"Unknown {payload.participant_id}",
            sex="",
            group_name="",
            club_name="",
        )
        session.add(participant)
        session.flush()

    ev = models.TimingEvent(
        race_id=payload.race_id,
        race_part_id=payload.race_part_id,
        participant_id=payload.participant_id,
        race_part_fk=part.id,
        participant_fk=participant.id,
    )

    if part.time_event_type == "duration":
        if not payload.duration:
            raise ValueError("Duration required")
        ev.duration_seconds = parse_duration(payload.duration)
    else:
        # end_time events: store server time as naive local time in race timezone
        tz_name = (race.race_timezone or "UTC")
        end_dt = datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
        ev.end_time_utc = end_dt

    if payload.client_timestamp_ms:
        try:
            ev.client_timestamp_ms = int(payload.client_timestamp_ms)
        except Exception:
            pass

    session.add(ev)
    session.commit()


def upsert_start_time(session: Session, payload: StartTimeUpsert) -> None:
    part = get_race_part(session, payload.race_id, payload.race_part_id)
    if not part:
        raise ValueError("Race part not found")
    if part.time_event_type != "end_time":
        raise ValueError("Start times are only used for end-time race parts")

    group = (payload.group_name or "DEFAULT").strip() or "DEFAULT"
    race = get_race(session, payload.race_id)
    tz_name = (race.race_timezone if race else "UTC")
    start_time_hms_upper = (payload.start_time_hms or "").strip().upper()
    if start_time_hms_upper == "NOW":
        payload.start_time_hms = datetime.now(ZoneInfo(tz_name)).strftime("%H:%M:%S")
    existing = session.execute(
        select(models.RacePartStartTime).where(
            and_(
                models.RacePartStartTime.race_id == payload.race_id,
                models.RacePartStartTime.race_part_id == payload.race_part_id,
                models.RacePartStartTime.group_name == group,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.start_time_hms = payload.start_time_hms
    else:
        row = models.RacePartStartTime(
            race_id=payload.race_id,
            race_part_id=payload.race_part_id,
            group_name=group,
            start_time_hms=payload.start_time_hms,
            race_part_fk=part.id,
        )
        session.add(row)
    session.commit()

def get_start_times(session: Session, race_id: str, race_part_id: str):
    return session.execute(
        select(models.RacePartStartTime).where(
            and_(models.RacePartStartTime.race_id == race_id, models.RacePartStartTime.race_part_id == race_part_id)
        ).order_by(models.RacePartStartTime.group_name.asc())
    ).scalars().all()

@dataclass
class ResultRow:
    bib: str
    name: str
    group: str
    club: str
    sex: str
    duration_seconds: Optional[int]
    duration_str: str
    note: str = ""
    splits: dict[str, str] = field(default_factory=dict)

def _get_start_time_for_group(session: Session, race_id: str, race_part_id: str, group_name: str) -> Optional[time]:
    group = (group_name or "").strip()
    # group-specific first, else DEFAULT
    row = session.execute(
        select(models.RacePartStartTime).where(
            and_(
                models.RacePartStartTime.race_id == race_id,
                models.RacePartStartTime.race_part_id == race_part_id,
                models.RacePartStartTime.group_name == group,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = session.execute(
            select(models.RacePartStartTime).where(
                and_(
                    models.RacePartStartTime.race_id == race_id,
                    models.RacePartStartTime.race_part_id == race_part_id,
                    models.RacePartStartTime.group_name == "DEFAULT",
                )
            )
        ).scalar_one_or_none()
    if not row:
        return None
    try:
        hh, mm, ss = [int(x) for x in row.start_time_hms.split(":")]
        return time(hour=hh, minute=mm, second=ss)
    except Exception:
        return None

def _compute_duration_for_end_time_part(session: Session, race: models.Race, part: models.RacePart, ev: models.TimingEvent, participant: models.Participant) -> tuple[Optional[int], str]:
    if not ev.end_time_utc:
        return None, "No end time"
    st = _get_start_time_for_group(session, race.race_id, part.race_part_id, participant.group_name)
    if not st:
        return None, "Missing start time (set DEFAULT or group start time)"
    # race_date + start_time (interpreted in local timezone only for display; we treat it as same date)
    # store end_time_utc in naive UTC; we'll just compute duration using naive datetimes (sufficient for local timing)
    start_dt = datetime.combine(race.race_date, st)
    end_dt = ev.end_time_utc  # naive but captured from server clock
    # If end_dt appears before start_dt (e.g. server clock in UTC and start_dt local), fallback to pure delta using "now"
    # We'll assume server clock and start time are in same local clock when running locally.
    delta = end_dt - start_dt
    if delta.total_seconds() < 0:
        return None, "End time < start time (check server clock/timezone)"
    return int(delta.total_seconds()), ""

def get_results(session: Session, race_id: str, race_part_id: str) -> list[ResultRow]:
    race = get_race(session, race_id)
    part = get_race_part(session, race_id, race_part_id)
    if not race or not part:
        return []

    participants = list_participants(session, race_id)
    # best timing event per participant depending on part type
    rows: list[ResultRow] = []
    splits_map: dict[str, dict[str, str]] = {}

    if part.time_event_type == "overall":
        # Sum best durations across all non-overall parts
        non_overall_parts = session.execute(
            select(models.RacePart).where(and_(models.RacePart.race_id == race_id, models.RacePart.time_event_type != "overall"))
        ).scalars().all()
        # Precompute best durations per (part, participant)
        best = {}
        for p in non_overall_parts:
            best[p.race_part_id] = _best_durations_for_part(session, race, p, participants)
        for participant in participants:
            splits: dict[str, str] = {}
            total = 0
            missing = []
            for p in non_overall_parts:
                d = best[p.race_part_id].get(participant.participant_id)
                splits[p.race_part_id] = _format_seconds(d) if d is not None else ""
                if d is None:
                    missing.append(p.name)
                else:
                    total += d
            splits_map[participant.participant_id] = splits
            note = ""
            total_val = None
            if non_overall_parts and missing:
                note = "Missing: " + ", ".join(missing)
            elif non_overall_parts:
                total_val = total
            rows.append(
                ResultRow(
                    bib=participant.participant_id,
                    name=f"{participant.firstname} {participant.lastname}",
                    group=participant.group_name or "",
                    club=participant.club_name or "",
                    sex=participant.sex or "",
                    duration_seconds=total_val,
                    duration_str=_format_seconds(total_val),
                    note=note,
                splits=splits_map.get(participant.participant_id, {}),
                )
            )
        # sort by total duration (None last)
        rows.sort(key=lambda r: (r.duration_seconds is None, r.duration_seconds or 10**12, r.bib))
        return rows

    best_map = _best_durations_for_part(session, race, part, participants)

    for participant in participants:
        d = best_map.get(participant.participant_id)
        note = ""
        if d is None:
            # maybe there is an event but missing start time etc; detect
            if part.time_event_type == "end_time":
                ev = _best_event_for_end_time(session, race_id, race_part_id, participant.participant_id)
                if ev and ev.end_time_utc:
                    _, note = _compute_duration_for_end_time_part(session, race, part, ev, participant)
        rows.append(
            ResultRow(
                bib=participant.participant_id,
                name=f"{participant.firstname} {participant.lastname}",
                group=participant.group_name or "",
                club=participant.club_name or "",
                sex=participant.sex or "",
                duration_seconds=d,
                duration_str=_format_seconds(d),
                note=note,
                splits=splits_map.get(participant.participant_id, {}),
            )
        )
    rows.sort(key=lambda r: (r.duration_seconds is None, r.duration_seconds or 10**12, r.bib))
    return rows
def _best_event_for_duration(session: Session, race_id: str, race_part_id: str, bib: str) -> Optional[models.TimingEvent]:
    return session.execute(
        select(models.TimingEvent)
        .where(
            and_(
                models.TimingEvent.race_id == race_id,
                models.TimingEvent.race_part_id == race_part_id,
                models.TimingEvent.participant_id == bib,
                models.TimingEvent.duration_seconds.is_not(None),
            )
        )
        .order_by(models.TimingEvent.duration_seconds.asc(), models.TimingEvent.created_at_utc.asc())
        .limit(1)
    ).scalar_one_or_none()

def _best_event_for_end_time(session: Session, race_id: str, race_part_id: str, bib: str) -> Optional[models.TimingEvent]:
    return session.execute(
        select(models.TimingEvent)
        .where(
            and_(
                models.TimingEvent.race_id == race_id,
                models.TimingEvent.race_part_id == race_part_id,
                models.TimingEvent.participant_id == bib,
                models.TimingEvent.end_time_utc.is_not(None),
            )
        )
        .order_by(models.TimingEvent.end_time_utc.asc(), models.TimingEvent.created_at_utc.asc())
        .limit(1)
    ).scalar_one_or_none()

def _best_durations_for_part(session: Session, race: models.Race, part: models.RacePart, participants: list[models.Participant]) -> dict[str, Optional[int]]:
    out: dict[str, Optional[int]] = {}
    for participant in participants:
        if part.time_event_type == "duration":
            ev = _best_event_for_duration(session, race.race_id, part.race_part_id, participant.participant_id)
            out[participant.participant_id] = ev.duration_seconds if ev else None
        elif part.time_event_type == "end_time":
            ev = _best_event_for_end_time(session, race.race_id, part.race_part_id, participant.participant_id)
            if not ev:
                out[participant.participant_id] = None
            else:
                d, _note = _compute_duration_for_end_time_part(session, race, part, ev, participant)
                out[participant.participant_id] = d
        else:
            out[participant.participant_id] = None
    return out


def import_participants_csv(session: Session, race_id: str, csv_text: str) -> tuple[int, int]:
    """Import participants for a race from CSV text. Returns (added, skipped)."""
    import csv as _csv
    from io import StringIO
    reader = _csv.DictReader(StringIO(csv_text))
    added = 0
    skipped = 0

    for row in reader:
        pid = (row.get("participant_id") or row.get("bib") or row.get("bib_number") or "").strip()
        firstname = (row.get("firstname") or row.get("first_name") or row.get("voornaam") or "").strip()
        lastname = (row.get("lastname") or row.get("last_name") or row.get("achternaam") or "").strip()
        if not pid:
            skipped += 1
            continue
        if not firstname:
            firstname = "Unknown"
        if not lastname:
            lastname = f"Unknown {pid}"

        sex = (row.get("sex") or row.get("m/f") or row.get("gender") or "").strip()
        group_name = (row.get("group_name") or row.get("group") or row.get("cat") or "").strip()
        club_name = (row.get("club_name") or row.get("club") or "").strip()

        existing = session.execute(
            select(models.Participant).where(and_(models.Participant.race_id == race_id, models.Participant.participant_id == pid))
        ).scalar_one_or_none()
        if existing:
            skipped += 1
            continue

        p = models.Participant(
            race_id=race_id,
            participant_id=pid,
            firstname=firstname,
            lastname=lastname,
            sex=sex,
            group_name=group_name,
            club_name=club_name,
        )
        session.add(p)
        added += 1

    session.commit()
    return added, skipped
