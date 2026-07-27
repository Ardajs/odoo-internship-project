from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "phase4e")
class TestProgramOverview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal = cls.env.ref("base.group_user")
        supervisor_group = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        manager_group = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        intern_group = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )

        def create_user(name, group):
            login = name.lower().replace(" ", "-") + "@phase4e.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([internal.id, group.id])],
            })

        cls.supervisor = create_user("Overview Supervisor", supervisor_group)
        cls.other_supervisor = create_user("Other Supervisor", supervisor_group)
        cls.manager = create_user("Overview Manager", manager_group)
        cls.intern = create_user("Overview Intern", intern_group)
        cls.student = cls.env["internship.student"].create({
            "name": "Overview Student",
            "student_number": "OVERVIEW-001",
            "user_id": cls.intern.id,
            "university": "Overview University",
            "department": "Computer Engineering",
        })
        cls.program = cls.env["internship.program"].create({
            "name": "Overview Program",
            "student_id": cls.student.id,
            "company_name": "Overview Company",
            "department": "Platform Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": cls.supervisor.id,
            "start_date": fields.Date.today() - timedelta(days=5),
            "end_date": fields.Date.today() + timedelta(days=5),
            "state": "active",
        })
        states = ("submitted", "approved", "revision")
        cls.entries = cls.env["internship.daily.entry"]
        for offset, state in enumerate(states):
            cls.entries |= cls.env["internship.daily.entry"].create({
                "program_id": cls.program.id,
                "entry_date": fields.Date.today() - timedelta(days=offset),
                "title": f"Overview Entry {offset}",
                "work_description": "Backend overview test entry.",
                "work_hours": offset + 1,
                "state": state,
            })

    def test_overview_counters_and_related_information(self):
        self.assertEqual(self.program.student_number, "OVERVIEW-001")
        self.assertEqual(self.program.student_university, "Overview University")
        self.assertEqual(self.program.student_department, "Computer Engineering")
        self.assertEqual(self.program.daily_entry_count, 3)
        self.assertEqual(self.program.submitted_entry_count, 1)
        self.assertEqual(self.program.approved_entry_count, 1)
        self.assertEqual(self.program.revision_entry_count, 1)
        self.assertEqual(self.program.completed_entry_count, 0)
        self.assertEqual(self.program.total_work_hours, 6)

    def test_overview_view_and_smart_buttons(self):
        arch = etree.fromstring(self.env.ref(
            "internship_logbook.view_internship_program_form"
        ).arch_db.encode())
        for field_name in (
            "student_number", "student_university", "student_department",
            "daily_entry_count", "submitted_entry_count",
            "approved_entry_count", "revision_entry_count",
            "completed_entry_count", "total_work_hours",
            "missing_day_count", "approval_percentage",
            "completion_percentage",
        ):
            self.assertTrue(arch.xpath(f"//field[@name='{field_name}']"))
        for method in (
            "action_view_daily_entries", "action_view_review_queue",
            "action_view_student_overview", "action_view_analytics",
            "action_export_pdf",
        ):
            self.assertTrue(arch.xpath(f"//button[@name='{method}']"))
        recent_list = arch.xpath("//field[@name='daily_entry_ids']/list")[0]
        self.assertEqual(
            recent_list.get("default_order"), "entry_date desc, id desc"
        )

    def test_smart_button_actions_are_program_scoped(self):
        self.assertEqual(
            self.program.action_view_daily_entries()["domain"],
            [("program_id", "=", self.program.id)],
        )
        analytics = self.program.action_view_analytics()
        self.assertEqual(
            analytics["domain"], [("program_id", "=", self.program.id)]
        )
        report = self.program.with_user(self.manager).action_export_pdf()
        self.assertEqual(report["type"], "ir.actions.report")

    def test_supervisor_isolation_manager_visibility_and_intern_menu_denial(self):
        program_model = self.env["internship.program"]
        self.assertEqual(
            program_model.with_user(self.supervisor).search([
                ("id", "=", self.program.id)
            ]),
            self.program,
        )
        self.assertFalse(program_model.with_user(self.other_supervisor).search([
            ("id", "=", self.program.id)
        ]))
        self.assertEqual(
            program_model.with_user(self.manager).search([
                ("id", "=", self.program.id)
            ]),
            self.program,
        )
        menu = self.env.ref(
            "internship_logbook.menu_internship_program_overview"
        )
        self.assertNotIn(
            self.env.ref("internship_logbook.group_internship_intern"),
            menu.group_ids,
        )
        with self.assertRaises(AccessError):
            program_model.with_user(self.other_supervisor).browse(
                self.program.id
            ).check_access("read")
