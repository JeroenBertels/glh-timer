from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime
import time
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.db import Base, SessionLocal, get_db, get_engine
from app.models import Organiser, OrganiserRace, Participant, Race, RacePart, TimingEvent
from app.security import hash_password, verify_password
from app.settings import get_settings
from app.utils import (
    classify_race_status,
    compute_best_duration_seconds,
    format_seconds,
    parse_duration_to_seconds,
    parse_time_or_now,
)

settings = get_settings()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["format_seconds"] = format_seconds


def init_db() -> None:
    engine = get_engine()
    last_error: Exception | None = None
    for _ in range(10):
        try:
            Base.metadata.create_all(bind=engine)
            with SessionLocal() as db:
                races = db.scalars(select(Race)).all()
                for race in races:
                    ensure_overall_race_part(db, race.race_id)
                db.commit()
            return
        except Exception as exc:  # pragma: no cover - startup retry
            last_error = exc
            time.sleep(1)
    if last_error:
        raise last_error


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def current_user(request: Request) -> dict | None:
    return request.session.get("user")


def back_context(url: str | None, label: str | None = None) -> dict:
    if not url:
        return {"back_url": None, "back_label": None}
    return {"back_url": url, "back_label": label or "Back"}


def require_admin(request: Request) -> None:
    user = current_user(request)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403)


def require_organiser(request: Request, race_id: str | None = None) -> None:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=403)
    if user.get("role") == "admin":
        return
    if user.get("role") == "organiser":
        if race_id is None:
            return
        if race_id in user.get("race_ids", []):
            return
    raise HTTPException(status_code=403)


def ensure_overall_race_part(db: Session, race_id: str) -> None:
    existing = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == "Overall"
        )
    )
    if existing:
        existing.is_overall = True
        existing.race_order = -1
        return
    overall = RacePart(
        race_id=race_id,
        race_part_id="Overall",
        race_order=-1,
        is_overall=True,
    )
    db.add(overall)


def parse_comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_filter_values(values: list[str] | str | None) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [item.strip() for item in values if item.strip()]
    return parse_comma_list(values)


def race_timezone(race: Race) -> ZoneInfo:
    return ZoneInfo(race.race_timezone)


def parse_duration_field(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return parse_duration_to_seconds(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def parse_time_field(
    value: str | None, race: Race, server_now: datetime
) -> datetime | None:
    if not value:
        return None
    try:
        return parse_time_or_now(value, race.race_date, race.race_timezone, server_now)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def compute_participant_duration(
    db: Session, race: Race, race_part_id: str, participant: Participant
) -> int | None:
    events = db.scalars(
        select(TimingEvent).where(
            TimingEvent.race_id == race.race_id,
            TimingEvent.race_part_id == race_part_id,
            (TimingEvent.participant_id == participant.participant_id)
            | (TimingEvent.group == participant.group),
        )
    ).all()
    duration_values = [
        event.duration_seconds for event in events if event.duration_seconds is not None
    ]
    start_times = [event.start_time for event in events if event.start_time]
    end_times = [event.end_time for event in events if event.end_time]
    return compute_best_duration_seconds(duration_values, start_times, end_times)


def compute_overall_duration(
    db: Session, race: Race, participant: Participant, race_parts: list[RacePart]
) -> int | None:
    total = 0
    for part in race_parts:
        if part.is_overall:
            continue
        duration = compute_participant_duration(db, race, part.race_part_id, participant)
        if duration is None:
            return None
        total += duration
    return total


def build_results(
    db: Session, race: Race, race_part: RacePart, group_filters: list[str], sex_filters: list[str]
) -> list[dict]:
    participants = db.scalars(
        select(Participant)
        .where(Participant.race_id == race.race_id)
        .order_by(Participant.participant_id)
    ).all()
    rows = []
    non_overall_parts = sorted(
        [part for part in race.race_parts if not part.is_overall],
        key=lambda item: item.race_order,
    )
    for participant in participants:
        if group_filters and participant.group not in group_filters:
            continue
        if sex_filters and participant.sex not in sex_filters:
            continue
        if race_part.is_overall:
            duration = compute_overall_duration(db, race, participant, non_overall_parts)
        else:
            duration = compute_participant_duration(db, race, race_part.race_part_id, participant)
        row = {
            "bib": participant.participant_id,
            "name": f"{participant.first_name} {participant.last_name}",
            "group": participant.group,
            "sex": participant.sex,
            "duration": format_seconds(duration) if duration is not None else "DNF",
        }
        if race_part.is_overall:
            per_part = {}
            for part in non_overall_parts:
                part_duration = compute_participant_duration(
                    db, race, part.race_part_id, participant
                )
                per_part[part.race_part_id] = (
                    format_seconds(part_duration) if part_duration is not None else "DNF"
                )
            row["parts"] = per_part
        rows.append(row)
    return rows


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    races = db.scalars(select(Race).order_by(Race.race_date)).all()
    today = date.today()
    race_rows = [
        {"race": race, "status": classify_race_status(race.race_date, today)}
        for race in races
    ]
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "races": race_rows,
            "user": current_user(request),
            **back_context(None),
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None, **back_context("/", "< Races")},
    )


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if username == settings.admin_username and password == settings.admin_password:
        request.session["user"] = {
            "role": "admin",
            "username": username,
            "race_ids": [race.race_id for race in db.scalars(select(Race)).all()],
        }
        return RedirectResponse("/", status_code=303)

    organiser = db.scalar(select(Organiser).where(Organiser.username == username))
    if organiser and verify_password(password, organiser.password_hash):
        race_ids = [link.race_id for link in organiser.races]
        request.session["user"] = {
            "role": "organiser",
            "username": organiser.username,
            "organiser_id": organiser.id,
            "race_ids": race_ids,
        }
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "user": None,
            "error": "Invalid credentials",
            **back_context("/", "< Races"),
        },
        status_code=401,
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/manage/races", response_class=HTMLResponse)
def manage_races(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    races = db.scalars(select(Race).order_by(Race.race_date)).all()
    return templates.TemplateResponse(
        "manage_races.html",
        {
            "request": request,
            "races": races,
            "user": current_user(request),
            **back_context("/", "< Races"),
        },
    )


@app.post("/manage/races")
def create_race(
    request: Request,
    race_id: str = Form(...),
    race_date: str = Form(...),
    race_timezone: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request)
    race = Race(
        race_id=race_id.strip(),
        race_date=date.fromisoformat(race_date),
        race_timezone=race_timezone.strip(),
    )
    db.add(race)
    db.commit()
    ensure_overall_race_part(db, race.race_id)
    db.commit()
    return RedirectResponse("/manage/races", status_code=303)


@app.get("/manage/races/{race_id}/edit", response_class=HTMLResponse)
def edit_race(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_admin(request)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "edit_race.html",
        {
            "request": request,
            "race": race,
            "user": current_user(request),
            **back_context("/manage/races", "< Manage Races"),
        },
    )


@app.post("/manage/races/{race_id}/edit")
def update_race(
    request: Request,
    race_id: str,
    race_date: str = Form(...),
    race_timezone: str = Form(...),
    db: Session = Depends(get_db),
):
    require_admin(request)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    race.race_date = date.fromisoformat(race_date)
    race.race_timezone = race_timezone.strip()
    db.commit()
    return RedirectResponse("/manage/races", status_code=303)


@app.post("/manage/races/{race_id}/delete")
def delete_race(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_admin(request)
    race = db.get(Race, race_id)
    if race:
        db.delete(race)
        db.commit()
    return RedirectResponse("/manage/races", status_code=303)


@app.get("/manage/races/csv", response_class=StreamingResponse)
def download_races_csv(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["race_id", "race_date", "race_timezone"])
    for race in db.scalars(select(Race).order_by(Race.race_date)).all():
        writer.writerow([race.race_id, race.race_date.isoformat(), race.race_timezone])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=races.csv"},
    )


def diff_rows(existing: dict, incoming: dict) -> bool:
    return any(existing.get(key) != value for key, value in incoming.items())


def build_csv_preview(
    incoming_rows: list[dict],
    existing_rows: dict,
) -> dict:
    added = []
    modified = []
    ignored = []
    for row in incoming_rows:
        key = row["_key"]
        if key not in existing_rows:
            added.append(row)
        else:
            if diff_rows(existing_rows[key], row):
                modified.append(row)
            else:
                ignored.append(row)
    return {"added": added, "modified": modified, "ignored": ignored}


@app.post("/manage/races/csv", response_class=HTMLResponse)
def upload_races_csv(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    require_admin(request)
    contents = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(contents))
    incoming_rows = []
    for row in reader:
        if not row.get("race_id"):
            continue
        incoming_rows.append(
            {
                "_key": row["race_id"].strip(),
                "race_id": row["race_id"].strip(),
                "race_date": row.get("race_date", "").strip(),
                "race_timezone": row.get("race_timezone", "").strip(),
            }
        )
    existing_rows = {
        race.race_id: {
            "_key": race.race_id,
            "race_id": race.race_id,
            "race_date": race.race_date.isoformat(),
            "race_timezone": race.race_timezone,
        }
        for race in db.scalars(select(Race)).all()
    }
    preview = build_csv_preview(incoming_rows, existing_rows)
    payload = json.dumps(preview)
    return templates.TemplateResponse(
        "csv_preview.html",
        {
            "request": request,
            "user": current_user(request),
            "title": "Races CSV Preview",
            "preview": preview,
            "apply_url": "/manage/races/csv/apply",
            "payload": payload,
            **back_context("/manage/races", "< Manage Races"),
        },
    )


@app.post("/manage/races/csv/apply")
def apply_races_csv(
    request: Request, payload: str = Form(...), db: Session = Depends(get_db)
):
    require_admin(request)
    preview = json.loads(payload)
    for row in preview.get("added", []):
        race = Race(
            race_id=row["race_id"],
            race_date=date.fromisoformat(row["race_date"]),
            race_timezone=row["race_timezone"],
        )
        db.add(race)
    for row in preview.get("modified", []):
        race = db.get(Race, row["race_id"])
        if race:
            race.race_date = date.fromisoformat(row["race_date"])
            race.race_timezone = row["race_timezone"]
    db.commit()
    for row in preview.get("added", []):
        ensure_overall_race_part(db, row["race_id"])
    db.commit()
    return RedirectResponse("/manage/races", status_code=303)


@app.get("/manage/organisers", response_class=HTMLResponse)
def manage_organisers(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    organisers = db.scalars(select(Organiser).order_by(Organiser.username)).all()
    races = db.scalars(select(Race).order_by(Race.race_date)).all()
    return templates.TemplateResponse(
        "manage_organisers.html",
        {
            "request": request,
            "organisers": organisers,
            "races": races,
            "user": current_user(request),
            **back_context("/", "< Races"),
        },
    )


@app.post("/manage/organisers")
def create_organiser(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    race_ids: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    require_admin(request)
    organiser = Organiser(username=username.strip(), password_hash=hash_password(password))
    db.add(organiser)
    db.flush()
    for race_id in race_ids:
        db.add(OrganiserRace(organiser_id=organiser.id, race_id=race_id))
    db.commit()
    return RedirectResponse("/manage/organisers", status_code=303)


@app.post("/manage/organisers/{organiser_id}/update")
def update_organiser(
    request: Request,
    organiser_id: int,
    password: str = Form(""),
    race_ids: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    require_admin(request)
    organiser = db.get(Organiser, organiser_id)
    if not organiser:
        raise HTTPException(status_code=404)
    if password:
        organiser.password_hash = hash_password(password)
    organiser.races.clear()
    for race_id in race_ids:
        organiser.races.append(OrganiserRace(race_id=race_id))
    db.commit()
    return RedirectResponse("/manage/organisers", status_code=303)


@app.post("/manage/organisers/{organiser_id}/delete")
def delete_organiser(request: Request, organiser_id: int, db: Session = Depends(get_db)):
    require_admin(request)
    organiser = db.get(Organiser, organiser_id)
    if organiser:
        db.delete(organiser)
        db.commit()
    return RedirectResponse("/manage/organisers", status_code=303)


@app.get("/race/{race_id}", response_class=HTMLResponse)
def race_detail(request: Request, race_id: str, db: Session = Depends(get_db)):
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    race_parts = db.scalars(
        select(RacePart)
        .where(RacePart.race_id == race_id)
        .order_by(RacePart.is_overall, RacePart.race_order)
    ).all()
    return templates.TemplateResponse(
        "race.html",
        {
            "request": request,
            "race": race,
            "race_parts": race_parts,
            "user": current_user(request),
            **back_context("/", "< Races"),
        },
    )


@app.get("/race/{race_id}/manage/race-parts", response_class=HTMLResponse)
def manage_race_parts(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    race_parts = db.scalars(
        select(RacePart)
        .where(RacePart.race_id == race_id)
        .order_by(RacePart.is_overall, RacePart.race_order)
    ).all()
    return templates.TemplateResponse(
        "manage_race_parts.html",
        {
            "request": request,
            "race": race,
            "race_parts": race_parts,
            "user": current_user(request),
            **back_context(f"/race/{race_id}", f"< {race_id}"),
        },
    )


@app.post("/race/{race_id}/manage/race-parts")
def create_race_part(
    request: Request,
    race_id: str,
    race_part_id: str = Form(...),
    race_order: int = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    part = RacePart(
        race_id=race_id,
        race_part_id=race_part_id.strip(),
        race_order=race_order,
        is_overall=False,
    )
    db.add(part)
    db.commit()
    ensure_overall_race_part(db, race_id)
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/race-parts", status_code=303)


@app.post("/race/{race_id}/manage/race-parts/{part_id}/delete")
def delete_race_part(request: Request, race_id: str, part_id: int, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    part = db.get(RacePart, part_id)
    if part and not part.is_overall:
        db.delete(part)
        db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/race-parts", status_code=303)


@app.get("/race/{race_id}/manage/race-parts/{part_id}/edit", response_class=HTMLResponse)
def edit_race_part(request: Request, race_id: str, part_id: int, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    part = db.get(RacePart, part_id)
    if not part:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "edit_race_part.html",
        {
            "request": request,
            "race_id": race_id,
            "part": part,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/manage/race-parts", "< Manage Race Parts"),
        },
    )


@app.post("/race/{race_id}/manage/race-parts/{part_id}/edit")
def update_race_part(
    request: Request,
    race_id: str,
    part_id: int,
    race_part_id: str = Form(...),
    race_order: int = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    part = db.get(RacePart, part_id)
    if not part:
        raise HTTPException(status_code=404)
    if not part.is_overall:
        part.race_part_id = race_part_id.strip()
        part.race_order = race_order
    db.commit()
    ensure_overall_race_part(db, race_id)
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/race-parts", status_code=303)


@app.get("/race/{race_id}/manage/race-parts/csv", response_class=StreamingResponse)
def download_race_parts_csv(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["race_part_id", "race_order"])
    for part in db.scalars(
        select(RacePart)
        .where(RacePart.race_id == race_id)
        .order_by(RacePart.is_overall, RacePart.race_order)
    ).all():
        writer.writerow([part.race_part_id, part.race_order])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={race_id}-race-parts.csv"},
    )


@app.post("/race/{race_id}/manage/race-parts/csv", response_class=HTMLResponse)
def upload_race_parts_csv(
    request: Request, race_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    contents = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(contents))
    incoming_rows = []
    for row in reader:
        part_id = row.get("race_part_id", "").strip()
        if not part_id:
            continue
        incoming_rows.append(
            {
                "_key": part_id,
                "race_part_id": part_id,
                "race_order": int(row.get("race_order", "0") or 0),
            }
        )
    existing_rows = {
        part.race_part_id: {
            "_key": part.race_part_id,
            "race_part_id": part.race_part_id,
            "race_order": part.race_order,
        }
        for part in db.scalars(select(RacePart).where(RacePart.race_id == race_id)).all()
    }
    preview = build_csv_preview(incoming_rows, existing_rows)
    for row in preview["modified"] + preview["added"]:
        if row["race_part_id"] == "Overall":
            preview["ignored"].append(row)
    preview["added"] = [row for row in preview["added"] if row["race_part_id"] != "Overall"]
    preview["modified"] = [
        row for row in preview["modified"] if row["race_part_id"] != "Overall"
    ]
    payload = json.dumps(preview)
    return templates.TemplateResponse(
        "csv_preview.html",
        {
            "request": request,
            "user": current_user(request),
            "title": "Race Parts CSV Preview",
            "preview": preview,
            "apply_url": f"/race/{race_id}/manage/race-parts/csv/apply",
            "payload": payload,
            **back_context(f"/race/{race_id}/manage/race-parts", "< Manage Race Parts"),
        },
    )


@app.post("/race/{race_id}/manage/race-parts/csv/apply")
def apply_race_parts_csv(
    request: Request, race_id: str, payload: str = Form(...), db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    preview = json.loads(payload)
    for row in preview.get("added", []):
        db.add(
            RacePart(
                race_id=race_id,
                race_part_id=row["race_part_id"],
                race_order=row["race_order"],
                is_overall=row["race_part_id"] == "Overall",
            )
        )
    for row in preview.get("modified", []):
        part = db.scalar(
            select(RacePart).where(
                RacePart.race_id == race_id, RacePart.race_part_id == row["race_part_id"]
            )
        )
        if part and not part.is_overall:
            part.race_order = row["race_order"]
    db.commit()
    ensure_overall_race_part(db, race_id)
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/race-parts", status_code=303)


@app.get("/race/{race_id}/manage/participants", response_class=HTMLResponse)
def manage_participants(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    participants = db.scalars(
        select(Participant)
        .where(Participant.race_id == race_id)
        .order_by(Participant.participant_id)
    ).all()
    return templates.TemplateResponse(
        "manage_participants.html",
        {
            "request": request,
            "race": race,
            "participants": participants,
            "user": current_user(request),
            **back_context(f"/race/{race_id}", f"< {race_id}"),
        },
    )


@app.post("/race/{race_id}/manage/participants")
def create_participant(
    request: Request,
    race_id: str,
    participant_id: int = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    group: str = Form(...),
    club: str = Form(""),
    sex: str = Form(""),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    participant = Participant(
        race_id=race_id,
        participant_id=participant_id,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        group=group.strip(),
        club=club.strip(),
        sex=sex.strip(),
    )
    db.add(participant)
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/participants", status_code=303)


@app.get("/race/{race_id}/manage/participants/{participant_pk}/edit", response_class=HTMLResponse)
def edit_participant(
    request: Request, race_id: str, participant_pk: int, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    participant = db.get(Participant, participant_pk)
    if not participant:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "edit_participant.html",
        {
            "request": request,
            "race_id": race_id,
            "participant": participant,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/manage/participants", "< Manage Participants"),
        },
    )


@app.post("/race/{race_id}/manage/participants/{participant_pk}/edit")
def update_participant(
    request: Request,
    race_id: str,
    participant_pk: int,
    participant_id: int = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    group: str = Form(...),
    club: str = Form(""),
    sex: str = Form(""),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    participant = db.get(Participant, participant_pk)
    if not participant:
        raise HTTPException(status_code=404)
    participant.participant_id = participant_id
    participant.first_name = first_name.strip()
    participant.last_name = last_name.strip()
    participant.group = group.strip()
    participant.club = club.strip()
    participant.sex = sex.strip()
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/participants", status_code=303)


@app.post("/race/{race_id}/manage/participants/{participant_pk}/delete")
def delete_participant(
    request: Request, race_id: str, participant_pk: int, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    participant = db.get(Participant, participant_pk)
    if participant:
        db.delete(participant)
        db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/participants", status_code=303)


@app.get("/race/{race_id}/manage/participants/csv", response_class=StreamingResponse)
def download_participants_csv(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["participant_id", "first_name", "last_name", "group", "club", "sex"])
    participants = db.scalars(
        select(Participant)
        .where(Participant.race_id == race_id)
        .order_by(Participant.participant_id)
    ).all()
    for participant in participants:
        writer.writerow(
            [
                participant.participant_id,
                participant.first_name,
                participant.last_name,
                participant.group,
                participant.club,
                participant.sex,
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={race_id}-participants.csv"
        },
    )


@app.post("/race/{race_id}/manage/participants/csv", response_class=HTMLResponse)
def upload_participants_csv(
    request: Request, race_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    contents = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(contents))
    incoming_rows = []
    for row in reader:
        participant_id = row.get("participant_id", "").strip()
        if not participant_id:
            continue
        incoming_rows.append(
            {
                "_key": int(participant_id),
                "participant_id": int(participant_id),
                "first_name": row.get("first_name", "").strip(),
                "last_name": row.get("last_name", "").strip(),
                "group": row.get("group", "").strip(),
                "club": row.get("club", "").strip(),
                "sex": row.get("sex", "").strip(),
            }
        )
    existing_rows = {
        participant.participant_id: {
            "_key": participant.participant_id,
            "participant_id": participant.participant_id,
            "first_name": participant.first_name,
            "last_name": participant.last_name,
            "group": participant.group,
            "club": participant.club,
            "sex": participant.sex,
        }
        for participant in db.scalars(
            select(Participant).where(Participant.race_id == race_id)
        ).all()
    }
    preview = build_csv_preview(incoming_rows, existing_rows)
    payload = json.dumps(preview)
    return templates.TemplateResponse(
        "csv_preview.html",
        {
            "request": request,
            "user": current_user(request),
            "title": "Participants CSV Preview",
            "preview": preview,
            "apply_url": f"/race/{race_id}/manage/participants/csv/apply",
            "payload": payload,
            **back_context(
                f"/race/{race_id}/manage/participants", "< Manage Participants"
            ),
        },
    )


@app.post("/race/{race_id}/manage/participants/csv/apply")
def apply_participants_csv(
    request: Request, race_id: str, payload: str = Form(...), db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    preview = json.loads(payload)
    for row in preview.get("added", []):
        db.add(
            Participant(
                race_id=race_id,
                participant_id=row["participant_id"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                group=row["group"],
                club=row.get("club", ""),
                sex=row.get("sex", ""),
            )
        )
    for row in preview.get("modified", []):
        participant = db.scalar(
            select(Participant).where(
                Participant.race_id == race_id,
                Participant.participant_id == row["participant_id"],
            )
        )
        if participant:
            participant.first_name = row["first_name"]
            participant.last_name = row["last_name"]
            participant.group = row["group"]
            participant.club = row.get("club", "")
            participant.sex = row.get("sex", "")
    db.commit()
    return RedirectResponse(f"/race/{race_id}/manage/participants", status_code=303)


@app.get("/race/{race_id}/part/{race_part_id}", response_class=HTMLResponse)
def race_part_results(
    request: Request,
    race_id: str,
    race_part_id: str,
    group: list[str] | None = Query(None),
    sex: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part:
        raise HTTPException(status_code=404)
    group_filters = normalize_filter_values(group)
    sex_filters = normalize_filter_values(sex)
    rows = build_results(db, race, part, group_filters, sex_filters)
    parts = db.scalars(
        select(RacePart)
        .where(RacePart.race_id == race_id)
        .order_by(RacePart.is_overall, RacePart.race_order)
    ).all()
    groups = sorted({p.group for p in race.participants})
    sexes = sorted({p.sex for p in race.participants if p.sex})
    return templates.TemplateResponse(
        "race_part_results.html",
        {
            "request": request,
            "race": race,
            "race_part": part,
            "rows": rows,
            "group_filters": group_filters,
            "sex_filters": sex_filters,
            "parts": parts,
            "groups": groups,
            "sexes": sexes,
            "user": current_user(request),
            **back_context(f"/race/{race_id}", f"< {race_id}"),
        },
    )


@app.get("/race/{race_id}/part/{race_part_id}/manage/timing-events", response_class=HTMLResponse)
def manage_timing_events(
    request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    events = db.scalars(
        select(TimingEvent)
        .where(TimingEvent.race_id == race_id, TimingEvent.race_part_id == race_part_id)
        .order_by(TimingEvent.server_time.desc())
    ).all()
    return templates.TemplateResponse(
        "manage_timing_events.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "events": events,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/part/{race_part_id}", f"< {race_part_id} Results"),
        },
    )


@app.get(
    "/race/{race_id}/part/{race_part_id}/manage/timing-events/{event_id}/edit",
    response_class=HTMLResponse,
)
def edit_timing_event(
    request: Request,
    race_id: str,
    race_part_id: str,
    event_id: int,
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    event = db.get(TimingEvent, event_id)
    if not race or not event:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    duration_value = format_seconds(event.duration_seconds) if event.duration_seconds else ""
    start_value = event.start_time.astimezone(race_timezone(race)).strftime("%H:%M:%S") if event.start_time else ""
    end_value = event.end_time.astimezone(race_timezone(race)).strftime("%H:%M:%S") if event.end_time else ""
    return templates.TemplateResponse(
        "edit_timing_event.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "event": event,
            "duration_value": duration_value,
            "start_value": start_value,
            "end_value": end_value,
            "user": current_user(request),
            **back_context(
                f"/race/{race_id}/part/{race_part_id}/manage/timing-events",
                "< Manage Timing Events",
            ),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/manage/timing-events/{event_id}/edit")
def update_timing_event(
    request: Request,
    race_id: str,
    race_part_id: str,
    event_id: int,
    participant_id: int | None = Form(None),
    group: str | None = Form(None),
    duration: str | None = Form(None),
    start_time: str | None = Form(None),
    end_time: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    event = db.get(TimingEvent, event_id)
    if not race or not event:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    provided = [value for value in [duration, start_time, end_time] if value]
    if len(provided) != 1:
        raise HTTPException(
            status_code=400, detail="Provide exactly one of duration, start, or end"
        )
    server_now = datetime.now(tz=race_timezone(race))
    event.participant_id = participant_id
    event.group = group.strip() if group else None
    event.duration_seconds = parse_duration_field(duration)
    event.start_time = parse_time_field(start_time, race, server_now)
    event.end_time = parse_time_field(end_time, race, server_now)
    db.commit()
    return RedirectResponse(
        f"/race/{race_id}/part/{race_part_id}/manage/timing-events", status_code=303
    )


def create_timing_event(
    db: Session,
    race: Race,
    race_part_id: str,
    participant_id: int | None,
    group: str | None,
    client_time: datetime,
    duration_seconds: int | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> TimingEvent:
    server_now = datetime.now(tz=race_timezone(race))
    event = TimingEvent(
        race_id=race.race_id,
        race_part_id=race_part_id,
        participant_id=participant_id,
        group=group,
        client_time=client_time,
        server_time=server_now,
        duration_seconds=duration_seconds,
        start_time=start_time,
        end_time=end_time,
    )
    db.add(event)
    return event


@app.post("/race/{race_id}/part/{race_part_id}/manage/timing-events")
def create_timing_event_manual(
    request: Request,
    race_id: str,
    race_part_id: str,
    participant_id: int | None = Form(None),
    group: str | None = Form(None),
    duration: str | None = Form(None),
    start_time: str | None = Form(None),
    end_time: str | None = Form(None),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    if not participant_id and not group:
        raise HTTPException(status_code=400, detail="Participant or group required")
    if participant_id and group:
        raise HTTPException(status_code=400, detail="Use either participant or group")
    provided = [value for value in [duration, start_time, end_time] if value]
    if len(provided) != 1:
        raise HTTPException(
            status_code=400, detail="Provide exactly one of duration, start, or end"
        )
    server_now = datetime.now(tz=race_timezone(race))
    duration_seconds = parse_duration_field(duration)
    start_dt = parse_time_field(start_time, race, server_now)
    end_dt = parse_time_field(end_time, race, server_now)
    create_timing_event(
        db,
        race,
        race_part_id,
        participant_id,
        group.strip() if group else None,
        client_time=server_now,
        duration_seconds=duration_seconds,
        start_time=start_dt,
        end_time=end_dt,
    )
    db.commit()
    return RedirectResponse(f"/race/{race_id}/part/{race_part_id}/manage/timing-events", status_code=303)


@app.post("/race/{race_id}/part/{race_part_id}/manage/timing-events/{event_id}/delete")
def delete_timing_event(
    request: Request,
    race_id: str,
    race_part_id: str,
    event_id: int,
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    event = db.get(TimingEvent, event_id)
    if event:
        db.delete(event)
        db.commit()
    return RedirectResponse(f"/race/{race_id}/part/{race_part_id}/manage/timing-events", status_code=303)


@app.get(
    "/race/{race_id}/part/{race_part_id}/manage/timing-events/csv",
    response_class=StreamingResponse,
)
def download_timing_events_csv(
    request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "participant_id",
            "group",
            "client_time",
            "server_time",
            "duration",
            "start_time",
            "end_time",
        ]
    )
    events = db.scalars(
        select(TimingEvent).where(
            TimingEvent.race_id == race_id, TimingEvent.race_part_id == race_part_id
        )
    ).all()
    for event in events:
        writer.writerow(
            [
                event.id,
                event.participant_id or "",
                event.group or "",
                event.client_time.isoformat(),
                event.server_time.isoformat(),
                format_seconds(event.duration_seconds)
                if event.duration_seconds is not None
                else "",
                event.start_time.isoformat() if event.start_time else "",
                event.end_time.isoformat() if event.end_time else "",
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={race_id}-{race_part_id}-timing-events.csv"
        },
    )


@app.post(
    "/race/{race_id}/part/{race_part_id}/manage/timing-events/csv",
    response_class=HTMLResponse,
)
def upload_timing_events_csv(
    request: Request,
    race_id: str,
    race_part_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    contents = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(contents))
    incoming_rows = []
    for row in reader:
        event_id = row.get("id", "").strip()
        incoming_rows.append(
            {
                "_key": int(event_id) if event_id else None,
                "id": int(event_id) if event_id else None,
                "participant_id": int(row["participant_id"]) if row.get("participant_id") else None,
                "group": row.get("group", "").strip() or None,
                "client_time": row.get("client_time", "").strip(),
                "server_time": row.get("server_time", "").strip(),
                "duration": row.get("duration", "").strip(),
                "start_time": row.get("start_time", "").strip(),
                "end_time": row.get("end_time", "").strip(),
            }
        )
    existing_rows = {
        event.id: {
            "_key": event.id,
            "id": event.id,
            "participant_id": event.participant_id,
            "group": event.group,
            "client_time": event.client_time.isoformat(),
            "server_time": event.server_time.isoformat(),
            "duration": format_seconds(event.duration_seconds)
            if event.duration_seconds is not None
            else "",
            "start_time": event.start_time.isoformat() if event.start_time else "",
            "end_time": event.end_time.isoformat() if event.end_time else "",
        }
        for event in db.scalars(
            select(TimingEvent).where(
                TimingEvent.race_id == race_id, TimingEvent.race_part_id == race_part_id
            )
        ).all()
    }
    preview = build_csv_preview(
        [row for row in incoming_rows if row["_key"] is not None], existing_rows
    )
    preview["added"].extend([row for row in incoming_rows if row["_key"] is None])
    payload = json.dumps(preview)
    return templates.TemplateResponse(
        "csv_preview.html",
        {
            "request": request,
            "user": current_user(request),
            "title": "Timing Events CSV Preview",
            "preview": preview,
            "apply_url": f"/race/{race_id}/part/{race_part_id}/manage/timing-events/csv/apply",
            "payload": payload,
            **back_context(
                f"/race/{race_id}/part/{race_part_id}/manage/timing-events",
                "< Manage Timing Events",
            ),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/manage/timing-events/csv/apply")
def apply_timing_events_csv(
    request: Request,
    race_id: str,
    race_part_id: str,
    payload: str = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    preview = json.loads(payload)
    tz = race_timezone(race)
    for row in preview.get("added", []):
        client_time = datetime.fromisoformat(row["client_time"]) if row.get("client_time") else datetime.now(tz=tz)
        server_time = datetime.fromisoformat(row["server_time"]) if row.get("server_time") else datetime.now(tz=tz)
        duration_seconds = parse_duration_to_seconds(row["duration"]) if row.get("duration") else None
        start_time = datetime.fromisoformat(row["start_time"]) if row.get("start_time") else None
        end_time = datetime.fromisoformat(row["end_time"]) if row.get("end_time") else None
        event = TimingEvent(
            race_id=race_id,
            race_part_id=race_part_id,
            participant_id=row.get("participant_id"),
            group=row.get("group"),
            client_time=client_time,
            server_time=server_time,
            duration_seconds=duration_seconds,
            start_time=start_time,
            end_time=end_time,
        )
        db.add(event)
    for row in preview.get("modified", []):
        event = db.get(TimingEvent, row.get("id"))
        if event:
            event.participant_id = row.get("participant_id")
            event.group = row.get("group")
            if row.get("client_time"):
                event.client_time = datetime.fromisoformat(row["client_time"])
            if row.get("server_time"):
                event.server_time = datetime.fromisoformat(row["server_time"])
            event.duration_seconds = (
                parse_duration_to_seconds(row["duration"]) if row.get("duration") else None
            )
            event.start_time = (
                datetime.fromisoformat(row["start_time"]) if row.get("start_time") else None
            )
            event.end_time = (
                datetime.fromisoformat(row["end_time"]) if row.get("end_time") else None
            )
    db.commit()
    return RedirectResponse(
        f"/race/{race_id}/part/{race_part_id}/manage/timing-events", status_code=303
    )


@app.get("/race/{race_id}/part/{race_part_id}/submit-start", response_class=HTMLResponse)
def submit_start_form(request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "submit_start.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/part/{race_part_id}", f"< {race_part_id} Results"),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/submit-start")
def submit_start(
    request: Request,
    race_id: str,
    race_part_id: str,
    targets: str = Form(...),
    time_value: str = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    server_now = datetime.now(tz=race_timezone(race))
    start_dt = parse_time_field(time_value, race, server_now)
    for token in parse_comma_list(targets):
        if token.isdigit():
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=int(token),
                group=None,
                client_time=server_now,
                duration_seconds=None,
                start_time=start_dt,
                end_time=None,
            )
        else:
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=None,
                group=token,
                client_time=server_now,
                duration_seconds=None,
                start_time=start_dt,
                end_time=None,
            )
    db.commit()
    return RedirectResponse(
        f"/race/{race_id}/part/{race_part_id}/submit-start", status_code=303
    )


@app.get("/race/{race_id}/part/{race_part_id}/submit-start/wave", response_class=HTMLResponse)
def wave_starts_form(
    request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "wave_starts.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "user": current_user(request),
            **back_context(
                f"/race/{race_id}/part/{race_part_id}/submit-start",
                "< Submit Start Times",
            ),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/submit-start/wave/data")
def wave_starts_data(
    request: Request,
    race_id: str,
    race_part_id: str,
    targets: str = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    target_list = parse_comma_list(targets)
    participants = db.scalars(
        select(Participant).where(Participant.race_id == race_id)
    ).all()
    filtered = []
    for participant in participants:
        if str(participant.participant_id) in target_list or participant.group in target_list:
            filtered.append(participant)
    race_parts = db.scalars(
        select(RacePart)
        .where(RacePart.race_id == race_id)
        .order_by(RacePart.is_overall, RacePart.race_order)
    ).all()
    current_part = next((part for part in race_parts if part.race_part_id == race_part_id), None)
    if not current_part:
        raise HTTPException(status_code=404)
    previous_parts = [
        part
        for part in race_parts
        if not part.is_overall and part.race_order < current_part.race_order
    ]
    schedule = []
    for participant in filtered:
        total = 0
        valid = True
        for part in previous_parts:
            duration = compute_participant_duration(db, race, part.race_part_id, participant)
            if duration is None:
                valid = False
                break
            total += duration
        if valid:
            schedule.append(
                {
                    "participant_id": participant.participant_id,
                    "group": participant.group,
                    "offset_seconds": total,
                }
            )
    schedule.sort(key=lambda item: item["offset_seconds"])
    return {"schedule": schedule}


@app.post("/race/{race_id}/part/{race_part_id}/submit-start/api")
def submit_start_api(
    request: Request,
    race_id: str,
    race_part_id: str,
    participant_id: int = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    server_now = datetime.now(tz=race_timezone(race))
    create_timing_event(
        db,
        race,
        race_part_id,
        participant_id=participant_id,
        group=None,
        client_time=server_now,
        duration_seconds=None,
        start_time=server_now,
        end_time=None,
    )
    db.commit()
    return {"ok": True}


@app.get("/race/{race_id}/part/{race_part_id}/submit-end", response_class=HTMLResponse)
def submit_end_form(request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "submit_end.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/part/{race_part_id}", f"< {race_part_id} Results"),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/submit-end")
def submit_end(
    request: Request,
    race_id: str,
    race_part_id: str,
    targets: str = Form(...),
    time_value: str = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    server_now = datetime.now(tz=race_timezone(race))
    end_dt = parse_time_field(time_value, race, server_now)
    for token in parse_comma_list(targets):
        if token.isdigit():
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=int(token),
                group=None,
                client_time=server_now,
                duration_seconds=None,
                start_time=None,
                end_time=end_dt,
            )
        else:
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=None,
                group=token,
                client_time=server_now,
                duration_seconds=None,
                start_time=None,
                end_time=end_dt,
            )
    db.commit()
    return RedirectResponse(
        f"/race/{race_id}/part/{race_part_id}/submit-end", status_code=303
    )


@app.get("/race/{race_id}/part/{race_part_id}/submit-duration", response_class=HTMLResponse)
def submit_duration_form(
    request: Request, race_id: str, race_part_id: str, db: Session = Depends(get_db)
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "submit_duration.html",
        {
            "request": request,
            "race": race,
            "race_part_id": race_part_id,
            "user": current_user(request),
            **back_context(f"/race/{race_id}/part/{race_part_id}", f"< {race_part_id} Results"),
        },
    )


@app.post("/race/{race_id}/part/{race_part_id}/submit-duration")
def submit_duration(
    request: Request,
    race_id: str,
    race_part_id: str,
    targets: str = Form(...),
    duration: str = Form(...),
    db: Session = Depends(get_db),
):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    part = db.scalar(
        select(RacePart).where(
            RacePart.race_id == race_id, RacePart.race_part_id == race_part_id
        )
    )
    if not part or part.is_overall:
        raise HTTPException(status_code=404)
    duration_seconds = parse_duration_field(duration)
    server_now = datetime.now(tz=race_timezone(race))
    for token in parse_comma_list(targets):
        if token.isdigit():
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=int(token),
                group=None,
                client_time=server_now,
                duration_seconds=duration_seconds,
                start_time=None,
                end_time=None,
            )
        else:
            create_timing_event(
                db,
                race,
                race_part_id,
                participant_id=None,
                group=token,
                client_time=server_now,
                duration_seconds=duration_seconds,
                start_time=None,
                end_time=None,
            )
    db.commit()
    return RedirectResponse(
        f"/race/{race_id}/part/{race_part_id}/submit-duration", status_code=303
    )


@app.get("/race/{race_id}/qrcodes.zip", response_class=StreamingResponse)
def download_qr_codes(request: Request, race_id: str, db: Session = Depends(get_db)):
    require_organiser(request, race_id)
    race = db.get(Race, race_id)
    if not race:
        raise HTTPException(status_code=404)
    participants = db.scalars(
        select(Participant)
        .where(Participant.race_id == race_id)
        .order_by(Participant.participant_id)
    ).all()
    import qrcode

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipf:
        for participant in participants:
            qr = qrcode.make(str(participant.participant_id))
            img_bytes = io.BytesIO()
            qr.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            filename = f"{participant.participant_id}.png"
            zipf.writestr(filename, img_bytes.getvalue())
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={race_id}-qrcodes.zip"},
    )
