from urllib.parse import urlparse

from odoo import Command, http
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalDailyEntryEditing(HttpCase):
    PASSWORD = "Portal-daily-edit-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Daily Edit {suffix}",
            "login": f"portal-daily-edit-{suffix}@example.test",
            "email": f"portal-daily-edit-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"].create({
            "name": user.name,
            "student_number": f"EDIT-{suffix.upper()}",
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
        start_date="2028-06-01",
        end_date="2028-06-30",
    ):
        values = {
            "name": f"Portal Edit Program {suffix}",
            "student_id": student.id,
            "company_name": f"Portal Edit Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "start_date": start_date,
            "end_date": end_date,
            "state": state,
        }
        if workflow_mode == "supervised":
            values["supervisor_id"] = self.env.ref("base.user_admin").id
        return self.env["internship.program"].create(values)

    def _create_entry(
        self,
        program,
        suffix,
        *,
        entry_date="2028-06-10",
        state="draft",
    ):
        return self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": entry_date,
            "title": f"Existing Draft {suffix}",
            "work_description": f"Existing description {suffix}.",
            "work_hours": 7.5,
            "state": state,
        })

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _valid_form(self, **overrides):
        values = {
            "entry_date": "2028-06-11",
            "title": "Updated Portal Draft Unique",
            "work_description": "Updated through the secure portal form.",
            "work_hours": "8.25",
            "csrf_token": http.Request.csrf_token(self),
        }
        values.update(overrides)
        return values

    def _edit_url(self, entry):
        return f"/my/internship/daily/{entry.id}/edit"

    def test_owned_draft_form_prepopulates_only_safe_fields(self):
        user, student = self._create_portal_user("form")
        program = self._create_program(student, "form")
        entry = self._create_entry(program, "Prepopulated Unique")
        self._authenticate(user)

        response = self.url_open(self._edit_url(entry))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Edit Daily Entry", response.text)
        self.assertIn("Existing Draft Prepopulated Unique", response.text)
        self.assertIn(
            "Existing description Prepopulated Unique.",
            response.text,
        )
        self.assertIn('value="2028-06-10"', response.text)
        self.assertIn('value="7.5"', response.text)
        for forbidden_field in (
            "student_id",
            "program_id",
            "supervisor_id",
            "state",
            "workflow_mode",
            "supervisor_comment",
        ):
            self.assertNotIn(f'name="{forbidden_field}"', response.text)

    def test_public_ordinary_portal_and_foreign_entry_access(self):
        owner, owner_student = self._create_portal_user("owner")
        owner_program = self._create_program(owner_student, "owner")
        entry = self._create_entry(owner_program, "Foreign Unique")

        self.authenticate(None, None)
        public_response = self.url_open(
            self._edit_url(entry),
            allow_redirects=False,
        )
        self.assertIn(public_response.status_code, (302, 303))
        self.assertIn("/web/login", public_response.headers["Location"])

        ordinary, _ordinary_student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        ordinary_response = self.url_open(self._edit_url(entry))
        self.assertEqual(ordinary_response.status_code, 403)

        foreign, _foreign_student = self._create_portal_user("foreign")
        self._authenticate(foreign)
        foreign_get = self.url_open(self._edit_url(entry))
        foreign_post = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(),
        )
        self.assertEqual(foreign_get.status_code, 404)
        self.assertEqual(foreign_post.status_code, 404)
        entry.invalidate_recordset()
        self.assertEqual(entry.title, "Existing Draft Foreign Unique")

    def test_valid_post_updates_only_safe_fields_and_redirects(self):
        user, student = self._create_portal_user("valid")
        program = self._create_program(student, "valid")
        entry = self._create_entry(program, "Valid Unique")
        original_student = entry.student_id
        self._authenticate(user)

        response = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            urlparse(response.headers["Location"]).path,
            "/my/internship/daily",
        )
        entry.invalidate_recordset()
        self.assertEqual(entry.title, "Updated Portal Draft Unique")
        self.assertEqual(
            entry.work_description,
            "Updated through the secure portal form.",
        )
        self.assertEqual(entry.work_hours, 8.25)
        self.assertEqual(str(entry.entry_date), "2028-06-11")
        self.assertEqual(entry.program_id, program)
        self.assertEqual(entry.student_id, original_student)
        self.assertEqual(entry.state, "draft")

        list_response = self.url_open("/my/internship/daily")
        self.assertIn("Daily entry updated.", list_response.text)
        self.assertIn("Updated Portal Draft Unique", list_response.text)

    def test_tampered_ownership_state_and_unknown_fields_are_ignored(self):
        user, student = self._create_portal_user("tamper")
        program = self._create_program(student, "tamper")
        entry = self._create_entry(program, "Tamper Unique")
        other_user, other_student = self._create_portal_user("tamper-other")
        other_program = self._create_program(other_student, "tamper-other")
        self._authenticate(user)

        response = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(
                student_id=str(other_student.id),
                program_id=str(other_program.id),
                user_id=str(other_user.id),
                supervisor_id=str(other_user.id),
                state="approved",
                workflow_mode="supervised",
                supervisor_comment="Injected",
                arbitrary_unknown_field="Injected",
            ),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(entry.program_id, program)
        self.assertEqual(entry.student_id, student)
        self.assertEqual(entry.state, "draft")
        self.assertFalse(entry.supervisor_comment)

    def test_validation_errors_are_atomic(self):
        invalid_cases = (
            ({"title": "   "}, "Work title is required."),
            (
                {"work_description": "   "},
                "Work description is required.",
            ),
            ({"entry_date": "not-a-date"}, "Enter a valid entry date."),
            (
                {"entry_date": "2028-07-01"},
                "Entry date must be within the internship period.",
            ),
            ({"work_hours": "invalid"}, "Enter valid work hours."),
            ({"work_hours": "NaN"}, "Enter valid work hours."),
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
        for index, (overrides, message) in enumerate(invalid_cases):
            with self.subTest(overrides=overrides):
                user, student = self._create_portal_user(
                    f"invalid-{index}"
                )
                program = self._create_program(
                    student,
                    f"invalid-{index}",
                )
                entry = self._create_entry(
                    program,
                    f"Invalid {index} Unique",
                )
                original = (
                    entry.entry_date,
                    entry.title,
                    entry.work_description,
                    entry.work_hours,
                )
                self._authenticate(user)

                response = self.url_open(
                    self._edit_url(entry),
                    data=self._valid_form(**overrides),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.text)
                entry.invalidate_recordset()
                self.assertEqual(
                    (
                        entry.entry_date,
                        entry.title,
                        entry.work_description,
                        entry.work_hours,
                    ),
                    original,
                )

    def test_same_free_duplicate_and_other_program_dates(self):
        user, student = self._create_portal_user("dates")
        program = self._create_program(student, "dates")
        entry = self._create_entry(program, "Dates Unique")
        conflicting = self._create_entry(
            program,
            "Conflict Unique",
            entry_date="2028-06-12",
        )
        _other_user, other_student = self._create_portal_user(
            "dates-other-owner"
        )
        other_program = self._create_program(
            other_student,
            "dates-other-program",
            start_date="2028-06-01",
            end_date="2028-06-30",
        )
        self._create_entry(
            other_program,
            "Other Program Unique",
            entry_date="2028-06-13",
        )
        self._authenticate(user)

        same_date = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(entry_date="2028-06-10"),
            allow_redirects=False,
        )
        self.assertEqual(same_date.status_code, 303)

        free_date = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(entry_date="2028-06-14"),
            allow_redirects=False,
        )
        self.assertEqual(free_date.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(str(entry.entry_date), "2028-06-14")

        duplicate = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(entry_date="2028-06-12"),
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(
            "A daily entry already exists for this date.",
            duplicate.text,
        )
        entry.invalidate_recordset()
        self.assertEqual(str(entry.entry_date), "2028-06-14")
        self.assertEqual(str(conflicting.entry_date), "2028-06-12")

        different_program_date = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(entry_date="2028-06-13"),
            allow_redirects=False,
        )
        self.assertEqual(different_program_date.status_code, 303)

    def test_private_service_enforces_ownership_allowlist_and_draft(self):
        user, student = self._create_portal_user("service")
        program = self._create_program(student, "service")
        entry = self._create_entry(program, "Service Unique")
        other_user, other_student = self._create_portal_user("service-other")
        other_program = self._create_program(other_student, "service-other")
        other_entry = self._create_entry(
            other_program,
            "Other Service Unique",
        )
        service = self.env["internship.daily.entry"].sudo()
        values = {
            "entry_date": "2028-06-11",
            "title": "Service Updated Unique",
            "work_description": "Updated by the controlled edit service.",
            "work_hours": 8,
        }

        updated = service._portal_update_draft_entry(
            user.id,
            entry.id,
            values,
        )
        self.assertEqual(updated.state, "draft")
        self.assertEqual(updated.program_id, program)
        conflict = self._create_entry(
            program,
            "Service Conflict Unique",
            entry_date="2028-06-12",
        )
        with self.assertRaises(UserError):
            service._portal_update_draft_entry(
                user.id,
                entry.id,
                {**values, "entry_date": conflict.entry_date},
            )
        entry.invalidate_recordset()
        self.assertEqual(str(entry.entry_date), "2028-06-11")
        with self.assertRaises(AccessError):
            service._portal_update_draft_entry(
                user.id,
                other_entry.id,
                values,
            )
        with self.assertRaises(AccessError):
            service._portal_update_draft_entry(
                user.id,
                entry.id,
                {**values, "state": "approved"},
            )

        with self.assertRaises(AccessError):
            entry.with_user(user).write({"title": "Generic write denied"})

    def test_csrf_and_generic_portal_write_remain_denied(self):
        user, student = self._create_portal_user("csrf")
        program = self._create_program(student, "csrf")
        entry = self._create_entry(program, "CSRF Unique")
        self._authenticate(user)

        response = self.url_open(
            self._edit_url(entry),
            data={
                key: value
                for key, value in self._valid_form().items()
                if key != "csrf_token"
            },
        )

        self.assertEqual(response.status_code, 400)
        entry.invalidate_recordset()
        self.assertEqual(entry.title, "Existing Draft CSRF Unique")
        with self.assertRaises(AccessError):
            entry.with_user(user).write({"title": "Generic write denied"})

    def test_non_draft_states_have_no_edit_access_or_button(self):
        user, student = self._create_portal_user("states")
        independent = self._create_program(student, "states-independent")
        completed = self._create_entry(
            independent,
            "Completed Unique",
            state="completed",
        )
        supervised = self._create_program(
            student,
            "states-supervised",
            workflow_mode="supervised",
            start_date="2028-07-01",
            end_date="2028-07-31",
        )
        entries = [
            completed,
            self._create_entry(
                supervised,
                "Submitted Unique",
                entry_date="2028-07-15",
                state="submitted",
            ),
            self._create_entry(
                supervised,
                "Revision Unique",
                entry_date="2028-07-16",
                state="revision",
            ),
            self._create_entry(
                supervised,
                "Approved Unique",
                entry_date="2028-07-17",
                state="approved",
            ),
        ]
        self._authenticate(user)

        list_response = self.url_open("/my/internship/daily")
        for entry in entries:
            self.assertNotIn(
                f'/my/internship/daily/{entry.id}/edit',
                list_response.text,
            )
            original_title = entry.title
            get_response = self.url_open(
                self._edit_url(entry),
                allow_redirects=False,
            )
            post_response = self.url_open(
                self._edit_url(entry),
                data=self._valid_form(),
                allow_redirects=False,
            )
            self.assertIn(get_response.status_code, (302, 303))
            self.assertEqual(post_response.status_code, 303)
            entry.invalidate_recordset()
            self.assertEqual(entry.title, original_title)

    def test_stale_draft_form_cannot_overwrite_submitted_entry(self):
        user, student = self._create_portal_user("stale")
        program = self._create_program(
            student,
            "stale",
            workflow_mode="supervised",
        )
        entry = self._create_entry(program, "Stale Unique")
        self._authenticate(user)
        initial_get = self.url_open(self._edit_url(entry))
        self.assertEqual(initial_get.status_code, 200)

        entry._write_workflow_state("submitted")
        stale_post = self.url_open(
            self._edit_url(entry),
            data=self._valid_form(title="Must Not Replace Submitted"),
            allow_redirects=False,
        )

        self.assertEqual(stale_post.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "submitted")
        self.assertEqual(entry.title, "Existing Draft Stale Unique")
        list_response = self.url_open("/my/internship/daily")
        self.assertIn(
            "Only draft entries in an active internship can be edited.",
            list_response.text,
        )

    def test_edit_button_is_draft_only_and_no_out_of_scope_controls(self):
        user, student = self._create_portal_user("controls")
        independent = self._create_program(student, "controls")
        draft = self._create_entry(independent, "Draft Button Unique")
        completed = self._create_entry(
            independent,
            "Completed Button Unique",
            entry_date="2028-06-12",
            state="completed",
        )
        self._authenticate(user)

        response = self.url_open("/my/internship/daily")

        self.assertIn(
            f'/my/internship/daily/{draft.id}/edit',
            response.text,
        )
        self.assertNotIn(
            f'/my/internship/daily/{completed.id}/edit',
            response.text,
        )
        for forbidden_control in (
            "Delete Daily Entry",
            "Submit Daily Entry",
            "Approve Daily Entry",
        ):
            self.assertNotIn(forbidden_control, response.text)
