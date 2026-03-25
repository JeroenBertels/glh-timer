import os
import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db import Base
from app.main import load_pending_end_events, update_pending_end_event_targets
from app.models import Race, TimingEvent


class PendingEndEventTests(unittest.TestCase):
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

    def test_load_pending_end_events_hides_resolved_empty_entries(self) -> None:
        pending = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=None,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime.now(timezone.utc),
            duration_seconds=None,
            start_time=None,
            end_time=datetime.now(timezone.utc),
            created_by_username="organiser",
            pending_resolved=False,
        )
        resolved = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=None,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime.now(timezone.utc),
            duration_seconds=None,
            start_time=None,
            end_time=datetime.now(timezone.utc),
            created_by_username="organiser",
            pending_resolved=True,
        )
        self.db.add_all([pending, resolved])
        self.db.commit()

        events = load_pending_end_events(self.db, self.race.race_id, "Leg1", "organiser")

        self.assertEqual([event.id for event in events], [pending.id])

    def test_update_pending_end_event_targets_can_resolve_without_target(self) -> None:
        event = TimingEvent(
            race_id=self.race.race_id,
            race_part_id="Leg1",
            participant_id=None,
            group=None,
            client_time=datetime.now(timezone.utc),
            server_time=datetime.now(timezone.utc),
            duration_seconds=None,
            start_time=None,
            end_time=datetime.now(timezone.utc),
            created_by_username="organiser",
            pending_resolved=False,
        )
        self.db.add(event)
        self.db.commit()

        count = update_pending_end_event_targets(
            self.db,
            event,
            "",
            "organiser",
            confirm_empty=True,
        )
        self.db.commit()

        self.assertEqual(count, 0)
        self.assertTrue(event.pending_resolved)
        events = load_pending_end_events(self.db, self.race.race_id, "Leg1", "organiser")
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
