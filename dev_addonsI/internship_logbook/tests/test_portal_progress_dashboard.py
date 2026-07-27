from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from odoo.addons.internship_logbook.controllers.portal import (
    InternshipPortal,
)


@tagged("post_install", "-at_install")
class TestPortalProgressDashboard(HttpCase):
    PASSWORD = "Portal-progress-dashboard-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Progress {suffix}",
            "login": f"portal-progress-{suffix}@example.test",
            "email": f"portal-progress-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"].create({
            "name": user.name,
            "student_number": f"PROGRESS-{suffix.upper()}",
            "email": user.email,
            "user_id": user.id,
        })
        return user, student

    def _create_program(
        self,
        student,
        suffix,
        *,
        workflow_mode="independent",
        state="active",
        active=True,
        start_date="2026-07-01",
        end_date="2026-07-10",
    ):
        values = {
            "name": f"Progress Program {suffix}",
            "student_id": student.id,
            "company_name": f"Progress Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "start_date": start_date,
            "end_date": end_date,
            "state": state,
            "active": active,
        }
        if workflow_mode == "supervised":
            values["supervisor_id"] = self.env.ref("base.user_admin").id
        return self.env["internship.program"].with_context(
            active_test=False,
        ).create(values)

    def _create_entry(
        self,
        program,
        suffix,
        entry_date,
        *,
        state="draft",
        work_hours=8,
        supervisor_comment=False,
    ):
        return self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": entry_date,
            "title": f"Progress Entry {suffix}",
            "work_description": f"Progress dashboard work for {suffix}.",
            "work_hours": work_hours,
            "state": state,
            "supervisor_comment": supervisor_comment,
        })

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _dashboard(self, today=date(2026, 7, 5)):
        with patch.object(
            InternshipPortal,
            "_portal_context_today",
            return_value=today,
        ):
            return self.url_open("/my/internship")

    def _document(self, response):
        return html.fromstring(response.content)

    def _metric(self, response, metric):
        values = self._document(response).xpath(
            f"//*[@data-metric='{metric}']/@data-value"
        )
        self.assertEqual(len(values), 1)
        return values[0]

    def test_access_no_program_and_dashboard_navigation(self):
        user, _student = self._create_portal_user("access")
        self._authenticate(user)

        dashboard = self._dashboard()

        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Create Your First Internship", dashboard.text)
        self.assertIn('href="/my/internship/create"', dashboard.text)
        self.assertIn('href="/my/internship/daily"', dashboard.text)

        self.authenticate(None, None)
        public = self.url_open("/my/internship", allow_redirects=False)
        self.assertIn(public.status_code, (302, 303))
        self.assertIn("/web/login", public.headers["Location"])

        ordinary, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        self.assertEqual(self.url_open("/my/internship").status_code, 403)

    def test_active_independent_program_summary_and_labels(self):
        user, student = self._create_portal_user("active-independent")
        program = self._create_program(student, "Active Independent")
        self._authenticate(user)

        response = self._dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertIn(program.name, response.text)
        self.assertIn(program.company_name, response.text)
        self.assertIn("Independent", response.text)
        self.assertIn("Active", response.text)
        self.assertIn("07/01/2026", response.text)
        self.assertIn("07/10/2026", response.text)
        self.assertIn('href="/my/internship/daily/new"', response.text)
        self.assertIn("View All Daily Entries", response.text)

    def test_date_metrics_before_during_and_after_program(self):
        user, student = self._create_portal_user("dates")
        self._create_program(student, "Dates")
        self._authenticate(user)

        cases = (
            (date(2026, 6, 30), "0", "10"),
            (date(2026, 7, 5), "5", "5"),
            (date(2026, 7, 20), "10", "0"),
        )
        for today, elapsed, remaining in cases:
            with self.subTest(today=today):
                response = self._dashboard(today)
                self.assertEqual(
                    self._metric(response, "total-days"),
                    "10",
                )
                self.assertEqual(
                    self._metric(response, "elapsed-days"),
                    elapsed,
                )
                self.assertEqual(
                    self._metric(response, "remaining-days"),
                    remaining,
                )

    def test_entry_metrics_hours_progress_and_foreign_isolation(self):
        user, student = self._create_portal_user("metrics")
        program = self._create_program(student, "Metrics")
        self._create_entry(
            program,
            "Draft",
            "2026-07-01",
            work_hours=2.5,
        )
        for day, hours in ((2, 3.25), (3, 4), (4, 5)):
            self._create_entry(
                program,
                f"Completed {day}",
                f"2026-07-{day:02d}",
                state="completed",
                work_hours=hours,
            )

        _foreign_user, foreign_student = self._create_portal_user(
            "metrics-foreign"
        )
        foreign_program = self._create_program(
            foreign_student,
            "Foreign Secret",
        )
        self._create_entry(
            foreign_program,
            "Foreign Secret",
            "2026-07-01",
            state="completed",
            work_hours=24,
        )
        self._authenticate(user)

        response = self._dashboard()

        self.assertEqual(self._metric(response, "total-entries"), "4")
        self.assertEqual(self._metric(response, "draft-entries"), "1")
        self.assertEqual(self._metric(response, "completed-entries"), "3")
        self.assertEqual(self._metric(response, "recorded-hours"), "14.75")
        progress = self._document(response).xpath(
            "//*[@role='progressbar']/@aria-valuenow"
        )
        self.assertEqual(progress, ["30.0"])
        self.assertNotIn("Foreign Secret", response.text)

    def test_other_states_are_not_counted_as_completed(self):
        user, student = self._create_portal_user("supervised")
        program = self._create_program(
            student,
            "Supervised",
            workflow_mode="supervised",
        )
        entry = self.env["internship.daily.entry"]
        for day, state in enumerate(
            ("draft", "submitted", "revision", "approved"),
            start=1,
        ):
            entry = self._create_entry(
                program,
                f"Supervised {state}",
                f"2026-07-{day:02d}",
                state=state,
                work_hours=day,
                supervisor_comment=(
                    "Private supervisor comment must never appear."
                    if state == "revision"
                    else False
                ),
            )
        entry.message_post(body="Private chatter content must not appear.")
        self._authenticate(user)

        response = self._dashboard()

        self.assertIn("Supervised", response.text)
        self.assertEqual(self._metric(response, "total-entries"), "4")
        self.assertEqual(self._metric(response, "draft-entries"), "1")
        self.assertEqual(self._metric(response, "completed-entries"), "0")
        self.assertEqual(self._metric(response, "other-entries"), "3")
        self.assertNotIn(
            "Private supervisor comment must never appear.",
            response.text,
        )
        self.assertNotIn(
            "Private chatter content must not appear.",
            response.text,
        )
        self.assertNotIn('href="/my/internship/daily/new"', response.text)

    def test_progress_is_clamped_and_draft_does_not_increase_it(self):
        user, student = self._create_portal_user("clamp")
        program = self._create_program(
            student,
            "Clamp",
            start_date="2026-07-01",
            end_date="2026-07-02",
        )
        self._create_entry(
            program,
            "Completed One",
            "2026-07-01",
            state="completed",
        )
        self._create_entry(
            program,
            "Draft Does Not Count",
            "2026-07-02",
        )
        self._authenticate(user)

        response = self._dashboard()

        progress = self._document(response).xpath(
            "//*[@role='progressbar']/@aria-valuenow"
        )
        self.assertEqual(progress, ["50.0"])
        self.assertEqual(self._metric(response, "completed-entries"), "1")
        self.assertEqual(self._metric(response, "draft-entries"), "1")

        controller = InternshipPortal()
        with (
            patch.object(
                controller,
                "_portal_program_date_metrics",
                return_value={
                    "valid": True,
                    "total_program_days": 2,
                    "elapsed_program_days": 2,
                    "remaining_program_days": 0,
                },
            ),
            patch.object(
                controller,
                "_portal_program_entry_metrics",
                return_value={
                    "total_entry_count": 3,
                    "draft_entry_count": 0,
                    "completed_entry_count": 3,
                    "other_entry_count": 0,
                    "total_work_hours": 24.0,
                },
            ),
        ):
            clamped = controller._portal_program_progress(
                SimpleNamespace(),
                SimpleNamespace(),
            )
        self.assertEqual(clamped["progress_percentage"], 100.0)

    def test_recent_entries_are_owned_ordered_and_limited(self):
        user, student = self._create_portal_user("recent")
        program = self._create_program(student, "Recent")
        titles = []
        for day in range(1, 7):
            entry = self._create_entry(
                program,
                f"Recent {day}",
                f"2026-07-{day:02d}",
                state="completed",
            )
            titles.append(entry.title)
        self._authenticate(user)

        response = self._dashboard()

        self.assertNotIn(titles[0], response.text)
        for title in titles[1:]:
            self.assertIn(title, response.text)
        positions = [response.text.index(title) for title in reversed(titles[1:])]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('href="/my/internship/daily"', response.text)

    def test_empty_recent_entries_render_safely(self):
        user, student = self._create_portal_user("empty")
        self._create_program(student, "Empty")
        self._authenticate(user)

        response = self._dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertIn("No daily entries yet.", response.text)
        self.assertEqual(self._metric(response, "total-entries"), "0")
        self.assertEqual(self._metric(response, "recorded-hours"), "0.0")

    def test_historical_and_draft_program_policy_is_read_only(self):
        cases = (
            ("draft", "Draft"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        )
        for suffix, state_label in cases:
            with self.subTest(state=state_label):
                user, student = self._create_portal_user(
                    f"historical-{suffix}"
                )
                program = self._create_program(
                    student,
                    f"Historical {suffix}",
                    state=suffix,
                )
                self._authenticate(user)

                response = self._dashboard()

                self.assertIn(program.name, response.text)
                self.assertIn(state_label, response.text)
                if suffix == "draft":
                    self.assertIn(
                        "waiting to be",
                        response.text,
                    )
                else:
                    self.assertIn(
                        "shown below as a read-only summary",
                        response.text,
                    )
                self.assertNotIn(
                    'href="/my/internship/daily/new"',
                    response.text,
                )

    def test_most_recent_historical_program_is_selected(self):
        user, student = self._create_portal_user("historical-selection")
        older = self._create_program(
            student,
            "Older Historical",
            state="completed",
            start_date="2025-01-01",
            end_date="2025-01-10",
        )
        newer = self._create_program(
            student,
            "Newer Historical",
            state="completed",
            start_date="2026-01-01",
            end_date="2026-01-10",
        )
        self._authenticate(user)

        response = self._dashboard()

        self.assertIn(newer.name, response.text)
        self.assertNotIn(older.name, response.text)

    def test_multiple_active_programs_show_ambiguity_without_mixing(self):
        user, student = self._create_portal_user("ambiguous")
        first = self._create_program(
            student,
            "Ambiguous First",
            start_date="2025-01-01",
            end_date="2025-01-10",
        )
        second = self._create_program(
            student,
            "Ambiguous Second",
            start_date="2026-01-01",
            end_date="2026-01-10",
        )
        self._create_entry(
            first,
            "Must Not Aggregate First",
            "2025-01-01",
        )
        self._create_entry(
            second,
            "Must Not Aggregate Second",
            "2026-01-01",
        )
        self._authenticate(user)

        response = self._dashboard()

        self.assertIn("More than one active internship program", response.text)
        self.assertNotIn(first.name, response.text)
        self.assertNotIn(second.name, response.text)
        self.assertNotIn("Must Not Aggregate First", response.text)
        self.assertNotIn("Must Not Aggregate Second", response.text)
        self.assertNotIn(
            'href="/my/internship/daily/new"',
            response.text,
        )
        self.assertFalse(
            self._document(response).xpath("//*[@data-metric]")
        )

    def test_legacy_zero_work_hours_are_handled_safely(self):
        user, student = self._create_portal_user("legacy-hours")
        program = self._create_program(student, "Legacy Hours")
        entry = self._create_entry(
            program,
            "Legacy Zero Hours",
            "2026-07-01",
        )
        self.env.cr.execute(
            "UPDATE internship_daily_entry "
            "SET work_hours = 0 WHERE id = %s",
            [entry.id],
        )
        entry.invalidate_recordset()
        self._authenticate(user)

        response = self._dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._metric(response, "total-entries"), "1")
        self.assertEqual(self._metric(response, "recorded-hours"), "0.0")

    def test_invalid_legacy_date_metrics_are_safe(self):
        controller = InternshipPortal()
        missing = SimpleNamespace(start_date=False, end_date=False)
        reversed_dates = SimpleNamespace(
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 1),
        )

        for program in (missing, reversed_dates):
            with self.subTest(program=program):
                metrics = controller._portal_program_date_metrics(
                    program,
                    today=date(2026, 7, 5),
                )
                self.assertFalse(metrics["valid"])
                self.assertEqual(metrics["total_program_days"], 0)
                self.assertEqual(metrics["elapsed_program_days"], 0)
                self.assertEqual(metrics["remaining_program_days"], 0)

    def test_dashboard_adds_no_state_changing_entry_controls(self):
        user, student = self._create_portal_user("controls")
        program = self._create_program(student, "Controls")
        self._create_entry(program, "Control Draft", "2026-07-01")
        self._authenticate(user)

        response = self._dashboard()

        self.assertNotIn("/submit-confirm", response.text)
        self.assertNotIn("/edit", response.text)
        self.assertNotIn("Delete Daily Entry", response.text)
        self.assertNotIn("Approve Daily Entry", response.text)
        self.assertNotIn("Request Revision", response.text)
