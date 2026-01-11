from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .settings import settings
from .db import init_db, get_session
from . import services
from .auth import (
    get_current_admin,
    login_admin,
    logout_admin,
    admin_required,
)
from .schemas import (
    RaceCreate,
    RacePartCreate,
    ParticipantCreate,
    TimingEventCreate,
    StartTimeUpsert,
)

app = FastAPI(title="GLH Timer")

from .auth import AdminCookieMiddleware
app.add_middleware(AdminCookieMiddleware)

app.mount("/static", StaticFiles(directory=str((__file__).rsplit("/", 1)[0] + "/static")), name="static")
templates = Jinja2Templates(directory=str((__file__).rsplit("/", 1)[0] + "/templates"))

@app.on_event("startup")
def _startup() -> None:
    init_db()

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/projects", response_class=HTMLResponse)
def projects(request: Request):
    return templates.TemplateResponse("projects.html", {"request": request})

@app.get("/projects/glh-timer", response_class=HTMLResponse)
def glh_timer_home(request: Request):
    return RedirectResponse(url="/races", status_code=302)

# ---------------------------
# Auth
# ---------------------------

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})

@app.post("/admin/login")
def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not login_admin(request, username=username, password=password):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )
    return RedirectResponse(url="/races", status_code=302)

@app.post("/admin/logout")
def admin_logout(request: Request):
    logout_admin(request)
    return RedirectResponse(url="/races", status_code=302)

# ---------------------------
# Pages
# ---------------------------

@app.get("/races", response_class=HTMLResponse)
def races_page(request: Request, admin=Depends(get_current_admin), session=Depends(get_session)):
    races = services.list_races(session)
    return templates.TemplateResponse("races.html", {"request": request, "races": races, "admin": admin})

@app.get("/races/{race_id}", response_class=HTMLResponse)
def race_detail_page(race_id: str, request: Request, admin=Depends(get_current_admin), session=Depends(get_session)):
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    parts = services.list_race_parts(session, race_id)
    return templates.TemplateResponse("race_detail.html", {"request": request, "race": race, "parts": parts, "admin": admin})

@app.get("/races/{race_id}/parts/{race_part_id}", response_class=HTMLResponse)
def race_part_page(
    race_id: str,
    race_part_id: str,
    request: Request,
    admin=Depends(get_current_admin),
    session=Depends(get_session),
):
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    part = services.get_race_part(session, race_id, race_part_id)
    if not part:
        raise HTTPException(status_code=404, detail="Race part not found")

    # initial table render; subsequent refresh uses partial endpoint
    table = services.get_results(session, race_id, race_part_id)
    start_times = services.get_start_times(session, race_id, race_part_id)

    return templates.TemplateResponse(
        "race_part.html",
        {
            "request": request,
            "race": race,
            "part": part,
            "results": table,
            "admin": admin,
            "start_times": start_times,
            "poll_ms": settings.RESULTS_POLL_MS,
        },
    )

# ---------------------------
# Forms (admin)
# ---------------------------

@app.get("/admin/races/new", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def new_race_form(request: Request):
    return templates.TemplateResponse("race_new.html", {"request": request, "tz_default": "Europe/Brussels"})

@app.post("/admin/races/new", dependencies=[Depends(admin_required)])
def new_race_submit(
    race_id: str = Form(...),
    race_date: str = Form(...),
    race_timezone: str = Form(...),
    session=Depends(get_session),
):
    services.create_race(session, RaceCreate(race_id=race_id, race_date=race_date, race_timezone=race_timezone))
    return RedirectResponse(url="/races", status_code=302)

@app.get("/admin/races/{race_id}/parts/new", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def new_part_form(race_id: str, request: Request):
    return templates.TemplateResponse("race_part_new.html", {"request": request, "race_id": race_id})

@app.post("/admin/races/{race_id}/parts/new", dependencies=[Depends(admin_required)])
def new_part_submit(
    race_id: str,
    race_part_id: str = Form(...),
    name: str = Form(...),
    time_event_type: str = Form(...),  # duration | end_time
    session=Depends(get_session),
):
    services.create_race_part(
        session,
        RacePartCreate(
            race_id=race_id,
            race_part_id=race_part_id,
            name=name,
            time_event_type=time_event_type,
        ),
    )
    return RedirectResponse(url=f"/races/{race_id}", status_code=302)

@app.get("/admin/races/{race_id}/participants/new", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def new_participant_form(race_id: str, request: Request):
    return templates.TemplateResponse("participant_new.html", {"request": request, "race_id": race_id})

@app.post("/admin/races/{race_id}/participants/new", dependencies=[Depends(admin_required)])
def new_participant_submit(
    race_id: str,
    participant_id: str = Form(...),
    firstname: str = Form(...),
    lastname: str = Form(...),
    sex: str = Form(""),
    group_name: str = Form(""),
    club_name: str = Form(""),
    session=Depends(get_session),
):
    services.create_participant(
        session,
        ParticipantCreate(
            race_id=race_id,
            participant_id=participant_id,
            firstname=firstname,
            lastname=lastname,
            sex=sex,
            group_name=group_name,
            club_name=club_name,
        ),
    )
    return RedirectResponse(url=f"/races/{race_id}", status_code=302)

@app.get(
    "/admin/races/{race_id}/parts/{race_part_id}/timing/new",
    response_class=HTMLResponse,
    dependencies=[Depends(admin_required)],
)
def new_timing_form(race_id: str, race_part_id: str, request: Request, session=Depends(get_session)):
    race = services.get_race(session, race_id)
    part = services.get_race_part(session, race_id, race_part_id)
    if not race or not part:
        raise HTTPException(status_code=404, detail="Not found")
    participants = services.list_participants(session, race_id)
    return templates.TemplateResponse(
        "timing_event_new.html",
        {"request": request, "race": race, "part": part, "participants": participants},
    )

@app.post("/admin/races/{race_id}/parts/{race_part_id}/timing/new", dependencies=[Depends(admin_required)])
def new_timing_submit(
    race_id: str,
    race_part_id: str,
    participant_id: str = Form(...),
    duration: str = Form(""),
    client_timestamp_ms: str = Form(""),
    session=Depends(get_session),
):
    services.create_timing_event(
        session,
        TimingEventCreate(
            race_id=race_id,
            race_part_id=race_part_id,
            participant_id=participant_id.strip(),
            duration=duration.strip(),
            client_timestamp_ms=client_timestamp_ms.strip() or None,
        ),
    )
    return RedirectResponse(url=f"/races/{race_id}/parts/{race_part_id}", status_code=302)

@app.get(
    "/admin/races/{race_id}/parts/{race_part_id}/start-times",
    response_class=HTMLResponse,
    dependencies=[Depends(admin_required)],
)
def start_times_form(race_id: str, race_part_id: str, request: Request, session=Depends(get_session)):
    race = services.get_race(session, race_id)
    part = services.get_race_part(session, race_id, race_part_id)
    if not race or not part:
        raise HTTPException(status_code=404, detail="Not found")
    rows = services.get_start_times(session, race_id, race_part_id)
    return templates.TemplateResponse(
        "start_times.html",
        {"request": request, "race": race, "part": part, "rows": rows},
    )

@app.post(
    "/admin/races/{race_id}/parts/{race_part_id}/start-times",
    dependencies=[Depends(admin_required)],
)
def start_times_submit(
    race_id: str,
    race_part_id: str,
    group_name: str = Form(...),
    start_time_hms: str = Form(...),
    session=Depends(get_session),
):
    services.upsert_start_time(
        session,
        StartTimeUpsert(race_id=race_id, race_part_id=race_part_id, group_name=group_name, start_time_hms=start_time_hms),
    )
    return RedirectResponse(url=f"/races/{race_id}/parts/{race_part_id}", status_code=302)

# ---------------------------
# API (partials + CSV)
# ---------------------------

@app.get("/api/races/{race_id}/parts/{race_part_id}/results/partial", response_class=HTMLResponse)
def results_partial(race_id: str, race_part_id: str, request: Request, session=Depends(get_session)):
    table = services.get_results(session, race_id, race_part_id)
    return templates.TemplateResponse(
        "partials/results_table.html",
        {"request": request, "results": table},
    )

from .csv_export import router as csv_router
app.include_router(csv_router, prefix="/api", tags=["csv"])
