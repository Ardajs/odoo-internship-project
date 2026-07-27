from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_datetime


class PortalInternshipLogbookReport(models.AbstractModel):
    _name = (
        "report.internship_logbook.report_portal_internship_logbook"
    )
    _description = "Portal Internship Logbook PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        programs = self.env["internship.program"].browse(docids).exists()
        programs.check_access("read")
        if len(programs) != 1:
            raise UserError(
                _("Exactly one internship program is required for export.")
            )
        program = programs
        student = program.student_id

        user = self.env.user
        if user.share:
            if not user.has_group(
                "internship_logbook.group_internship_portal_intern"
            ):
                raise AccessError(
                    _("This account cannot export an internship logbook.")
                )
            students = self.env["internship.student"].search(
                [("user_id", "=", user.id), ("active", "=", True)],
                limit=2,
            )
            if len(students) != 1 or student != students:
                raise AccessError(
                    _("This internship program is not available for export.")
                )

        entries = self.env["internship.daily.entry"].search(
            [
                ("program_id", "=", program.id),
                ("student_id", "=", student.id),
                ("program_id.student_id", "=", student.id),
                ("active", "=", True),
                ("state", "!=", "draft"),
            ],
            order="entry_date asc, id asc",
        )
        state_field = self.env["internship.daily.entry"].fields_get(
            ["state"],
            attributes=["selection"],
        ).get("state", {})
        workflow_field = self.env["internship.program"].fields_get(
            ["workflow_mode", "state"],
            attributes=["selection"],
        )
        generated_at = fields.Datetime.now()

        return {
            "doc_ids": program.ids,
            "doc_model": "internship.program",
            "docs": program,
            "program": program,
            "student": student,
            "entries": entries,
            "entry_count": len(entries),
            "total_work_hours": sum(entries.mapped("work_hours")),
            "entry_state_labels": dict(state_field.get("selection") or []),
            "workflow_labels": dict(
                workflow_field.get("workflow_mode", {}).get("selection")
                or []
            ),
            "program_state_labels": dict(
                workflow_field.get("state", {}).get("selection") or []
            ),
            "institution_title": (
                student.university
                or self.env.company.name
                or _("Internship Logbook")
            ),
            "generated_at": generated_at,
            "generated_at_display": format_datetime(
                self.env,
                generated_at,
            ),
        }
