import os
import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db import Base
from app.main import (
    START_TIMER_LAST_SUBMITTED,
    load_start_timer_events,
    selected_start_timer_choice,
)
from app.models import Race, TimingEvent


class TimerStartEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.race = Race(
            race_id="spring-run",
            race_date=date(2026, 4, 1),
            race_timezone="UTC",
        )
        self.db.add(self.race)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_load_start_timer_events_matches_show_timer_order_and_labels(self) -> None:
        ignored_end_event = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=7,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime(2026, 4, 1, 8, 10, tzinfo=timezone.utc),
            duration_seconds=None,
            start_time=None,
            end_time=datetime(2026, 4, 1, 8, 9, tzinfo=timezone.utc),
        )
        manual_start = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=None,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime(2026, 4, 1, 8, 31, tzinfo=timezone.utc),
            duration_seconds=None,
            start_time=datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
            end_time=None,
        )
        group_start = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=None,
            group="Open",
            client_time=datetime.now(timezone.utc),
            server_time=datetime(2026, 4, 1, 9, 1, tzinfo=timezone.utc),
            duration_seconds=None,
            start_time=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
            end_time=None,
        )
        bib_start = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=12,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime(2026, 4, 1, 9, 6, tzinfo=timezone.utc),
            duration_seconds=None,
            start_time=datetime(2026, 4, 1, 9, 5, tzinfo=timezone.utc),
            end_time=None,
        )
        self.db.add_all([ignored_end_event, manual_start, group_start, bib_start])
        self.db.commit()

        start_events = load_start_timer_events(self.db, self.race, "Leg1")

        self.assertEqual(
            [event["id"] for event in start_events],
            [bib_start.id, group_start.id, manual_start.id],
        )
        self.assertEqual(
            [event["target_label"] for event in start_events],
            ["Bib 12", "Group Open", "Manual entry"],
        )
        self.assertEqual(
            [event["start_label"] for event in start_events],
            ["09:05:00", "09:00:00", "08:30:00"],
        )
        self.assertEqual(
            selected_start_timer_choice(start_events),
            START_TIMER_LAST_SUBMITTED,
        )
        self.assertEqual(
            selected_start_timer_choice(start_events, str(manual_start.id)),
            str(manual_start.id),
        )
        self.assertEqual(
            selected_start_timer_choice(start_events, "999999"),
            START_TIMER_LAST_SUBMITTED,
        )
        self.assertEqual(
            selected_start_timer_choice(start_events, START_TIMER_LAST_SUBMITTED),
            START_TIMER_LAST_SUBMITTED,
        )


if __name__ == "__main__":
    unittest.main()
