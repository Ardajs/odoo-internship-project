from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install", "phase4c")
class TestBackendAnalytics(TransactionCase):
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

        def new_user(name, group):
            login = name.lower().replace(" ", "-") + "@phase4c.test"
            return cls.env["res.users"].with_context(
                no_reset_password=True
            ).create({
                "name": name,
                "login": login,
                "email": login,
                "group_ids": [Command.set([user_group.id, group.id])],
            })

        cls.supervisor = new_user("Analytics Supervisor", supervisor_group)
        cls.foreign_supervisor = new_user(
            "Foreign Analytics Supervisor", supervisor_group
        )
        cls.manager = new_user("Analytics Manager", manager_group)
        cls.ordinary = new_user("Analytics Employee", user_group)
        cls.own_entry = cls._create_chain(cls.supervisor, "OWN", 9)
        cls.foreign_entry = cls._create_chain(
            cls.foreign_supervisor, "FOREIGN", 4
        )

    @classmethod
    def _create_chain(cls, supervisor, suffix, hours):
        student = cls.env["internship.student"].create({
            "name": f"Analytics Student {suffix}",
            "student_number": f"ANALYTICS-{suffix}",
            "university": f"University {suffix}",
            "department": "Computer Engineering",
        })
        program = cls.env["internship.program"].create({
            "name": f"Analytics Program {suffix}",
            "student_id": student.id,
            "company_name": f"Company {suffix}",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": supervisor.id,
            "start_date": cls.today - timedelta(days=10),
            "end_date": cls.today + timedelta(days=10),
            "state": "active",
        })
        return cls.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": cls.today,
            "title": f"Analytics Entry {suffix}",
            "work_description": "Analytics test work.",
            "work_hours": hours,
            "state": "submitted",
        })

    def test_analytics_actions_and_menu_permissions(self):
        for xml_id in (
            "action_internship_daily_entry_analytics",
            "action_internship_monthly_report",
            "action_internship_company_report",
            "action_internship_monthly_hours_report",
            "action_internship_university_report",
            "action_internship_supervisor_report",
            "action_internship_approved_revision_report",
            "action_internship_submitted_approved_report",
        ):
            action = self.env.ref(f"internship_logbook.{xml_id}")
            self.assertEqual(action.res_model, "internship.daily.entry")
            self.assertIn("graph", action.view_mode)

        menu = self.env.ref("internship_logbook.menu_internship_analytics")
        expected = (
            self.env.ref("internship_logbook.group_internship_supervisor")
            | self.env.ref("internship_logbook.group_internship_manager")
        )
        self.assertEqual(menu.group_ids, expected)

    def test_pivot_dimensions_and_measures(self):
        arch = etree.fromstring(self.env.ref(
            "internship_logbook.view_internship_daily_entry_analytics_pivot"
        ).arch_db.encode())
        for field_name in (
            "supervisor_id",
            "company_name",
            "student_university",
            "student_id",
            "program_id",
            "state",
            "entry_date",
        ):
            self.assertTrue(
                arch.xpath(f"//field[@name='{field_name}']"), field_name
            )
        self.assertTrue(arch.xpath(
            "//field[@name='work_hours'][@type='measure']"
        ))

    def test_graph_views_load_with_native_dimensions(self):
        expected = {
            "view_internship_entries_by_month_graph": "entry_date",
            "view_internship_hours_by_month_graph": "entry_date",
            "view_internship_entries_by_company_graph": "company_name",
            "view_internship_entries_by_university_graph": "student_university",
            "view_internship_entries_by_supervisor_graph": "supervisor_id",
            "view_internship_approved_revision_graph": "state",
            "view_internship_submitted_approved_graph": "state",
        }
        for xml_id, dimension in expected.items():
            view = self.env.ref(f"internship_logbook.{xml_id}")
            self.assertEqual(view.type, "graph")
            arch = etree.fromstring(view.arch_db.encode())
            self.assertTrue(arch.xpath(f"//field[@name='{dimension}']"))
        hours_arch = etree.fromstring(self.env.ref(
            "internship_logbook.view_internship_hours_by_month_graph"
        ).arch_db.encode())
        self.assertTrue(hours_arch.xpath(
            "//field[@name='work_hours'][@type='measure']"
        ))

    def test_search_period_hour_filters_and_group_by(self):
        arch = etree.fromstring(self.env.ref(
            "internship_logbook.view_internship_daily_entry_search"
        ).arch_db.encode())
        for name in (
            "filter_last_30_days",
            "filter_current_month",
            "filter_previous_month",
            "filter_current_year",
            "filter_high_hours",
            "filter_low_hours",
            "group_by_supervisor",
            "group_by_company",
            "group_by_university",
            "group_by_student",
            "group_by_program",
            "group_by_state",
            "group_by_entry_month",
        ):
            nodes = arch.xpath(f"//filter[@name='{name}']")
            self.assertTrue(nodes, name)
            if nodes[0].get("domain"):
                safe_eval(nodes[0].get("domain"), {
                    "context_today": lambda: self.today,
                    "relativedelta": __import__(
                        "dateutil.relativedelta", fromlist=["relativedelta"]
                    ).relativedelta,
                })

    def test_supervisor_isolation_and_manager_visibility(self):
        model = self.env["internship.daily.entry"]
        supervisor_entries = model.with_user(self.supervisor).search([])
        self.assertEqual(supervisor_entries, self.own_entry)
        grouped = model.with_user(self.supervisor)._read_group(
            [], ["company_name"], ["__count", "work_hours:sum"]
        )
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0][1], 1)
        self.assertEqual(grouped[0][2], 9)

        manager_entries = model.with_user(self.manager).search([
            ("id", "in", (self.own_entry | self.foreign_entry).ids)
        ])
        self.assertEqual(manager_entries, self.own_entry | self.foreign_entry)
        with self.assertRaises(AccessError):
            model.with_user(self.ordinary).check_access("read")
