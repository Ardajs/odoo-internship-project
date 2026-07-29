import math
from datetime import date, timedelta

from werkzeug.exceptions import Forbidden

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import content_disposition, request
from odoo.tools.misc import format_date

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class InternshipPortal(CustomerPortal):
    _ONBOARDING_TEXT_MAX = 200
    _DAILY_ENTRIES_PAGE_SIZE = 30
    _DASHBOARD_RECENT_ENTRY_LIMIT = 5
    _MISSING_DATE_PREVIEW_LIMIT = 5
    _MAX_CALENDAR_SPAN_DAYS = 1096
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

    def _program_selection_labels(self, field_name):
        field = request.env["internship.program"].fields_get(
            [field_name],
            attributes=["selection"],
        ).get(field_name, {})
        return dict(field.get("selection") or [])

    def _portal_context_today(self):
        return fields.Date.context_today(request.env.user)

    def _resolve_portal_dashboard_program(self, student):
        empty_program = request.env["internship.program"]
        if not student:
            return {
                "program": empty_program,
                "status": "none",
            }

        owned_domain = [("student_id", "=", student.id)]
        active_programs = request.env["internship.program"].search([
            *owned_domain,
            ("active", "=", True),
            ("state", "=", "active"),
        ], order="start_date desc, id desc", limit=2)
        if len(active_programs) == 1:
            return {
                "program": active_programs,
                "status": "active",
            }
        if len(active_programs) > 1:
            return {
                "program": empty_program,
                "status": "multiple_active",
            }

        historical_program = request.env[
            "internship.program"
        ].with_context(active_test=False).search(
            owned_domain,
            order="start_date desc, id desc",
            limit=1,
        )
        return {
            "program": historical_program,
            "status": "historical" if historical_program else "none",
        }

    def _portal_program_date_metrics(self, program, *, today=None):
        metrics = {
            "valid": False,
            "total_program_days": 0,
            "elapsed_program_days": 0,
            "remaining_program_days": 0,
        }
        if (
            not program
            or not program.start_date
            or not program.end_date
            or program.end_date < program.start_date
        ):
            return metrics

        today = today or self._portal_context_today()
        total_days = (program.end_date - program.start_date).days + 1
        if today < program.start_date:
            elapsed_days = 0
        elif today > program.end_date:
            elapsed_days = total_days
        else:
            elapsed_days = (today - program.start_date).days + 1
        metrics.update({
            "valid": True,
            "total_program_days": total_days,
            "elapsed_program_days": elapsed_days,
            "remaining_program_days": total_days - elapsed_days,
        })
        return metrics

    def _portal_program_entry_domain(self, program, student):
        return [
            ("program_id", "=", program.id),
            ("student_id", "=", student.id),
            ("program_id.student_id", "=", student.id),
            ("active", "=", True),
        ]

    def _portal_program_entry_metrics(self, program, student):
        metrics = {
            "total_entry_count": 0,
            "draft_entry_count": 0,
            "completed_entry_count": 0,
            "other_entry_count": 0,
            "total_work_hours": 0.0,
        }
        if not program or not student:
            return metrics

        entry_model = request.env["internship.daily.entry"]
        domain = self._portal_program_entry_domain(program, student)
        grouped_states = entry_model._read_group(
            domain,
            groupby=["state"],
            aggregates=["__count"],
        )
        state_counts = {
            state: count
            for state, count in grouped_states
        }
        total_count = sum(state_counts.values())
        valid_hours = entry_model._read_group(
            [
                *domain,
                ("work_hours", ">", 0),
                ("work_hours", "<=", 24),
            ],
            aggregates=["work_hours:sum"],
        )
        total_hours = valid_hours[0][0] if valid_hours else 0.0
        draft_count = state_counts.get("draft", 0)
        completed_count = state_counts.get("completed", 0)
        metrics.update({
            "total_entry_count": total_count,
            "draft_entry_count": draft_count,
            "completed_entry_count": completed_count,
            "other_entry_count": (
                total_count - draft_count - completed_count
            ),
            "total_work_hours": round(float(total_hours or 0.0), 2),
        })
        return metrics

    def _portal_recent_daily_entries(self, program, student, limit=None):
        if not program or not student:
            return request.env["internship.daily.entry"]
        return request.env["internship.daily.entry"].search(
            self._portal_program_entry_domain(program, student),
            order="entry_date desc, id desc",
            limit=limit or self._DASHBOARD_RECENT_ENTRY_LIMIT,
        )

    def _portal_program_progress(self, program, student):
        date_metrics = self._portal_program_date_metrics(program)
        entry_metrics = self._portal_program_entry_metrics(
            program,
            student,
        )
        total_days = date_metrics["total_program_days"]
        progress = (
            entry_metrics["completed_entry_count"] / total_days * 100
            if total_days > 0
            else 0.0
        )
        return {
            **date_metrics,
            **entry_metrics,
            "progress_percentage": round(
                min(max(progress, 0.0), 100.0),
                2,
            ),
        }

    def _empty_portal_calendar_analysis(self, reason, *, today=None):
        return {
            "analysis_available": False,
            "reason": reason,
            "today": today or self._portal_context_today(),
            "start_date": False,
            "end_date": False,
            "evaluation_end_date": False,
            "missing_dates": [],
            "missing_count": 0,
            "missing_preview": [],
            "status_by_date": {},
            "status_counts": {
                "completed": 0,
                "draft": 0,
                "other": 0,
                "missing": 0,
                "future": 0,
            },
            "month_groups": [],
            "weekday_labels": [],
        }

    def _portal_daily_entry_status_priority(self, state):
        if state == "completed":
            return 3
        if state == "draft":
            return 1
        return 2

    def _portal_program_entry_status_by_date(
        self,
        program,
        student,
        start_date,
        end_date,
    ):
        state_labels = self._daily_entry_state_labels()
        entries = request.env["internship.daily.entry"].search(
            [
                *self._portal_program_entry_domain(program, student),
                ("entry_date", ">=", start_date),
                ("entry_date", "<=", end_date),
            ],
            order="entry_date asc, id asc",
        )
        status_by_date = {}
        for entry in entries:
            normalized_status = (
                entry.state
                if entry.state in ("completed", "draft")
                else "other"
            )
            candidate = {
                "status": normalized_status,
                "status_label": {
                    "completed": _("Completed"),
                    "draft": _("Draft"),
                    "other": _("Other"),
                }[normalized_status],
                "entry_state_label": state_labels.get(
                    entry.state,
                    entry.state or _("Unknown"),
                ),
                "entry_title": entry.title or "",
                "work_hours": entry.work_hours,
                "priority": self._portal_daily_entry_status_priority(
                    entry.state
                ),
            }
            current = status_by_date.get(entry.entry_date)
            if not current or candidate["priority"] >= current["priority"]:
                status_by_date[entry.entry_date] = candidate
        return status_by_date

    def _portal_calendar_months(self, calendar_days):
        months = []
        current_key = None
        month = None
        for day_info in calendar_days:
            day = day_info["date"]
            key = (day.year, day.month)
            if key != current_key:
                month_start = date(day.year, day.month, 1)
                month = {
                    "key": f"{day.year:04d}-{day.month:02d}",
                    "label": format_date(
                        request.env,
                        month_start,
                        date_format="MMMM y",
                    ),
                    "cells": [False] * month_start.weekday(),
                    "weeks": [],
                }
                months.append(month)
                current_key = key
            month["cells"].append(day_info)

        for month in months:
            trailing_cells = (-len(month["cells"])) % 7
            month["cells"].extend([False] * trailing_cells)
            month["weeks"] = [
                month["cells"][index:index + 7]
                for index in range(0, len(month["cells"]), 7)
            ]
            del month["cells"]
        return months

    def _portal_program_calendar_analysis(
        self,
        program,
        student,
        *,
        today=None,
    ):
        today = today or self._portal_context_today()
        if not program or not student:
            return self._empty_portal_calendar_analysis(
                "no_program",
                today=today,
            )
        if (
            not program.start_date
            or not program.end_date
            or program.end_date < program.start_date
        ):
            return self._empty_portal_calendar_analysis(
                "invalid_dates",
                today=today,
            )

        start_date = program.start_date
        end_date = program.end_date
        total_days = (end_date - start_date).days + 1
        if total_days > self._MAX_CALENDAR_SPAN_DAYS:
            analysis = self._empty_portal_calendar_analysis(
                "range_too_long",
                today=today,
            )
            analysis.update({
                "start_date": start_date,
                "end_date": end_date,
            })
            return analysis

        evaluation_end_date = min(today, end_date)
        status_by_date = self._portal_program_entry_status_by_date(
            program,
            student,
            start_date,
            end_date,
        )
        missing_dates = []
        calendar_days = []
        status_counts = {
            "completed": 0,
            "draft": 0,
            "other": 0,
            "missing": 0,
            "future": 0,
        }
        current_date = start_date
        while current_date <= end_date:
            entry_status = status_by_date.get(current_date)
            if entry_status:
                day_info = dict(entry_status)
            elif current_date <= evaluation_end_date:
                day_info = {
                    "status": "missing",
                    "status_label": _("Missing"),
                    "entry_state_label": "",
                    "entry_title": "",
                    "work_hours": False,
                }
                missing_dates.append(current_date)
            else:
                day_info = {
                    "status": "future",
                    "status_label": _("Future"),
                    "entry_state_label": "",
                    "entry_title": "",
                    "work_hours": False,
                }
            day_info.update({
                "date": current_date,
                "day_number": current_date.day,
                "display_date": format_date(request.env, current_date),
            })
            day_info.pop("priority", None)
            status_counts[day_info["status"]] += 1
            calendar_days.append(day_info)
            current_date += timedelta(days=1)

        preview_dates = missing_dates[:self._MISSING_DATE_PREVIEW_LIMIT]
        weekday_reference = date(2024, 1, 1)
        return {
            "analysis_available": True,
            "reason": (
                "not_started" if today < start_date else "available"
            ),
            "today": today,
            "start_date": start_date,
            "end_date": end_date,
            "evaluation_end_date": (
                evaluation_end_date
                if evaluation_end_date >= start_date
                else False
            ),
            "missing_dates": missing_dates,
            "missing_count": len(missing_dates),
            "missing_preview": [
                {
                    "date": missing_date,
                    "display": format_date(request.env, missing_date),
                }
                for missing_date in preview_dates
            ],
            "status_by_date": status_by_date,
            "status_counts": status_counts,
            "month_groups": self._portal_calendar_months(calendar_days),
            "weekday_labels": [
                format_date(
                    request.env,
                    weekday_reference + timedelta(days=offset),
                    date_format="EEE",
                )
                for offset in range(7)
            ],
        }

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
        dashboard_selection = self._resolve_portal_dashboard_program(student)
        dashboard_program = dashboard_selection["program"]
        dashboard_status = dashboard_selection["status"]
        program_metrics = (
            self._portal_program_progress(dashboard_program, student)
            if dashboard_program
            else {}
        )
        calendar_analysis = (
            self._portal_program_calendar_analysis(
                dashboard_program,
                student,
            )
            if dashboard_program
            else self._empty_portal_calendar_analysis(dashboard_status)
        )
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "internship",
            "student": student,
            "programs": programs,
            "dashboard_program": dashboard_program,
            "dashboard_program_status": dashboard_status,
            "program_metrics": program_metrics,
            "calendar_analysis": calendar_analysis,
            "recent_entries": self._portal_recent_daily_entries(
                dashboard_program,
                student,
            ),
            "program_workflow_labels": self._program_selection_labels(
                "workflow_mode"
            ),
            "program_state_labels": self._program_selection_labels("state"),
            "daily_entry_state_labels": self._daily_entry_state_labels(),
            "can_create_daily_entry": (
                dashboard_status == "active"
                and bool(
                    self._resolve_portal_entry_program(student)
                )
            ),
            "education_complete": bool(
                student.university and student.department
            ),
        })
        return values

    def _prepare_internship_calendar_values(self, student):
        dashboard_selection = self._resolve_portal_dashboard_program(student)
        program = dashboard_selection["program"]
        selection_status = dashboard_selection["status"]
        analysis = (
            self._portal_program_calendar_analysis(program, student)
            if program
            else self._empty_portal_calendar_analysis(selection_status)
        )
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "internship_calendar",
            "student": student,
            "program": program,
            "dashboard_program_status": selection_status,
            "calendar_analysis": analysis,
            "program_workflow_labels": self._program_selection_labels(
                "workflow_mode"
            ),
            "program_state_labels": self._program_selection_labels("state"),
            "can_create_daily_entry": (
                selection_status == "active"
                and bool(self._resolve_portal_entry_program(student))
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
        sitemap=False,
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
        "/my/internship/calendar",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_internship_calendar(self, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        return request.render(
            "internship_logbook.portal_internship_calendar",
            self._prepare_internship_calendar_values(student),
        )

    @http.route(
        "/my/internship/export/pdf",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_internship_export_pdf(self, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()

        selection = self._resolve_portal_dashboard_program(student)
        program = selection["program"]
        if not program:
            return request.render(
                "internship_logbook.portal_internship_export_unavailable",
                {
                    "page_name": "internship_export",
                    "export_status": selection["status"],
                },
            )

        pdf, _output_type = request.env[
            "ir.actions.report"
        ].with_context(report_pdf_no_attachment=True)._render_qweb_pdf(
            "internship_logbook.action_report_portal_internship_logbook",
            res_ids=program.ids,
        )
        filename = _("Internship Logbook - %s.pdf") % program.name
        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(pdf))),
                ("Content-Disposition", content_disposition(filename)),
                ("X-Content-Type-Options", "nosniff"),
                ("Cache-Control", "private, no-store"),
            ],
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
        "/my/internship/daily/<int:entry_id>",
        type="http",
        auth="user",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def portal_daily_entry_detail(self, entry_id, **_ignored):
        if not self._is_portal_intern():
            raise Forbidden()
        student = self._resolve_portal_student()
        if not student:
            raise Forbidden()
        entry = self._resolve_portal_daily_entry(student, entry_id)
        if not entry:
            raise request.not_found()

        state_labels = self._daily_entry_state_labels()
        values = self._prepare_portal_layout_values()
        values.update({
            "entry": entry,
            "state_label": state_labels.get(
                entry.state,
                entry.state or _("Unknown"),
            ),
            "can_edit": self._is_portal_daily_entry_editable(entry),
            "can_submit": self._is_portal_daily_entry_submittable(entry),
        })
        return request.render(
            "internship_logbook.portal_daily_entry_detail",
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
