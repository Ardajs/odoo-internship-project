from urllib.parse import urlparse

from psycopg2 import IntegrityError

from odoo import Command, http
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalDailyEntryCreation(HttpCase):
    PASSWORD = "Portal-daily-create-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True, student=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Daily Create {suffix}",
            "login": f"portal-daily-create-{suffix}@example.test",
            "email": f"portal-daily-create-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student_record = self.env["internship.student"]
        if student:
            student_record = self.env["internship.student"].create({
                "name": user.name,
                "student_number": f"CREATE-{suffix.upper()}",
                "email": user.email,
                "user_id": user.id,
            })
        return user, student_record

    def _create_program(
        self,
        student,
        suffix,
        *,
        state="active",
        workflow_mode="independent",
    ):
        values = {
            "name": f"Portal Create Program {suffix}",
            "student_id": student.id,
            "company_name": f"Portal Create Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "start_date": "2028-04-01",
            "end_date": "2028-04-30",
            "state": state,
        }
        if workflow_mode == "supervised":
            values["supervisor_id"] = self.env.ref("base.user_admin").id
        return self.env["internship.program"].create(values)

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _valid_form(self, **overrides):
        values = {
            "entry_date": "2028-04-10",
            "title": "Portal Draft Entry Unique",
            "work_description": "Implemented and reviewed a portal feature.",
            "work_hours": "7.5",
            "csrf_token": http.Request.csrf_token(self),
        }
        values.update(overrides)
        return values

    def _entries_for(self, program):
        return self.env["internship.daily.entry"].search([
            ("program_id", "=", program.id),
        ])

    def test_valid_portal_intern_can_open_form_with_safe_fields(self):
        user, student = self._create_portal_user("form")
        self._create_program(student, "form")
        self._authenticate(user)

        response = self.url_open("/my/internship/daily/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Create Daily Entry", response.text)
        self.assertIn('name="entry_date"', response.text)
        self.assertIn('name="title"', response.text)
        self.assertIn('name="work_description"', response.text)
        self.assertIn('name="work_hours"', response.text)
        for forbidden_field in (
            "student_id",
            "program_id",
            "supervisor_id",
            "state",
            "workflow_mode",
        ):
            self.assertNotIn(f'name="{forbidden_field}"', response.text)

    def test_public_and_ordinary_portal_access(self):
        self.authenticate(None, None)
        public_response = self.url_open(
            "/my/internship/daily/new",
            allow_redirects=False,
        )
        self.assertIn(public_response.status_code, (302, 303))
        self.assertIn("/web/login", public_response.headers["Location"])

        ordinary_user, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary_user)
        ordinary_response = self.url_open("/my/internship/daily/new")
        self.assertEqual(ordinary_response.status_code, 403)

    def test_missing_or_ineligible_program_cannot_create(self):
        no_program_user, _student = self._create_portal_user("no-program")
        self._authenticate(no_program_user)
        no_program_get = self.url_open(
            "/my/internship/daily/new",
            allow_redirects=False,
        )
        no_program_post = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertIn(no_program_get.status_code, (302, 303))
        self.assertEqual(no_program_post.status_code, 303)

        draft_user, draft_student = self._create_portal_user("draft-program")
        draft_program = self._create_program(
            draft_student,
            "draft-program",
            state="draft",
        )
        self._authenticate(draft_user)
        draft_response = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertEqual(draft_response.status_code, 303)
        self.assertFalse(self._entries_for(draft_program))

    def test_valid_post_creates_owned_draft_and_redirects(self):
        user, student = self._create_portal_user("valid")
        program = self._create_program(student, "valid")
        self._authenticate(user)

        response = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            urlparse(response.headers["Location"]).path,
            "/my/internship/daily",
        )
        entries = self._entries_for(program)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.program_id, program)
        self.assertEqual(entries.student_id, student)
        self.assertEqual(entries.state, "draft")

    def test_tampered_ownership_state_and_unknown_fields_are_ignored(self):
        user, student = self._create_portal_user("tamper")
        program = self._create_program(student, "tamper")
        other_user, other_student = self._create_portal_user("tamper-other")
        other_program = self._create_program(other_student, "tamper-other")
        self._authenticate(user)

        response = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(
                student_id=str(other_student.id),
                program_id=str(other_program.id),
                user_id=str(other_user.id),
                supervisor_id=str(other_user.id),
                state="approved",
                workflow_mode="supervised",
                company_id="999999",
                supervisor_comment="Injected",
                arbitrary_unknown_field="Injected",
            ),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        entry = self._entries_for(program)
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.program_id, program)
        self.assertEqual(entry.student_id, student)
        self.assertEqual(entry.state, "draft")
        self.assertFalse(self._entries_for(other_program))
        self.assertFalse(entry.supervisor_comment)

    def test_required_date_and_hours_validation_is_atomic(self):
        invalid_cases = (
            ({"title": "   "}, "Work title is required."),
            ({"work_description": "   "}, "Work description is required."),
            ({"entry_date": "not-a-date"}, "Enter a valid entry date."),
            (
                {"entry_date": "2028-05-01"},
                "Entry date must be within the internship period.",
            ),
            ({"work_hours": "invalid"}, "Enter valid work hours."),
            (
                {"work_hours": "0"},
                "Work hours must be greater than zero and at most 24.",
            ),
            (
                {"work_hours": "-1"},
                "Work hours must be greater than zero and at most 24.",
            ),
            (
                {"work_hours": "25"},
                "Work hours must be greater than zero and at most 24.",
            ),
        )
        for index, (overrides, expected_message) in enumerate(invalid_cases):
            with self.subTest(overrides=overrides):
                user, student = self._create_portal_user(f"invalid-{index}")
                program = self._create_program(student, f"invalid-{index}")
                self._authenticate(user)
                response = self.url_open(
                    "/my/internship/daily/new",
                    data=self._valid_form(**overrides),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_message, response.text)
                self.assertFalse(self._entries_for(program))

    def test_duplicate_date_is_rejected_but_other_program_date_is_allowed(self):
        user, student = self._create_portal_user("duplicate")
        program = self._create_program(student, "duplicate")
        self._authenticate(user)
        first = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertEqual(first.status_code, 303)

        duplicate = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(title="Duplicate Attempt Unique"),
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(
            "A daily entry already exists for this date.",
            duplicate.text,
        )
        self.assertEqual(len(self._entries_for(program)), 1)

        _other_user, other_student = self._create_portal_user(
            "duplicate-other"
        )
        other_program = self._create_program(
            other_student,
            "duplicate-other",
        )
        other_entry = self.env["internship.daily.entry"].create({
            "program_id": other_program.id,
            "entry_date": "2028-04-10",
            "title": "Same Date Other Student",
            "work_description": "A separate student's valid entry.",
            "work_hours": 8,
        })
        self.assertTrue(other_entry)

    def test_private_service_enforces_allowlist_and_duplicate_invariant(self):
        user, student = self._create_portal_user("service")
        program = self._create_program(student, "service")
        service = self.env["internship.daily.entry"].sudo()
        values = {
            "entry_date": "2028-04-11",
            "title": "Private Service Draft",
            "work_description": "Created through the controlled service.",
            "work_hours": 8,
        }

        entry = service._portal_create_draft_entry(
            user.id,
            program.id,
            values,
        )
        self.assertEqual(entry.state, "draft")
        with self.assertRaises(AccessError):
            service._portal_create_draft_entry(
                user.id,
                program.id,
                {**values, "state": "approved"},
            )
        with self.assertRaises(UserError):
            service._portal_create_draft_entry(
                user.id,
                program.id,
                values,
            )

    def test_database_constraint_rejects_same_program_date(self):
        _user, student = self._create_portal_user("database-unique")
        program = self._create_program(student, "database-unique")
        values = {
            "program_id": program.id,
            "entry_date": "2028-04-12",
            "title": "Database Unique First",
            "work_description": "First entry for this program and date.",
            "work_hours": 8,
        }
        self.env["internship.daily.entry"].create(values)

        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["internship.daily.entry"].create({
                **values,
                "title": "Database Unique Duplicate",
            })

    def test_multiple_eligible_programs_are_not_selected_silently(self):
        user, student = self._create_portal_user("ambiguous")
        first_program = self._create_program(student, "ambiguous-first")
        second_program = self.env["internship.program"].create({
            "name": "Portal Create Program ambiguous-second",
            "student_id": student.id,
            "company_name": "Portal Create Company ambiguous-second",
            "department": "Engineering",
            "workflow_mode": "independent",
            "start_date": "2028-05-01",
            "end_date": "2028-05-31",
            "state": "active",
        })
        self._authenticate(user)

        list_response = self.url_open("/my/internship/daily")
        create_response = self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(),
            allow_redirects=False,
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertNotIn(
            'href="/my/internship/daily/new"',
            list_response.text,
        )
        self.assertEqual(create_response.status_code, 303)
        self.assertFalse(self._entries_for(first_program))
        self.assertFalse(self._entries_for(second_program))

    def test_created_entry_appears_in_list_and_button_is_eligibility_gated(self):
        user, student = self._create_portal_user("list")
        program = self._create_program(student, "list")
        self._authenticate(user)

        eligible_list = self.url_open("/my/internship/daily")
        self.assertIn('href="/my/internship/daily/new"', eligible_list.text)

        self.url_open(
            "/my/internship/daily/new",
            data=self._valid_form(title="Visible Portal Draft Unique"),
        )
        daily_list = self.url_open("/my/internship/daily")
        self.assertIn("Visible Portal Draft Unique", daily_list.text)
        self.assertIn("Draft", daily_list.text)

        program.write({"state": "completed"})
        ineligible_list = self.url_open("/my/internship/daily")
        self.assertNotIn(
            'href="/my/internship/daily/new"',
            ineligible_list.text,
        )

    def test_csrf_and_read_only_scope_remain_enforced(self):
        user, student = self._create_portal_user("scope")
        program = self._create_program(student, "scope")
        self._authenticate(user)

        csrf_response = self.url_open(
            "/my/internship/daily/new",
            data={
                key: value
                for key, value in self._valid_form().items()
                if key != "csrf_token"
            },
        )
        self.assertEqual(csrf_response.status_code, 400)
        self.assertFalse(self._entries_for(program))

        portal_entries = self.env["internship.daily.entry"].with_user(user)
        with self.assertRaises(AccessError):
            portal_entries.create({
                "program_id": program.id,
                "entry_date": "2028-04-12",
                "title": "Generic Create Must Fail",
                "work_description": "Generic ORM create remains forbidden.",
                "work_hours": 8,
            })

        list_response = self.url_open("/my/internship/daily")
        for forbidden_control in (
            "Edit Daily Entry",
            "Delete Daily Entry",
            "Submit Daily Entry",
        ):
            self.assertNotIn(forbidden_control, list_response.text)
