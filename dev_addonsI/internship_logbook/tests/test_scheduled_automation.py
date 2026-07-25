from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.addons.mail.models.mail_template import MailTemplate
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase5b")
class TestScheduledAutomation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        internal = cls.env.ref("base.group_user")
        portal = cls.env.ref("base.group_portal")
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        portal_intern_group = cls.env.ref(
            "internship_logbook.group_internship_portal_intern"
        )

        def user(name, groups):
            login = name.lower().replace(" ", "-") + "@phase5b.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([group.id for group in groups])],
            })

        cls.intern = user("Cron Intern", (internal, intern_group))
        cls.supervisor = user(
            "Cron Supervisor", (internal, supervisor_group)
        )
        cls.other_supervisor = user(
            "Other Cron Supervisor", (internal, supervisor_group)
        )
        cls.manager = user("Cron Manager", (internal, manager_group))
        cls.portal_intern = user(
            "Cron Portal Intern", (portal, portal_intern_group)
        )
        cls.student = cls._student(
            "Cron Student", "PHASE5B-001", cls.intern
        )
        cls.program = cls._program(
            cls.student,
            cls.supervisor,
            "Cron Program",
            start=cls.today - timedelta(days=2),
            end=cls.today + timedelta(days=2),
        )

    @classmethod
    def _student(cls, name, number, user):
        return cls.env["internship.student"].create({
            "name": name,
            "student_number": number,
            "user_id": user.id if user else False,
            "university": "Cron University",
            "department": "Computer Engineering",
        })

    @classmethod
    def _program(cls, student, supervisor, name, start, end, state="active"):
        return cls.env["internship.program"].create({
            "name": name,
            "student_id": student.id,
            "company_name": "Cron Company",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": supervisor.id,
            "start_date": start,
            "end_date": end,
            "state": state,
        })

    def _entry(self, program=None, state="submitted", offset=0):
        program = program or self.program
        return self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": self.today + timedelta(days=offset),
            "title": f"Cron Entry {program.id}-{offset}",
            "work_description": "Scheduled automation test entry.",
            "work_hours": 8,
            "state": state,
        })

    def _activities(self, record, summary):
        record.invalidate_recordset(["activity_ids"])
        return record.activity_ids.filtered(
            lambda activity: activity.summary == summary
        )

    def test_cron_records_are_daily_inactive_and_bound(self):
        expected = {
            "ir_cron_pending_review_reminders": (
                "internship.daily.entry", "_cron_remind_pending_reviews"
            ),
            "ir_cron_missing_entry_reminders": (
                "internship.program", "_cron_remind_missing_entries"
            ),
            "ir_cron_ending_soon_reminders": (
                "internship.program", "_cron_remind_programs_ending_soon"
            ),
        }
        for xml_id, (model, method) in expected.items():
            cron = self.env.ref(f"internship_logbook.{xml_id}")
            self.assertFalse(cron.active)
            self.assertEqual(cron.interval_number, 1)
            self.assertEqual(cron.interval_type, "days")
            self.assertEqual(cron.model_id.model, model)
            self.assertIn(method, cron.code)

    def test_pending_review_creation_reuse_and_idempotency(self):
        entry = self._entry()
        model = self.env["internship.daily.entry"].with_user(self.manager)
        domain = [("id", "=", entry.id)]
        with patch.object(MailTemplate, "send_mail") as send_mail:
            first = model._process_pending_review_reminders(domain=domain)
            second = model._process_pending_review_reminders(domain=domain)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["existing"], 1)
        self.assertEqual(len(self._activities(
            entry, entry._review_activity_summary
        )), 1)
        send_mail.assert_not_called()

    def test_existing_workflow_review_activity_is_reused(self):
        entry = self._entry()
        entry.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.supervisor.id,
            summary=entry._review_activity_summary,
        )
        stats = self.env["internship.daily.entry"].with_user(
            self.manager
        )._process_pending_review_reminders(
            domain=[("id", "=", entry.id)]
        )
        self.assertEqual(stats["existing"], 1)
        self.assertEqual(len(self._activities(
            entry, entry._review_activity_summary
        )), 1)

    def test_missing_entry_creation_duplicate_and_zero_cleanup(self):
        model = self.env["internship.program"].with_user(self.manager)
        domain = [("id", "=", self.program.id)]
        first = model._process_missing_entry_reminders(
            today=self.today, domain=domain
        )
        second = model._process_missing_entry_reminders(
            today=self.today, domain=domain
        )
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["existing"], 1)
        reminder = self._activities(
            self.program, self.program._missing_activity_summary
        )
        self.assertEqual(len(reminder), 1)
        self.assertEqual(reminder.user_id, self.intern)

        for offset in (-2, -1, 0):
            self._entry(state="draft", offset=offset)
        cleaned = model._process_missing_entry_reminders(
            today=self.today, domain=domain
        )
        self.assertGreaterEqual(cleaned["cleaned"], 1)
        self.assertFalse(self._activities(
            self.program, self.program._missing_activity_summary
        ))

    def test_portal_user_is_never_activity_assignee(self):
        portal_student = self._student(
            "Portal Cron Student", "PHASE5B-PORTAL", self.portal_intern
        )
        portal_program = self._program(
            portal_student,
            self.supervisor,
            "Portal Cron Program",
            self.today - timedelta(days=2),
            self.today + timedelta(days=3),
        )
        self.env["internship.program"].with_user(
            self.manager
        )._process_missing_entry_reminders(
            today=self.today, domain=[("id", "=", portal_program.id)]
        )
        reminder = self._activities(
            portal_program, portal_program._missing_activity_summary
        )
        self.assertEqual(reminder.user_id, self.supervisor)
        self.assertNotEqual(reminder.user_id, self.portal_intern)

    def test_ending_soon_creation_idempotency_and_window(self):
        model = self.env["internship.program"].with_user(self.manager)
        domain = [("id", "=", self.program.id)]
        first = model._process_ending_soon_reminders(
            days=7, today=self.today, domain=domain
        )
        second = model._process_ending_soon_reminders(
            days=7, today=self.today, domain=domain
        )
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["existing"], 1)
        reminder = self._activities(
            self.program, self.program._ending_activity_summary
        )
        self.assertEqual(len(reminder), 1)
        self.assertEqual(reminder.user_id, self.supervisor)

        far_student = self._student(
            "Far Cron Student", "PHASE5B-FAR", None
        )
        far_program = self._program(
            far_student,
            self.supervisor,
            "Far Cron Program",
            self.today + timedelta(days=20),
            self.today + timedelta(days=30),
        )
        model._process_ending_soon_reminders(
            days=7,
            today=self.today,
            domain=[("id", "=", far_program.id)],
        )
        self.assertFalse(self._activities(
            far_program, far_program._ending_activity_summary
        ))

    def test_terminal_program_states_cleanup_only_reminders(self):
        missing = self.program.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.intern.id,
            summary=self.program._missing_activity_summary,
        )
        ending = self.program.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.supervisor.id,
            summary=self.program._ending_activity_summary,
        )
        unrelated = self.program.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.supervisor.id,
            summary="Unrelated Program Activity",
        )
        self.program.with_user(self.supervisor).action_cancel()
        for activity in (missing, ending):
            activity.invalidate_recordset(["active"])
            self.assertFalse(activity.active)
        unrelated.invalidate_recordset(["active"])
        self.assertTrue(unrelated.active)

    def test_completed_cancelled_and_past_programs_are_not_reminded(self):
        model = self.env["internship.program"].with_user(self.manager)
        records = self.env["internship.program"]
        for index, state in enumerate(("completed", "cancelled")):
            student = self._student(
                f"Terminal Student {index}",
                f"PHASE5B-TERMINAL-{index}",
                None,
            )
            records |= self._program(
                student,
                self.supervisor,
                f"Terminal Program {index}",
                self.today - timedelta(days=2),
                self.today + timedelta(days=2),
                state=state,
            )
        past_student = self._student(
            "Past Cron Student", "PHASE5B-PAST", None
        )
        records |= self._program(
            past_student,
            self.supervisor,
            "Past Cron Program",
            self.today - timedelta(days=10),
            self.today - timedelta(days=1),
        )
        model._process_ending_soon_reminders(
            days=7,
            today=self.today,
            domain=[("id", "in", records.ids)],
        )
        for program in records:
            self.assertFalse(self._activities(
                program, program._ending_activity_summary
            ))

    def test_execution_user_guard_and_supervisor_isolation(self):
        self._entry()
        root_stats = self.env["internship.daily.entry"].with_user(
            self.env.ref("base.user_root")
        )._cron_remind_pending_reviews()
        supervisor_stats = self.env["internship.daily.entry"].with_user(
            self.supervisor
        )._cron_remind_pending_reviews()
        self.assertEqual(root_stats["failed"], 1)
        self.assertEqual(supervisor_stats["failed"], 1)
        self.assertFalse(self.program.activity_ids)

    def test_failure_isolation_and_no_mail_or_chatter(self):
        other_student = self._student(
            "Failure Cron Student", "PHASE5B-FAILURE", None
        )
        failing = self._program(
            other_student,
            self.supervisor,
            "Failure Cron Program",
            self.today - timedelta(days=1),
            self.today + timedelta(days=1),
        )
        model = self.env["internship.program"].with_user(self.manager)
        model_class = type(model)
        original = model_class._schedule_unique_program_reminder

        def fail_one(record, user, summary, note):
            if record.id == failing.id:
                raise RuntimeError("isolated test failure")
            return original(record, user, summary, note)

        before_messages = len(self.program.message_ids)
        with (
            patch.object(
                model_class,
                "_schedule_unique_program_reminder",
                fail_one,
            ),
            patch.object(MailTemplate, "send_mail") as send_mail,
        ):
            stats = model._process_ending_soon_reminders(
                days=7,
                today=self.today,
                domain=[("id", "in", (self.program | failing).ids)],
            )
        self.assertEqual(stats["failed"], 1)
        self.assertGreaterEqual(stats["created"], 1)
        self.assertEqual(len(self.program.message_ids), before_messages)
        send_mail.assert_not_called()
