from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase4d")
class TestBulkReviewOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        user_group = cls.env.ref("base.group_user")
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )

        def new_user(name, group):
            login = name.lower().replace(" ", "-") + "@phase4d.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([user_group.id, group.id])],
            })

        cls.supervisor = new_user("Bulk Supervisor", supervisor_group)
        cls.foreign_supervisor = new_user(
            "Foreign Bulk Supervisor", supervisor_group
        )
        cls.manager = new_user("Bulk Manager", manager_group)
        cls.intern = new_user("Bulk Intern", intern_group)
        cls.student = cls.env["internship.student"].create({
            "name": "Bulk Student",
            "student_number": "BULK-001",
            "user_id": cls.intern.id,
            "university": "Bulk University",
            "department": "Computer Engineering",
        })
        cls.program = cls._program(
            cls.student, cls.supervisor, "Main", "supervised"
        )
        cls.foreign_student = cls.env["internship.student"].create({
            "name": "Foreign Bulk Student",
            "student_number": "BULK-FOREIGN",
            "university": "Foreign University",
            "department": "Computer Engineering",
        })
        cls.foreign_program = cls._program(
            cls.foreign_student,
            cls.foreign_supervisor,
            "Foreign",
            "supervised",
        )
        cls.independent_student = cls.env["internship.student"].create({
            "name": "Independent Bulk Student",
            "student_number": "BULK-INDEPENDENT",
            "university": "Independent University",
            "department": "Computer Engineering",
        })
        cls.independent_program = cls._program(
            cls.independent_student, False, "Independent", "independent"
        )

    @classmethod
    def _program(cls, student, supervisor, suffix, workflow_mode):
        return cls.env["internship.program"].create({
            "name": f"Bulk Program {suffix}",
            "student_id": student.id,
            "company_name": f"Bulk Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "supervisor_id": supervisor.id if supervisor else False,
            "start_date": cls.today - timedelta(days=10),
            "end_date": cls.today + timedelta(days=10),
            "state": "active",
        })

    def _entry(self, offset, *, state="submitted", program=None, comment=None):
        program = program or self.program
        entry = self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": self.today + timedelta(days=offset),
            "title": f"Bulk {program.name} {offset} {state}",
            "work_description": "Complete bulk review test work.",
            "work_hours": 8,
            "state": state,
            "supervisor_comment": comment,
        })
        if state == "submitted" and program.supervisor_id:
            entry.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=program.supervisor_id.id,
                summary="Review Daily Internship Entry",
            )
        return entry

    @staticmethod
    def _message(action):
        return action["params"]["message"]

    def test_contextual_actions_are_list_only_and_group_restricted(self):
        expected_groups = (
            self.env.ref("internship_logbook.group_internship_supervisor")
            | self.env.ref("internship_logbook.group_internship_manager")
        )
        for xml_id in (
            "action_server_internship_bulk_approve",
            "action_server_internship_bulk_request_revision",
        ):
            action = self.env.ref(f"internship_logbook.{xml_id}")
            self.assertEqual(action.binding_view_types, "list")
            self.assertEqual(action.binding_model_id.model, "internship.daily.entry")
            self.assertEqual(action.group_ids, expected_groups)

    def test_bulk_approve_reuses_workflow_and_side_effects(self):
        entries = self._entry(0) | self._entry(1)
        with patch.object(MailTemplate, "send_mail") as send_mail:
            action = entries.with_user(self.supervisor).action_bulk_approve()
        entries.invalidate_recordset()
        self.assertEqual(set(entries.mapped("state")), {"approved"})
        self.assertIn("Approved: 2", self._message(action))
        self.assertEqual(send_mail.call_count, 2)
        for entry in entries:
            reviews = entry.activity_ids.filtered(
                lambda activity: activity.summary == "Review Daily Internship Entry"
            )
            reviews.invalidate_recordset(["active"])
            self.assertFalse(reviews.active)
            self.assertEqual(sum(
                "Daily internship entry approved." in str(message.body or "")
                for message in entry.message_ids
            ), 1)

    def test_bulk_revision_uses_stored_comments_and_no_duplicates(self):
        entries = self._entry(
            0, comment="Clarify the result."
        ) | self._entry(1, comment="Add testing detail.")
        with patch.object(MailTemplate, "send_mail") as send_mail:
            action = entries.with_user(
                self.supervisor
            ).action_bulk_request_revision()
        entries.invalidate_recordset()
        self.assertEqual(set(entries.mapped("state")), {"revision"})
        self.assertIn("Revision Requested: 2", self._message(action))
        self.assertEqual(send_mail.call_count, 2)
        for entry in entries:
            self.assertEqual(len(entry.activity_ids.filtered(
                lambda activity: activity.summary == "Revise Daily Internship Entry"
            )), 1)
            self.assertEqual(sum(
                "Revision requested by the internship supervisor."
                in str(message.body or "")
                for message in entry.message_ids
            ), 1)

        repeated = entries.with_user(
            self.supervisor
        ).action_bulk_request_revision()
        self.assertIn("Already Revision Requested: 2", self._message(repeated))
        for entry in entries:
            self.assertEqual(len(entry.activity_ids.filtered(
                lambda activity: activity.summary == "Revise Daily Internship Entry"
            )), 1)

    def test_mixed_selection_is_partial_and_categorized(self):
        valid = self._entry(0)
        approved = self._entry(1, state="approved")
        revision = self._entry(2, state="revision")
        draft = self._entry(3, state="draft")
        independent = self._entry(
            0, state="completed", program=self.independent_program
        )
        selection = valid | approved | revision | draft | independent
        with patch.object(MailTemplate, "send_mail"):
            action = selection.with_user(self.manager).action_bulk_approve()
        selection.invalidate_recordset()
        self.assertEqual(valid.state, "approved")
        self.assertEqual(approved.state, "approved")
        self.assertEqual(revision.state, "revision")
        self.assertEqual(draft.state, "draft")
        self.assertEqual(independent.state, "completed")
        message = self._message(action)
        for expected in (
            "Approved: 1",
            "Rejected: 1",
            "Already Approved: 1",
            "Already Revision Requested: 1",
            "Independent Workflow: 1",
        ):
            self.assertIn(expected, message)

    def test_supervisor_isolation_and_intern_denial(self):
        foreign = self._entry(0, program=self.foreign_program)
        action = foreign.with_user(self.supervisor).action_bulk_approve()
        self.assertIn("Unauthorized: 1", self._message(action))
        with self.assertRaises(AccessError):
            self._entry(0).with_user(self.intern).action_bulk_approve()
        self.assertEqual(foreign.state, "submitted")

    def test_manager_can_process_multiple_supervisors(self):
        own = self._entry(0)
        foreign = self._entry(0, program=self.foreign_program)
        with patch.object(MailTemplate, "send_mail"):
            action = (own | foreign).with_user(
                self.manager
            ).action_bulk_approve()
        self.assertIn("Approved: 2", self._message(action))
        self.assertEqual(own.state, "approved")
        self.assertEqual(foreign.state, "approved")

    def test_stale_and_invalid_revision_are_rejected_without_side_effects(self):
        stale = self._entry(0, state="approved", comment="Stale comment")
        missing_comment = self._entry(1, comment="   ")
        action = (stale | missing_comment).with_user(
            self.supervisor
        ).action_bulk_request_revision()
        stale.invalidate_recordset()
        missing_comment.invalidate_recordset()
        self.assertEqual(stale.state, "approved")
        self.assertEqual(missing_comment.state, "submitted")
        self.assertIn("Already Approved: 1", self._message(action))
        self.assertIn("Rejected: 1", self._message(action))
        self.assertFalse(missing_comment.activity_ids.filtered(
            lambda activity: activity.summary == "Revise Daily Internship Entry"
        ))
