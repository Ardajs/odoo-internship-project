from werkzeug.exceptions import Forbidden

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class InternshipPortal(CustomerPortal):
    _ONBOARDING_TEXT_MAX = 200
    _DAILY_ENTRIES_PAGE_SIZE = 30

    def _is_portal_intern(self):
        return request.env.user.has_group(
            "internship_logbook.group_internship_portal_intern"
        )

    def _resolve_portal_student(self):
        if not self._is_portal_intern():
            return request.env["internship.student"]
        students = request.env["internship.student"].search(
            [("user_id", "=", request.env.user.id), ("active", "=", True)],
            limit=2,
        )
        return students if len(students) == 1 else students.browse()

    def _portal_programs(self, student):
        if not student:
            return request.env["internship.program"]
        return request.env["internship.program"].search(
            [("student_id", "=", student.id)],
            order="start_date desc, id desc",
        )

    def _portal_daily_entry_domain(self, student):
        return [
            ("student_id", "=", student.id),
            ("program_id.student_id", "=", student.id),
        ]

    def _portal_daily_entries(self, student, *, offset=0, limit=None):
        if not student:
            return request.env["internship.daily.entry"]
        return request.env["internship.daily.entry"].search(
            self._portal_daily_entry_domain(student),
            order="entry_date desc, id desc",
            offset=offset,
            limit=limit,
        )

    def _daily_entry_state_labels(self):
        state_field = request.env["internship.daily.entry"].fields_get(
            ["state"],
            attributes=["selection"],
        ).get("state", {})
        return dict(state_field.get("selection") or [])

    def _is_onboarding_eligible(self, student):
        return bool(student) and not self._portal_programs(student)

    def _prepare_internship_portal_values(self, student):
        programs = self._portal_programs(student)
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "internship",
            "student": student,
            "programs": programs,
            "education_complete": bool(
                student.university and student.department
            ),
        })
        return values

    def _empty_onboarding_values(self):
        return {
            "company_name": "",
            "department": "",
            "start_date": "",
            "end_date": "",
            "workflow_mode": "independent",
        }

    def _validate_onboarding_form(self, post):
        values = {
            "company_name": (post.get("company_name") or "").strip(),
            "department": (post.get("department") or "").strip(),
            "start_date": (post.get("start_date") or "").strip(),
            "end_date": (post.get("end_date") or "").strip(),
            "workflow_mode": (post.get("workflow_mode") or "").strip(),
        }
        errors = {}
        for field_name, label in (
            ("company_name", _("Company")),
            ("department", _("Department")),
        ):
            if not values[field_name]:
                errors[field_name] = _("%s is required.") % label
            elif len(values[field_name]) > self._ONBOARDING_TEXT_MAX:
                errors[field_name] = _(
                    "%s must not exceed %s characters."
                ) % (label, self._ONBOARDING_TEXT_MAX)

        parsed_dates = {}
        for field_name, label in (
            ("start_date", _("Start date")),
            ("end_date", _("End date")),
        ):
            try:
                parsed_dates[field_name] = fields.Date.to_date(
                    values[field_name]
                )
            except (TypeError, ValueError):
                parsed_dates[field_name] = False
            if not parsed_dates[field_name]:
                errors[field_name] = _("%s is required and must be valid.") % label

        if (
            parsed_dates.get("start_date")
            and parsed_dates.get("end_date")
            and parsed_dates["end_date"] < parsed_dates["start_date"]
        ):
            errors["end_date"] = _(
                "End date cannot be earlier than start date."
            )

        if values["workflow_mode"] != "independent":
            errors["workflow_mode"] = _(
                "Select a valid internship mode."
            )
        return values, errors

    def _render_onboarding_form(self, values=None, errors=None, form_error=None):
        portal_values = self._prepare_portal_layout_values()
        portal_values.update({
            "page_name": "internship_create",
            "form_values": values or self._empty_onboarding_values(),
            "errors": errors or {},
            "form_error": form_error,
        })
        return request.render(
            "internship_logbook.portal_create_internship",
            portal_values,
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
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        return request.render(
            "internship_logbook.portal_my_internship",
            self._prepare_internship_portal_values(student),
        )

    @http.route(
        [
            "/my/internship/daily",
            "/my/internship/daily/page/<int:page>",
        ],
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_daily_entries(self, page=1, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()

        programs = self._portal_programs(student)
        entry_model = request.env["internship.daily.entry"]
        domain = self._portal_daily_entry_domain(student)
        entry_count = entry_model.search_count(domain)
        pager = portal_pager(
            url="/my/internship/daily",
            total=entry_count,
            page=page,
            step=self._DAILY_ENTRIES_PAGE_SIZE,
        )
        entries = self._portal_daily_entries(
            student,
            offset=pager["offset"],
            limit=self._DAILY_ENTRIES_PAGE_SIZE,
        )
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "internship_daily_entries",
            "student": student,
            "programs": programs,
            "entries": entries,
            "entry_count": entry_count,
            "pager": pager,
            "daily_entry_state_labels": self._daily_entry_state_labels(),
        })
        return request.render(
            "internship_logbook.portal_daily_entries",
            values,
        )

    @http.route(
        "/my/internship/create",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_create_internship_form(self, **_ignored):
        student = self._resolve_portal_student()
        if not self._is_onboarding_eligible(student):
            return request.redirect("/my/internship")
        return self._render_onboarding_form()

    @http.route(
        "/my/internship/create",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def portal_create_internship_submit(self, **post):
        student = self._resolve_portal_student()
        if not self._is_onboarding_eligible(student):
            return request.redirect("/my/internship", code=303)

        values, errors = self._validate_onboarding_form(post)
        if errors:
            return self._render_onboarding_form(values, errors)

        try:
            request.env["internship.program"].sudo()._portal_create_first_program(
                request.env.user.id,
                values,
            )
        except UserError:
            # A concurrent or repeated request completed onboarding first.
            return request.redirect("/my/internship", code=303)
        except (AccessError, ValidationError):
            return self._render_onboarding_form(
                values,
                form_error=_(
                    "The internship could not be created. "
                    "Review the submitted information and try again."
                ),
            )
        return request.redirect("/my/internship", code=303)
