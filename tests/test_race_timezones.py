import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.main import DEFAULT_RACE_TIMEZONE, race_timezone_options


class RaceTimezoneOptionsTests(unittest.TestCase):
    def test_default_timezone_is_first_option(self) -> None:
        options = race_timezone_options()

        self.assertGreater(len(options), 0)
        self.assertEqual(options[0], DEFAULT_RACE_TIMEZONE)
        self.assertEqual(options.count(DEFAULT_RACE_TIMEZONE), 1)
        self.assertIn("UTC", options)

    def test_selected_timezone_is_preserved_once(self) -> None:
        selected_timezone = "America/New_York"

        options = race_timezone_options(selected_timezone)

        self.assertEqual(options[0], DEFAULT_RACE_TIMEZONE)
        self.assertIn(selected_timezone, options)
        self.assertEqual(options.count(selected_timezone), 1)

    def test_unknown_selected_timezone_is_kept_for_editing(self) -> None:
        selected_timezone = "Legacy/Custom-Timezone"

        options = race_timezone_options(selected_timezone)

        self.assertEqual(options[:2], [DEFAULT_RACE_TIMEZONE, selected_timezone])
        self.assertEqual(options.count(selected_timezone), 1)


if __name__ == "__main__":
    unittest.main()
