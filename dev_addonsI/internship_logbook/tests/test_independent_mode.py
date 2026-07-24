from unittest.mock import patch

from lxml import html

from odoo import Command
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.ai_provider import AIProviderService


@tagged("post_install", "-at_install")
class TestIndependentInternshipMode(TransactionCase):
    AI_RESULT = {
        "suggested_text": "Professionally improved internship entry text.",
        "feedback": "The text was improved without changing its facts.",
        "warnings": [],
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )

        cls.intern_user = cls._create_user(
            "Independent Intern",
            "independent_mode_intern",
            internal_group | intern_group,
        )
        cls.other_intern_user = cls._create_user(
            "Other Independent Intern",
            "other_independent_mode_intern",
            internal_group | intern_group,
        )
        cls.supervised_intern_user = cls._create_user(
            "Supervised Intern",
            "supervised_mode_intern",
            internal_group | intern_group,
        )
        cls.supervisor_user = cls._create_user(
            "Independent Mode Supervisor",
            "independent_mode_supervisor",
            internal_group | supervisor_group,
        )
        cls.manager_user = cls._create_user(
            "Independent Mode Manager",
            "independent_mode_manager",
            internal_group | manager_group,
        )

        cls.student = cls._create_student(
            "Independent Student",
            "IND-001",
            cls.intern_user,
        )
        cls.other_student = cls._create_student(
            "Other Independent Student",
            "IND-002",
            cls.other_intern_user,
        )
        cls.supervised_student = cls._create_student(
            "Supervised Student",
            "SUP-001",
            cls.supervised_intern_user,
        )

        cls.independent_program = cls.env["internship.program"].create(
            cls._program_values(
                cls.student,
                "Independent Program",
                "2026-09-01",
                "2026-09-30",
                workflow_mode="independent",
                state="active",
            )
        )
        cls.other_independent_program = cls.env["internship.program"].create(
            cls._program_values(
                cls.other_student,
                "Other Independent Program",
                "2026-10-01",
                "2026-10-31",
                workflow_mode="independent",
                state="active",
            )
        )
        cls.supervised_program = cls.env["internship.program"].create(
            cls._program_values(
                cls.supervised_student,
                "Supervised Program",
                "2026-11-01",
                "2026-11-30",
                supervisor=cls.supervisor_user,
                state="active",
            )
        )

    @classmethod
    def _create_user(cls, name, login, groups):
        return cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": name,
                "login": login,
                "group_ids": [Command.set(groups.ids)],
            }
        )

    @classmethod
    def _create_student(cls, name, number, user):
        values = {
            "name": name,
            "student_number": number,
            "university": "Test University",
            "department": "Software Engineering",
        }
        if user:
            values["user_id"] = user.id
        return cls.env["internship.student"].create(values)

    @classmethod
    def _program_values(
        cls,
        student,
        name,
        start_date,
        end_date,
        workflow_mode=None,
        supervisor=None,
        state="draft",
    ):
        values = {
            "name": name,
            "student_id": student.id,
            "company_name": "Test Company",
            "department": "Engineering",
            "start_date": start_date,
            "end_date": end_date,
            "state": state,
        }
        if workflow_mode:
            values["workflow_mode"] = workflow_mode
        if supervisor:
            values["supervisor_id"] = supervisor.id
        return values

    @classmethod
    def _entry_values(cls, program, date, title="Daily work"):
        return {
            "title": title,
            "program_id": program.id,
            "entry_date": date,
            "work_hours": 8,
            "technologies": "Odoo",
            "work_description": "I implemented the assigned Odoo task.",
            "learned_topics": "I learned how Odoo models organize data.",
            "challenges": "I found and corrected a validation problem.",
        }

    def setUp(self):
        super().setUp()
        self.entry = self.env["internship.daily.entry"].create(
            self._entry_values(
                self.independent_program,
                "2026-09-02",
                "Independent daily work",
            )
        )
        self.supervised_entry = self.env["internship.daily.entry"].create(
            self._entry_values(
                self.supervised_program,
                "2026-11-02",
                "Supervised daily work",
            )
        )

    def _new_student(self, suffix, user=None):
        return self._create_student(
            f"Temporary Student {suffix}",
            f"TMP-{suffix}",
            user,
        )

    def _new_program(
        self,
        suffix,
        workflow_mode="independent",
        state="draft",
        supervisor=None,
        student=None,
    ):
        student = student or self._new_student(suffix)
        return self.env["internship.program"].create(
            self._program_values(
                student,
                f"Temporary Program {suffix}",
                "2027-01-01",
                "2027-01-31",
                workflow_mode=workflow_mode,
                supervisor=supervisor,
                state=state,
            )
        )

    def _create_ai_wizard(self, entry=None, action_type="improve"):
        entry = entry or self.entry
        target_fields = {
            "improve": "work_description",
            "suggestions": "work_description",
            "missing_details": "work_description",
            "revision": "work_description",
            "improve_learned_topics": "learned_topics",
            "improve_challenges": "challenges",
        }
        target_field = target_fields[action_type]
        return self.env["internship.ai.assistant.wizard"].with_user(
            self.intern_user
        ).create(
            {
                "entry_id": entry.id,
                "action_type": action_type,
                "target_field": target_field,
                "original_text": entry[target_field],
                "suggested_text": self.AI_RESULT["suggested_text"],
                "feedback": self.AI_RESULT["feedback"],
            }
        )

    def _render_report_text(self, program):
        report = self.env.ref(
            "internship_logbook.action_report_internship_logbook"
        )
        rendered = self.env["ir.actions.report"]._render_qweb_html(
            report.id,
            program.ids,
        )[0]
        return " ".join(html.fromstring(rendered).text_content().split())

    def test_program_mode_defaults_and_supervisor_constraints(self):
        default_program = self._new_program(
            "DEFAULT",
            workflow_mode="supervised",
            supervisor=self.supervisor_user,
        )
        self.assertEqual(default_program.workflow_mode, "supervised")

        values = self._program_values(
            self._new_student("NO-MODE"),
            "Default Mode Program",
            "2027-02-01",
            "2027-02-28",
            supervisor=self.supervisor_user,
        )
        program_without_explicit_mode = self.env[
            "internship.program"
        ].create(values)
        self.assertEqual(
            program_without_explicit_mode.workflow_mode,
            "supervised",
        )

        with self.assertRaises(ValidationError):
            self._new_program("SUP-NO-SUP", workflow_mode="supervised")
        with self.assertRaises(ValidationError):
            self._new_program(
                "IND-WITH-SUP",
                workflow_mode="independent",
                supervisor=self.supervisor_user,
            )

    def test_independent_program_without_supervisor_is_valid(self):
        self.assertEqual(
            self.independent_program.workflow_mode,
            "independent",
        )
        self.assertFalse(self.independent_program.supervisor_id)

    def test_mode_change_is_manager_only_and_draft_without_entries(self):
        draft_program = self._new_program("MODE")
        with self.assertRaises(AccessError):
            draft_program.with_user(self.intern_user).write(
                {"workflow_mode": "supervised"}
            )

        draft_program.write(
            {
                "workflow_mode": "supervised",
                "supervisor_id": self.supervisor_user.id,
            }
        )
        self.assertEqual(draft_program.workflow_mode, "supervised")

        with_entry = self._new_program("MODE-ENTRY")
        self.env["internship.daily.entry"].create(
            self._entry_values(with_entry, "2027-01-02")
        )
        with self.assertRaises(ValidationError):
            with_entry.write(
                {
                    "workflow_mode": "supervised",
                    "supervisor_id": self.supervisor_user.id,
                }
            )

        active_program = self._new_program("MODE-ACTIVE", state="active")
        with self.assertRaises(ValidationError):
            active_program.write(
                {
                    "workflow_mode": "supervised",
                    "supervisor_id": self.supervisor_user.id,
                }
            )

    def test_intern_cannot_change_program_identity_or_assignment(self):
        for values in (
            {"workflow_mode": "supervised"},
            {"student_id": self.other_student.id},
            {"supervisor_id": self.supervisor_user.id},
        ):
            with self.subTest(values=values), self.assertRaises(AccessError):
                self.independent_program.with_user(
                    self.intern_user
                ).write(values)

    def test_owning_intern_can_complete_and_reopen_independent_program(self):
        self.entry.with_user(self.intern_user).action_complete()

        program = self.independent_program.with_user(self.intern_user)
        program.action_complete()
        self.assertEqual(program.state, "completed")

        program.action_reopen()
        self.assertEqual(program.state, "active")

    def test_intern_cannot_complete_another_or_supervised_program(self):
        with self.assertRaises(AccessError):
            self.other_independent_program.with_user(
                self.intern_user
            ).action_complete()

        with self.assertRaises(AccessError):
            self.supervised_program.with_user(
                self.intern_user
            ).action_complete()

    def test_intern_cannot_write_program_state_directly(self):
        program = self.independent_program.with_user(self.intern_user)
        with self.assertRaises(AccessError):
            program.write({"state": "completed"})
        with self.assertRaises(AccessError):
            program.with_context(
                _internship_program_workflow_transition=True
            ).write({"state": "completed"})
        self.assertEqual(program.state, "active")

    def test_supervisor_cannot_modify_independent_program(self):
        program = self.independent_program.with_user(self.supervisor_user)
        with self.assertRaises(AccessError):
            program.write({"notes": "Unauthorized supervisor change"})
        with self.assertRaises(AccessError):
            program.action_complete()

    def test_manager_can_complete_independent_program(self):
        self.entry.with_user(self.intern_user).action_complete()
        program = self.independent_program.with_user(self.manager_user)
        program.action_complete()
        self.assertEqual(program.state, "completed")

    def test_intern_own_entry_create_and_cross_intern_access(self):
        own_entry = self.env["internship.daily.entry"].with_user(
            self.intern_user
        ).create(
            self._entry_values(self.independent_program, "2026-09-03")
        )
        self.assertEqual(own_entry.student_id.user_id, self.intern_user)
        with self.assertRaises(AccessError):
            self.env["internship.daily.entry"].with_user(
                self.other_intern_user
            ).create(
                self._entry_values(
                    self.independent_program,
                    "2026-09-04",
                )
            )
        with self.assertRaises(AccessError):
            own_entry.with_user(self.other_intern_user).check_access("read")
        with self.assertRaises(AccessError):
            own_entry.with_user(self.other_intern_user).write(
                {"title": "Unauthorized change"}
            )

    def test_non_manager_create_requires_draft(self):
        values = self._entry_values(
            self.independent_program,
            "2026-09-03",
        )
        values["state"] = "completed"
        with self.assertRaises(AccessError):
            self.env["internship.daily.entry"].with_user(
                self.intern_user
            ).create(values)

    def test_complete_and_reopen_independent_entry(self):
        self.entry.with_user(self.intern_user).action_complete()
        self.assertEqual(self.entry.state, "completed")
        self.assertTrue(any(
            "Independent daily entry marked as completed." in str(
                message.body or ""
            )
            for message in self.entry.message_ids
        ))

        with self.assertRaises(AccessError):
            self.entry.with_user(self.intern_user).write(
                {"work_description": "Unauthorized completed edit"}
            )

        self.entry.with_user(self.intern_user).action_reopen()
        self.assertEqual(self.entry.state, "draft")
        self.assertTrue(any(
            "Independent daily entry reopened for editing." in str(
                message.body or ""
            )
            for message in self.entry.message_ids
        ))

    def test_complete_and_reopen_require_active_program(self):
        draft_program = self._new_program(
            "INACTIVE",
            student=self.student,
        )
        entry = self.env["internship.daily.entry"].create(
            self._entry_values(draft_program, "2027-01-02")
        )
        with self.assertRaises(ValidationError):
            entry.with_user(self.intern_user).action_complete()

        self.entry.with_user(self.intern_user).action_complete()
        self.independent_program.state = "completed"
        with self.assertRaises(ValidationError):
            self.entry.with_user(self.intern_user).action_reopen()

    def test_supervised_actions_reject_independent_entries(self):
        for method_name in (
            "action_submit",
            "action_approve",
            "action_request_revision",
            "action_reset_to_draft",
        ):
            with self.subTest(method_name=method_name), self.assertRaises(
                UserError
            ):
                getattr(
                    self.entry.with_user(self.manager_user),
                    method_name,
                )()
        self.assertEqual(self.entry.state, "draft")

    def test_direct_state_manipulation_is_rejected(self):
        with self.assertRaises(AccessError):
            self.entry.with_user(self.intern_user).write(
                {"state": "completed"}
            )
        with self.assertRaises(AccessError):
            self.entry.with_user(self.intern_user).with_context(
                _internship_workflow_transition=True
            ).write({"state": "completed"})
        with self.assertRaises(ValidationError):
            self.entry.write({"state": "approved"})
        with self.assertRaises(ValidationError):
            self.supervised_entry.write({"state": "completed"})

    def test_independent_program_completion_semantics_and_statistics(self):
        empty_program = self._new_program("EMPTY", state="active")
        with self.assertRaises(ValidationError):
            empty_program.action_complete()

        second_entry = self.env["internship.daily.entry"].create(
            self._entry_values(
                self.independent_program,
                "2026-09-03",
                "Second independent entry",
            )
        )
        self.entry.with_user(self.intern_user).action_complete()
        with self.assertRaises(ValidationError):
            self.independent_program.action_complete()

        second_entry.with_user(self.intern_user).action_complete()
        self.independent_program.invalidate_recordset()
        self.assertEqual(self.independent_program.completed_entry_count, 2)
        self.assertEqual(self.independent_program.completed_work_hours, 16)
        self.assertEqual(self.independent_program.completion_percentage, 100)
        self.independent_program.action_complete()
        self.assertEqual(self.independent_program.state, "completed")

    def test_independent_workflow_creates_no_supervisor_side_effects(self):
        initial_mail_count = self.env["mail.mail"].search_count([])
        with patch.object(MailTemplate, "send_mail") as send_mail:
            self.entry.with_user(self.intern_user).action_complete()
            self.entry.with_user(self.intern_user).action_reopen()

        send_mail.assert_not_called()
        self.assertEqual(
            self.env["mail.mail"].search_count([]),
            initial_mail_count,
        )
        self.assertFalse(self.entry.activity_ids)
        self.assertNotIn(
            self.supervisor_user.partner_id,
            self.entry.message_partner_ids,
        )
        self.assertFalse(any(
            "supervisor" in str(message.body or "").lower()
            for message in self.entry.message_ids
        ))

    def test_supervisor_cannot_see_independent_records(self):
        supervisor_programs = self.env["internship.program"].with_user(
            self.supervisor_user
        ).search([("id", "=", self.independent_program.id)])
        supervisor_entries = self.env["internship.daily.entry"].with_user(
            self.supervisor_user
        ).search([("id", "=", self.entry.id)])
        self.assertFalse(supervisor_programs)
        self.assertFalse(supervisor_entries)
        with self.assertRaises(AccessError):
            self.entry.with_user(self.supervisor_user).write(
                {"supervisor_comment": "Unauthorized"}
            )

    def test_manager_can_administer_both_modes(self):
        self.independent_program.with_user(self.manager_user).write(
            {"notes": "Manager independent note"}
        )
        self.supervised_program.with_user(self.manager_user).write(
            {"notes": "Manager supervised note"}
        )
        self.entry.with_user(self.manager_user).write(
            {"work_description": "Manager-updated independent entry."}
        )
        self.supervised_entry.with_user(self.manager_user).write(
            {"work_description": "Manager-updated supervised entry."}
        )
        self.assertTrue(self.independent_program.notes)
        self.assertTrue(self.supervised_program.notes)

    def test_five_non_revision_ai_actions_allowed_on_independent_draft(self):
        method_names = (
            "action_ai_improve_writing",
            "action_ai_give_suggestions",
            "action_ai_find_missing_details",
            "action_ai_improve_learned_topics",
            "action_ai_improve_challenges",
        )
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.AI_RESULT,
        ):
            for method_name in method_names:
                with self.subTest(method_name=method_name):
                    action = getattr(
                        self.entry.with_user(self.intern_user),
                        method_name,
                    )()
                    self.assertEqual(action["target"], "new")

    def test_revision_ai_is_rejected_for_independent_mode(self):
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.AI_RESULT,
        ) as generate, self.assertRaises(ValidationError):
            self.entry.with_user(
                self.intern_user
            ).action_ai_revision_assistant()
        generate.assert_not_called()

    def test_independent_ai_apply_updates_only_target_field(self):
        original = {
            "title": self.entry.title,
            "state": self.entry.state,
            "work_description": self.entry.work_description,
            "learned_topics": self.entry.learned_topics,
            "challenges": self.entry.challenges,
            "supervisor_comment": self.entry.supervisor_comment,
        }
        wizard = self._create_ai_wizard(
            action_type="improve_learned_topics"
        )
        wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.learned_topics,
            self.AI_RESULT["suggested_text"],
        )
        for field_name in (
            "title",
            "state",
            "work_description",
            "challenges",
            "supervisor_comment",
        ):
            self.assertEqual(self.entry[field_name], original[field_name])

    def test_independent_ai_cross_intern_and_completed_denials(self):
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.AI_RESULT,
        ), self.assertRaises(AccessError):
            self.entry.with_user(
                self.other_intern_user
            ).action_ai_improve_writing()

        wizard = self._create_ai_wizard()
        self.entry.with_user(self.intern_user).action_complete()
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.AI_RESULT,
        ) as generate, self.assertRaises(ValidationError):
            self.entry.with_user(
                self.intern_user
            ).action_ai_improve_writing()
        generate.assert_not_called()
        with self.assertRaises(ValidationError):
            wizard.action_regenerate()
        with self.assertRaises(ValidationError):
            wizard.action_apply_suggestion()

    def test_independent_ai_stale_suggestion_protection(self):
        wizard = self._create_ai_wizard(action_type="improve_challenges")
        self.entry.with_user(self.intern_user).write(
            {"challenges": "A newer problem description."}
        )
        with self.assertRaises(UserError):
            wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.challenges,
            "A newer problem description.",
        )

    def test_independent_report_is_mode_aware(self):
        self.entry.with_user(self.intern_user).action_complete()
        draft_entry = self.env["internship.daily.entry"].create(
            self._entry_values(
                self.independent_program,
                "2026-09-03",
                "Draft entry must be excluded",
            )
        )
        report_text = self._render_report_text(self.independent_program)
        self.assertIn(self.entry.title, report_text)
        self.assertNotIn(draft_entry.title, report_text)
        self.assertIn(self.entry.learned_topics, report_text)
        self.assertIn(self.entry.challenges, report_text)
        self.assertIn("Completed Entries", report_text)
        self.assertNotIn("Supervisor Comment", report_text)
        self.assertNotIn("Internship Supervisor", report_text)
        self.assertNotIn("Approval", report_text)

    def test_supervised_workflow_regression(self):
        with patch.object(MailTemplate, "send_mail") as send_mail:
            self.supervised_entry.with_user(
                self.supervised_intern_user
            ).action_submit()
            review_activity = self.supervised_entry.activity_ids.filtered(
                lambda activity:
                    activity.user_id == self.supervisor_user
                    and activity.summary == "Review Daily Internship Entry"
            )
            self.assertEqual(len(review_activity), 1)

            self.supervised_entry.with_user(self.supervisor_user).write(
                {"supervisor_comment": "Please clarify the test result."}
            )
            self.supervised_entry.with_user(
                self.supervisor_user
            ).action_request_revision()
            self.assertEqual(self.supervised_entry.state, "revision")
            self.assertTrue(self.supervised_entry.activity_ids.filtered(
                lambda activity:
                    activity.user_id == self.supervised_intern_user
                    and activity.summary == "Revise Daily Internship Entry"
            ))

            self.supervised_entry.with_user(
                self.supervised_intern_user
            ).action_submit()
            self.supervised_entry.with_user(
                self.supervisor_user
            ).action_approve()

        self.assertEqual(self.supervised_entry.state, "approved")
        review_activity.invalidate_recordset(["active"])
        self.assertFalse(review_activity.active)
        self.assertEqual(send_mail.call_count, 4)

        self.supervised_program.with_user(
            self.supervisor_user
        ).action_complete()
        self.assertEqual(self.supervised_program.state, "completed")

    def test_supervised_report_and_statistics_regression(self):
        self.supervised_entry.with_user(
            self.supervised_intern_user
        ).action_submit()
        self.supervised_entry.with_user(
            self.supervisor_user
        ).action_approve()
        draft_entry = self.env["internship.daily.entry"].create(
            self._entry_values(
                self.supervised_program,
                "2026-11-03",
                "Unapproved supervised entry",
            )
        )
        self.supervised_program.invalidate_recordset()
        self.assertEqual(self.supervised_program.approved_entry_count, 1)
        self.assertEqual(self.supervised_program.approved_work_hours, 8)
        self.assertEqual(self.supervised_program.approval_percentage, 50)
        report_text = self._render_report_text(self.supervised_program)
        self.assertIn(self.supervised_entry.title, report_text)
        self.assertNotIn(draft_entry.title, report_text)
        self.assertIn("Supervisor", report_text)
        self.assertIn("Approved Entries", report_text)

    def test_supervised_ai_and_stale_protection_regression(self):
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.AI_RESULT,
        ):
            action = self.supervised_entry.with_user(
                self.supervised_intern_user
            ).action_ai_improve_writing()
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        ).with_user(self.supervised_intern_user)
        self.supervised_entry.with_user(
            self.supervised_intern_user
        ).write(
            {"work_description": "A newer supervised description."}
        )
        with self.assertRaises(UserError):
            wizard.action_apply_suggestion()

    def test_existing_supervised_state_values_remain_valid(self):
        for index, state in enumerate(
            ("draft", "submitted", "revision", "approved"),
            start=4,
        ):
            with self.subTest(state=state):
                entry = self.env["internship.daily.entry"].create(
                    {
                        **self._entry_values(
                            self.supervised_program,
                            f"2026-11-{index:02d}",
                            f"Existing {state} entry",
                        ),
                        "state": state,
                    }
                )
                self.assertEqual(entry.state, state)
