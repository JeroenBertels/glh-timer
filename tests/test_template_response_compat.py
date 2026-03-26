import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from starlette.requests import Request

from app.main import templates


class TemplateResponseCompatibilityTests(unittest.TestCase):
    def test_legacy_name_context_template_response_still_renders(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [],
            }
        )

        response = templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "races": [],
                "user": None,
                "back_url": None,
                "back_label": None,
                "title": None,
            },
        )

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
