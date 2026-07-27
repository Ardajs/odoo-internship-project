from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase4b")
class TestSupervisorReviewWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        user_group = cls.env.ref("base.group_user")
        cls.supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        cls.manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        cls.intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )

        def new_user(name, group):
            login = name.lower().replace(" ", "-") + "@phase4b.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([user_group.id, group.id])],
            })

        cls.supervisor = new_user("Review Supervisor", cls.supervisor_group)
        cls.other_supervisor = new_user(
            "Other Review Supervisor", cls.supervisor_group
        )
        cls.manager = new_user("Review Manager", cls.manager_group)
        cls.intern = new_user("Review Intern", cls.intern_group)
        cls.ordinary = new_user("Ordinary Employee", user_group)
        cls.student = cls.env["internship.student"].create({
            "name": "Phase 4B Student",
            "student_number": "PHASE4B-001",
            "user_id": cls.intern.id,
            "university": "Test University",
            "department": "Computer Engineering",
        })
        cls.program = cls.env["internship.program"].create({
            "name": "Phase 4B Program",
            "student_id": cls.student.id,
            "company_name": "Review Company",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": cls.supervisor.id,
            "start_date": cls.today - timedelta(days=5),
            "end_date": cls.today + timedelta(days=5),
            "state": "active",
        })

    def _entry(self, *, state="submitted", title=None, offset=0):
        entry = self.env["internship.daily.entry"].create({
            "program_id": self.program.id,
            "entry_date": self.today + timedelta(days=offset),
            "title": title or f"Review {state}",
            "work_description": "A complete daily work description.",
            "work_hours": 8,
            "state": state,
        })
        if state == "submitted":
            entry.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=self.supervisor.id,
                summary="Review Daily Internship Entry",
            )
        return entry

    def test_assigned_supervisor_approval_and_queue_navigation(self):
        entry = self._entry()
        next_entry = self._entry(title="Next review", offset=1)
        with patch.object(MailTemplate, "send_mail") as send_mail:
            action = entry.with_user(self.supervisor).action_approve()
        self.assertEqual(entry.state, "approved")
        self.assertEqual(action["res_id"], next_entry.id)
        self.assertEqual(send_mail.call_count, 1)
        review = entry.activity_ids.filtered(
            lambda activity: activity.summary == "Review Daily Internship Entry"
        )
        review.invalidate_recordset(["active"])
        self.assertFalse(review.active)
        self.assertTrue(any(
            "Daily internship entry approved." in str(message.body or "")
            for message in entry.message_ids
        ))

    def test_revision_requires_comment_before_any_transition(self):
        for offset, comment in enumerate((False, "   ")):
            entry = self._entry(
                title=f"Empty comment {comment!r}", offset=offset
            )
            entry.with_user(self.supervisor).write(
                {"supervisor_comment": comment}
            )
            with self.assertRaises(ValidationError):
                entry.with_user(self.supervisor).action_request_revision()
            self.assertEqual(entry.state, "submitted")
            self.assertFalse(entry.activity_ids.filtered(
                lambda activity: (
                    activity.summary == "Revise Daily Internship Entry"
                )
            ))

    def test_valid_revision_comment_activity_and_no_duplicates(self):
        entry = self._entry()
        entry.with_user(self.supervisor).write({
            "supervisor_comment": "  Explain the test outcome clearly.  "
        })
        with patch.object(MailTemplate, "send_mail") as send_mail:
            entry.with_user(self.supervisor).action_request_revision()
        self.assertEqual(entry.state, "revision")
        self.assertEqual(
            entry.supervisor_comment, "Explain the test outcome clearly."
        )
        revisions = entry.activity_ids.filtered(
            lambda activity: activity.summary == "Revise Daily Internship Entry"
        )
        self.assertEqual(len(revisions), 1)
        self.assertEqual(send_mail.call_count, 1)
        with self.assertRaises(UserError):
            entry.with_user(self.supervisor).action_request_revision()
        self.assertEqual(len(entry.activity_ids.filtered(
            lambda activity: activity.summary == "Revise Daily Internship Entry"
        )), 1)

    def test_authorization_and_foreign_supervisor_isolation(self):
        entry = self._entry()
        with self.assertRaises(AccessError):
            entry.with_user(self.other_supervisor).action_approve()
        with self.assertRaises(AccessError):
            entry.with_user(self.intern).action_approve()
        with self.assertRaises(AccessError):
            entry.with_user(self.ordinary).action_request_revision()
        self.assertEqual(entry.state, "submitted")

    def test_manager_can_review_and_closes_assigned_supervisor_activity(self):
        entry = self._entry()
        with patch.object(MailTemplate, "send_mail"):
            entry.with_user(self.manager).action_approve()
        self.assertEqual(entry.state, "approved")
        review = entry.activity_ids.filtered(
            lambda activity: activity.summary == "Review Daily Internship Entry"
        )
        review.invalidate_recordset(["active"])
        self.assertFalse(review.active)

    def test_invalid_and_stale_states_do_not_change(self):
        for offset, state in enumerate(("draft", "revision", "approved")):
            entry = self._entry(
                state=state, title=f"Invalid {state}", offset=offset
            )
            with self.assertRaises(UserError):
                entry.with_user(self.supervisor).action_approve()
            self.assertEqual(entry.state, state)

        stale = self._entry(title="Stale submitted", offset=3)
        stale._write_workflow_state("approved")
        stale.supervisor_comment = "A valid but stale comment."
        with self.assertRaises(UserError):
            stale.with_user(self.supervisor).action_request_revision()
        self.assertEqual(stale.state, "approved")

    def test_independent_and_multirecord_reviews_are_rejected(self):
        independent_student = self.env["internship.student"].create({
            "name": "Independent Phase 4B Student",
            "student_number": "PHASE4B-INDEPENDENT",
            "university": "Test University",
            "department": "Computer Engineering",
        })
        independent_program = self.env["internship.program"].create({
            "name": "Independent Review Exclusion",
            "student_id": independent_student.id,
            "company_name": "Independent Company",
            "department": "Engineering",
            "workflow_mode": "independent",
            "start_date": self.today - timedelta(days=1),
            "end_date": self.today + timedelta(days=1),
            "state": "active",
        })
        independent = self.env["internship.daily.entry"].create({
            "program_id": independent_program.id,
            "entry_date": self.today,
            "title": "Independent completed",
            "work_description": "Independent work.",
            "work_hours": 8,
            "state": "completed",
        })
        with self.assertRaises(UserError):
            independent.with_user(self.manager).action_approve()
        entries = self._entry(title="Multi one") | self._entry(
            title="Multi two", offset=1
        )
        with self.assertRaises(ValueError):
            entries.with_user(self.supervisor).action_approve()

    def test_form_review_fields_and_buttons_are_state_aware(self):
        arch = etree.fromstring(self.env.ref(
            "internship_logbook.view_internship_daily_entry_form"
        ).arch_db.encode())
        for method in (
            "action_approve",
            "action_request_revision",
            "action_review_next",
            "action_open_student",
            "action_open_program",
        ):
            self.assertTrue(arch.xpath(f"//button[@name='{method}']"), method)
        self.assertTrue(arch.xpath("//field[@name='company_name']"))
        self.assertTrue(arch.xpath("//field[@name='program_department']"))
        self.assertIn(
            "state != 'submitted'",
            arch.xpath("//button[@name='action_approve']/@invisible")[0],
        )
