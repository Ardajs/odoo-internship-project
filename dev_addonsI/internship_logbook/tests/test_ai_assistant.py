import os
from unittest.mock import patch

import requests

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.ai_provider import AIProviderService


@tagged("post_install", "-at_install")
class TestInternshipAIAssistant(TransactionCase):
    MOCK_ENVIRONMENT = {
        "INTERNSHIP_AI_ENABLED": "True",
        "INTERNSHIP_AI_PROVIDER": "mock",
    }
    PROVIDER_RESULT = {
        "suggested_text": "I implemented and tested the assigned Odoo model.",
        "feedback": "Grammar and clarity were improved without adding facts.",
        "warnings": [],
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        cls.intern_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "AI Test Intern",
                "login": "ai_test_intern",
                "group_ids": [
                    Command.set((internal_group | intern_group).ids)
                ],
            }
        )
        cls.other_intern_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Other AI Test Intern",
                "login": "other_ai_test_intern",
                "group_ids": [
                    Command.set((internal_group | intern_group).ids)
                ],
            }
        )
        cls.manager_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "AI Test Manager",
                "login": "ai_test_manager",
                "group_ids": [
                    Command.set((internal_group | manager_group).ids)
                ],
            }
        )
        cls.supervisor_user = cls.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "AI Test Supervisor",
                "login": "ai_test_supervisor",
                "group_ids": [
                    Command.set((internal_group | supervisor_group).ids)
                ],
            }
        )

        cls.student = cls.env["internship.student"].create(
            {
                "name": "AI Test Student",
                "student_number": "AI-TEST-001",
                "user_id": cls.intern_user.id,
                "university": "Test University",
                "department": "Software Engineering",
            }
        )
        cls.other_student = cls.env["internship.student"].create(
            {
                "name": "Other AI Test Student",
                "student_number": "AI-TEST-002",
                "user_id": cls.other_intern_user.id,
                "university": "Test University",
                "department": "Software Engineering",
            }
        )
        cls.program = cls.env["internship.program"].create(
            {
                "name": "AI Test Program",
                "student_id": cls.student.id,
                "company_name": "Test Company",
                "department": "Engineering",
                "supervisor_id": cls.supervisor_user.id,
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
                "state": "active",
            }
        )
        cls.other_program = cls.env["internship.program"].create(
            {
                "name": "Other AI Test Program",
                "student_id": cls.other_student.id,
                "company_name": "Test Company",
                "department": "Engineering",
                "supervisor_id": cls.supervisor_user.id,
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "state": "active",
            }
        )

    def setUp(self):
        super().setUp()
        self.entry = self.env["internship.daily.entry"].create(
            {
                "title": "Odoo model work",
                "program_id": self.program.id,
                "entry_date": "2026-07-02",
                "work_hours": 8,
                "work_description": "i implemented and tested assigned odoo model",
                "learned_topics": "i learned how odoo models are structured",
                "challenges": (
                    "i found a validation issue and fixed it by correcting the domain"
                ),
                "state": "draft",
            }
        )

    def _open_with_result(self, method_name, result=None):
        with patch.object(
            AIProviderService,
            "generate",
            return_value=result or self.PROVIDER_RESULT,
        ):
            return getattr(self.entry.with_user(self.intern_user), method_name)()

    def _create_wizard(self, action_type, suggested_text="Improved text"):
        target_fields = {
            "improve": "work_description",
            "revision": "work_description",
            "suggestions": "work_description",
            "missing_details": "work_description",
            "improve_learned_topics": "learned_topics",
            "improve_challenges": "challenges",
        }
        target_field = target_fields[action_type]
        return self.env["internship.ai.assistant.wizard"].with_user(
            self.intern_user
        ).create(
            {
                "entry_id": self.entry.id,
                "action_type": action_type,
                "target_field": target_field,
                "original_text": self.entry[target_field],
                "suggested_text": suggested_text,
                "feedback": "Test feedback",
            }
        )

    def test_draft_entry_opens_ai_wizard(self):
        action = self._open_with_result("action_ai_improve_writing")
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        )
        self.assertEqual(action["target"], "new")
        self.assertEqual(wizard.entry_id, self.entry)
        self.assertEqual(wizard.action_type, "improve")

    def test_revision_entry_opens_revision_assistant(self):
        self.entry.write(
            {
                "state": "revision",
                "supervisor_comment": "Explain the testing process in more detail.",
            }
        )
        action = self._open_with_result("action_ai_revision_assistant")
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        )
        self.assertEqual(wizard.action_type, "revision")
        self.assertEqual(
            wizard.supervisor_comment,
            self.entry.supervisor_comment,
        )

    def test_draft_entry_opens_learned_topics_ai_wizard(self):
        action = self._open_with_result(
            "action_ai_improve_learned_topics",
        )
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        )
        self.assertEqual(wizard.action_type, "improve_learned_topics")
        self.assertEqual(wizard.target_field, "learned_topics")
        self.assertEqual(wizard.original_text, self.entry.learned_topics)

    def test_draft_entry_opens_challenges_ai_wizard(self):
        action = self._open_with_result(
            "action_ai_improve_challenges",
        )
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        )
        self.assertEqual(wizard.action_type, "improve_challenges")
        self.assertEqual(wizard.target_field, "challenges")
        self.assertEqual(wizard.original_text, self.entry.challenges)

    def test_submitted_entry_rejects_apply(self):
        wizard = self._create_wizard("improve")
        self.entry.state = "submitted"
        with self.assertRaises(ValidationError):
            wizard.action_apply_suggestion()

    def test_approved_entry_rejects_apply(self):
        wizard = self._create_wizard("improve")
        self.entry.state = "approved"
        with self.assertRaises(ValidationError):
            wizard.action_apply_suggestion()

    def test_new_field_actions_reject_apply_after_submission_or_approval(self):
        for action_type in (
            "improve_learned_topics",
            "improve_challenges",
        ):
            for state in ("submitted", "approved"):
                with self.subTest(action_type=action_type, state=state):
                    self.entry.state = "draft"
                    wizard = self._create_wizard(action_type)
                    self.entry.state = state
                    with self.assertRaises(ValidationError):
                        wizard.action_apply_suggestion()

    def test_approve_completes_only_supervisor_review_activity(self):
        self.entry.with_user(self.intern_user).action_submit()

        supervisor_activity = self.entry.activity_ids.filtered(
            lambda activity:
                activity.user_id == self.supervisor_user
                and activity.summary == "Review Daily Internship Entry"
        )
        self.assertEqual(len(supervisor_activity), 1)

        unrelated_activity = self.entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.manager_user.id,
            summary="Review Daily Internship Entry",
            note="This unrelated manager activity must remain open.",
        )

        self.entry.with_user(self.supervisor_user).action_approve()

        self.assertEqual(self.entry.state, "approved")
        supervisor_activity.invalidate_recordset(["active", "feedback"])
        self.assertFalse(supervisor_activity.active)
        self.assertEqual(
            supervisor_activity.feedback,
            "Daily internship entry reviewed and approved.",
        )
        self.assertTrue(unrelated_activity.exists())
        self.assertTrue(unrelated_activity.active)
        self.assertEqual(unrelated_activity.user_id, self.manager_user)
        self.assertTrue(any(
            "Daily internship entry approved." in str(message.body or "")
            for message in self.entry.message_ids
        ))

    def test_resubmit_completes_only_intern_revision_activity(self):
        self.entry.with_user(self.intern_user).action_submit()
        self.entry.supervisor_comment = "Please clarify the testing outcome."
        self.entry.with_user(self.supervisor_user).action_request_revision()

        intern_activity = self.entry.activity_ids.filtered(
            lambda activity:
                activity.user_id == self.intern_user
                and activity.summary == "Revise Daily Internship Entry"
        )
        self.assertEqual(len(intern_activity), 1)

        unrelated_activity = self.entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.manager_user.id,
            summary="Revise Daily Internship Entry",
            note="This unrelated manager activity must remain open.",
        )

        self.entry.with_user(self.intern_user).action_submit()

        self.assertEqual(self.entry.state, "submitted")
        intern_activity.invalidate_recordset(["active", "feedback"])
        self.assertFalse(intern_activity.active)
        self.assertEqual(
            intern_activity.feedback,
            "Daily internship entry revised and resubmitted.",
        )
        self.assertTrue(unrelated_activity.exists())
        self.assertTrue(unrelated_activity.active)
        self.assertEqual(unrelated_activity.user_id, self.manager_user)

    def test_other_intern_entry_is_not_accessible(self):
        other_entry = self.env["internship.daily.entry"].create(
            {
                "title": "Other intern work",
                "program_id": self.other_program.id,
                "entry_date": "2026-08-02",
                "work_hours": 8,
                "work_description": "Other intern description",
            }
        )
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.PROVIDER_RESULT,
        ), self.assertRaises(AccessError):
            other_entry.with_user(
                self.intern_user
            ).action_ai_improve_writing()

    def test_supervisor_cannot_use_ai_to_edit_student_content(self):
        with patch.object(
            AIProviderService,
            "generate",
            return_value=self.PROVIDER_RESULT,
        ), self.assertRaises(AccessError):
            self.entry.with_user(
                self.supervisor_user
            ).action_ai_improve_writing()

    def test_supervisor_cannot_use_new_field_ai_actions(self):
        for method_name in (
            "action_ai_improve_learned_topics",
            "action_ai_improve_challenges",
        ):
            with self.subTest(method_name=method_name), patch.object(
                AIProviderService,
                "generate",
                return_value=self.PROVIDER_RESULT,
            ), self.assertRaises(AccessError):
                getattr(
                    self.entry.with_user(self.supervisor_user),
                    method_name,
                )()

    def test_missing_configuration_is_user_friendly(self):
        original_text = self.entry.work_description
        with patch.dict(
            os.environ,
            {"INTERNSHIP_AI_ENABLED": "false"},
            clear=False,
        ), self.assertRaisesRegex(UserError, "AI Assistant is not configured"):
            self.entry.with_user(
                self.intern_user
            ).action_ai_improve_writing()
        self.assertEqual(self.entry.work_description, original_text)

    def test_provider_error_leaves_entry_unchanged(self):
        original_text = self.entry.work_description
        with patch.object(
            AIProviderService,
            "generate",
            side_effect=UserError("The AI Assistant timed out."),
        ), self.assertRaises(UserError):
            self.entry.with_user(
                self.intern_user
            ).action_ai_improve_writing()
        self.assertEqual(self.entry.work_description, original_text)

    def test_apply_updates_editable_entry(self):
        action = self._open_with_result("action_ai_improve_writing")
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        ).with_user(self.intern_user)
        wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.work_description,
            self.PROVIDER_RESULT["suggested_text"],
        )

    def test_apply_learned_topics_updates_only_target_field(self):
        original_values = {
            "title": self.entry.title,
            "state": self.entry.state,
            "supervisor_comment": self.entry.supervisor_comment,
            "work_description": self.entry.work_description,
            "challenges": self.entry.challenges,
        }
        action = self._open_with_result(
            "action_ai_improve_learned_topics",
        )
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        ).with_user(self.intern_user)
        wizard.action_apply_suggestion()

        self.assertEqual(
            self.entry.learned_topics,
            self.PROVIDER_RESULT["suggested_text"],
        )
        for field_name, value in original_values.items():
            self.assertEqual(self.entry[field_name], value)

    def test_apply_challenges_updates_only_target_field(self):
        original_values = {
            "title": self.entry.title,
            "state": self.entry.state,
            "supervisor_comment": self.entry.supervisor_comment,
            "work_description": self.entry.work_description,
            "learned_topics": self.entry.learned_topics,
        }
        action = self._open_with_result(
            "action_ai_improve_challenges",
        )
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        ).with_user(self.intern_user)
        wizard.action_apply_suggestion()

        self.assertEqual(
            self.entry.challenges,
            self.PROVIDER_RESULT["suggested_text"],
        )
        for field_name, value in original_values.items():
            self.assertEqual(self.entry[field_name], value)

    def test_suggestions_do_not_change_entry(self):
        original_text = self.entry.work_description
        feedback_result = {
            "suggested_text": "",
            "feedback": "Describe the testing method.",
            "warnings": [],
        }
        action = self._open_with_result(
            "action_ai_give_suggestions",
            feedback_result,
        )
        wizard = self.env["internship.ai.assistant.wizard"].browse(
            action["res_id"]
        ).with_user(self.intern_user)
        self.assertEqual(self.entry.work_description, original_text)
        with self.assertRaises(ValidationError):
            wizard.action_apply_suggestion()

    def test_missing_details_do_not_change_entry(self):
        original_text = self.entry.work_description
        feedback_result = {
            "suggested_text": "",
            "feedback": "The problem and learning outcome are not described.",
            "warnings": [],
        }
        self._open_with_result(
            "action_ai_find_missing_details",
            feedback_result,
        )
        self.assertEqual(self.entry.work_description, original_text)

    def test_stale_suggestion_cannot_overwrite_newer_text(self):
        wizard = self._create_wizard("improve")
        self.entry.work_description = "A newer manual edit"
        with self.assertRaises(UserError):
            wizard.action_apply_suggestion()
        self.assertEqual(self.entry.work_description, "A newer manual edit")

    def test_stale_learned_topics_suggestion_is_rejected(self):
        wizard = self._create_wizard("improve_learned_topics")
        self.entry.learned_topics = "A newer learning summary"
        with self.assertRaises(UserError):
            wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.learned_topics,
            "A newer learning summary",
        )

    def test_stale_challenges_suggestion_is_rejected(self):
        wizard = self._create_wizard("improve_challenges")
        self.entry.challenges = "A newer problem and solution summary"
        with self.assertRaises(UserError):
            wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.challenges,
            "A newer problem and solution summary",
        )

    def test_new_target_snapshot_is_independent_from_work_description(self):
        wizard = self._create_wizard(
            "improve_learned_topics",
            suggested_text="Improved learning summary.",
        )
        self.entry.work_description = "A newer work description"
        wizard.action_apply_suggestion()
        self.assertEqual(
            self.entry.learned_topics,
            "Improved learning summary.",
        )
        self.assertEqual(
            self.entry.work_description,
            "A newer work description",
        )

    def test_regenerate_refreshes_new_target_field_snapshot(self):
        for action_type, target_field, new_text in (
            (
                "improve_learned_topics",
                "learned_topics",
                "I learned how record rules are evaluated.",
            ),
            (
                "improve_challenges",
                "challenges",
                "I corrected a record rule domain after testing access.",
            ),
        ):
            with self.subTest(action_type=action_type):
                wizard = self._create_wizard(action_type)
                self.entry[target_field] = new_text
                regenerated_result = {
                    **self.PROVIDER_RESULT,
                    "suggested_text": f"Improved: {new_text}",
                }
                with patch.object(
                    AIProviderService,
                    "generate",
                    return_value=regenerated_result,
                ):
                    wizard.action_regenerate()

                self.assertEqual(wizard.original_text, new_text)
                wizard.action_apply_suggestion()
                self.assertEqual(
                    self.entry[target_field],
                    regenerated_result["suggested_text"],
                )

    def test_target_field_tampering_is_rejected(self):
        wizard = self._create_wizard("improve_learned_topics")
        wizard.target_field = "challenges"
        with self.assertRaisesRegex(ValidationError, "target field is invalid"):
            wizard.action_apply_suggestion()
        self.assertNotEqual(
            self.entry.challenges,
            wizard.suggested_text,
        )

    def test_mock_provider_never_calls_http_or_reads_api_key(self):
        service = AIProviderService(self.env)
        with patch.dict(
            os.environ,
            self.MOCK_ENVIRONMENT,
            clear=False,
        ), patch.object(
            requests,
            "post",
        ) as http_post, patch.object(
            service,
            "_get_setting",
            wraps=service._get_setting,
        ) as get_setting:
            result = service.generate(
                action_type="improve",
                title=self.entry.title,
                original_text=self.entry.work_description,
            )

        http_post.assert_not_called()
        requested_settings = [call.args[0] for call in get_setting.call_args_list]
        self.assertNotIn("api_key", requested_settings)
        self.assertNotIn("model", requested_settings)
        self.assertNotIn("endpoint", requested_settings)
        self.assertTrue(result["suggested_text"])

    def test_mock_provider_returns_all_structured_action_results(self):
        service = AIProviderService(self.env)
        revision_comment = "Explain the testing process more clearly."
        with patch.dict(
            os.environ,
            self.MOCK_ENVIRONMENT,
            clear=False,
        ), patch.object(requests, "post") as http_post:
            results = {
                action_type: service.generate(
                    action_type=action_type,
                    title=self.entry.title,
                    original_text=self.entry.work_description,
                    revision_comment=(
                        revision_comment if action_type == "revision" else None
                    ),
                )
                for action_type in (
                    "improve",
                    "suggestions",
                    "missing_details",
                    "revision",
                    "improve_learned_topics",
                    "improve_challenges",
                )
            }

        http_post.assert_not_called()
        for result in results.values():
            self.assertEqual(
                set(result),
                {"suggested_text", "feedback", "warnings"},
            )
            self.assertTrue(result["feedback"])
            self.assertIsInstance(result["warnings"], list)

        self.assertTrue(results["improve"]["suggested_text"])
        self.assertTrue(results["revision"]["suggested_text"])
        self.assertTrue(results["improve_learned_topics"]["suggested_text"])
        self.assertTrue(results["improve_challenges"]["suggested_text"])
        self.assertIn(revision_comment, results["revision"]["feedback"])
        self.assertFalse(results["suggestions"]["suggested_text"])
        self.assertFalse(results["missing_details"]["suggested_text"])
        for category in (
            "Yapılan görev",
            "Teknoloji/araç",
            "Süreç/yöntem",
            "Problem",
            "Çözüm",
            "Öğrenilen kazanım",
        ):
            self.assertIn(category, results["missing_details"]["feedback"])

    def test_mock_provider_meaningfully_rewrites_short_new_field_texts(self):
        service = AIProviderService(self.env)
        learned_source = "I learned about Odoo models."
        challenge_source = (
            "I had a database connection problem and fixed it."
        )
        with patch.dict(
            os.environ,
            self.MOCK_ENVIRONMENT,
            clear=False,
        ), patch.object(requests, "post") as http_post:
            learned_result = service.generate(
                action_type="improve_learned_topics",
                title=self.entry.title,
                original_text=learned_source,
                work_description=self.entry.work_description,
            )
            challenge_result = service.generate(
                action_type="improve_challenges",
                title=self.entry.title,
                original_text=challenge_source,
                work_description=self.entry.work_description,
            )
            suggestions_result = service.generate(
                action_type="suggestions",
                title=self.entry.title,
                original_text=self.entry.work_description,
            )
            missing_result = service.generate(
                action_type="missing_details",
                title=self.entry.title,
                original_text=self.entry.work_description,
            )

        http_post.assert_not_called()
        self.assertNotEqual(
            learned_result["suggested_text"],
            learned_source,
        )
        self.assertIn(
            "Odoo models",
            learned_result["suggested_text"],
        )
        for invented_detail in (
            "Python",
            "PostgreSQL",
            "custom module",
            "implemented",
        ):
            self.assertNotIn(
                invented_detail,
                learned_result["suggested_text"],
            )

        self.assertNotEqual(
            challenge_result["suggested_text"],
            challenge_source,
        )
        self.assertIn(
            "database connection",
            challenge_result["suggested_text"],
        )
        self.assertIn(
            "resolved",
            challenge_result["suggested_text"],
        )
        for invented_detail in (
            "port",
            "credential",
            "password",
            "command",
            "root cause",
            "configuration",
        ):
            self.assertNotIn(
                invented_detail,
                challenge_result["suggested_text"].lower(),
            )

        self.assertFalse(suggestions_result["suggested_text"])
        self.assertFalse(missing_result["suggested_text"])

    def test_mock_provider_apply_flow_uses_existing_wizard_rules(self):
        original_text = self.entry.work_description
        with patch.dict(
            os.environ,
            self.MOCK_ENVIRONMENT,
            clear=False,
        ), patch.object(requests, "post") as http_post:
            action = self.entry.with_user(
                self.intern_user
            ).action_ai_improve_writing()
            wizard = self.env["internship.ai.assistant.wizard"].browse(
                action["res_id"]
            ).with_user(self.intern_user)
            self.assertEqual(self.entry.work_description, original_text)
            wizard.action_apply_suggestion()

        http_post.assert_not_called()
        self.assertEqual(
            self.entry.work_description,
            "I implemented and tested assigned odoo model.",
        )

    def test_mock_provider_regenerate_is_different_and_deterministic(self):
        with patch.dict(
            os.environ,
            self.MOCK_ENVIRONMENT,
            clear=False,
        ), patch.object(requests, "post") as http_post:
            action = self.entry.with_user(
                self.intern_user
            ).action_ai_give_suggestions()
            wizard = self.env["internship.ai.assistant.wizard"].browse(
                action["res_id"]
            ).with_user(self.intern_user)
            initial_feedback = wizard.feedback
            wizard.action_regenerate()
            regenerated_feedback = wizard.feedback
            wizard.action_regenerate()

        http_post.assert_not_called()
        self.assertNotEqual(initial_feedback, regenerated_feedback)
        self.assertEqual(wizard.feedback, regenerated_feedback)
        self.assertFalse(wizard.suggested_text)
