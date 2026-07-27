from unittest.mock import patch

from lxml import html

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from odoo.addons.base.models.ir_actions_report import IrActionsReport


@tagged("post_install", "-at_install")
class TestPortalInternshipPdfExport(HttpCase):
    PASSWORD = "Portal-pdf-export-passphrase-2026!"
    REPORT_XMLID = (
        "internship_logbook.action_report_portal_internship_logbook"
    )

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal PDF {suffix}",
            "login": f"portal-pdf-{suffix}@example.test",
            "email": f"portal-pdf-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"].create({
            "name": user.name,
            "student_number": f"PDF-{suffix.upper()}",
            "user_id": user.id,
            "email": user.email,
            "university": f"PDF University {suffix}",
            "department": "Computer Engineering",
        })
        return user, student

    def _create_program(
        self,
        student,
        suffix,
        *,
        workflow_mode="independent",
        state="active",
        active=True,
        start_date="2026-09-01",
        end_date="2026-09-30",
    ):
        values = {
            "name": f"PDF Program {suffix}",
            "student_id": student.id,
            "company_name": f"PDF Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "state": state,
            "active": active,
            "start_date": start_date,
            "end_date": end_date,
        }
        if workflow_mode == "supervised":
            values["supervisor_id"] = self.env.ref("base.user_admin").id
        return self.env["internship.program"].with_context(
            active_test=False,
        ).create(values)

    def _create_entry(
        self,
        program,
        suffix,
        entry_date,
        *,
        state,
        work_hours=8,
        active=True,
        supervisor_comment=False,
    ):
        return self.env["internship.daily.entry"].create({
            "program_id": program.id,
            "entry_date": entry_date,
            "title": f"PDF Entry {suffix}",
            "work_description": f"PDF description {suffix}",
            "work_hours": work_hours,
            "state": state,
            "active": active,
            "supervisor_comment": supervisor_comment,
        })

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _render_report(self, user, program):
        report = self.env.ref(self.REPORT_XMLID)
        rendered = self.env["ir.actions.report"].with_user(
            user
        )._render_qweb_html(report.id, program.ids)[0]
        return rendered.decode()

    def _report_values(self, user, program):
        return self.env[
            "report.internship_logbook.report_portal_internship_logbook"
        ].with_user(user)._get_report_values(program.ids)

    def _fake_pdf_response(self, url="/my/internship/export/pdf"):
        fake_pdf = b"%PDF-1.4\n% portal export test\n"
        with patch.object(
            IrActionsReport,
            "_render_qweb_pdf",
            autospec=True,
            return_value=(fake_pdf, "pdf"),
        ) as renderer:
            response = self.url_open(url, allow_redirects=False)
        return response, renderer, fake_pdf

    def test_portal_export_route_downloads_selected_owned_program(self):
        user, student = self._create_portal_user("route")
        program = self._create_program(student, "Route")
        _foreign_user, foreign_student = self._create_portal_user("foreign")
        foreign_program = self._create_program(
            foreign_student,
            "Foreign",
        )
        self._authenticate(user)

        response, renderer, fake_pdf = self._fake_pdf_response(
            "/my/internship/export/pdf"
            f"?student_id={foreign_student.id}"
            f"&program_id={foreign_program.id}"
            "&entry_id=999&start_date=1900-01-01"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, fake_pdf)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("Internship%20Logbook", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(renderer.call_args.kwargs["res_ids"], program.ids)

    def test_public_redirect_and_ordinary_portal_denial(self):
        public = self.url_open(
            "/my/internship/export/pdf",
            allow_redirects=False,
        )
        self.assertIn(public.status_code, (302, 303))
        self.assertIn("/web/login", public.headers["Location"])

        ordinary, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        response = self.url_open(
            "/my/internship/export/pdf",
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_no_program_and_multiple_active_are_safe(self):
        no_program_user, _student = self._create_portal_user("none")
        self._authenticate(no_program_user)
        no_program = self.url_open("/my/internship/export/pdf")
        self.assertEqual(no_program.status_code, 200)
        self.assertIn("No internship program is currently available", no_program.text)

        user, student = self._create_portal_user("multiple")
        self._create_program(
            student,
            "First",
            start_date="2026-01-01",
            end_date="2026-01-31",
        )
        self._create_program(
            student,
            "Second",
            start_date="2026-03-01",
            end_date="2026-03-31",
        )
        self._authenticate(user)
        multiple = self.url_open("/my/internship/export/pdf")
        self.assertEqual(multiple.status_code, 200)
        self.assertIn("More than one active internship program", multiple.text)

    def test_historical_program_is_selected_for_export(self):
        user, student = self._create_portal_user("historical")
        historical = self._create_program(
            student,
            "Historical",
            state="completed",
        )
        self._authenticate(user)

        response, renderer, _fake_pdf = self._fake_pdf_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(renderer.call_args.kwargs["res_ids"], historical.ids)

    def test_supervised_export_filter_totals_order_and_safe_content(self):
        user, student = self._create_portal_user("filter")
        program = self._create_program(
            student,
            "Filter",
            workflow_mode="supervised",
        )
        draft = self._create_entry(
            program,
            "Draft Secret",
            "2026-09-01",
            state="draft",
            work_hours=2,
        )
        approved = self._create_entry(
            program,
            "Approved",
            "2026-09-04",
            state="approved",
            work_hours=5,
            supervisor_comment="SUPERVISOR-COMMENT-SECRET",
        )
        submitted = self._create_entry(
            program,
            "Submitted",
            "2026-09-02",
            state="submitted",
            work_hours=3,
        )
        revision = self._create_entry(
            program,
            "Revision",
            "2026-09-03",
            state="revision",
            work_hours=4,
        )
        archived = self._create_entry(
            program,
            "Archived Secret",
            "2026-09-05",
            state="approved",
            work_hours=6,
            active=False,
        )
        approved.message_post(body="CHATTER-CONTENT-SECRET")

        _foreign_user, foreign_student = self._create_portal_user(
            "filter-foreign"
        )
        foreign_program = self._create_program(
            foreign_student,
            "Filter Foreign",
            workflow_mode="supervised",
        )
        foreign_entry = self._create_entry(
            foreign_program,
            "Foreign Secret",
            "2026-09-01",
            state="approved",
            work_hours=24,
        )

        values = self._report_values(user, program)
        self.assertEqual(values["entries"], submitted | revision | approved)
        self.assertEqual(values["entry_count"], 3)
        self.assertEqual(values["total_work_hours"], 12)

        rendered = self._render_report(user, program)
        self.assertNotIn(draft.title, rendered)
        self.assertNotIn(archived.title, rendered)
        self.assertNotIn(foreign_program.name, rendered)
        self.assertNotIn(foreign_entry.title, rendered)
        self.assertNotIn("SUPERVISOR-COMMENT-SECRET", rendered)
        self.assertNotIn("CHATTER-CONTENT-SECRET", rendered)
        self.assertLess(rendered.index(submitted.title), rendered.index(revision.title))
        self.assertLess(rendered.index(revision.title), rendered.index(approved.title))
        for label in ("Submitted", "Revision Requested", "Approved"):
            self.assertIn(label, rendered)
        self.assertIn("Exported Entries", rendered)
        self.assertIn(">3<", rendered)
        self.assertIn(">12.0<", rendered)

    def test_independent_completed_entry_and_empty_export_render(self):
        user, student = self._create_portal_user("independent")
        program = self._create_program(student, "Independent")
        completed = self._create_entry(
            program,
            "Completed",
            "2026-09-01",
            state="completed",
            work_hours=7.5,
        )

        rendered = self._render_report(user, program)
        self.assertIn(completed.title, rendered)
        self.assertIn("Completed", rendered)
        self.assertIn(">7.5<", rendered)
        self.assertIn("Student", rendered)
        self.assertIn("Supervisor", rendered)
        self.assertIn("Company", rendered)
        self.assertIn("Page", rendered)

        empty_user, empty_student = self._create_portal_user("empty")
        empty_program = self._create_program(empty_student, "Empty")
        empty_rendered = self._render_report(empty_user, empty_program)
        self.assertIn("No completed or otherwise exportable", empty_rendered)

    def test_report_model_rejects_foreign_and_ordinary_portal_access(self):
        owner, owner_student = self._create_portal_user("owner")
        program = self._create_program(owner_student, "Owner")
        foreign, _foreign_student = self._create_portal_user("not-owner")
        ordinary, _ordinary_student = self._create_portal_user(
            "report-ordinary",
            dedicated=False,
        )

        with self.assertRaises(AccessError):
            self._report_values(foreign, program)
        with self.assertRaises(AccessError):
            self._report_values(ordinary, program)

    def test_dashboard_and_calendar_show_export_link_only_with_program(self):
        user, student = self._create_portal_user("navigation")
        self._authenticate(user)
        without_program = self.url_open("/my/internship")
        self.assertNotIn('href="/my/internship/export/pdf"', without_program.text)

        self._create_program(student, "Navigation")
        dashboard = self.url_open("/my/internship")
        calendar = self.url_open("/my/internship/calendar")
        self.assertIn('href="/my/internship/export/pdf"', dashboard.text)
        self.assertIn('href="/my/internship/export/pdf"', calendar.text)
