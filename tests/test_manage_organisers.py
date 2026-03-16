import os
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db import Base
from app.main import replace_organiser_races
from app.models import Organiser, OrganiserRace, Race


class ReplaceOrganiserRacesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all(
            [
                Race(race_id="race-1", race_date=date(2026, 1, 1), race_timezone="UTC"),
                Race(race_id="race-2", race_date=date(2026, 1, 2), race_timezone="UTC"),
            ]
        )
        organiser = Organiser(username="organiser", password_hash="hash")
        self.db.add(organiser)
        self.db.flush()
        self.organiser_id = organiser.id
        self.db.add(OrganiserRace(organiser_id=organiser.id, race_id="race-1"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_replace_organiser_races_allows_changing_link_count(self) -> None:
        organiser = self.db.get(Organiser, self.organiser_id)
        assert organiser is not None

        replace_organiser_races(self.db, organiser, ["race-1", "race-2"])
        self.db.commit()

        organiser = self.db.get(Organiser, self.organiser_id)
        assert organiser is not None
        self.assertEqual(sorted(link.race_id for link in organiser.races), ["race-1", "race-2"])

        replace_organiser_races(self.db, organiser, ["race-2"])
        self.db.commit()

        organiser = self.db.get(Organiser, self.organiser_id)
        assert organiser is not None
        self.assertEqual([link.race_id for link in organiser.races], ["race-2"])


if __name__ == "__main__":
    unittest.main()
