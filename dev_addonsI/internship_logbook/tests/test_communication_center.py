from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase5c")
class TestCommunicationCenter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        internal = cls.env.ref("base.group_user")
        portal = cls.env.ref("base.group_portal")
        intern_group = cls.env.ref("internship_logbook.group_internship_intern")
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        portal_group = cls.env.ref(
            "internship_logbook.group_internship_portal_intern"
        )

        def user(name, groups, email=True):
            login = name.lower().replace(" ", "-") + "@phase5c.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login if email else False,
                "group_ids": [Command.set([group.id for group in groups])],
            })

        cls.intern = user("Communication Intern", (internal, intern_group))
        cls.supervisor = user(
            "Communication Supervisor", (internal, supervisor_group)
        )
        cls.foreign_supervisor = user(
            "Foreign Communication Supervisor", (internal, supervisor_group)
        )
        cls.manager = user("Communication Manager", (internal, manager_group))
        cls.portal = user("Communication Portal", (portal, portal_group))
        cls.student = cls.env["internship.student"].create({
            "name": "Communication Student",
            "student_number": "PHASE5C-001",
            "user_id": cls.intern.id,
            "university": "Communication University",
            "department": "Computer Engineering",
        })
        cls.program = cls.env["internship.program"].create({
            "name": "Communication Program",
            "student_id": cls.student.id,
            "company_name": "Communication Company",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": cls.supervisor.id,
            "start_date": cls.today - timedelta(days=2),
            "end_date": cls.today + timedelta(days=7),
            "state": "active",
        })

    def _entry(self, state="submitted", offset=0):
        return self.env["internship.daily.entry"].create({
            "program_id": self.program.id,
            "entry_date": self.today + timedelta(days=offset),
            "title": f"Communication Entry {state} {offset}",
            "work_description": "Communication Center test entry.",
            "work_hours": 8,
            "state": state,
        })

    def _service(self, user):
        return self.env["internship.communication.service"].with_user(user)

    def test_menu_and_wizard_access_are_restricted(self):
        menu = self.env.ref("internship_logbook.menu_internship_communication")
        allowed = self.env.ref("internship_logbook.group_internship_supervisor")
        manager = self.env.ref("internship_logbook.group_internship_manager")
        self.assertEqual(menu.group_ids, allowed | manager)
        wizard_model = "internship.communication.center.wizard"
        self.assertTrue(
            self.env["ir.model.access"].with_user(self.supervisor).check(
                wizard_model, "create", raise_exception=False
            )
        )
        self.assertFalse(
            self.env["ir.model.access"].with_user(self.intern).check(
                wizard_model, "create", raise_exception=False
            )
        )
        self.assertFalse(
            self.env["ir.model.access"].with_user(self.portal).check(
                wizard_model, "create", raise_exception=False
            )
        )

    def test_allowlist_rejects_unsupported_model_and_record(self):
        entry = self._entry()
        service = self._service(self.manager)
        with self.assertRaises(ValidationError):
            service.prepare("unsupported", entry._name, entry.id)
        with self.assertRaises(ValidationError):
            service.prepare("entry_submitted", "internship.program", entry.id)
        with self.assertRaises(AccessError):
            service.prepare("entry_submitted", entry._name, 999999999)

    def test_recipient_resolution_and_rendering_for_entry_categories(self):
        cases = [
            ("entry_submitted", "submitted", self.supervisor),
            ("pending_review", "submitted", self.supervisor),
            ("revision_requested", "revision", self.intern),
            ("entry_approved", "approved", self.intern),
        ]
        for index, (category, state, recipient) in enumerate(cases):
            entry = self._entry(state=state, offset=index)
            values = self._service(self.manager).prepare(
                category, entry._name, entry.id
            )
            self.assertEqual(values["recipient"], recipient)
            self.assertIn("Internship Logbook", values["subject"])
            self.assertTrue(values["body"])

    def test_preview_has_no_mail_chatter_activity_or_state_side_effect(self):
        entry = self._entry()
        before = (
            self.env["mail.mail"].search_count([]),
            len(entry.message_ids),
            len(entry.activity_ids),
            entry.state,
        )
        self._service(self.supervisor).prepare(
            "entry_submitted", entry._name, entry.id
        )
        after = (
            self.env["mail.mail"].search_count([]),
            len(entry.message_ids),
            len(entry.activity_ids),
            entry.state,
        )
        self.assertEqual(after, before)

    def test_manual_send_queues_governed_mail_and_controlled_resend(self):
        entry = self._entry()
        service = self._service(self.supervisor)
        mail_id = service.send("entry_submitted", entry._name, entry.id)
        mail = self.env["mail.mail"].browse(mail_id)
        self.assertEqual(mail.state, "outgoing")
        self.assertEqual(mail.email_to, self.supervisor.email)
        self.assertEqual(
            mail.subtype_id,
            self.env.ref("internship_logbook.mt_communication_entry_submitted"),
        )
        self.assertEqual(mail.model, entry._name)
        self.assertEqual(mail.res_id, entry.id)
        with self.assertRaises(UserError):
            service.send("entry_submitted", entry._name, entry.id)
        resent_id = service.send(
            "entry_submitted", entry._name, entry.id, allow_resend=True
        )
        self.assertNotEqual(resent_id, mail_id)
        self.assertEqual(entry.state, "submitted")

    def test_send_revalidates_state_and_recipient(self):
        entry = self._entry()
        entry.write({"state": "approved"})
        with self.assertRaises(ValidationError):
            self._service(self.manager).send(
                "entry_submitted", entry._name, entry.id
            )
        self.supervisor.email = False
        pending = self._entry(offset=1)
        with self.assertRaises(ValidationError):
            self._service(self.manager).prepare(
                "pending_review", pending._name, pending.id
            )

    def test_supervisor_isolation_and_manager_visibility(self):
        entry = self._entry()
        with self.assertRaises(AccessError):
            self._service(self.foreign_supervisor).prepare(
                "entry_submitted", entry._name, entry.id
            )
        values = self._service(self.manager).prepare(
            "entry_submitted", entry._name, entry.id
        )
        self.assertEqual(values["recipient"], self.supervisor)

    def test_intern_and_portal_service_denial(self):
        entry = self._entry()
        for user in (self.intern, self.portal):
            with self.assertRaises(AccessError):
                self._service(user).prepare(
                    "entry_submitted", entry._name, entry.id
                )

    def test_program_reminder_preview_and_no_automatic_cron_email(self):
        missing = self._service(self.manager).prepare(
            "missing_entries", self.program._name, self.program.id
        )
        ending = self._service(self.manager).prepare(
            "program_ending", self.program._name, self.program.id
        )
        self.assertTrue(missing["subject"])
        self.assertEqual(ending["recipient"], self.supervisor)
        cron_xmlids = (
            "ir_cron_pending_review_reminders",
            "ir_cron_missing_entry_reminders",
            "ir_cron_ending_soon_reminders",
        )
        self.assertTrue(all(
            not self.env.ref(f"internship_logbook.{xmlid}").active
            for xmlid in cron_xmlids
        ))

    def test_history_is_category_and_record_scoped(self):
        entry = self._entry()
        service = self._service(self.manager)
        service.send("entry_submitted", entry._name, entry.id)
        other = self._entry(offset=1)
        self.assertTrue(service.prepare(
            "entry_submitted", entry._name, entry.id
        )["already_sent"])
        self.assertFalse(service.prepare(
            "entry_submitted", other._name, other.id
        )["already_sent"])

    def test_template_render_failure_is_safely_translated(self):
        entry = self._entry()
        with patch.object(
            type(self.env["mail.template"]),
            "_render_field",
            side_effect=RuntimeError("render"),
        ), self.assertRaisesRegex(
            UserError, "preview could not be rendered"
        ):
            self._service(self.manager).prepare(
                "entry_submitted", entry._name, entry.id
            )
