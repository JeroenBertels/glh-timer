import os
import unittest
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.main import templates


class ActionCardVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.race = SimpleNamespace(race_id="spring-run", race_date=date(2026, 4, 1))
        self.part = SimpleNamespace(race_part_id="Leg1", is_overall=False)
        self.overall_part = SimpleNamespace(race_part_id="Overall", is_overall=True)
        self.parts = [self.part, self.overall_part]

    def render(self, template_name: str, **context: object) -> str:
        template = templates.env.get_template(template_name)
        base_context = {
            "request": None,
            "back_url": None,
            "back_label": None,
            "title": None,
        }
        base_context.update(context)
        return template.render(base_context)

    def test_home_hides_admin_action_card_when_logged_out(self) -> None:
        html = self.render("home.html", races=[], user=None)

        self.assertNotIn("Manage Races", html)
        self.assertEqual(html.count('<div class="card">'), 1)

    def test_home_shows_admin_action_card_when_logged_in(self) -> None:
        html = self.render("home.html", races=[], user={"role": "admin"})

        self.assertIn("Manage Races", html)
        self.assertEqual(html.count('<div class="card">'), 2)

    def test_race_hides_action_card_when_logged_out(self) -> None:
        html = self.render(
            "race.html",
            race=self.race,
            race_parts=[self.part, self.overall_part],
            user=None,
        )

        self.assertNotIn("Manage Race Parts", html)
        self.assertEqual(html.count('<div class="card">'), 1)

    def test_race_shows_action_card_for_allowed_user(self) -> None:
        html = self.render(
            "race.html",
            race=self.race,
            race_parts=[self.part, self.overall_part],
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn("Manage Race Parts", html)
        self.assertNotIn("Download QR Codes", html)
        self.assertEqual(html.count('<div class="card">'), 2)

    def test_manage_participants_shows_qr_codes_before_download_csv(self) -> None:
        html = self.render(
            "manage_participants.html",
            race=self.race,
            participants=[],
            error=None,
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn("Download QR Codes", html)
        self.assertIn("Download CSV", html)
        self.assertLess(html.index("Download QR Codes"), html.index("Download CSV"))

    def test_race_part_results_hide_action_card_when_logged_out(self) -> None:
        html = self.render(
            "race_part_results.html",
            race=self.race,
            race_part=self.part,
            rows=[],
            group_filters=[],
            sex_filters=[],
            parts=self.parts,
            groups=[],
            sexes=[],
            user=None,
        )

        self.assertNotIn("Manage Timing Events", html)
        self.assertEqual(html.count('<div class="card">'), 2)

    def test_race_part_results_show_action_card_for_allowed_user(self) -> None:
        html = self.render(
            "race_part_results.html",
            race=self.race,
            race_part=self.part,
            rows=[],
            group_filters=[],
            sex_filters=[],
            parts=self.parts,
            groups=[],
            sexes=[],
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn("Manage Timing Events", html)
        self.assertEqual(html.count('<div class="card">'), 3)
        self.assertLess(
            html.index("Manage Timing Events"),
            html.index("Group filter (multi-select)"),
        )

    def test_race_part_results_show_download_csv_button(self) -> None:
        html = self.render(
            "race_part_results.html",
            race=self.race,
            race_part=self.part,
            rows=[],
            group_filters=[],
            sex_filters=[],
            parts=self.parts,
            groups=[],
            sexes=[],
            user=None,
        )

        self.assertIn("Download CSV", html)
        self.assertIn(
            f'/race/{self.race.race_id}/part/{self.part.race_part_id}/results.csv',
            html,
        )

    def test_submit_start_defaults_to_open_live_timer(self) -> None:
        html = self.render(
            "submit_start.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn(
            '<input type="checkbox" name="auto_show_timer" value="true" checked />',
            html,
        )

    def test_submit_end_renders_timer_toggle_card(self) -> None:
        html = self.render(
            "submit_end.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            pending_end_events=[],
            start_events=[],
            selected_start_event_choice="latest",
            start_events_endpoint=f"/race/{self.race.race_id}/part/{self.part.race_part_id}/timer/start-events",
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn('id="toggle-timer"', html)
        self.assertIn("Show Timer", html)
        self.assertIn('id="submit-end-timer-panel" hidden', html)

    def test_submit_end_script_uses_stacked_pending_event_rows(self) -> None:
        html = self.render(
            "submit_end.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            pending_end_events=[],
            start_events=[],
            selected_start_event_choice="latest",
            start_events_endpoint=f"/race/{self.race.race_id}/part/{self.part.race_part_id}/timer/start-events",
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn("pending-end-meta", html)
        self.assertIn("pending-end-controls", html)
        self.assertIn("pending-end-caption", html)
        self.assertIn("row.append(meta, caption, controls);", html)

    def test_submit_end_renders_pending_max_counter_summary(self) -> None:
        html = self.render(
            "submit_end.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            pending_end_events=[],
            start_events=[],
            selected_start_event_choice="latest",
            start_events_endpoint=f"/race/{self.race.race_id}/part/{self.part.race_part_id}/timer/start-events",
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn('id="pending-end-max-counter"', html)
        self.assertIn("Rank: -", html)
        self.assertIn("refreshPendingMaxCounter()", html)

    def test_submit_end_timer_defaults_to_last_submitted_option(self) -> None:
        html = self.render(
            "submit_end.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            pending_end_events=[],
            start_events=[],
            selected_start_event_choice="latest",
            start_events_endpoint=f"/race/{self.race.race_id}/part/{self.part.race_part_id}/timer/start-events",
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn('option value="latest" selected', html)
        self.assertIn("Last Submitted", html)
        self.assertIn("syncStartEvents", html)

    def test_wave_starts_uses_shared_digital_timer_markup(self) -> None:
        html = self.render(
            "wave_starts.html",
            race=self.race,
            race_part_id=self.part.race_part_id,
            user={"role": "admin", "race_ids": [self.race.race_id]},
        )

        self.assertIn('id="wave-live-timer-panel"', html)
        self.assertIn('class="digital-timer wave-live-timer"', html)


if __name__ == "__main__":
    unittest.main()
