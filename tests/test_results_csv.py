import asyncio
import csv
import io
import os
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db import Base, SoftDeleteSession
from app.main import download_race_part_results_csv
from app.models import Participant, Race, RacePart, TimingEvent


class ResultsCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = SoftDeleteSession(bind=self.engine)
        now = datetime.now(tz=ZoneInfo("UTC"))

        race = Race(race_id="spring-run", race_date=date(2026, 4, 1), race_timezone="UTC")
        self.db.add(race)
        self.db.add_all(
            [
                RacePart(race_id=race.race_id, race_part_id="Overall", race_order=-1, is_overall=True),
                RacePart(race_id=race.race_id, race_part_id="Leg1", race_order=1, is_overall=False),
                RacePart(race_id=race.race_id, race_part_id="Leg2", race_order=2, is_overall=False),
                Participant(
                    race_id=race.race_id,
                    participant_id=12,
                    first_name="Ada",
                    last_name="Lovelace",
                    group="Open",
                    club="GLH",
                    sex="F",
                ),
                TimingEvent(
                    race_id=race.race_id,
                    race_part_id="Leg1",
                    participant_id=12,
                    group=None,
                    client_time=now,
                    server_time=now,
                    duration_seconds=60,
                    start_time=None,
                    end_time=None,
                ),
                TimingEvent(
                    race_id=race.race_id,
                    race_part_id="Leg2",
                    participant_id=12,
                    group=None,
                    client_time=now,
                    server_time=now,
                    duration_seconds=90,
                    start_time=None,
                    end_time=None,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def read_csv(self, response) -> list[list[str]]:
        async def collect() -> str:
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        content = asyncio.run(collect())
        return list(csv.reader(io.StringIO(content)))

    def test_non_overall_results_csv_downloads_full_results(self) -> None:
        response = download_race_part_results_csv(None, "spring-run", "Leg1", self.db)
        rows = self.read_csv(response)

        self.assertEqual(rows[0], ["position", "bib", "name", "group", "time"])
        self.assertEqual(rows[1], ["1", "12", "Ada Lovelace", "Open", "01:00"])

    def test_overall_results_csv_includes_all_parts_and_overall(self) -> None:
        response = download_race_part_results_csv(None, "spring-run", "Overall", self.db)
        rows = self.read_csv(response)

        self.assertEqual(
            rows[0],
            ["position", "bib", "name", "group", "Leg1", "Leg2", "overall"],
        )
        self.assertEqual(
            rows[1],
            ["1", "12", "Ada Lovelace", "Open", "01:00", "01:30", "02:30"],
        )


if __name__ == "__main__":
    unittest.main()
