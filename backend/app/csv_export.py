from __future__ import annotations

import csv
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from . import models
from .auth import admin_required, staff_required, assert_can_access_race

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

@router.get("/race-parts.csv")
def race_parts_csv(
    race_id: str | None = None,
    user=Depends(staff_required),
    session: Session = Depends(get_session),
):
    if user.role == "organizer":
        race_id = race_id or user.race_id
        if not race_id:
            raise HTTPException(status_code=400, detail="Organizer is not linked to a race")
        assert_can_access_race(user, race_id)
    q = select(models.RacePart).order_by(models.RacePart.race_id.asc(), models.RacePart.id.asc())
    if race_id:
        q = q.where(models.RacePart.race_id == race_id)
    rows = session.execute(q).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_part_id", "name", "time_event_type"])
    for r in rows:
        w.writerow([r.race_id, r.race_part_id, r.name, r.time_event_type])
    return _csv_response("race-parts.csv", buf.getvalue())

@router.get("/participants.csv")
def participants_csv(
    race_id: str | None = None,
    user=Depends(staff_required),
    session: Session = Depends(get_session),
):
    if user.role == "organizer":
        race_id = race_id or user.race_id
        if not race_id:
            raise HTTPException(status_code=400, detail="Organizer is not linked to a race")
        assert_can_access_race(user, race_id)

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
def timing_events_csv(
    race_id: str | None = None,
    user=Depends(staff_required),
    session: Session = Depends(get_session),
):
    if user.role == "organizer":
        race_id = race_id or user.race_id
        if not race_id:
            raise HTTPException(status_code=400, detail="Organizer is not linked to a race")
        assert_can_access_race(user, race_id)

    q = select(models.TimingEvent).order_by(models.TimingEvent.created_at_utc.asc())
    if race_id:
        q = q.where(models.TimingEvent.race_id == race_id)
    rows = session.execute(q).scalars().all()
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["race_id", "race_part_id", "participant_id", "duration_seconds", "end_time_utc", "client_timestamp_ms", "created_at_utc"])
    for ev in rows:
        w.writerow([
            ev.race_id,
            ev.race_part_id,
            ev.participant_id,
            ev.duration_seconds,
            ev.end_time_utc.isoformat() if ev.end_time_utc else "",
            ev.client_timestamp_ms or "",
            ev.created_at_utc.isoformat() if ev.created_at_utc else "",
        ])
    return _csv_response("timing-events.csv", buf.getvalue())

@router.get("/results.csv")
def results_csv(
    race_id: str,
    race_part_id: str,
    user=Depends(staff_required),
    session: Session = Depends(get_session),
):
    assert_can_access_race(user, race_id)
    from . import services as _services

    table = _services.get_results(session, race_id, race_part_id)
    buf = StringIO()
    w = csv.writer(buf)

    # overall includes splits columns
    if race_part_id == "OVERALL":
        # infer split columns from first row
        part_ids = []
        if table:
            part_ids = list(table[0].splits.keys())
        w.writerow(["bib", "name", "sex", "group", "club", "overall", *part_ids, "note"])
        for r in table:
            w.writerow([r.bib, r.name, r.sex, r.group, r.club, r.duration_str, *[r.splits.get(pid,"") for pid in part_ids], r.note])
    else:
        w.writerow(["bib", "name", "sex", "group", "club", "time", "note"])
        for r in table:
            w.writerow([r.bib, r.name, r.sex, r.group, r.club, r.duration_str, r.note])

    safe_race = race_id.replace(" ", "_")
    return _csv_response(f"results_{safe_race}_{race_part_id}.csv", buf.getvalue())
