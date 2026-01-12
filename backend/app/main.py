from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .settings import settings
from .db import init_db, get_session
from . import services
from .auth import (
    get_current_user,
    staff_required,
    admin_required,
    assert_can_access_race,
    set_login_cookie,
    clear_login_cookie,
)
from .schemas import (
    RaceCreate,
    RacePartCreate,
    ParticipantCreate,
    TimingEventCreate,
    StartTimeUpsert,
)

app = FastAPI(title="GLH Timer")

from .auth import AuthCookieMiddleware
app.add_middleware(AuthCookieMiddleware)

app.mount("/static", StaticFiles(directory=str((__file__).rsplit("/", 1)[0] + "/static")), name="static")
templates = Jinja2Templates(directory=str((__file__).rsplit("/", 1)[0] + "/templates"))

@app.on_event("startup")
def _startup() -> None:
    init_db()
    # Ensure the single admin account exists
    from sqlalchemy.orm import Session
    from .db import _SessionLocal
    if _SessionLocal is not None:
        s = _SessionLocal()
        try:
            services.ensure_admin_user(s)
        finally:
            s.close()

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

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url="/races", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session=Depends(get_session),
):
    u = services.authenticate_user(session, username=username.strip(), password=password)
    if not u:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid username or password."}, status_code=401)
    set_login_cookie(request, user_id=u.id, username=u.username, role=u.role, race_id=u.race_id)
    return RedirectResponse(url="/races", status_code=302)

@app.post("/logout")
def logout(request: Request):
    clear_login_cookie(request)
    return RedirectResponse(url="/races", status_code=302)

# Backwards-compatible URL
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_redirect(request: Request):
    return RedirectResponse(url="/login", status_code=302)

@app.post("/admin/logout")
def admin_logout_redirect(request: Request):
    clear_login_cookie(request)
    return RedirectResponse(url="/races", status_code=302)

# ---------------------------
# Pages
# ---------------------------

# ---------------------------

@app.get("/races", response_class=HTMLResponse)
def races_page(request: Request, user=Depends(get_current_user), session=Depends(get_session)):
    # Everyone can see all races. Organizer permissions are enforced per-race.
    races = services.list_races(session)
    return templates.TemplateResponse(
        "races.html",
        {"request": request, "races": races, "user": user, "admin": (user if user and user.is_admin else None), "staff": user},
    )

@app.get("/races/{race_id}", response_class=HTMLResponse)
def race_detail_page(race_id: str, request: Request, user=Depends(get_current_user), session=Depends(get_session)):
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    parts = services.list_race_parts(session, race_id)
    staff_for_race = user if (user and (user.is_admin or (user.role == "organizer" and user.race_id == race_id))) else None
    return templates.TemplateResponse(
        "race_detail.html",
        {"request": request, "race": race, "parts": parts, "user": user, "admin": (user if user and user.is_admin else None), "staff": staff_for_race},
    )

@app.get("/races/{race_id}/parts/{race_part_id}", response_class=HTMLResponse)
def race_part_page(
    race_id: str,
    race_part_id: str,
    request: Request,
    user=Depends(get_current_user),
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

    # needed for OVERALL split columns
    non_overall_parts = [p for p in services.list_race_parts(session, race_id) if p.time_event_type != "overall"]

    staff_for_race = user if (user and (user.is_admin or (user.role == "organizer" and user.race_id == race_id))) else None

    return templates.TemplateResponse(
        "race_part.html",
        {
            "request": request,
            "race": race,
            "part": part,
            "results": table,
            "user": user, "admin": (user if user and user.is_admin else None), "staff": staff_for_race,
            "start_times": start_times,
            "poll_ms": settings.RESULTS_POLL_MS,
            "non_overall_parts": non_overall_parts,
        },
    )

# ---------------------------
# Forms (admin)
# ---------------------------


# ---------------------------
# User management (admin only)
# ---------------------------

@app.get("/admin/users", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def users_page(request: Request, session=Depends(get_session)):
    users = services.list_users(session)
    races = services.list_races(session)
    return templates.TemplateResponse("users.html", {"request": request, "users": users, "races": races})

@app.get("/admin/users/new", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def user_new_form(
    request: Request,
    session=Depends(get_session),
    race_id: str | None = Query(default=None),
):
    races = services.list_races(session)
    return templates.TemplateResponse(
        "user_new.html",
        {"request": request, "races": races, "error": None, "preselected_race_id": race_id},
    )

@app.post("/admin/users/new", dependencies=[Depends(admin_required)])
def user_new_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    race_id: str = Form(...),
    session=Depends(get_session),
):
    try:
        services.create_organizer_user(session, username=username.strip(), password=password, race_id=race_id)
    except Exception as e:
        races = services.list_races(session)
        # Keep any preselected race so the admin doesn't have to re-select after an error.
        preselected = request.query_params.get("race_id")
        return templates.TemplateResponse(
            "user_new.html",
            {"request": request, "races": races, "error": str(e), "preselected_race_id": preselected},
            status_code=400,
        )
    return RedirectResponse(url="/admin/users", status_code=302)

@app.get("/admin/races/new", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def new_race_form(request: Request):
    return templates.TemplateResponse("race_new.html", {"request": request, "tz_default": "Europe/Brussels", "error": None})

@app.post("/admin/races/new", dependencies=[Depends(admin_required)])
def new_race_submit(
    race_id: str = Form(...),
    race_date: str = Form(...),
    race_timezone: str = Form(...),
    session=Depends(get_session),
):
    try:
        services.create_race(session, RaceCreate(race_id=race_id, race_date=race_date, race_timezone=race_timezone))
    except Exception as e:
        return templates.TemplateResponse(
            "race_new.html",
            {"request": request, "tz_default": "Europe/Brussels", "error": str(e)},
            status_code=400,
        )
    return RedirectResponse(url="/races", status_code=302)

@app.get("/admin/races/{race_id}/parts/new", response_class=HTMLResponse, dependencies=[Depends(staff_required)])
def new_part_form(race_id: str, request: Request, user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
    return templates.TemplateResponse("race_part_new.html", {"request": request, "race_id": race_id, "error": None})

@app.post("/admin/races/{race_id}/parts/new", dependencies=[Depends(staff_required)])
def new_part_submit(
    request: Request,
    race_id: str,
    user=Depends(staff_required),
    race_part_id: str = Form(...),
    name: str = Form(...),
    time_event_type: str = Form(...),  # duration | end_time
    session=Depends(get_session),
):
    assert_can_access_race(user, race_id)
    try:
        services.create_race_part(
            session,
            RacePartCreate(
                race_id=race_id,
                race_part_id=race_part_id,
                name=name,
                time_event_type=time_event_type,
            ),
        )
    except Exception as e:
        return templates.TemplateResponse(
            "race_part_new.html",
            {"request": request, "race_id": race_id, "error": str(e)},
            status_code=400,
        )
    return RedirectResponse(url=f"/races/{race_id}", status_code=302)


@app.post("/admin/races/{race_id}/parts/{race_part_id}/delete", dependencies=[Depends(admin_required)])
def delete_race_part_submit(race_id: str, race_part_id: str, session=Depends(get_session)):
    try:
        services.delete_race_part(session, race_id, race_part_id)
    except Exception:
        # ignore and just return to race page
        pass
    return RedirectResponse(url=f"/races/{race_id}", status_code=302)

@app.get("/admin/races/{race_id}/participants/new", response_class=HTMLResponse, dependencies=[Depends(staff_required)])
def new_participant_form(race_id: str, request: Request, user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
    return templates.TemplateResponse("participant_new.html", {"request": request, "race_id": race_id, "error": None})

@app.post("/admin/races/{race_id}/participants/new", dependencies=[Depends(staff_required)])
def new_participant_submit(
    request: Request,
    race_id: str,
    user=Depends(staff_required),
    participant_id: str = Form(...),
    firstname: str = Form(...),
    lastname: str = Form(...),
    sex: str = Form(""),
    group_name: str = Form(""),
    club_name: str = Form(""),
    session=Depends(get_session),
):
    assert_can_access_race(user, race_id)
    try:
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
    except Exception as e:
        return templates.TemplateResponse(
            "participant_new.html",
            {"request": request, "race_id": race_id, "error": str(e)},
            status_code=400,
        )
    return RedirectResponse(url=f"/races/{race_id}", status_code=302)


@app.get("/admin/races/{race_id}/participants", response_class=HTMLResponse, dependencies=[Depends(admin_required)])
def manage_participants_page(race_id: str, request: Request, session=Depends(get_session)):
    # admin can manage any race
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    participants = services.list_participants(session, race_id)
    return templates.TemplateResponse(
        "participants_manage.html",
        {"request": request, "race": race, "participants": participants, "error": None},
    )


@app.post("/admin/races/{race_id}/participants/{participant_id}/delete", dependencies=[Depends(admin_required)])
def delete_participant_submit(race_id: str, participant_id: str, request: Request, session=Depends(get_session)):
    try:
        services.delete_participant(session, race_id=race_id, participant_id=participant_id)
    except Exception as e:
        race = services.get_race(session, race_id)
        participants = services.list_participants(session, race_id)
        return templates.TemplateResponse(
            "participants_manage.html",
            {"request": request, "race": race, "participants": participants, "error": str(e)},
            status_code=400,
        )
    return RedirectResponse(url=f"/admin/races/{race_id}/participants", status_code=302)

@app.get(
    "/admin/races/{race_id}/parts/{race_part_id}/timing/new",
    response_class=HTMLResponse,
    dependencies=[Depends(staff_required)],
)
def new_timing_form(race_id: str, race_part_id: str, request: Request, user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
    race = services.get_race(session, race_id)
    part = services.get_race_part(session, race_id, race_part_id)
    if not race or not part:
        raise HTTPException(status_code=404, detail="Not found")
    participants = services.list_participants(session, race_id)
    return templates.TemplateResponse(
        "timing_event_new.html",
        {"request": request, "race": race, "part": part, "participants": participants},
    )

@app.post("/admin/races/{race_id}/parts/{race_part_id}/timing/new")
def new_timing_submit(
    request: Request,
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

    if request.headers.get("X-Requested-With") == "fetch":
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True})

    return RedirectResponse(
        url=f"/admin/races/{race_id}/parts/{race_part_id}/timing/new?ok=1&bib={participant_id.strip()}",
        status_code=302,
    )

@app.get("/admin/races/{race_id}/participants/upload", response_class=HTMLResponse, dependencies=[Depends(staff_required)])
def upload_participants_form(race_id: str, request: Request, user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    return templates.TemplateResponse("participants_upload.html", {"request": request, "race": race, "error": None, "msg": None})

@app.post("/admin/races/{race_id}/participants/upload", response_class=HTMLResponse, dependencies=[Depends(staff_required)])
async def upload_participants_submit(race_id: str, request: Request, file: UploadFile = File(...), user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
    race = services.get_race(session, race_id)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    try:
        content = (await file.read()).decode("utf-8-sig")
        added, skipped = services.import_participants_csv(session, race_id, content)
        msg = f"Imported {added} participants. Skipped {skipped} rows."
        return templates.TemplateResponse("participants_upload.html", {"request": request, "race": race, "error": None, "msg": msg})
    except Exception as e:
        return templates.TemplateResponse("participants_upload.html", {"request": request, "race": race, "error": str(e), "msg": None}, status_code=400)

@app.get(
    "/admin/races/{race_id}/parts/{race_part_id}/start-times",
    response_class=HTMLResponse,
    dependencies=[Depends(staff_required)],
)
def start_times_form(race_id: str, race_part_id: str, request: Request, user=Depends(staff_required), session=Depends(get_session)):
    assert_can_access_race(user, race_id)
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
    dependencies=[Depends(staff_required)],
)
def start_times_submit(
    race_id: str,
    race_part_id: str,
    user=Depends(staff_required),
    group_name: str = Form(...),
    start_time_hms: str = Form(...),
    session=Depends(get_session),
):
    assert_can_access_race(user, race_id)
    services.upsert_start_time(
        session,
        StartTimeUpsert(race_id=race_id, race_part_id=race_part_id, group_name=group_name, start_time_hms=start_time_hms),
    )
    return RedirectResponse(
        url=f"/admin/races/{race_id}/parts/{race_part_id}/start-times?ok=1",
        status_code=302
    )

# ---------------------------
# API (partials + CSV)
# ---------------------------

@app.get("/api/races/{race_id}/parts/{race_part_id}/results/partial", response_class=HTMLResponse)
def results_partial(race_id: str, race_part_id: str, request: Request, session=Depends(get_session)):
    race = services.get_race(session, race_id)
    part = services.get_race_part(session, race_id, race_part_id)
    if not race or not part:
        raise HTTPException(status_code=404, detail="Not found")

    table = services.get_results(session, race_id, race_part_id)
    non_overall_parts = [p for p in services.list_race_parts(session, race_id) if p.time_event_type != "overall"]

    return templates.TemplateResponse(
        "partials/results_table.html",
        {"request": request, "race": race, "part": part, "results": table, "non_overall_parts": non_overall_parts},
    )

from .csv_export import router as csv_router
app.include_router(csv_router, prefix="/api", tags=["csv"])
