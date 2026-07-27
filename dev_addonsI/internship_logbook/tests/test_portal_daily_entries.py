from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalDailyEntries(HttpCase):
    PASSWORD = "Portal-daily-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True, student=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Daily {suffix}",
            "login": f"portal-daily-{suffix}@example.test",
            "email": f"portal-daily-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student_record = self.env["internship.student"]
        if student:
            student_record = self.env["internship.student"].create({
                "name": user.name,
                "student_number": f"DAILY-{suffix.upper()}",
                "email": user.email,
                "user_id": user.id,
            })
        return user, student_record

    def _create_program(self, student, suffix):
        return self.env["internship.program"].create({
            "name": f"Portal Daily Program {suffix}",
            "student_id": student.id,
            "company_name": f"Portal Daily Company {suffix}",
            "department": "Engineering",
            "workflow_mode": "independent",
            "start_date": "2028-03-01",
            "end_date": "2028-03-31",
            "state": "active",
        })

    def _create_entry(self, program, title, entry_date, **overrides):
        values = {
            "program_id": program.id,
            "title": title,
            "entry_date": entry_date,
            "work_hours": 8,
            "work_description": f"Read-only portal test for {title}.",
        }
        values.update(overrides)
        return self.env["internship.daily.entry"].create(values)

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def test_valid_portal_intern_can_open_daily_list(self):
        user, student = self._create_portal_user("valid")
        self._create_program(student, "valid")
        self._authenticate(user)

        response = self.url_open("/my/internship/daily")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Daily Internship Entries", response.text)

    def test_public_visitor_is_redirected_to_login(self):
        self.authenticate(None, None)
        public_response = self.url_open(
            "/my/internship/daily",
            allow_redirects=False,
        )
        self.assertIn(public_response.status_code, (302, 303))
        self.assertIn("/web/login", public_response.headers["Location"])

    def test_ordinary_portal_access_is_denied(self):
        portal_user, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(portal_user)

        ordinary_response = self.url_open("/my/internship/daily")

        self.assertEqual(ordinary_response.status_code, 403)

    def test_no_program_renders_safe_empty_state(self):
        no_program_user, _student = self._create_portal_user("no-program")
        self._authenticate(no_program_user)

        no_program_response = self.url_open("/my/internship/daily")

        self.assertEqual(no_program_response.status_code, 200)
        self.assertIn("Create your first internship", no_program_response.text)
        self.assertIn('href="/my/internship"', no_program_response.text)

    def test_program_without_entries_renders_empty_list(self):
        no_entry_user, no_entry_student = self._create_portal_user("no-entry")
        self._create_program(no_entry_student, "no-entry")
        self._authenticate(no_entry_user)

        no_entry_response = self.url_open("/my/internship/daily")

        self.assertEqual(no_entry_response.status_code, 200)
        self.assertIn("No daily entries yet.", no_entry_response.text)

    def test_only_owned_entries_are_rendered_and_filters_are_ignored(self):
        user, student = self._create_portal_user("ownership")
        program = self._create_program(student, "ownership")
        self._create_entry(
            program,
            "Own Older Entry Unique",
            "2028-03-04",
            state="completed",
        )
        self._create_entry(
            program,
            "Own Newer Entry Unique",
            "2028-03-09",
        )

        _other_user, other_student = self._create_portal_user("other")
        other_program = self._create_program(other_student, "other")
        self._create_entry(
            other_program,
            "Other Intern Private Entry Unique",
            "2028-03-10",
        )
        self._authenticate(user)

        response = self.url_open(
            "/my/internship/daily"
            f"?student_id={other_student.id}&program_id={other_program.id}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Own Older Entry Unique", response.text)
        self.assertIn("Own Newer Entry Unique", response.text)
        self.assertNotIn("Other Intern Private Entry Unique", response.text)

    def test_entries_are_rendered_newest_date_first(self):
        user, student = self._create_portal_user("ordering")
        program = self._create_program(student, "ordering")
        self._create_entry(
            program,
            "Ordering Older Entry Unique",
            "2028-03-04",
            state="completed",
        )
        self._create_entry(
            program,
            "Ordering Newer Entry Unique",
            "2028-03-09",
        )
        self._authenticate(user)

        response = self.url_open("/my/internship/daily")

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            response.text.index("Ordering Newer Entry Unique"),
            response.text.index("Ordering Older Entry Unique"),
        )
        self.assertIn("Completed", response.text)
        self.assertIn("Draft", response.text)

    def test_dashboard_contains_daily_entries_link(self):
        user, _student = self._create_portal_user("dashboard-link")
        self._authenticate(user)

        response = self.url_open("/my/internship")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/my/internship/daily"', response.text)
        self.assertIn("Daily Entries", response.text)
