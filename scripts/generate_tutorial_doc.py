from __future__ import annotations

import asyncio
import base64
import html
import json
import math
import os
import shutil
import subprocess
import sys
import time
from zipfile import ZIP_DEFLATED, ZipFile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import websockets
from PIL import Image


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "tutorial_output"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
DB_PATH = OUTPUT_DIR / "glh_tutorial.db"
HTML_PATH = OUTPUT_DIR / "glh_timer_tutorial.html"
DOCX_PATH = OUTPUT_DIR / "glh_timer_tutorial.docx"
APP_PORT = 8001
APP_URL = f"http://127.0.0.1:{APP_PORT}"
CHROME_PORT = 9222
CHROME_URL = f"http://127.0.0.1:{CHROME_PORT}"
CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CHROME_PROFILE_DIR = OUTPUT_DIR / "chrome-profile"
VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python"
TIMEZONE_NAME = "Europe/Brussels"
ONGOING_RACE_ID = "GLH-Spring-Tri-2026"


@dataclass(frozen=True)
class TutorialPage:
    slug: str
    title: str
    description: str
    url: str
    wait_expression: str | None = None
    prepare_script: str | None = None


def log(message: str) -> None:
    print(message, flush=True)


def require_paths() -> None:
    if not VENV_PYTHON.exists():
        raise FileNotFoundError(f"Missing virtualenv python at {VENV_PYTHON}")
    if not CHROME_PATH.exists():
        raise FileNotFoundError(f"Missing Chrome binary at {CHROME_PATH}")


def clean_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if CHROME_PROFILE_DIR.exists():
        shutil.rmtree(CHROME_PROFILE_DIR)
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    for screenshot in SCREENSHOT_DIR.glob("*.png"):
        screenshot.unlink()
    for artifact in [HTML_PATH, DOCX_PATH]:
        if artifact.exists():
            artifact.unlink()


def demo_database_url() -> str:
    return f"sqlite:///{DB_PATH}"


def seed_demo_data() -> None:
    os.environ["DATABASE_URL"] = demo_database_url()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models import Organiser, OrganiserRace, Participant, Race, RacePart, TimingEvent
    from app.security import hash_password

    engine = create_engine(demo_database_url())
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    timezone = ZoneInfo(TIMEZONE_NAME)
    race_date = date(2026, 3, 20)
    past_race_date = date(2026, 2, 14)
    future_race_date = date(2026, 6, 14)
    now_local = datetime.now(timezone).replace(microsecond=0)

    def race_time(hour: int, minute: int, second: int) -> datetime:
        return datetime(2026, 3, 20, hour, minute, second, tzinfo=timezone)

    def event(
        race_part_id: str,
        *,
        participant_id: int | None = None,
        group: str | None = None,
        duration_seconds: int | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        server_time: datetime | None = None,
        created_by_username: str | None = None,
    ) -> TimingEvent:
        timestamp = server_time or now_local
        return TimingEvent(
            race_id=ONGOING_RACE_ID,
            race_part_id=race_part_id,
            participant_id=participant_id,
            group=group,
            client_time=timestamp,
            server_time=timestamp,
            duration_seconds=duration_seconds,
            start_time=start_time,
            end_time=end_time,
            created_by_username=created_by_username,
        )

    races = [
        Race(race_id="WinterDuathlon-2026", race_date=past_race_date, race_timezone=TIMEZONE_NAME),
        Race(race_id=ONGOING_RACE_ID, race_date=race_date, race_timezone=TIMEZONE_NAME),
        Race(race_id="Summer-Challenge-2026", race_date=future_race_date, race_timezone=TIMEZONE_NAME),
    ]
    session.add_all(races)
    session.flush()

    session.add_all(
        [
            RacePart(race_id=ONGOING_RACE_ID, race_part_id="Overall", race_order=-1, is_overall=True),
            RacePart(race_id=ONGOING_RACE_ID, race_part_id="Swim", race_order=1, is_overall=False),
            RacePart(race_id=ONGOING_RACE_ID, race_part_id="Bike", race_order=2, is_overall=False),
            RacePart(race_id=ONGOING_RACE_ID, race_part_id="Run", race_order=3, is_overall=False),
            RacePart(
                race_id="Summer-Challenge-2026",
                race_part_id="Overall",
                race_order=-1,
                is_overall=True,
            ),
            RacePart(
                race_id="Summer-Challenge-2026",
                race_part_id="Sprint",
                race_order=1,
                is_overall=False,
            ),
        ]
    )

    participants = [
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=101,
            first_name="Ava",
            last_name="Martin",
            group="Open",
            club="GLH",
            sex="F",
        ),
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=102,
            first_name="Liam",
            last_name="Peeters",
            group="Open",
            club="GLH",
            sex="M",
        ),
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=103,
            first_name="Noor",
            last_name="Jacobs",
            group="Open",
            club="TRI Leuven",
            sex="F",
        ),
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=104,
            first_name="Jules",
            last_name="Vermeulen",
            group="M40",
            club="Tri4Fun",
            sex="M",
        ),
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=105,
            first_name="Mila",
            last_name="Claes",
            group="Open",
            club="Brussels Sharks",
            sex="F",
        ),
        Participant(
            race_id=ONGOING_RACE_ID,
            participant_id=106,
            first_name="Arthur",
            last_name="De Smet",
            group="M40",
            club="GLH",
            sex="M",
        ),
    ]
    session.add_all(participants)

    organisers = [
        Organiser(username="racelead", password_hash=hash_password("racelead")),
        Organiser(username="assistant", password_hash=hash_password("assistant")),
    ]
    session.add_all(organisers)
    session.flush()
    session.add_all(
        [
            OrganiserRace(organiser_id=organisers[0].id, race_id=ONGOING_RACE_ID),
            OrganiserRace(organiser_id=organisers[0].id, race_id="Summer-Challenge-2026"),
            OrganiserRace(organiser_id=organisers[1].id, race_id="WinterDuathlon-2026"),
        ]
    )

    session.add_all(
        [
            event(
                "Swim",
                group="Open",
                start_time=race_time(9, 0, 0),
                server_time=race_time(8, 59, 45),
                created_by_username="admin",
            ),
            event(
                "Swim",
                group="M40",
                start_time=race_time(9, 5, 0),
                server_time=race_time(9, 4, 45),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=101,
                start_time=now_local - timedelta_seconds(95),
                server_time=now_local - timedelta_seconds(94),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=102,
                start_time=now_local - timedelta_seconds(58),
                server_time=now_local - timedelta_seconds(57),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=101,
                end_time=race_time(9, 18, 12),
                server_time=race_time(9, 18, 13),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=102,
                end_time=race_time(9, 16, 47),
                server_time=race_time(9, 16, 48),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=103,
                end_time=race_time(9, 19, 5),
                server_time=race_time(9, 19, 6),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=104,
                end_time=race_time(9, 22, 31),
                server_time=race_time(9, 22, 32),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=105,
                end_time=race_time(9, 21, 10),
                server_time=race_time(9, 21, 11),
                created_by_username="admin",
            ),
            event(
                "Swim",
                participant_id=106,
                end_time=race_time(9, 23, 40),
                server_time=race_time(9, 23, 41),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=101,
                start_time=race_time(9, 20, 0),
                server_time=race_time(9, 20, 1),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=102,
                start_time=race_time(9, 18, 10),
                server_time=race_time(9, 18, 11),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=101,
                duration_seconds=41 * 60 + 32,
                server_time=race_time(10, 1, 33),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=102,
                duration_seconds=39 * 60 + 58,
                server_time=race_time(9, 58, 9),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=103,
                duration_seconds=43 * 60 + 11,
                server_time=race_time(10, 2, 17),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=104,
                duration_seconds=40 * 60 + 10,
                server_time=race_time(10, 2, 42),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=105,
                duration_seconds=42 * 60 + 45,
                server_time=race_time(10, 3, 56),
                created_by_username="admin",
            ),
            event(
                "Bike",
                participant_id=106,
                duration_seconds=41 * 60 + 2,
                server_time=race_time(10, 4, 50),
                created_by_username="admin",
            ),
            event(
                "Bike",
                end_time=race_time(10, 15, 20),
                server_time=race_time(10, 15, 21),
                created_by_username="admin",
            ),
            event(
                "Run",
                participant_id=101,
                duration_seconds=21 * 60 + 4,
                server_time=race_time(10, 24, 45),
                created_by_username="admin",
            ),
            event(
                "Run",
                participant_id=102,
                duration_seconds=20 * 60 + 11,
                server_time=race_time(10, 18, 30),
                created_by_username="admin",
            ),
            event(
                "Run",
                participant_id=103,
                duration_seconds=22 * 60 + 30,
                server_time=race_time(10, 26, 40),
                created_by_username="admin",
            ),
            event(
                "Run",
                participant_id=104,
                duration_seconds=19 * 60 + 54,
                server_time=race_time(10, 22, 40),
                created_by_username="admin",
            ),
            event(
                "Run",
                participant_id=105,
                duration_seconds=21 * 60 + 48,
                server_time=race_time(10, 29, 10),
                created_by_username="admin",
            ),
        ]
    )

    session.commit()
    session.close()
    engine.dispose()


def timedelta_seconds(seconds: int) -> timedelta:
    return timedelta(seconds=seconds)


def wait_for_url(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except URLError as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


@contextmanager
def managed_process(command: list[str], *, env: dict[str, str] | None = None) -> Any:
    process = subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def start_server() -> managed_process:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": demo_database_url(),
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "admin",
            "SECRET_KEY": "tutorial-secret-key",
        }
    )
    return managed_process(
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(APP_PORT),
        ],
        env=environment,
    )


def start_chrome() -> managed_process:
    return managed_process(
        [
            str(CHROME_PATH),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={CHROME_PROFILE_DIR}",
            f"--remote-debugging-port={CHROME_PORT}",
            "about:blank",
        ]
    )


def fetch_json(url: str, *, method: str = "GET") -> Any:
    request = Request(url, method=method)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class ChromeSession:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.websocket: Any | None = None
        self.next_message_id = 1

    async def connect(self) -> None:
        self.websocket = await websockets.connect(self.websocket_url, max_size=None)
        await self.send("Page.enable")
        await self.send("Runtime.enable")

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.websocket is None:
            raise RuntimeError("ChromeSession is not connected")
        message_id = self.next_message_id
        self.next_message_id += 1
        payload = {"id": message_id, "method": method, "params": params or {}}
        await self.websocket.send(json.dumps(payload))
        while True:
            raw_message = await self.websocket.recv()
            message = json.loads(raw_message)
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method} failed: {message['error']}")
            return message.get("result", {})

    async def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        result = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        return result.get("result", {}).get("value")

    async def wait_for_expression(
        self, expression: str, *, timeout_seconds: float = 15.0, interval_seconds: float = 0.1
    ) -> Any:
        deadline = time.time() + timeout_seconds
        last_value: Any = None
        while time.time() < deadline:
            last_value = await self.evaluate(expression)
            if last_value:
                return last_value
            await asyncio.sleep(interval_seconds)
        raise RuntimeError(f"Timed out waiting for expression: {expression} (last value: {last_value!r})")

    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})
        await self.wait_for_expression("document.readyState === 'complete'")
        await asyncio.sleep(0.35)

    async def prepare_page(self, script: str) -> None:
        await self.evaluate(script, await_promise=True)
        await asyncio.sleep(0.35)

    async def login(self, username: str, password: str) -> None:
        await self.navigate(f"{APP_URL}/login")
        await self.wait_for_expression("!!document.querySelector('form[action=\"/login\"]')")
        script = f"""
        (() => {{
          document.querySelector('input[name="username"]').value = {json.dumps(username)};
          document.querySelector('input[name="password"]').value = {json.dumps(password)};
          document.querySelector('form[action="/login"]').submit();
          return true;
        }})()
        """
        await self.evaluate(script)
        await self.wait_for_expression(
            "location.pathname === '/' && document.querySelector('h1') && document.querySelector('h1').textContent.includes('Races')",
            timeout_seconds=20.0,
        )
        await asyncio.sleep(0.5)

    async def capture_full_page(self, output_path: Path) -> None:
        metrics = await self.send("Page.getLayoutMetrics")
        content_size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
        width = max(1280, math.ceil(content_size.get("width", 1280)))
        height = max(900, math.ceil(content_size.get("height", 900)))
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        screenshot = await self.send(
            "Page.captureScreenshot",
            {"format": "png", "captureBeyondViewport": True, "fromSurface": True},
        )
        output_path.write_bytes(base64.b64decode(screenshot["data"]))


def compress_screenshot(path: Path, max_width: int = 1200) -> None:
    with Image.open(path) as image:
        if image.width <= max_width:
            return
        height = int((max_width / image.width) * image.height)
        resized = image.resize((max_width, height), Image.Resampling.LANCZOS)
        resized.save(path, optimize=True)


def tutorial_pages() -> list[TutorialPage]:
    race_path = f"/race/{ONGOING_RACE_ID}"
    return [
        TutorialPage(
            slug="01-login",
            title="Log In",
            description="Open the login page and sign in with an admin account or an organiser account linked to the race you want to manage.",
            url=f"{APP_URL}/login",
            wait_expression="!!document.querySelector('form[action=\"/login\"]')",
        ),
        TutorialPage(
            slug="02-home",
            title="Races Dashboard",
            description="The home screen lists all races and their status. Admin users also see shortcuts to race and organiser management.",
            url=f"{APP_URL}/",
            wait_expression="document.querySelectorAll('tbody tr').length >= 3",
        ),
        TutorialPage(
            slug="03-manage-races",
            title="Manage Races",
            description="Use the race management screen to add races, edit existing entries, or import and export the race list as CSV.",
            url=f"{APP_URL}/manage/races",
            wait_expression="document.querySelectorAll('tbody tr').length >= 3",
        ),
        TutorialPage(
            slug="04-manage-organisers",
            title="Manage Organisers",
            description="Admin users can create organiser accounts and grant access to one or more races from the organiser management page.",
            url=f"{APP_URL}/manage/organisers",
            wait_expression="document.querySelectorAll('tbody tr').length >= 2",
        ),
        TutorialPage(
            slug="05-race-overview",
            title="Race Overview",
            description="Each race overview page links to its race parts, participant administration, and QR code export for check-in and timing.",
            url=f"{APP_URL}{race_path}",
            wait_expression="document.querySelectorAll('tbody tr').length >= 4",
        ),
        TutorialPage(
            slug="06-manage-race-parts",
            title="Manage Race Parts",
            description="Race parts define the sequence used for results and automated wave starts. The Overall part is generated automatically.",
            url=f"{APP_URL}{race_path}/manage/race-parts",
            wait_expression="document.querySelectorAll('tbody tr').length >= 4",
        ),
        TutorialPage(
            slug="07-manage-participants",
            title="Manage Participants",
            description="Add participants manually or through CSV import. QR codes can be downloaded per participant for fast timing capture.",
            url=f"{APP_URL}{race_path}/manage/participants",
            wait_expression="document.querySelectorAll('tbody tr').length >= 6",
        ),
        TutorialPage(
            slug="08-overall-results",
            title="Review Results",
            description="Results pages show rankings per part and overall. Filters let you narrow the table by group or sex.",
            url=f"{APP_URL}{race_path}/part/Overall",
            wait_expression="document.querySelectorAll('#results-body tr').length >= 6",
        ),
        TutorialPage(
            slug="09-submit-start",
            title="Submit Start Times",
            description="Use the start submission form for manual starts. You can enter bib numbers, groups, or ranges in a single action.",
            url=f"{APP_URL}{race_path}/part/Swim/submit-start",
            wait_expression="!!document.querySelector('#submit-start-form')",
        ),
        TutorialPage(
            slug="10-wave-starts",
            title="Automated Wave Starts",
            description="Wave starts compute offsets from previous part results. This is useful when the next leg should start in ranking order.",
            url=f"{APP_URL}{race_path}/part/Bike/submit-start/wave",
            wait_expression="!!document.querySelector('#wave-form')",
            prepare_script="""
            (() => {
              document.querySelector('input[name="targets"]').value = '101-106';
              document.querySelector('input[name="start_offset_seconds"]').value = '20';
              document.querySelector('#wave-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
              return true;
            })()
            """,
        ),
        TutorialPage(
            slug="11-live-timer",
            title="Show Timer",
            description="The timer screen can be projected on-site. It tracks elapsed time from the selected start event and supports full-screen display.",
            url=f"{APP_URL}{race_path}/part/Swim/timer",
            wait_expression="!!document.querySelector('#timer-display')",
        ),
        TutorialPage(
            slug="12-submit-end",
            title="Submit End Times",
            description="End times can be entered directly, scanned through QR codes, or captured first and assigned to bibs afterward from the pending queue.",
            url=f"{APP_URL}{race_path}/part/Bike/submit-end",
            wait_expression="document.querySelectorAll('.pending-end-item').length >= 1",
        ),
        TutorialPage(
            slug="13-submit-duration",
            title="Submit Durations",
            description="Duration entry is useful when you have elapsed times already measured and want to add them without separate start and end events.",
            url=f"{APP_URL}{race_path}/part/Run/submit-duration",
            wait_expression="!!document.querySelector('form[action$=\"/submit-duration\"]')",
        ),
        TutorialPage(
            slug="14-manage-timing-events",
            title="Manage Timing Events",
            description="The timing event ledger lets organisers review, edit, delete, and bulk import recorded timing data for a race part.",
            url=f"{APP_URL}{race_path}/part/Bike/manage/timing-events",
            wait_expression="document.querySelectorAll('tbody tr').length >= 7",
        ),
    ]


async def capture_screenshots() -> list[TutorialPage]:
    target = fetch_json(f"{CHROME_URL}/json/new?{quote('about:blank', safe=':/?=&')}", method="PUT")
    websocket_url = target["webSocketDebuggerUrl"]
    session = ChromeSession(websocket_url)
    pages = tutorial_pages()
    await session.connect()
    try:
        log("Capturing login page")
        login_page = pages[0]
        await session.navigate(login_page.url)
        if login_page.wait_expression:
            await session.wait_for_expression(login_page.wait_expression)
        await session.capture_full_page(SCREENSHOT_DIR / f"{login_page.slug}.png")
        compress_screenshot(SCREENSHOT_DIR / f"{login_page.slug}.png")

        log("Logging into the demo app")
        await session.login("admin", "admin")

        for page in pages[1:]:
            log(f"Capturing {page.slug}")
            await session.navigate(page.url)
            if page.prepare_script:
                await session.prepare_page(page.prepare_script)
            if page.wait_expression:
                await session.wait_for_expression(page.wait_expression, timeout_seconds=20.0)
            if page.slug == "10-wave-starts":
                await session.wait_for_expression(
                    "document.querySelectorAll('#wave-table tbody tr').length >= 6",
                    timeout_seconds=20.0,
                )
            await session.capture_full_page(SCREENSHOT_DIR / f"{page.slug}.png")
            compress_screenshot(SCREENSHOT_DIR / f"{page.slug}.png")
    finally:
        await session.close()
    return pages


def build_html_document(pages: list[TutorialPage]) -> None:
    generated_on = datetime.now().strftime("%Y-%m-%d %H:%M")
    sections: list[str] = []
    for index, page in enumerate(pages, start=1):
        image_uri = (SCREENSHOT_DIR / f"{page.slug}.png").resolve().as_uri()
        sections.append(
            f"""
            <section class="page-section">
              <h2>{index}. {html.escape(page.title)}</h2>
              <p>{html.escape(page.description)}</p>
              <img src="{image_uri}" alt="{html.escape(page.title)} screenshot" />
            </section>
            """
        )

    html_output = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>GLH Timer Tutorial</title>
  <style>
    body {{
      font-family: Helvetica, Arial, sans-serif;
      color: #1a1a1a;
      margin: 36px;
      line-height: 1.45;
    }}
    h1 {{
      font-size: 28px;
      margin-bottom: 6px;
    }}
    h2 {{
      font-size: 18px;
      margin: 0 0 8px;
    }}
    p, li {{
      font-size: 11pt;
    }}
    ul {{
      margin-top: 6px;
      margin-bottom: 16px;
    }}
    .meta {{
      color: #4a4a4a;
      margin-bottom: 20px;
    }}
    .page-section {{
      page-break-inside: avoid;
      margin-top: 26px;
    }}
    img {{
      width: 100%;
      max-width: 900px;
      border: 1px solid #d8d8d8;
      margin-top: 10px;
    }}
  </style>
</head>
<body>
  <h1>GLH Timer Tutorial</h1>
  <p class="meta">Generated on {html.escape(generated_on)} from a seeded demo environment.</p>
  <p>This tutorial walks through the main admin workflow in GLH Timer using the sample race <strong>{html.escape(ONGOING_RACE_ID)}</strong>.</p>
  <ul>
    <li>Admin login used for the screenshots: <strong>admin</strong> / <strong>admin</strong></li>
    <li>Demo organiser accounts included in the data set: <strong>racelead</strong> and <strong>assistant</strong></li>
    <li>Race statuses reflect the seeded dates around March 20, 2026</li>
  </ul>
  {''.join(sections)}
</body>
</html>
"""
    HTML_PATH.write_text(html_output, encoding="utf-8")


def xml_escape(value: str) -> str:
    return html.escape(value, quote=False)


def paragraph_xml(
    text: str,
    *,
    bold: bool = False,
    size_half_points: int | None = None,
    center: bool = False,
) -> str:
    text_xml = xml_escape(text)
    run_properties: list[str] = []
    if bold:
        run_properties.append("<w:b/>")
    if size_half_points is not None:
        run_properties.append(f'<w:sz w:val="{size_half_points}"/>')
    run_properties_xml = f"<w:rPr>{''.join(run_properties)}</w:rPr>" if run_properties else ""
    paragraph_properties = (
        '<w:pPr><w:jc w:val="center"/><w:spacing w:after="180"/></w:pPr>'
        if center
        else '<w:pPr><w:spacing w:after="180"/></w:pPr>'
    )
    return (
        f"<w:p>{paragraph_properties}<w:r>{run_properties_xml}"
        f"<w:t xml:space=\"preserve\">{text_xml}</w:t></w:r></w:p>"
    )


def page_break_xml() -> str:
    return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def image_paragraph_xml(rel_id: str, filename: str, image_id: int, width_px: int, height_px: int) -> str:
    max_width_emu = 5_760_000
    image_width_emu = min(max_width_emu, width_px * 9525)
    image_height_emu = int(image_width_emu * height_px / width_px)
    return f"""
    <w:p>
      <w:pPr><w:spacing w:after="240"/></w:pPr>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0">
            <wp:extent cx="{image_width_emu}" cy="{image_height_emu}"/>
            <wp:effectExtent l="0" t="0" r="0" b="0"/>
            <wp:docPr id="{image_id}" name="Picture {image_id}" descr="{xml_escape(filename)}"/>
            <wp:cNvGraphicFramePr>
              <a:graphicFrameLocks noChangeAspect="1"/>
            </wp:cNvGraphicFramePr>
            <a:graphic>
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic>
                  <pic:nvPicPr>
                    <pic:cNvPr id="{image_id}" name="{xml_escape(filename)}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rel_id}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm>
                      <a:off x="0" y="0"/>
                      <a:ext cx="{image_width_emu}" cy="{image_height_emu}"/>
                    </a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
    """


def build_docx_document(pages: list[TutorialPage]) -> None:
    image_entries: list[dict[str, Any]] = []
    for index, page in enumerate(pages, start=1):
        image_path = SCREENSHOT_DIR / f"{page.slug}.png"
        with Image.open(image_path) as image:
            width_px, height_px = image.size
        image_entries.append(
            {
                "index": index,
                "page": page,
                "path": image_path,
                "width_px": width_px,
                "height_px": height_px,
                "rel_id": f"rId{index}",
                "media_name": f"image{index}.png",
            }
        )

    body_parts: list[str] = [
        paragraph_xml("GLH Timer Tutorial", bold=True, size_half_points=36, center=True),
        paragraph_xml(
            f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')} from a seeded demo environment.",
            center=True,
        ),
        paragraph_xml(
            f"This tutorial walks through the main admin workflow in GLH Timer using the sample race {ONGOING_RACE_ID}.",
        ),
        paragraph_xml("Admin login used for the screenshots: admin / admin"),
        paragraph_xml("Demo organiser accounts included in the data set: racelead and assistant"),
        paragraph_xml("Race statuses reflect the seeded dates around March 20, 2026"),
        page_break_xml(),
    ]

    for position, entry in enumerate(image_entries, start=1):
        page = entry["page"]
        body_parts.append(paragraph_xml(f"{position}. {page.title}", bold=True, size_half_points=28))
        body_parts.append(paragraph_xml(page.description))
        body_parts.append(
            image_paragraph_xml(
                entry["rel_id"],
                entry["media_name"],
                position,
                entry["width_px"],
                entry["height_px"],
            )
        )
        if position != len(image_entries):
            body_parts.append(page_break_xml())

    body_parts.append(
        """
        <w:sectPr>
          <w:pgSz w:w="12240" w:h="15840"/>
          <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="708" w:footer="708" w:gutter="0"/>
        </w:sectPr>
        """
    )

    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
  xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
  xmlns:v="urn:schemas-microsoft-com:vml"
  xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:w10="urn:schemas-microsoft-com:office:word"
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
  xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"
  xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
  xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
  xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
  xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
  mc:Ignorable="w14 w15 wp14">
  <w:body>
    {''.join(body_parts)}
  </w:body>
</w:document>
"""

    document_relationships = [
        f'<Relationship Id="{entry["rel_id"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{entry["media_name"]}"/>'
        for entry in image_entries
    ]
    document_rels_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {''.join(document_relationships)}
</Relationships>
"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""

    root_relationships_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""

    timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>GLH Timer Tutorial</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>
"""

    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Title</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>GLH Timer Tutorial</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>1.0</AppVersion>
</Properties>
"""

    with ZipFile(DOCX_PATH, "w", compression=ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types_xml)
        docx.writestr("_rels/.rels", root_relationships_xml)
        docx.writestr("docProps/core.xml", core_xml)
        docx.writestr("docProps/app.xml", app_xml)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", document_rels_xml)
        for entry in image_entries:
            docx.write(entry["path"], f'word/media/{entry["media_name"]}')


def verify_outputs(pages: list[TutorialPage]) -> None:
    missing = [page.slug for page in pages if not (SCREENSHOT_DIR / f"{page.slug}.png").exists()]
    if missing:
        raise RuntimeError(f"Missing screenshots: {', '.join(missing)}")
    if not HTML_PATH.exists():
        raise RuntimeError(f"Missing HTML output at {HTML_PATH}")
    if not DOCX_PATH.exists() or DOCX_PATH.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty DOCX output at {DOCX_PATH}")


def print_summary(pages: list[TutorialPage]) -> None:
    log(f"Tutorial DOCX: {DOCX_PATH}")
    log(f"Tutorial HTML: {HTML_PATH}")
    log(f"Screenshot directory: {SCREENSHOT_DIR}")
    log(f"Captured pages: {len(pages)}")


def main() -> int:
    require_paths()
    clean_output_dir()
    log("Seeding demo data")
    seed_demo_data()
    with start_server():
        wait_for_url(f"{APP_URL}/login")
        with start_chrome():
            wait_for_url(f"{CHROME_URL}/json/version")
            pages = asyncio.run(capture_screenshots())
        build_html_document(pages)
        build_docx_document(pages)
    verify_outputs(pages)
    print_summary(pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
