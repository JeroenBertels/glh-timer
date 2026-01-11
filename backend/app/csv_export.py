from __future__ import annotations

import csv
from io import StringIO
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from .db import get_session
from . import models
from .auth import admin_required

router = APIRouter()

def _csv_response(filename: str, text: str) -> Response:
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.get("/races.csv", dependencies=[Depends(admin_required)])
def races_csv(session: Session = Depends(get_session)):
    rows = session.execute(select(models.Race).order_by(models.Race.race_date.desc())).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_date", "race_timezone"])
    for r in rows:
        w.writerow([r.race_id, r.race_date.isoformat(), r.race_timezone])
    return _csv_response("races.csv", buf.getvalue())

@router.get("/race-parts.csv", dependencies=[Depends(admin_required)])
def race_parts_csv(race_id: str | None = None, session: Session = Depends(get_session)):
    q = select(models.RacePart).order_by(models.RacePart.race_id.asc(), models.RacePart.id.asc())
    if race_id:
        q = q.where(models.RacePart.race_id == race_id)
    rows = session.execute(q).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_part_id", "name", "time_event_type"])
    for p in rows:
        w.writerow([p.race_id, p.race_part_id, p.name, p.time_event_type])
    return _csv_response("race_parts.csv", buf.getvalue())

@router.get("/participants.csv", dependencies=[Depends(admin_required)])
def participants_csv(race_id: str | None = None, session: Session = Depends(get_session)):
    q = select(models.Participant).order_by(models.Participant.race_id.asc(), models.Participant.participant_id.asc())
    if race_id:
        q = q.where(models.Participant.race_id == race_id)
    rows = session.execute(q).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "participant_id", "firstname", "lastname", "sex", "group_name", "club_name"])
    for p in rows:
        w.writerow([p.race_id, p.participant_id, p.firstname, p.lastname, p.sex, p.group_name, p.club_name])
    return _csv_response("participants.csv", buf.getvalue())

@router.get("/timing-events.csv", dependencies=[Depends(admin_required)])
def timing_events_csv(race_id: str | None = None, session: Session = Depends(get_session)):
    q = select(models.TimingEvent).order_by(models.TimingEvent.race_id.asc(), models.TimingEvent.created_at_utc.asc())
    if race_id:
        q = q.where(models.TimingEvent.race_id == race_id)
    rows = session.execute(q).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_part_id", "participant_id", "duration_seconds", "end_time_utc", "client_timestamp_ms", "created_at_utc"])
    for e in rows:
        w.writerow([
            e.race_id,
            e.race_part_id,
            e.participant_id,
            e.duration_seconds if e.duration_seconds is not None else "",
            e.end_time_utc.isoformat() if e.end_time_utc else "",
            e.client_timestamp_ms if e.client_timestamp_ms is not None else "",
            e.created_at_utc.isoformat() if e.created_at_utc else "",
        ])
    return _csv_response("timing_events.csv", buf.getvalue())


@router.get("/results.csv", dependencies=[Depends(admin_required)])
def results_csv(
    race_id: str,
    race_part_id: str,
    session: Session = Depends(get_session),
):
    """Export the computed results table for a race part (including OVERALL splits)."""
    from . import services as _services

    race = _services.get_race(session, race_id)
    part = _services.get_race_part(session, race_id, race_part_id)
    if not race or not part:
        return _csv_response("results.csv", "")

    rows = _services.get_results(session, race_id, race_part_id)

    # For OVERALL we want stable split columns for each non-overall part
    non_overall_parts = [p for p in _services.list_race_parts(session, race_id) if p.time_event_type != "overall"]

    buf = StringIO()
    w = csv.writer(buf)

    if part.race_part_id == "OVERALL":
        header = ["bib", "name", "sex", "group", "club"]
        header += [p.race_part_id for p in non_overall_parts]
        header += ["total", "note"]
        w.writerow(header)
        for r in rows:
            row = [r.bib, r.name, r.sex, r.group, r.club]
            for p in non_overall_parts:
                row.append((r.splits or {}).get(p.race_part_id, ""))
            row += [r.duration_str, r.note]
            w.writerow(row)
    else:
        w.writerow(["bib", "name", "sex", "group", "club", "duration", "duration_seconds", "note"])
        for r in rows:
            w.writerow([r.bib, r.name, r.sex, r.group, r.club, r.duration_str, r.duration_seconds or "", r.note])

    safe_part = part.race_part_id.replace(" ", "_")
    return _csv_response(f"results_{safe_part}.csv", buf.getvalue())
