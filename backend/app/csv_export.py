from __future__ import annotations

import csv
from io import StringIO
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from .db import get_session
from . import models

router = APIRouter()

def _csv_response(filename: str, text: str) -> Response:
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.get("/races.csv")
def races_csv(session: Session = Depends(get_session)):
    rows = session.execute(select(models.Race).order_by(models.Race.race_date.desc())).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_date", "race_timezone"])
    for r in rows:
        w.writerow([r.race_id, r.race_date.isoformat(), r.race_timezone])
    return _csv_response("races.csv", buf.getvalue())

@router.get("/race-parts.csv")
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

@router.get("/participants.csv")
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

@router.get("/timing-events.csv")
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
