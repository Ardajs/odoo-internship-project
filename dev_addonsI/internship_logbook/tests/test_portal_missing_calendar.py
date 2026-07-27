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
class TestPortalMissingCalendar(HttpCase):
    PASSWORD = "Portal-missing-calendar-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Calendar {suffix}",
            "login": f"portal-calendar-{suffix}@example.test",
            "email": f"portal-calendar-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"].create({
            "name": user.name,
            "student_number": f"CALENDAR-{suffix.upper()}",
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
            "name": f"Calendar Program {suffix}",
            "student_id": student.id,
            "company_name": f"Calendar Company {suffix}",
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
            "title": f"Calendar Entry {suffix}",
            "work_description": f"Calendar work for {suffix}.",
            "work_hours": work_hours,
            "state": state,
            "supervisor_comment": supervisor_comment,
        })

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _open(self, path, *, today=date(2026, 7, 5), **kwargs):
        with patch.object(
            InternshipPortal,
            "_portal_context_today",
            return_value=today,
        ):
            return self.url_open(path, **kwargs)

    def _document(self, response):
        return html.fromstring(response.content)

    def _status_dates(self, response, status):
        return self._document(response).xpath(
            f"//*[@data-calendar-status='{status}']"
            "/@data-calendar-date"
        )

    def _missing_count(self, response):
        values = self._document(response).xpath(
            "//*[@data-calendar-missing-count='true']/text()"
        )
        self.assertEqual(len(values), 1)
        return int(values[0].strip())

    def test_calendar_access_public_and_ordinary_portal(self):
        user, student = self._create_portal_user("access")
        program = self._create_program(student, "Access")
        self._authenticate(user)

        response = self._open("/my/internship/calendar")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Internship Calendar", response.text)
        self.assertIn(program.name, response.text)

        self.authenticate(None, None)
        public = self.url_open(
            "/my/internship/calendar",
            allow_redirects=False,
        )
        self.assertIn(public.status_code, (302, 303))
        self.assertIn("/web/login", public.headers["Location"])

        ordinary, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        self.assertEqual(
            self.url_open("/my/internship/calendar").status_code,
            403,
        )

    def test_no_program_and_multiple_active_are_safe(self):
        no_program_user, _student = self._create_portal_user("no-program")
        self._authenticate(no_program_user)
        no_program = self._open("/my/internship/calendar")
        self.assertEqual(no_program.status_code, 200)
        self.assertIn("No internship program has been created", no_program.text)

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
        self._authenticate(user)
        ambiguous = self._open("/my/internship/calendar")
        self.assertIn("More than one active internship program", ambiguous.text)
        self.assertNotIn(first.name, ambiguous.text)
        self.assertNotIn(second.name, ambiguous.text)
        self.assertFalse(
            self._document(ambiguous).xpath("//*[@data-calendar-date]")
        )
        self.assertNotIn('href="/my/internship/daily/new"', ambiguous.text)

    def test_ownership_scope_ignores_foreign_and_request_parameters(self):
        user, student = self._create_portal_user("owner")
        program = self._create_program(student, "Owned")
        own_entry = self._create_entry(
            program,
            "Owned Completed",
            "2026-07-01",
            state="completed",
        )
        own_entry.message_post(body="Private chatter must not appear.")

        _foreign_user, foreign_student = self._create_portal_user("foreign")
        foreign_program = self._create_program(foreign_student, "Foreign")
        foreign_entry = self._create_entry(
            foreign_program,
            "Foreign Secret",
            "2026-07-02",
            state="completed",
            supervisor_comment="Private supervisor comment.",
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship/calendar"
            f"?student_id={foreign_student.id}"
            f"&program_id={foreign_program.id}"
            "&start_date=1900-01-01&end_date=2100-01-01"
            "&state=completed"
        )

        self.assertIn(program.name, response.text)
        self.assertIn(own_entry.title, response.text)
        self.assertNotIn(foreign_program.name, response.text)
        self.assertNotIn(foreign_entry.title, response.text)
        self.assertNotIn("Private supervisor comment.", response.text)
        self.assertNotIn("Private chatter must not appear.", response.text)
        self.assertEqual(self._status_dates(response, "completed"), [
            "2026-07-01"
        ])

    def test_another_owned_program_does_not_affect_selected_program(self):
        user, student = self._create_portal_user("owned-history")
        active_program = self._create_program(student, "Selected Active")
        historical = self._create_program(
            student,
            "Other Historical",
            state="completed",
            start_date="2025-07-01",
            end_date="2025-07-10",
        )
        other_entry = self._create_entry(
            historical,
            "Other Program Secret",
            "2025-07-01",
            state="completed",
        )
        self._authenticate(user)

        response = self._open("/my/internship/calendar")

        self.assertIn(active_program.name, response.text)
        self.assertNotIn(historical.name, response.text)
        self.assertNotIn(other_entry.title, response.text)
        self.assertEqual(self._missing_count(response), 5)

    def test_future_program_and_one_day_future_semantics(self):
        user, student = self._create_portal_user("future")
        self._create_program(
            student,
            "Future One Day",
            start_date="2026-08-01",
            end_date="2026-08-01",
        )
        self._authenticate(user)

        calendar = self._open("/my/internship/calendar")
        dashboard = self._open("/my/internship")

        self.assertEqual(self._missing_count(calendar), 0)
        self.assertEqual(self._status_dates(calendar, "future"), [
            "2026-08-01"
        ])
        self.assertIn("The internship has not started yet.", calendar.text)
        self.assertIn("The internship has not started yet.", dashboard.text)

    def test_existing_future_entry_is_shown_and_inactive_entry_is_ignored(self):
        user, student = self._create_portal_user("entry-activity")
        program = self._create_program(
            student,
            "Entry Activity",
            start_date="2026-07-05",
            end_date="2026-07-06",
        )
        inactive_entry = self._create_entry(
            program,
            "Inactive Completed",
            "2026-07-05",
            state="completed",
        )
        inactive_entry.write({"active": False})
        future_entry = self._create_entry(
            program,
            "Future Draft Exists",
            "2026-07-06",
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship/calendar",
            today=date(2026, 7, 5),
        )

        self.assertEqual(self._status_dates(response, "missing"), [
            "2026-07-05"
        ])
        self.assertEqual(self._status_dates(response, "draft"), [
            "2026-07-06"
        ])
        self.assertFalse(self._status_dates(response, "future"))
        self.assertNotIn(inactive_entry.title, response.text)
        self.assertIn(future_entry.title, response.text)

    def test_one_day_missing_draft_completed_and_other_states(self):
        cases = (
            ("missing", "independent", False, "missing"),
            ("draft", "independent", "draft", "draft"),
            ("completed", "independent", "completed", "completed"),
            ("other", "supervised", "approved", "other"),
        )
        for suffix, mode, entry_state, expected_status in cases:
            with self.subTest(status=expected_status):
                user, student = self._create_portal_user(f"one-{suffix}")
                program = self._create_program(
                    student,
                    f"One {suffix}",
                    workflow_mode=mode,
                    start_date="2026-07-05",
                    end_date="2026-07-05",
                )
                if entry_state:
                    self._create_entry(
                        program,
                        f"One {suffix}",
                        "2026-07-05",
                        state=entry_state,
                    )
                self._authenticate(user)
                response = self._open("/my/internship/calendar")

                self.assertEqual(
                    self._status_dates(response, expected_status),
                    ["2026-07-05"],
                )
                expected_missing = 1 if expected_status == "missing" else 0
                self.assertEqual(self._missing_count(response), expected_missing)
                if expected_status == "other":
                    self.assertIn("Approved", response.text)

    def test_ongoing_range_future_and_calendar_day_weekend_semantics(self):
        user, student = self._create_portal_user("ongoing")
        program = self._create_program(
            student,
            "Weekend Ongoing",
            start_date="2026-07-03",
            end_date="2026-07-07",
        )
        self._create_entry(
            program,
            "Friday Draft",
            "2026-07-03",
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship/calendar",
            today=date(2026, 7, 5),
        )

        self.assertEqual(self._status_dates(response, "draft"), [
            "2026-07-03"
        ])
        self.assertEqual(self._status_dates(response, "missing"), [
            "2026-07-04",
            "2026-07-05",
        ])
        self.assertEqual(self._status_dates(response, "future"), [
            "2026-07-06",
            "2026-07-07",
        ])
        self.assertIn("Saturdays,", response.text)
        self.assertIn("public holidays are not excluded", response.text)

    def test_ended_program_uses_full_inclusive_range(self):
        user, student = self._create_portal_user("ended")
        self._create_program(
            student,
            "Ended",
            start_date="2026-06-29",
            end_date="2026-07-02",
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship/calendar",
            today=date(2026, 7, 20),
        )

        self.assertEqual(self._missing_count(response), 4)
        self.assertEqual(self._status_dates(response, "missing"), [
            "2026-06-29",
            "2026-06-30",
            "2026-07-01",
            "2026-07-02",
        ])
        months = self._document(response).xpath(
            "//*[@data-calendar-month]/@data-calendar-month"
        )
        self.assertEqual(months, ["2026-06", "2026-07"])

    def test_leap_month_and_year_boundaries(self):
        cases = (
            (
                "leap",
                "2028-02-28",
                "2028-03-01",
                date(2028, 3, 2),
                ["2028-02", "2028-03"],
                ["2028-02-28", "2028-02-29", "2028-03-01"],
            ),
            (
                "year",
                "2026-12-31",
                "2027-01-01",
                date(2027, 1, 2),
                ["2026-12", "2027-01"],
                ["2026-12-31", "2027-01-01"],
            ),
        )
        for suffix, start, end, today, expected_months, expected_dates in cases:
            with self.subTest(suffix=suffix):
                user, student = self._create_portal_user(suffix)
                self._create_program(
                    student,
                    suffix,
                    start_date=start,
                    end_date=end,
                )
                self._authenticate(user)
                response = self._open(
                    "/my/internship/calendar",
                    today=today,
                )
                months = self._document(response).xpath(
                    "//*[@data-calendar-month]/@data-calendar-month"
                )
                self.assertEqual(months, expected_months)
                self.assertEqual(
                    self._status_dates(response, "missing"),
                    expected_dates,
                )

    def test_missing_count_preview_limit_and_oldest_first_order(self):
        user, student = self._create_portal_user("preview")
        self._create_program(student, "Preview")
        self._authenticate(user)

        dashboard = self._open(
            "/my/internship",
            today=date(2026, 7, 8),
        )

        document = self._document(dashboard)
        count = document.xpath(
            "//*[@data-metric='missing-days']/@data-value"
        )
        preview = [
            value.strip()
            for value in document.xpath(
                "//*[@aria-label='Earliest missing dates']/li/text()"
            )
            if value.strip()
        ]
        self.assertEqual(count, ["8"])
        self.assertEqual(len(preview), 5)
        self.assertEqual(preview, [
            "07/01/2026",
            "07/02/2026",
            "07/03/2026",
            "07/04/2026",
            "07/05/2026",
        ])
        self.assertIn('href="/my/internship/calendar"', dashboard.text)

    def test_historical_program_calendar_is_read_only(self):
        user, student = self._create_portal_user("historical")
        program = self._create_program(
            student,
            "Historical",
            state="completed",
            start_date="2026-06-01",
            end_date="2026-06-02",
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship/calendar",
            today=date(2026, 7, 5),
        )

        self.assertIn(program.name, response.text)
        self.assertIn("read-only calendar", response.text)
        self.assertEqual(self._missing_count(response), 2)
        self.assertNotIn('href="/my/internship/daily/new"', response.text)

    def test_dashboard_no_missing_and_phase3a_metrics_are_preserved(self):
        user, student = self._create_portal_user("dashboard")
        program = self._create_program(
            student,
            "Dashboard",
            start_date="2026-07-01",
            end_date="2026-07-02",
        )
        self._create_entry(
            program,
            "Completed",
            "2026-07-01",
            state="completed",
            work_hours=5,
        )
        self._create_entry(
            program,
            "Draft",
            "2026-07-02",
            work_hours=3,
        )
        self._authenticate(user)

        response = self._open(
            "/my/internship",
            today=date(2026, 7, 2),
        )

        self.assertIn("No missing daily entries up to today.", response.text)
        document = self._document(response)
        self.assertEqual(
            document.xpath("//*[@data-metric='total-entries']/@data-value"),
            ["2"],
        )
        self.assertEqual(
            document.xpath("//*[@data-metric='completed-entries']/@data-value"),
            ["1"],
        )
        self.assertEqual(
            document.xpath("//*[@data-metric='draft-entries']/@data-value"),
            ["1"],
        )
        self.assertEqual(
            document.xpath("//*[@data-metric='recorded-hours']/@data-value"),
            ["8.0"],
        )

    def test_monday_first_legend_links_and_read_only_controls(self):
        user, student = self._create_portal_user("layout")
        self._create_program(student, "Layout")
        self._authenticate(user)

        response = self._open("/my/internship/calendar")
        document = self._document(response)

        weekdays = [
            value.strip()
            for value in document.xpath(
                "//*[@data-calendar-month][1]//thead/tr/th/text()"
            )
        ]
        self.assertEqual(weekdays[0], "Mon")
        for label in ("Completed", "Draft", "Other", "Missing", "Future"):
            self.assertIn(label, response.text)
        self.assertIn('href="/my/internship"', response.text)
        self.assertIn('href="/my/internship/daily"', response.text)
        self.assertIn('href="/my/internship/daily/new"', response.text)
        for forbidden in (
            "/edit",
            "/submit-confirm",
            "Delete Daily Entry",
            "Approve Daily Entry",
            "Request Revision",
        ):
            self.assertNotIn(forbidden, response.text)

    def test_create_daily_entry_link_uses_existing_eligibility(self):
        cases = (
            ("independent", "active", True, True),
            ("supervised", "active", True, False),
            ("independent", "draft", True, False),
            ("independent", "active", False, False),
        )
        for index, (mode, state, active, expected) in enumerate(cases):
            with self.subTest(mode=mode, state=state, active=active):
                user, student = self._create_portal_user(f"eligible-{index}")
                self._create_program(
                    student,
                    f"Eligible {index}",
                    workflow_mode=mode,
                    state=state,
                    active=active,
                )
                self._authenticate(user)
                response = self._open("/my/internship/calendar")
                present = 'href="/my/internship/daily/new"' in response.text
                self.assertEqual(present, expected)

    def test_invalid_dates_status_priority_and_defensive_span(self):
        controller = InternshipPortal()
        for program in (
            SimpleNamespace(start_date=False, end_date=False),
            SimpleNamespace(
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 1),
            ),
        ):
            with self.subTest(program=program):
                analysis = controller._portal_program_calendar_analysis(
                    program,
                    SimpleNamespace(),
                    today=date(2026, 7, 5),
                )
                self.assertFalse(analysis["analysis_available"])
                self.assertEqual(analysis["reason"], "invalid_dates")
                self.assertFalse(analysis["month_groups"])

        self.assertGreater(
            controller._portal_daily_entry_status_priority("completed"),
            controller._portal_daily_entry_status_priority("approved"),
        )
        self.assertGreater(
            controller._portal_daily_entry_status_priority("approved"),
            controller._portal_daily_entry_status_priority("draft"),
        )

        invalid_user, invalid_student = self._create_portal_user(
            "invalid-dates"
        )
        invalid_program = self._create_program(
            invalid_student,
            "Invalid Dates",
        )
        self.env.cr.execute(
            "UPDATE internship_program SET end_date = %s WHERE id = %s",
            ["2026-06-30", invalid_program.id],
        )
        invalid_program.invalidate_recordset()
        self._authenticate(invalid_user)
        invalid_calendar = self._open("/my/internship/calendar")
        invalid_dashboard = self._open("/my/internship")
        self.assertIn("dates are incomplete or invalid", invalid_calendar.text)
        self.assertIn("analysis is unavailable", invalid_dashboard.text)
        self.assertFalse(
            self._document(invalid_calendar).xpath(
                "//*[@data-calendar-date]"
            )
        )

        user, student = self._create_portal_user("long-range")
        self._create_program(
            student,
            "Long Range",
            start_date="2020-01-01",
            end_date="2024-01-01",
        )
        self._authenticate(user)
        response = self._open("/my/internship/calendar")
        self.assertIn("spans more than three years", response.text)
        self.assertFalse(
            self._document(response).xpath("//*[@data-calendar-date]")
        )
