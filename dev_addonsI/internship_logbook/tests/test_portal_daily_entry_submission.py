from unittest.mock import patch
from urllib.parse import urlparse

from odoo import Command, http
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalDailyEntrySubmission(HttpCase):
    PASSWORD = "Portal-daily-submit-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Daily Submit {suffix}",
            "login": f"portal-daily-submit-{suffix}@example.test",
            "email": f"portal-daily-submit-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"].create({
            "name": user.name,
            "student_number": f"SUBMIT-{suffix.upper()}",
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
    ):
        values = {
            "name": f"Portal Submit Program {suffix}",
            "student_id": student.id,
            "company_name": f"Portal Submit Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "start_date": "2028-08-01",
            "end_date": "2028-08-31",
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
        *,
        state="draft",
        entry_date="2028-08-10",
    ):
        return self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": entry_date,
            "title": f"Portal Submission {suffix}",
            "work_description": f"Completed valid work for {suffix}.",
            "work_hours": 8,
            "state": state,
        })

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _confirm_url(self, entry):
        return f"/my/internship/daily/{entry.id}/submit-confirm"

    def _submit_url(self, entry):
        return f"/my/internship/daily/{entry.id}/submit"

    def _submit_form(self, **extra):
        return {
            "csrf_token": http.Request.csrf_token(self),
            **extra,
        }

    def _completion_messages(self, entry):
        return entry.message_ids.filtered(
            lambda message:
                "Independent daily entry marked as completed."
                in (message.body or "")
        )

    def test_eligible_draft_shows_edit_submit_and_confirmation(self):
        user, student = self._create_portal_user("eligible")
        program = self._create_program(student, "eligible")
        entry = self._create_entry(program, "Eligible Unique")
        self._authenticate(user)

        daily_list = self.url_open("/my/internship/daily")
        confirmation = self.url_open(self._confirm_url(entry))

        self.assertIn(
            f"/my/internship/daily/{entry.id}/edit",
            daily_list.text,
        )
        self.assertIn(self._confirm_url(entry), daily_list.text)
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Submit Daily Entry", confirmation.text)
        self.assertIn(entry.title, confirmation.text)
        self.assertIn("Confirm Submission", confirmation.text)
        self.assertIn("Cancel", confirmation.text)
        self.assertEqual(entry.state, "draft")

    def test_submit_visibility_is_independent_active_draft_only(self):
        cases = (
            ("supervised", {"workflow_mode": "supervised"}, "draft"),
            ("inactive", {"active": False}, "draft"),
            ("program-draft", {"state": "draft"}, "draft"),
            ("program-completed", {"state": "completed"}, "draft"),
            ("completed", {}, "completed"),
        )
        for suffix, program_values, entry_state in cases:
            with self.subTest(suffix=suffix):
                user, student = self._create_portal_user(suffix)
                program = self._create_program(
                    student,
                    suffix,
                    **program_values,
                )
                entry = self._create_entry(
                    program,
                    suffix,
                    state=entry_state,
                )
                self._authenticate(user)

                response = self.url_open("/my/internship/daily")

                self.assertNotIn(self._confirm_url(entry), response.text)

        for state in ("submitted", "revision", "approved"):
            with self.subTest(state=state):
                user, student = self._create_portal_user(
                    f"state-{state}"
                )
                program = self._create_program(
                    student,
                    f"state-{state}",
                    workflow_mode="supervised",
                )
                entry = self._create_entry(
                    program,
                    f"State {state} Unique",
                    state=state,
                )
                self._authenticate(user)
                response = self.url_open("/my/internship/daily")
                self.assertNotIn(self._confirm_url(entry), response.text)

    def test_public_ordinary_portal_and_foreign_entry_access(self):
        owner, owner_student = self._create_portal_user("owner")
        owner_program = self._create_program(owner_student, "owner")
        entry = self._create_entry(owner_program, "Foreign Unique")

        self.authenticate(None, None)
        public_response = self.url_open(
            self._confirm_url(entry),
            allow_redirects=False,
        )
        self.assertIn(public_response.status_code, (302, 303))
        self.assertIn("/web/login", public_response.headers["Location"])

        ordinary, _ordinary_student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        ordinary_confirm = self.url_open(self._confirm_url(entry))
        ordinary_submit = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
        )
        self.assertEqual(ordinary_confirm.status_code, 403)
        self.assertEqual(ordinary_submit.status_code, 403)

        foreign, _foreign_student = self._create_portal_user("foreign")
        self._authenticate(foreign)
        foreign_confirm = self.url_open(self._confirm_url(entry))
        foreign_submit = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
        )
        self.assertEqual(foreign_confirm.status_code, 404)
        self.assertEqual(foreign_submit.status_code, 404)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "draft")

    def test_submit_route_is_post_only_and_csrf_protected(self):
        user, student = self._create_portal_user("csrf")
        program = self._create_program(student, "csrf")
        entry = self._create_entry(program, "CSRF Unique")
        self._authenticate(user)

        get_response = self.url_open(self._submit_url(entry))
        missing_csrf = self.url_open(
            self._submit_url(entry),
            data={"csrf_probe": "missing-token"},
        )

        self.assertIn(get_response.status_code, (404, 405))
        self.assertEqual(missing_csrf.status_code, 400)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "draft")
        self.assertFalse(self._completion_messages(entry))

    def test_valid_submission_completes_with_real_workflow_side_effects(self):
        user, student = self._create_portal_user("valid")
        program = self._create_program(student, "valid")
        entry = self._create_entry(program, "Valid Unique")
        original_program = entry.program_id
        original_student = entry.student_id
        self._authenticate(user)

        with patch.object(MailTemplate, "send_mail") as send_mail:
            response = self.url_open(
                self._submit_url(entry),
                data=self._submit_form(),
                allow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            urlparse(response.headers["Location"]).path,
            "/my/internship/daily",
        )
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "completed")
        self.assertEqual(entry.program_id, original_program)
        self.assertEqual(entry.student_id, original_student)
        self.assertEqual(len(self._completion_messages(entry)), 1)
        self.assertFalse(entry.activity_ids)
        self.assertFalse(entry.supervisor_id)
        send_mail.assert_not_called()

        daily_list = self.url_open("/my/internship/daily")
        self.assertIn("Daily entry completed successfully.", daily_list.text)
        self.assertIn(entry.title, daily_list.text)
        self.assertIn("Completed", daily_list.text)
        self.assertNotIn(self._confirm_url(entry), daily_list.text)
        self.assertNotIn(
            f"/my/internship/daily/{entry.id}/edit",
            daily_list.text,
        )

    def test_submission_ignores_all_client_controlled_values(self):
        user, student = self._create_portal_user("tamper")
        program = self._create_program(student, "tamper")
        entry = self._create_entry(program, "Tamper Unique")
        other_user, other_student = self._create_portal_user("tamper-other")
        other_program = self._create_program(other_student, "tamper-other")
        self._authenticate(user)

        response = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(
                state="approved",
                target_state="submitted",
                student_id=str(other_student.id),
                program_id=str(other_program.id),
                user_id=str(other_user.id),
                workflow_mode="supervised",
                unknown_field="ignored",
            ),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "completed")
        self.assertEqual(entry.student_id, student)
        self.assertEqual(entry.program_id, program)

    def test_completed_entry_cannot_be_edited_or_submitted_again(self):
        user, student = self._create_portal_user("after")
        program = self._create_program(student, "after")
        entry = self._create_entry(program, "After Unique")
        self._authenticate(user)
        first = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
            allow_redirects=False,
        )
        self.assertEqual(first.status_code, 303)

        edit_get = self.url_open(
            f"/my/internship/daily/{entry.id}/edit",
            allow_redirects=False,
        )
        stale_edit = self.url_open(
            f"/my/internship/daily/{entry.id}/edit",
            data={
                "entry_date": "2028-08-11",
                "title": "Must Not Change",
                "work_description": "Must not overwrite completed entry.",
                "work_hours": "7",
                "csrf_token": http.Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        repeated = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
            allow_redirects=False,
        )

        self.assertIn(edit_get.status_code, (302, 303))
        self.assertEqual(stale_edit.status_code, 303)
        self.assertEqual(repeated.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "completed")
        self.assertEqual(entry.title, "Portal Submission After Unique")
        self.assertEqual(len(self._completion_messages(entry)), 1)

    def test_incomplete_legacy_draft_is_rejected_without_side_effects(self):
        user, student = self._create_portal_user("legacy")
        program = self._create_program(student, "legacy")
        entry = self._create_entry(program, "Legacy Unique")
        self.env.cr.execute(
            "UPDATE internship_daily_entry "
            "SET work_description = '' WHERE id = %s",
            [entry.id],
        )
        entry.invalidate_recordset()
        self._authenticate(user)

        response = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "This daily entry is incomplete or invalid",
            response.text,
        )
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "draft")
        self.assertFalse(self._completion_messages(entry))

    def test_program_and_workflow_guards_are_enforced_server_side(self):
        cases = (
            ("supervised", {"workflow_mode": "supervised"}),
            ("inactive", {"active": False}),
            ("program-draft", {"state": "draft"}),
            ("program-completed", {"state": "completed"}),
        )
        service = self.env["internship.daily.entry"].sudo()
        for suffix, program_values in cases:
            with self.subTest(suffix=suffix):
                user, student = self._create_portal_user(
                    f"guard-{suffix}"
                )
                program = self._create_program(
                    student,
                    f"guard-{suffix}",
                    **program_values,
                )
                entry = self._create_entry(
                    program,
                    f"Guard {suffix} Unique",
                )

                with self.assertRaises(UserError):
                    service._portal_submit_draft_entry(
                        user.id,
                        entry.id,
                    )
                entry.invalidate_recordset()
                self.assertEqual(entry.state, "draft")
                self.assertFalse(self._completion_messages(entry))

    def test_private_service_validates_group_ownership_mode_and_state(self):
        owner, student = self._create_portal_user("service-owner")
        program = self._create_program(student, "service-owner")
        entry = self._create_entry(program, "Service Owner Unique")
        ordinary, _ordinary_student = self._create_portal_user(
            "service-ordinary",
            dedicated=False,
        )
        foreign, _foreign_student = self._create_portal_user(
            "service-foreign"
        )
        service = self.env["internship.daily.entry"].sudo()

        with self.assertRaises(AccessError):
            service._portal_submit_draft_entry(ordinary.id, entry.id)
        with self.assertRaises(AccessError):
            service._portal_submit_draft_entry(foreign.id, entry.id)

        service._portal_submit_draft_entry(owner.id, entry.id)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "completed")
        with self.assertRaises(UserError):
            service._portal_submit_draft_entry(owner.id, entry.id)
        self.assertEqual(len(self._completion_messages(entry)), 1)

    def test_stale_confirmation_does_not_repeat_transition(self):
        user, student = self._create_portal_user("stale")
        program = self._create_program(student, "stale")
        entry = self._create_entry(program, "Stale Unique")
        self._authenticate(user)
        confirmation = self.url_open(self._confirm_url(entry))
        self.assertEqual(confirmation.status_code, 200)

        self.env["internship.daily.entry"].sudo()._portal_submit_draft_entry(
            user.id,
            entry.id,
        )
        stale_response = self.url_open(
            self._submit_url(entry),
            data=self._submit_form(),
            allow_redirects=False,
        )

        self.assertEqual(stale_response.status_code, 303)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "completed")
        self.assertEqual(len(self._completion_messages(entry)), 1)
        daily_list = self.url_open("/my/internship/daily")
        self.assertIn(
            "This daily entry is no longer available for submission.",
            daily_list.text,
        )

    def test_generic_write_and_out_of_scope_controls_remain_denied(self):
        user, student = self._create_portal_user("scope")
        program = self._create_program(student, "scope")
        entry = self._create_entry(program, "Scope Unique")
        with self.assertRaises(AccessError):
            entry.with_user(user).write({"state": "completed"})
        self._authenticate(user)

        daily_list = self.url_open("/my/internship/daily")

        for forbidden_control in (
            "Delete Daily Entry",
            "Approve Daily Entry",
            "Request Revision",
        ):
            self.assertNotIn(forbidden_control, daily_list.text)
        entry.invalidate_recordset()
        self.assertEqual(entry.state, "draft")
