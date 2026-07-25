from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = "res.users"

    internship_pending_review_count = fields.Integer(
        string="Pending Review",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_revision_requested_count = fields.Integer(
        string="Revision Requested",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_approved_entries_count = fields.Integer(
        string="Approved Entries",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_completed_programs_count = fields.Integer(
        string="Completed Internships",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_active_programs_count = fields.Integer(
        string="Active Internships",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_ending_soon_count = fields.Integer(
        string="Ending Soon",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_students_missing_days_count = fields.Integer(
        string="Students With Missing Days",
        compute="_compute_internship_supervisor_dashboard",
    )
    internship_assigned_students_count = fields.Integer(
        string="Assigned Students",
        compute="_compute_internship_supervisor_dashboard",
    )

    @api.depends_context("uid")
    def _compute_internship_supervisor_dashboard(self):
        values_by_user = {
            user.id: {
                "pending": 0,
                "revision": 0,
                "approved": 0,
                "completed_programs": 0,
                "active_programs": 0,
                "ending_soon": 0,
                "missing_students": set(),
                "assigned_students": set(),
            }
            for user in self
        }
        user_ids = list(values_by_user)
        if user_ids:
            entry_groups = self.env["internship.daily.entry"]._read_group(
                [
                    ("active", "=", True),
                    ("workflow_mode", "=", "supervised"),
                    ("supervisor_id", "in", user_ids),
                    ("state", "in", [
                        "submitted",
                        "revision",
                        "approved",
                    ]),
                ],
                groupby=["supervisor_id", "state"],
                aggregates=["__count"],
            )
            entry_keys = {
                "submitted": "pending",
                "revision": "revision",
                "approved": "approved",
            }
            for supervisor, state, count in entry_groups:
                values_by_user[supervisor.id][entry_keys[state]] = count

            program_groups = self.env["internship.program"]._read_group(
                [
                    ("workflow_mode", "=", "supervised"),
                    ("supervisor_id", "in", user_ids),
                    ("state", "in", ["active", "completed"]),
                ],
                groupby=["supervisor_id", "state"],
                aggregates=["__count"],
            )
            for supervisor, state, count in program_groups:
                key = (
                    "active_programs"
                    if state == "active"
                    else "completed_programs"
                )
                values_by_user[supervisor.id][key] = count

            assigned_groups = self.env["internship.program"]._read_group(
                [
                    ("workflow_mode", "=", "supervised"),
                    ("supervisor_id", "in", user_ids),
                ],
                groupby=["supervisor_id", "student_id"],
                aggregates=["__count"],
            )
            for supervisor, student, _count in assigned_groups:
                values_by_user[supervisor.id]["assigned_students"].add(
                    student.id
                )

            today = fields.Date.context_today(self)
            ending_soon = self.env["internship.program"]._read_group(
                [
                    ("active", "=", True),
                    ("workflow_mode", "=", "supervised"),
                    ("state", "=", "active"),
                    ("supervisor_id", "in", user_ids),
                    ("end_date", ">=", today),
                    ("end_date", "<=", today + timedelta(days=14)),
                ],
                groupby=["supervisor_id"],
                aggregates=["__count"],
            )
            for supervisor, count in ending_soon:
                values_by_user[supervisor.id]["ending_soon"] = count

            active_programs = self.env["internship.program"].search([
                ("active", "=", True),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "active"),
                ("supervisor_id", "in", user_ids),
            ])
            missing_ids = active_programs._missing_day_counts(today=today)
            for program in active_programs.filtered(
                lambda item: item.id in missing_ids
            ):
                values_by_user[program.supervisor_id.id][
                    "missing_students"
                ].add(program.student_id.id)

        for user in self:
            values = values_by_user[user.id]
            user.internship_pending_review_count = values["pending"]
            user.internship_revision_requested_count = values["revision"]
            user.internship_approved_entries_count = values["approved"]
            user.internship_completed_programs_count = values[
                "completed_programs"
            ]
            user.internship_active_programs_count = values["active_programs"]
            user.internship_ending_soon_count = values["ending_soon"]
            user.internship_students_missing_days_count = len(
                values["missing_students"]
            )
            user.internship_assigned_students_count = len(
                values["assigned_students"]
            )

    def _check_internship_dashboard_access(self):
        self.ensure_one()
        is_manager = self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )
        if not (
            self.env.user.has_group(
                "internship_logbook.group_internship_supervisor"
            )
            or is_manager
        ):
            raise AccessError(_("This account cannot use the supervisor dashboard."))
        if self != self.env.user and not is_manager:
            raise AccessError(_("Supervisors can open only their own dashboard."))

    @api.model
    def action_open_internship_supervisor_dashboard(self):
        user = self.env.user
        user._check_internship_dashboard_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Supervisor Dashboard"),
            "res_model": "res.users",
            "res_id": user.id,
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "internship_logbook.view_internship_supervisor_dashboard"
                ).id,
                "form",
            )],
            "target": "current",
        }

    def _internship_dashboard_action(
        self,
        res_model,
        name,
        domain,
        *,
        view_mode="list,form",
        views=None,
    ):
        self._check_internship_dashboard_access()
        action = {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": res_model,
            "view_mode": view_mode,
            "domain": domain,
        }
        if views:
            action["views"] = views
        return action

    def action_internship_pending_review(self):
        return self._internship_dashboard_action(
            "internship.daily.entry",
            _("Pending Review"),
            [
                ("supervisor_id", "=", self.id),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "submitted"),
            ],
            view_mode="list,form,pivot,graph",
            views=[
                (
                    self.env.ref(
                        "internship_logbook."
                        "view_internship_supervisor_review_queue_list"
                    ).id,
                    "list",
                ),
                (False, "form"),
                (False, "pivot"),
                (False, "graph"),
            ],
        )

    def action_internship_revision_requested(self):
        return self._internship_dashboard_action(
            "internship.daily.entry",
            _("Revision Requested"),
            [
                ("supervisor_id", "=", self.id),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "revision"),
            ],
        )

    def action_internship_approved_entries(self):
        return self._internship_dashboard_action(
            "internship.daily.entry",
            _("Approved Entries"),
            [
                ("supervisor_id", "=", self.id),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "approved"),
            ],
        )

    def _program_dashboard_action(self, name, domain):
        return self._internship_dashboard_action(
            "internship.program",
            name,
            [
                ("supervisor_id", "=", self.id),
                ("workflow_mode", "=", "supervised"),
                *domain,
            ],
        )

    def action_internship_completed_programs(self):
        return self._program_dashboard_action(
            _("Completed Internships"),
            [("state", "=", "completed")],
        )

    def action_internship_active_programs(self):
        return self._program_dashboard_action(
            _("Active Internships"),
            [("state", "=", "active")],
        )

    def action_internship_ending_soon(self):
        today = fields.Date.context_today(self)
        return self._program_dashboard_action(
            _("Internships Ending Soon"),
            [
                ("active", "=", True),
                ("state", "=", "active"),
                ("end_date", ">=", today),
                ("end_date", "<=", today + timedelta(days=14)),
            ],
        )

    def action_internship_students_missing_days(self):
        self._check_internship_dashboard_access()
        programs = self.env["internship.program"].search([
            ("active", "=", True),
            ("workflow_mode", "=", "supervised"),
            ("state", "=", "active"),
            ("supervisor_id", "=", self.id),
        ])
        missing_ids = programs._missing_day_counts()
        student_ids = programs.filtered(
            lambda program: program.id in missing_ids
        ).student_id.ids
        return self._internship_dashboard_action(
            "internship.student",
            _("Students With Missing Days"),
            [("id", "in", student_ids)],
        )

    def action_internship_assigned_students(self):
        return self._internship_dashboard_action(
            "internship.student",
            _("Assigned Students"),
            [
                ("program_ids.workflow_mode", "=", "supervised"),
                ("program_ids.supervisor_id", "=", self.id),
            ],
        )
