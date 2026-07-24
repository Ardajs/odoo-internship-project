import math

from werkzeug.exceptions import Forbidden

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class InternshipPortal(CustomerPortal):
    _ONBOARDING_TEXT_MAX = 200
    _DAILY_ENTRIES_PAGE_SIZE = 30
    _DAILY_ENTRY_TITLE_MAX = 200
    _DAILY_ENTRY_DESCRIPTION_MAX = 10000

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

    def _resolve_portal_daily_entry(self, student, entry_id):
        if not student:
            return request.env["internship.daily.entry"]
        return request.env["internship.daily.entry"].search([
            ("id", "=", entry_id),
            *self._portal_daily_entry_domain(student),
        ], limit=1)

    def _is_portal_daily_entry_editable(self, entry):
        return bool(
            entry
            and entry.state == "draft"
            and entry.program_id.active
            and entry.program_state == "active"
        )

    def _is_portal_daily_entry_submittable(self, entry):
        return bool(
            entry
            and entry.state == "draft"
            and entry.program_id.active
            and entry.program_state == "active"
            and entry.workflow_mode == "independent"
        )

    def _resolve_portal_entry_program(self, student):
        if not student:
            return request.env["internship.program"]
        programs = request.env["internship.program"].search([
            ("student_id", "=", student.id),
            ("workflow_mode", "=", "independent"),
            ("state", "=", "active"),
            ("active", "=", True),
        ], limit=2)
        return programs if len(programs) == 1 else programs.browse()

    def _daily_entry_state_labels(self):
        state_field = request.env["internship.daily.entry"].fields_get(
            ["state"],
            attributes=["selection"],
        ).get("state", {})
        return dict(state_field.get("selection") or [])

    def _empty_daily_entry_values(self):
        return {
            "entry_date": fields.Date.to_string(
                fields.Date.context_today(request.env.user)
            ),
            "title": "",
            "work_description": "",
            "work_hours": "8",
        }

    def _daily_entry_form_values(self, entry):
        return {
            "entry_date": fields.Date.to_string(entry.entry_date),
            "title": entry.title or "",
            "work_description": entry.work_description or "",
            "work_hours": str(entry.work_hours),
        }

    def _validate_daily_entry_form(self, post, program, *, current_entry=None):
        values = {
            "entry_date": (post.get("entry_date") or "").strip(),
            "title": (post.get("title") or "").strip(),
            "work_description": (
                post.get("work_description") or ""
            ).strip(),
            "work_hours": (post.get("work_hours") or "").strip(),
        }
        errors = {}

        if not values["title"]:
            errors["title"] = _("Work title is required.")
        elif len(values["title"]) > self._DAILY_ENTRY_TITLE_MAX:
            errors["title"] = _(
                "Work title must not exceed %s characters."
            ) % self._DAILY_ENTRY_TITLE_MAX

        if not values["work_description"]:
            errors["work_description"] = _("Work description is required.")
        elif (
            len(values["work_description"])
            > self._DAILY_ENTRY_DESCRIPTION_MAX
        ):
            errors["work_description"] = _(
                "Work description must not exceed %s characters."
            ) % self._DAILY_ENTRY_DESCRIPTION_MAX

        try:
            parsed_date = fields.Date.to_date(values["entry_date"])
        except (TypeError, ValueError):
            parsed_date = False
        if not parsed_date:
            errors["entry_date"] = _("Enter a valid entry date.")
        elif program and (
            parsed_date < program.start_date
            or parsed_date > program.end_date
        ):
            errors["entry_date"] = _(
                "Entry date must be within the internship period."
            )

        try:
            parsed_hours = float(values["work_hours"].replace(",", "."))
        except (TypeError, ValueError):
            parsed_hours = False
        if parsed_hours is False or not math.isfinite(parsed_hours):
            errors["work_hours"] = _("Enter valid work hours.")
        elif parsed_hours <= 0 or parsed_hours > 24:
            errors["work_hours"] = _(
                "Work hours must be greater than zero and at most 24."
            )

        duplicate_domain = [
            ("program_id", "=", program.id),
            ("entry_date", "=", parsed_date),
        ]
        if current_entry:
            duplicate_domain.append(("id", "!=", current_entry.id))
        if (
            parsed_date
            and program
            and request.env["internship.daily.entry"].search_count(
                duplicate_domain,
                limit=1,
            )
        ):
            errors["entry_date"] = _(
                "A daily entry already exists for this date."
            )

        create_values = {
            "entry_date": parsed_date,
            "title": values["title"],
            "work_description": values["work_description"],
            "work_hours": parsed_hours,
        }
        return values, create_values, errors

    def _render_daily_entry_form(
        self,
        program,
        values=None,
        errors=None,
        form_error=None,
    ):
        portal_values = self._prepare_portal_layout_values()
        portal_values.update({
            "page_name": "internship_daily_entry_new",
            "program": program,
            "form_values": values or self._empty_daily_entry_values(),
            "errors": errors or {},
            "form_error": form_error,
        })
        return request.render(
            "internship_logbook.portal_create_daily_entry",
            portal_values,
        )

    def _render_daily_entry_edit_form(
        self,
        entry,
        values=None,
        errors=None,
        form_error=None,
    ):
        portal_values = self._prepare_portal_layout_values()
        portal_values.update({
            "page_name": "internship_daily_entry_edit",
            "entry": entry,
            "program": entry.program_id,
            "form_values": values or self._daily_entry_form_values(entry),
            "errors": errors or {},
            "form_error": form_error,
        })
        return request.render(
            "internship_logbook.portal_edit_daily_entry",
            portal_values,
        )

    def _render_daily_entry_submit_confirmation(
        self,
        entry,
        form_error=None,
    ):
        portal_values = self._prepare_portal_layout_values()
        portal_values.update({
            "page_name": "internship_daily_entry_submit",
            "entry": entry,
            "form_error": form_error,
        })
        return request.render(
            "internship_logbook.portal_submit_daily_entry",
            portal_values,
        )

    def _set_daily_entry_submit_denial(self, entry):
        if entry and entry.state == "draft":
            request.session[
                "internship_daily_entry_submit_program_denied"
            ] = True
        else:
            request.session[
                "internship_daily_entry_submit_state_denied"
            ] = True

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
        eligible_program = self._resolve_portal_entry_program(student)
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
            "eligible_program": eligible_program,
            "entries": entries,
            "entry_count": entry_count,
            "pager": pager,
            "daily_entry_state_labels": self._daily_entry_state_labels(),
            "daily_entry_saved": request.session.pop(
                "internship_daily_entry_saved",
                False,
            ),
            "daily_entry_updated": request.session.pop(
                "internship_daily_entry_updated",
                False,
            ),
            "daily_entry_edit_denied": request.session.pop(
                "internship_daily_entry_edit_denied",
                False,
            ),
            "daily_entry_completed": request.session.pop(
                "internship_daily_entry_completed",
                False,
            ),
            "daily_entry_submit_state_denied": request.session.pop(
                "internship_daily_entry_submit_state_denied",
                False,
            ),
            "daily_entry_submit_program_denied": request.session.pop(
                "internship_daily_entry_submit_program_denied",
                False,
            ),
        })
        return request.render(
            "internship_logbook.portal_daily_entries",
            values,
        )

    @http.route(
        "/my/internship/daily/new",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_create_daily_entry_form(self, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        program = self._resolve_portal_entry_program(student)
        if not program:
            return request.redirect("/my/internship/daily")
        return self._render_daily_entry_form(program)

    @http.route(
        "/my/internship/daily/new",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def portal_create_daily_entry_submit(self, **post):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        program = self._resolve_portal_entry_program(student)
        if not program:
            return request.redirect("/my/internship/daily", code=303)

        values, create_values, errors = self._validate_daily_entry_form(
            post,
            program,
        )
        if errors:
            return self._render_daily_entry_form(
                program,
                values,
                errors,
            )

        try:
            request.env[
                "internship.daily.entry"
            ].sudo()._portal_create_draft_entry(
                request.env.user.id,
                program.id,
                create_values,
            )
        except UserError:
            return self._render_daily_entry_form(
                program,
                values,
                form_error=_(
                    "A daily entry already exists for this date."
                ),
            )
        except (AccessError, ValidationError):
            return self._render_daily_entry_form(
                program,
                values,
                form_error=_(
                    "The daily entry could not be created. "
                    "Review the submitted information and try again."
                ),
            )

        request.session["internship_daily_entry_saved"] = True
        return request.redirect("/my/internship/daily", code=303)

    @http.route(
        "/my/internship/daily/<int:entry_id>/edit",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_edit_daily_entry_form(self, entry_id, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        entry = self._resolve_portal_daily_entry(student, entry_id)
        if not entry:
            raise request.not_found()
        if not self._is_portal_daily_entry_editable(entry):
            request.session["internship_daily_entry_edit_denied"] = True
            return request.redirect("/my/internship/daily")
        return self._render_daily_entry_edit_form(entry)

    @http.route(
        "/my/internship/daily/<int:entry_id>/edit",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def portal_edit_daily_entry_submit(self, entry_id, **post):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        entry = self._resolve_portal_daily_entry(student, entry_id)
        if not entry:
            raise request.not_found()
        if not self._is_portal_daily_entry_editable(entry):
            request.session["internship_daily_entry_edit_denied"] = True
            return request.redirect("/my/internship/daily", code=303)

        values, update_values, errors = self._validate_daily_entry_form(
            post,
            entry.program_id,
            current_entry=entry,
        )
        if errors:
            return self._render_daily_entry_edit_form(
                entry,
                values,
                errors,
            )

        try:
            request.env[
                "internship.daily.entry"
            ].sudo()._portal_update_draft_entry(
                request.env.user.id,
                entry.id,
                update_values,
            )
        except UserError:
            entry.invalidate_recordset()
            if not self._is_portal_daily_entry_editable(entry):
                request.session["internship_daily_entry_edit_denied"] = True
                return request.redirect("/my/internship/daily", code=303)
            return self._render_daily_entry_edit_form(
                entry,
                values,
                form_error=_(
                    "A daily entry already exists for this date."
                ),
            )
        except AccessError:
            raise request.not_found()
        except ValidationError:
            return self._render_daily_entry_edit_form(
                entry,
                values,
                form_error=_(
                    "The daily entry could not be updated. "
                    "Review the submitted information and try again."
                ),
            )

        request.session["internship_daily_entry_updated"] = True
        return request.redirect("/my/internship/daily", code=303)

    @http.route(
        "/my/internship/daily/<int:entry_id>/submit-confirm",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_submit_daily_entry_confirmation(self, entry_id, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        entry = self._resolve_portal_daily_entry(student, entry_id)
        if not entry:
            raise request.not_found()
        if not self._is_portal_daily_entry_submittable(entry):
            self._set_daily_entry_submit_denial(entry)
            return request.redirect("/my/internship/daily")
        return self._render_daily_entry_submit_confirmation(entry)

    @http.route(
        "/my/internship/daily/<int:entry_id>/submit",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def portal_submit_daily_entry(self, entry_id, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        entry = self._resolve_portal_daily_entry(student, entry_id)
        if not entry:
            raise request.not_found()
        if not self._is_portal_daily_entry_submittable(entry):
            self._set_daily_entry_submit_denial(entry)
            return request.redirect("/my/internship/daily", code=303)

        try:
            request.env[
                "internship.daily.entry"
            ].sudo()._portal_submit_draft_entry(
                request.env.user.id,
                entry.id,
            )
        except AccessError:
            raise request.not_found()
        except ValidationError:
            entry.invalidate_recordset()
            if not self._is_portal_daily_entry_submittable(entry):
                self._set_daily_entry_submit_denial(entry)
                return request.redirect("/my/internship/daily", code=303)
            return self._render_daily_entry_submit_confirmation(
                entry,
                form_error=_(
                    "This daily entry is incomplete or invalid and "
                    "could not be submitted."
                ),
            )
        except UserError:
            entry.invalidate_recordset()
            entry.program_id.invalidate_recordset(
                ["active", "state", "workflow_mode"]
            )
            self._set_daily_entry_submit_denial(entry)
            return request.redirect("/my/internship/daily", code=303)

        request.session["internship_daily_entry_completed"] = True
        return request.redirect("/my/internship/daily", code=303)

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
