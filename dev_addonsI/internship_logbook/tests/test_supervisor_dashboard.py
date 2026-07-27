from datetime import timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestInternshipSupervisorDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.group_user = cls.env.ref("base.group_user")
        cls.group_supervisor = cls.env.ref(
            "internship_logbook.group_internship_supervisor"
        )
        cls.group_manager = cls.env.ref(
            "internship_logbook.group_internship_manager"
        )
        cls.group_intern = cls.env.ref(
            "internship_logbook.group_internship_intern"
        )
        cls.supervisor_one = cls._create_user(
            "Supervisor Dashboard One",
            "dashboard-supervisor-one@example.test",
            cls.group_supervisor,
        )
        cls.supervisor_two = cls._create_user(
            "Supervisor Dashboard Two",
            "dashboard-supervisor-two@example.test",
            cls.group_supervisor,
        )
        cls.manager = cls._create_user(
            "Dashboard Manager",
            "dashboard-manager@example.test",
            cls.group_manager,
        )
        cls.intern = cls._create_user(
            "Dashboard Intern",
            "dashboard-intern@example.test",
            cls.group_intern,
        )

        cls.student_one = cls._create_student("ONE", cls.intern)
        cls.student_two = cls._create_student("TWO")
        cls.student_foreign = cls._create_student("FOREIGN")
        cls.student_independent = cls._create_student("INDEPENDENT")

        cls.active_program = cls._create_program(
            cls.student_one,
            "Active One",
            cls.supervisor_one,
            cls.today - timedelta(days=3),
            cls.today + timedelta(days=5),
        )
        cls.completed_program = cls._create_program(
            cls.student_two,
            "Completed One",
            cls.supervisor_one,
            cls.today - timedelta(days=40),
            cls.today - timedelta(days=20),
            state="completed",
        )
        cls.foreign_program = cls._create_program(
            cls.student_foreign,
            "Foreign Active",
            cls.supervisor_two,
            cls.today,
            cls.today + timedelta(days=10),
        )
        cls.independent_program = cls.env["internship.program"].create({
            "name": "Independent Excluded",
            "student_id": cls.student_independent.id,
            "company_name": "Independent Company",
            "department": "Engineering",
            "workflow_mode": "independent",
            "start_date": cls.today - timedelta(days=3),
            "end_date": cls.today + timedelta(days=5),
            "state": "active",
        })

        cls.pending_entry = cls._create_entry(
            cls.active_program,
            "Pending",
            cls.today - timedelta(days=3),
            "submitted",
        )
        cls.revision_entry = cls._create_entry(
            cls.active_program,
            "Revision",
            cls.today - timedelta(days=2),
            "revision",
        )
        cls.approved_entry = cls._create_entry(
            cls.active_program,
            "Approved",
            cls.today - timedelta(days=1),
            "approved",
        )
        cls.foreign_pending_entry = cls._create_entry(
            cls.foreign_program,
            "Foreign Pending",
            cls.today,
            "submitted",
        )
        cls._create_entry(
            cls.independent_program,
            "Independent Completed",
            cls.today - timedelta(days=1),
            "completed",
        )

    @classmethod
    def _create_user(cls, name, login, group):
        return cls.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": name,
            "login": login,
            "email": login,
            "group_ids": [Command.set([cls.group_user.id, group.id])],
        })

    @classmethod
    def _create_student(cls, suffix, user=None):
        return cls.env["internship.student"].create({
            "name": f"Dashboard Student {suffix}",
            "student_number": f"DASHBOARD-{suffix}",
            "user_id": user.id if user else False,
            "university": f"Dashboard University {suffix}",
            "department": "Computer Engineering",
        })

    @classmethod
    def _create_program(
        cls,
        student,
        suffix,
        supervisor,
        start_date,
        end_date,
        *,
        state="active",
    ):
        return cls.env["internship.program"].create({
            "name": f"Dashboard Program {suffix}",
            "student_id": student.id,
            "company_name": f"Dashboard Company {suffix}",
            "department": "Engineering",
            "workflow_mode": "supervised",
            "supervisor_id": supervisor.id,
            "start_date": start_date,
            "end_date": end_date,
            "state": state,
        })

    @classmethod
    def _create_entry(cls, program, suffix, entry_date, state):
        return cls.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": entry_date,
            "title": f"Dashboard Entry {suffix}",
            "work_description": f"Dashboard work {suffix}",
            "work_hours": 8,
            "state": state,
            "supervisor_comment": (
                "Please revise this entry." if state == "revision" else False
            ),
        })

    def _dashboard(self, user):
        return user.with_user(user)

    def test_dashboard_statistics_are_correct_and_mode_scoped(self):
        dashboard = self._dashboard(self.supervisor_one)

        self.assertEqual(dashboard.internship_pending_review_count, 1)
        self.assertEqual(dashboard.internship_revision_requested_count, 1)
        self.assertEqual(dashboard.internship_approved_entries_count, 1)
        self.assertEqual(dashboard.internship_completed_programs_count, 1)
        self.assertEqual(dashboard.internship_active_programs_count, 1)
        self.assertEqual(dashboard.internship_ending_soon_count, 1)
        self.assertEqual(dashboard.internship_students_missing_days_count, 1)
        self.assertEqual(dashboard.internship_assigned_students_count, 2)

        foreign_dashboard = self._dashboard(self.supervisor_two)
        self.assertEqual(foreign_dashboard.internship_pending_review_count, 1)
        self.assertEqual(foreign_dashboard.internship_revision_requested_count, 0)
        self.assertEqual(foreign_dashboard.internship_assigned_students_count, 1)

    def test_dashboard_and_menu_permissions(self):
        action = self.env["res.users"].with_user(
            self.supervisor_one
        ).action_open_internship_supervisor_dashboard()
        self.assertEqual(action["res_id"], self.supervisor_one.id)
        self.assertEqual(action["res_model"], "res.users")

        server_action = self.env.ref(
            "internship_logbook."
            "action_server_internship_supervisor_dashboard"
        ).with_user(self.supervisor_one).run()
        self.assertEqual(server_action["res_id"], self.supervisor_one.id)

        manager_action = self.env["res.users"].with_user(
            self.manager
        ).action_open_internship_supervisor_dashboard()
        self.assertEqual(manager_action["res_id"], self.manager.id)

        with self.assertRaises(AccessError):
            self.env["res.users"].with_user(
                self.intern
            ).action_open_internship_supervisor_dashboard()
        with self.assertRaises(AccessError):
            self.supervisor_two.with_user(
                self.supervisor_one
            ).action_internship_pending_review()

        menu = self.env.ref(
            "internship_logbook.menu_internship_supervisor_dashboard"
        )
        self.assertEqual(
            menu.group_ids,
            self.group_supervisor | self.group_manager,
        )

    def test_review_queue_and_dashboard_actions_preserve_ownership(self):
        queue_action = self.env.ref(
            "internship_logbook.action_internship_supervisor_review_queue"
        )
        queue_domain = safe_eval(queue_action.domain)
        supervisor_entries = self.env[
            "internship.daily.entry"
        ].with_user(self.supervisor_one).search(queue_domain)
        self.assertEqual(supervisor_entries, self.pending_entry)

        manager_entries = self.env[
            "internship.daily.entry"
        ].with_user(self.manager).search(queue_domain)
        self.assertIn(self.pending_entry, manager_entries)
        self.assertIn(self.foreign_pending_entry, manager_entries)

        dashboard_action = self._dashboard(
            self.supervisor_one
        ).action_internship_pending_review()
        dashboard_entries = self.env[
            "internship.daily.entry"
        ].with_user(self.supervisor_one).search(dashboard_action["domain"])
        self.assertEqual(dashboard_entries, self.pending_entry)

        self.assertFalse(
            self.env["internship.daily.entry"].with_user(
                self.supervisor_one
            ).search([("id", "=", self.foreign_pending_entry.id)])
        )
        self.assertFalse(
            self.env["internship.program"].with_user(
                self.supervisor_one
            ).search([("id", "=", self.foreign_program.id)])
        )

    def test_missing_days_filter_and_ending_soon_action(self):
        programs = self.env["internship.program"].with_user(
            self.supervisor_one
        ).search([("has_missing_days", "=", True)])
        self.assertEqual(programs, self.active_program)
        self.assertEqual(self.active_program.missing_day_count, 1)
        missing_program_entries = self.env[
            "internship.daily.entry"
        ].with_user(self.supervisor_one).search([
            ("program_id.has_missing_days", "=", True),
        ])
        self.assertEqual(
            set(missing_program_entries.ids),
            {
                self.pending_entry.id,
                self.revision_entry.id,
                self.approved_entry.id,
            },
        )

        missing_action = self._dashboard(
            self.supervisor_one
        ).action_internship_students_missing_days()
        students = self.env["internship.student"].with_user(
            self.supervisor_one
        ).search(missing_action["domain"])
        self.assertEqual(students, self.student_one)

        ending_action = self._dashboard(
            self.supervisor_one
        ).action_internship_ending_soon()
        ending_programs = self.env["internship.program"].with_user(
            self.supervisor_one
        ).search(ending_action["domain"])
        self.assertEqual(ending_programs, self.active_program)

    def test_search_filters_group_by_and_analytical_views(self):
        daily_arch = etree.fromstring(
            self.env.ref(
                "internship_logbook.view_internship_daily_entry_search"
            ).arch_db.encode()
        )
        for filter_name in (
            "filter_my_students",
            "filter_pending_review",
            "filter_submitted_today",
            "filter_this_week",
            "filter_missing_days",
            "filter_ending_soon",
            "group_by_supervisor",
            "group_by_company",
            "group_by_university",
            "group_by_program",
            "group_by_student",
            "group_by_state",
            "group_by_entry_month",
        ):
            self.assertTrue(
                daily_arch.xpath(f"//filter[@name='{filter_name}']"),
                filter_name,
            )

        program_arch = etree.fromstring(
            self.env.ref(
                "internship_logbook.view_internship_program_search"
            ).arch_db.encode()
        )
        for filter_name in (
            "filter_my_students",
            "filter_missing_days",
            "filter_ending_soon",
            "group_by_supervisor",
            "group_by_company",
            "group_by_university",
            "group_by_state",
            "group_by_start_month",
        ):
            self.assertTrue(
                program_arch.xpath(f"//filter[@name='{filter_name}']"),
                filter_name,
            )

        self.assertEqual(
            self.env.ref(
                "internship_logbook.view_internship_daily_entry_pivot"
            ).type,
            "pivot",
        )
        self.assertEqual(
            self.env.ref(
                "internship_logbook.view_internship_daily_entry_graph"
            ).type,
            "graph",
        )

    def test_review_queue_order_and_program_smart_buttons(self):
        review_view = etree.fromstring(
            self.env.ref(
                "internship_logbook.view_internship_supervisor_review_queue_list"
            ).arch_db.encode()
        )
        self.assertEqual(
            review_view.xpath("//list/@default_order"),
            ["write_date desc, entry_date desc, id desc"],
        )

        program = self.active_program.with_user(self.supervisor_one)
        review_action = program.action_view_review_queue()
        self.assertIn(("program_id", "=", program.id), review_action["domain"])
        self.assertIn(("state", "=", "submitted"), review_action["domain"])

        student_action = program.action_view_student_overview()
        self.assertEqual(student_action["res_id"], self.student_one.id)
        self.assertEqual(student_action["res_model"], "internship.student")

        missing_action = program.action_view_missing_days()
        self.assertEqual(missing_action["domain"], [("id", "=", program.id)])
        self.assertEqual(
            missing_action["context"]["search_default_filter_missing_days"],
            1,
        )

    def test_related_search_fields_and_existing_workflow_regression(self):
        self.assertEqual(
            self.pending_entry.company_name,
            self.active_program.company_name,
        )
        self.assertEqual(
            self.pending_entry.student_university,
            self.student_one.university,
        )
        self.assertEqual(
            self.active_program.student_university,
            self.student_one.university,
        )

        self.pending_entry.with_user(self.supervisor_one).action_approve()
        self.assertEqual(self.pending_entry.state, "approved")
        dashboard = self._dashboard(self.supervisor_one)
        self.assertEqual(dashboard.internship_pending_review_count, 0)
        self.assertEqual(dashboard.internship_approved_entries_count, 2)
