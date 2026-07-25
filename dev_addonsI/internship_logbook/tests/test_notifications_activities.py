from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase5a")
class TestNotificationsActivities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        internal = cls.env.ref("base.group_user")
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )

        def user(name, group):
            login = name.lower().replace(" ", "-") + "@phase5a.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([internal.id, group.id])],
            })

        cls.intern = user("Notification Intern", intern_group)
        cls.supervisor = user("Notification Supervisor", supervisor_group)
        cls.other_supervisor = user(
            "Other Notification Supervisor", supervisor_group
        )
        cls.manager = user("Notification Manager", manager_group)
        cls.student = cls.env["internship.student"].create({
            "name": "Notification Student",
            "student_number": "PHASE5A-001",
            "user_id": cls.intern.id,
            "university": "Notification University",
            "department": "Computer Engineering",
        })
        cls.program = cls.env["internship.program"].create({
            "name": "Notification Program",
            "student_id": cls.student.id,
            "company_name": "Notification Company",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": cls.supervisor.id,
            "start_date": cls.today - timedelta(days=2),
            "end_date": cls.today + timedelta(days=2),
            "state": "active",
        })

    def _entry(self, offset=0, state="draft"):
        return self.env["internship.daily.entry"].create({
            "program_id": self.program.id,
            "entry_date": self.today + timedelta(days=offset),
            "title": f"Notification Entry {offset}",
            "work_description": "Notification lifecycle test.",
            "work_hours": 8,
            "state": state,
        })

    def _active_activities(self, entry, summary):
        entry.invalidate_recordset(["activity_ids"])
        return entry.activity_ids.filtered(
            lambda activity: activity.summary == summary
        )

    def test_full_activity_lifecycle_and_notification_order(self):
        entry = self._entry()
        with patch.object(MailTemplate, "send_mail") as send_mail:
            entry.with_user(self.intern).action_submit()
            self.assertEqual(len(self._active_activities(
                entry, entry._review_activity_summary
            )), 1)
            entry.with_user(self.supervisor).write({
                "supervisor_comment": "Please add the result."
            })
            entry.with_user(self.supervisor).action_request_revision()
            self.assertFalse(self._active_activities(
                entry, entry._review_activity_summary
            ))
            self.assertEqual(len(self._active_activities(
                entry, entry._revision_activity_summary
            )), 1)
            entry.with_user(self.intern).action_submit()
            self.assertFalse(self._active_activities(
                entry, entry._revision_activity_summary
            ))
            self.assertEqual(len(self._active_activities(
                entry, entry._review_activity_summary
            )), 1)
            entry.with_user(self.supervisor).action_approve()
        self.assertEqual(entry.state, "approved")
        self.assertFalse(self._active_activities(
            entry, entry._review_activity_summary
        ))
        self.assertEqual(send_mail.call_count, 4)

        expected = [
            "Daily entry submitted for supervisor review.",
            "Revision requested by the internship supervisor.",
            "Daily entry submitted for supervisor review.",
            "Daily internship entry approved.",
        ]
        bodies = [str(message.body or "") for message in reversed(
            entry.message_ids
        )]
        positions = []
        cursor = 0
        for text in expected:
            position = next(
                index
                for index, body in enumerate(bodies[cursor:], start=cursor)
                if text in body
            )
            positions.append(position)
            cursor = position + 1
        self.assertEqual(positions, sorted(positions))

    def test_duplicate_review_activity_is_not_created(self):
        entry = self._entry()
        entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.supervisor.id,
            summary=entry._review_activity_summary,
        )
        with patch.object(MailTemplate, "send_mail"):
            entry.with_user(self.intern).action_submit()
        self.assertEqual(len(self._active_activities(
            entry, entry._review_activity_summary
        )), 1)

    def test_reset_to_draft_closes_revision_activity(self):
        entry = self._entry(state="revision")
        entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.intern.id,
            summary=entry._revision_activity_summary,
        )
        entry.with_user(self.intern).action_reset_to_draft()
        self.assertEqual(entry.state, "draft")
        self.assertFalse(self._active_activities(
            entry, entry._revision_activity_summary
        ))

    def test_program_cancellation_closes_workflow_activities(self):
        entry = self._entry(state="submitted")
        entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.supervisor.id,
            summary=entry._review_activity_summary,
        )
        entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.intern.id,
            summary=entry._revision_activity_summary,
        )
        self.program.with_user(self.supervisor).action_cancel()
        self.assertEqual(self.program.state, "cancelled")
        self.assertFalse(self._active_activities(
            entry, entry._review_activity_summary
        ))
        self.assertFalse(self._active_activities(
            entry, entry._revision_activity_summary
        ))

    def test_reminder_helpers_respect_scope_and_order(self):
        pending = self._entry(state="submitted")
        domain = [("id", "=", pending.id)]
        self.assertEqual(
            self.env["internship.daily.entry"].with_user(
                self.supervisor
            )._find_pending_reviews(domain=domain),
            pending,
        )
        self.assertFalse(
            self.env["internship.daily.entry"].with_user(
                self.other_supervisor
            )._find_pending_reviews(domain=domain)
        )
        ending = self.env["internship.program"].with_user(
            self.supervisor
        )._find_programs_ending_soon(days=7, today=self.today)
        self.assertEqual(ending, self.program)
        missing = self.env["internship.program"].with_user(
            self.supervisor
        )._find_missing_entries(today=self.today)
        self.assertIn(self.program, missing)
        manager_pending = self.env["internship.daily.entry"].with_user(
            self.manager
        )._find_pending_reviews(domain=domain)
        self.assertEqual(manager_pending, pending)

    def test_mail_templates_render_consistent_safe_headers(self):
        entry = self._entry()
        templates = (
            ("mail_template_daily_entry_submitted", self.supervisor.email),
            ("mail_template_daily_entry_revision", self.intern.email),
            ("mail_template_daily_entry_approved", self.intern.email),
        )
        for xml_id, recipient in templates:
            template = self.env.ref(f"internship_logbook.{xml_id}")
            subject = template._render_field("subject", [entry.id])[entry.id]
            email_to = template._render_field(
                "email_to", [entry.id]
            )[entry.id]
            self.assertTrue(subject.strip().startswith("[Internship Logbook]"))
            self.assertEqual(email_to.strip(), recipient)
            self.assertNotIn("False", email_to)

    def test_helper_security_does_not_bypass_record_rules(self):
        pending = self._entry(state="submitted")
        with self.assertRaises(AccessError):
            pending.with_user(self.other_supervisor).check_access("read")
        self.assertFalse(
            self.env["internship.daily.entry"].with_user(
                self.other_supervisor
            )._find_pending_reviews(domain=[("id", "=", pending.id)])
        )
