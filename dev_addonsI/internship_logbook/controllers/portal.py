from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class InternshipPortal(CustomerPortal):
    def _is_portal_intern(self):
        return request.env.user.has_group(
            "internship_logbook.group_internship_portal_intern"
        )

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if self._is_portal_intern() and "internship_program_count" in counters:
            values["internship_program_count"] = request.env[
                "internship.program"
            ].search_count([])
        return values

    @http.route(
        "/my/internship",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
    )
    def portal_my_internship(self, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = request.env["internship.student"].search(
            [("user_id", "=", request.env.user.id)],
            limit=1,
        )
        if not student:
            raise Forbidden()
        programs = request.env["internship.program"].search(
            [("student_id", "=", student.id)],
        )
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "internship",
            "student": student,
            "programs": programs,
            "education_complete": bool(
                student.university and student.department
            ),
        })
        return request.render(
            "internship_logbook.portal_my_internship",
            values,
        )
