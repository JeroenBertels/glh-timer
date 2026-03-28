import os
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db import Base, SoftDeleteSession
from app.main import archive_race, archived_race, permanently_delete_race, restore_race, with_deleted
from app.models import Organiser, OrganiserRace, Participant, Race, RacePart, TimingEvent


class RaceArchivingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = SoftDeleteSession(bind=self.engine)
        now = datetime.now(tz=ZoneInfo("UTC"))

        race = Race(race_id="race-1", race_date=date(2026, 1, 1), race_timezone="UTC")
        organiser = Organiser(username="organiser", password_hash="hash")
        self.db.add_all([race, organiser])
        self.db.flush()
        self.db.add_all(
            [
                OrganiserRace(organiser_id=organiser.id, race_id=race.race_id),
                RacePart(
                    race_id=race.race_id,
                    race_part_id="Leg1",
                    race_order=1,
                    is_overall=False,
                ),
                Participant(
                    race_id=race.race_id,
                    participant_id=101,
                    first_name="Ada",
                    last_name="Lovelace",
                    group="Open",
                    club="GLH",
                    sex="F",
                ),
                TimingEvent(
                    race_id=race.race_id,
                    race_part_id="Leg1",
                    participant_id=101,
                    group=None,
                    client_time=now,
                    server_time=now,
                    duration_seconds=120,
                    start_time=None,
                    end_time=None,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_archive_race_hides_linked_rows_from_default_queries(self) -> None:
        race = self.db.get(Race, "race-1")
        assert race is not None

        archive_race(self.db, race, "admin")
        self.db.commit()

        self.assertIsNone(self.db.get(Race, "race-1"))
        self.assertEqual(self.db.scalars(select(Race)).all(), [])
        self.assertEqual(self.db.scalars(select(RacePart)).all(), [])
        self.assertEqual(self.db.scalars(select(Participant)).all(), [])
        self.assertEqual(self.db.scalars(select(TimingEvent)).all(), [])

        archived = archived_race("race-1", self.db)
        assert archived is not None
        self.assertEqual(archived.deleted_by, "admin")

    def test_restore_race_restores_linked_rows(self) -> None:
        race = self.db.get(Race, "race-1")
        assert race is not None

        archive_race(self.db, race, "admin")
        self.db.commit()

        archived = archived_race("race-1", self.db)
        assert archived is not None
        restore_race(self.db, archived)
        self.db.commit()

        restored = self.db.get(Race, "race-1")
        assert restored is not None
        self.assertIsNotNone(self.db.scalar(select(RacePart).where(RacePart.race_id == "race-1")))
        self.assertIsNotNone(
            self.db.scalar(select(Participant).where(Participant.race_id == "race-1"))
        )
        self.assertIsNotNone(
            self.db.scalar(select(TimingEvent).where(TimingEvent.race_id == "race-1"))
        )

    def test_permanent_delete_removes_archived_race_tree(self) -> None:
        race = self.db.get(Race, "race-1")
        assert race is not None

        archive_race(self.db, race, "admin")
        self.db.commit()

        archived = archived_race("race-1", self.db)
        assert archived is not None
        permanently_delete_race(self.db, archived)
        self.db.commit()

        self.assertIsNone(
            self.db.scalar(with_deleted(select(Race).where(Race.race_id == "race-1")))
        )
        self.assertEqual(
            self.db.scalars(with_deleted(select(RacePart).where(RacePart.race_id == "race-1"))).all(),
            [],
        )
        self.assertEqual(
            self.db.scalars(
                with_deleted(select(Participant).where(Participant.race_id == "race-1"))
            ).all(),
            [],
        )
        self.assertEqual(
            self.db.scalars(
                with_deleted(select(TimingEvent).where(TimingEvent.race_id == "race-1"))
            ).all(),
            [],
        )
        self.assertEqual(
            self.db.scalars(select(OrganiserRace).where(OrganiserRace.race_id == "race-1")).all(),
            [],
        )


if __name__ == "__main__":
    unittest.main()
