from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class InternshipProgram(models.Model):
    _name = 'internship.program'
    _description = 'Internship Program'
    _order = 'start_date desc, id desc'

    name = fields.Char(
        string='Program Name',
        required=True,
    )

    student_id = fields.Many2one(
        comodel_name='internship.student',
        string='Student',
        required=True,
        ondelete='cascade',
        index=True,
    )

    company_name = fields.Char(
        string='Company Name',
        required=True,
    )

    department = fields.Char(
        string="Department",
        required=True,
    )

    workflow_mode = fields.Selection(
        selection=[
            ("supervised", "Supervised"),
            ("independent", "Independent"),
        ],
        string="Workflow Mode",
        required=True,
        default="supervised",
        index=True,
    )

    supervisor_id = fields.Many2one(
        comodel_name="res.users",
        string="Supervisor",
        index=True,
    )

    start_date = fields.Date(
        string='Start Date',
        required=True,
    )

    end_date = fields.Date(
        string='End Date',
        required=True,
    )

    duration_days = fields.Integer(
        string='Duration',
        compute='_compute_duration_days',
        store=True,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
    )

    daily_entry_ids = fields.One2many(
        comodel_name="internship.daily.entry",
        inverse_name="program_id",
        string="Daily Entries",
    )
    daily_entry_count = fields.Integer(
        string="Daily Entry Count",
        compute="_compute_daily_entry_statistics",
    )

    approved_entry_count = fields.Integer(
        string="Approved Entry Count",
        compute="_compute_daily_entry_statistics",
    )

    completed_entry_count = fields.Integer(
        string="Completed Entry Count",
        compute="_compute_daily_entry_statistics",
    )

    total_work_hours = fields.Float(
        string="Total Work Hours",
        compute="_compute_daily_entry_statistics",
    )

    approved_work_hours = fields.Float(
        string="Approved Work Hours",
        compute="_compute_daily_entry_statistics",
    )

    completed_work_hours = fields.Float(
        string="Completed Work Hours",
        compute="_compute_daily_entry_statistics",
    )

    approval_percentage = fields.Float(
        string="Approval Percentage",
        compute="_compute_daily_entry_statistics",
    )

    completion_percentage = fields.Float(
        string="Completion Percentage",
        compute="_compute_daily_entry_statistics",
    )

    notes = fields.Text(
        string='Notes',
    )

    active = fields.Boolean(
        string='Active Record',
        default=True,
    )

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for record in self:
            if record.start_date and record.end_date:
                record.duration_days = (
                    record.end_date - record.start_date
                ).days + 1
            else:
                record.duration_days = 0

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if (
                record.start_date
                and record.end_date
                and record.end_date < record.start_date
            ):
                raise ValidationError(
                    'End date cannot be earlier than start date.'
                )

    @api.constrains("workflow_mode", "supervisor_id")
    def _check_workflow_supervisor(self):
        for record in self:
            if record.workflow_mode == "supervised" and not record.supervisor_id:
                raise ValidationError(
                    "A supervisor is required for supervised internships."
                )
            if record.workflow_mode == "independent" and record.supervisor_id:
                raise ValidationError(
                    "Independent internships cannot have a supervisor."
                )

    @api.depends(
        "daily_entry_ids",
        "daily_entry_ids.state",
        "daily_entry_ids.work_hours",
    )
    def _compute_daily_entry_statistics(self):
        for program in self:
            entries = program.daily_entry_ids

            # Total number of daily entries
            program.daily_entry_count = len(entries)

            # Only approved entries
            approved_entries = entries.filtered(
                lambda entry: entry.state == "approved"
            )
            completed_entries = entries.filtered(
                lambda entry: entry.state == "completed"
            )

            # Number of approved entries
            program.approved_entry_count = len(approved_entries)
            program.completed_entry_count = len(completed_entries)

            # Work hours of all entries
            program.total_work_hours = sum(
                entries.mapped("work_hours")
            )

            # Work hours of approved entries only
            program.approved_work_hours = sum(
                approved_entries.mapped("work_hours")
            )
            program.completed_work_hours = sum(
                completed_entries.mapped("work_hours")
            )

            # Approval percentage
            if program.daily_entry_count:
                program.approval_percentage = (
                    program.approved_entry_count
                    / program.daily_entry_count
                ) * 100
            else:
                program.approval_percentage = 0.0
            if program.daily_entry_count:
                program.completion_percentage = (
                    program.completed_entry_count
                    / program.daily_entry_count
                ) * 100
            else:
                program.completion_percentage = 0.0


    @api.constrains("student_id", "start_date", "end_date")
    def _check_overlapping_internship_programs(self):
        for record in self:
            if not (
                record.student_id
                and record.start_date
                and record.end_date
            ):
                continue

            overlapping_program = self.search([
                ("id", "!=", record.id),
                ("student_id", "=", record.student_id.id),
                ("start_date", "<=", record.end_date),
                ("end_date", ">=", record.start_date),
            ], limit=1)

            if overlapping_program:
                raise ValidationError(
                    "This student already has an internship program "
                    "that overlaps with the selected date range."
                )

    @api.model
    @api.private
    def _portal_create_first_program(self, user_id, values):
        """Create the first portal internship with a serialized eligibility check."""
        allowed_fields = {
            "company_name",
            "department",
            "start_date",
            "end_date",
            "workflow_mode",
        }
        if set(values) - allowed_fields:
            raise AccessError(_("Unsupported internship onboarding values."))

        user = self.env["res.users"].browse(user_id).exists()
        if (
            len(user) != 1
            or not user.share
            or not user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        ):
            raise AccessError(_("This account cannot create an internship."))

        students = self.env["internship.student"].search(
            [("user_id", "=", user.id), ("active", "=", True)],
            limit=2,
        )
        if len(students) != 1:
            raise AccessError(
                _("A valid student profile is required for onboarding.")
            )
        student = students

        company_name = (values.get("company_name") or "").strip()
        department = (values.get("department") or "").strip()
        workflow_mode = values.get("workflow_mode")
        start_date = fields.Date.to_date(values.get("start_date"))
        end_date = fields.Date.to_date(values.get("end_date"))
        if not company_name or not department or not start_date or not end_date:
            raise ValidationError(_("Complete all required internship fields."))
        if len(company_name) > 200 or len(department) > 200:
            raise ValidationError(
                _("Company and department must not exceed 200 characters.")
            )
        if workflow_mode != "independent":
            raise ValidationError(
                _("Only independent internships are available in onboarding.")
            )
        if end_date < start_date:
            raise ValidationError(
                _("End date cannot be earlier than start date.")
            )

        # Serialize first-program creation without imposing a permanent unique
        # constraint that would block future historical/multi-program support.
        with self.env.cr.savepoint():
            self.env.cr.execute(
                "SELECT id FROM internship_student WHERE id = %s FOR UPDATE",
                [student.id],
            )
            if self.with_context(active_test=False).search_count(
                [("student_id", "=", student.id)],
                limit=1,
            ):
                raise UserError(
                    _("An internship program already exists for this account.")
                )
            return self.create({
                "name": _("Internship at %s") % company_name,
                "student_id": student.id,
                "company_name": company_name,
                "department": department,
                "workflow_mode": "independent",
                "supervisor_id": False,
                "start_date": start_date,
                "end_date": end_date,
                "state": "draft",
            })

    def write(self, values):
        protected_fields = {"workflow_mode", "student_id", "supervisor_id"}
        is_manager = self.env.su or self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )
        is_intern = self.env.user.has_group(
            "internship_logbook.group_internship_intern"
        )

        if not is_manager and is_intern and "state" in values:
            raise AccessError(
                "Internship program state changes must use an authorized "
                "workflow action."
            )

        if not is_manager and protected_fields.intersection(values):
            if "workflow_mode" in values:
                raise AccessError(
                    "Only internship managers can change the workflow mode."
                )
            if is_intern:
                raise AccessError(
                    "Interns cannot change the student or supervisor assignment."
                )

        if "workflow_mode" in values:
            for record in self:
                if values["workflow_mode"] == record.workflow_mode:
                    continue
                if not is_manager:
                    raise AccessError(
                        "Only internship managers can change the workflow mode."
                    )
                if record.state != "draft":
                    raise ValidationError(
                        "The workflow mode can only be changed while the "
                        "internship program is in draft."
                    )
                if record.daily_entry_ids:
                    raise ValidationError(
                        "The workflow mode cannot be changed after daily "
                        "entries have been created."
                    )

        return super().write(values)

    def _is_internship_manager(self):
        return self.env.su or self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )

    def _is_owning_intern(self):
        self.ensure_one()
        return self.env.user.has_group(
            "internship_logbook.group_internship_intern"
        ) and self.student_id.user_id == self.env.user

    def _check_independent_workflow_actor(self):
        self.ensure_one()
        self.check_access("write")
        if self._is_internship_manager():
            return
        if not self._is_owning_intern():
            raise AccessError(
                "Only the owning intern or an internship manager can "
                "use the independent internship program workflow."
            )

    def _check_supervised_workflow_actor(self):
        self.ensure_one()
        self.check_access("write")
        if self._is_internship_manager():
            return
        if self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        ):
            return
        raise AccessError(
            "Only the assigned internship supervisor or an internship "
            "manager can use the supervised internship program workflow."
        )

    @api.private
    def _write_workflow_state(self, state):
        return super(InternshipProgram, self).write({"state": state})

    def action_start(self):
        for record in self:
            record._check_supervised_workflow_actor()
            if record.state != "draft":
                raise ValidationError(
                    "Only draft internship programs can be started."
                )
            record._write_workflow_state("active")

    def action_complete(self):
        for record in self:
            record.check_access("write")
            if record.workflow_mode == "independent":
                record._check_independent_workflow_actor()
            else:
                record._check_supervised_workflow_actor()

            if record.state != "active":
                raise ValidationError(
                    "Only active internship programs can be completed."
                )

            required_entry_state = (
                "completed"
                if record.workflow_mode == "independent"
                else "approved"
            )
            unfinished_entries = record.daily_entry_ids.filtered(
                lambda entry: entry.state != required_entry_state
            )

            if unfinished_entries:
                if record.workflow_mode == "independent":
                    raise ValidationError(
                        "The internship program cannot be completed while "
                        "there are daily entries that have not been completed."
                    )
                raise ValidationError(
                    "The internship program cannot be completed while "
                    "there are daily entries that have not been approved."
                )

            if not record.daily_entry_ids:
                raise ValidationError(
                    "The internship program cannot be completed without "
                    "at least one daily entry."
                )

            record._write_workflow_state("completed")

    def action_reopen(self):
        for record in self:
            record._check_independent_workflow_actor()
            if record.workflow_mode != "independent":
                raise ValidationError(
                    "Only independent internship programs can be reopened."
                )
            if record.state != "completed":
                raise ValidationError(
                    "Only completed independent internship programs "
                    "can be reopened."
                )
            record._write_workflow_state("active")

    def action_cancel(self):
        for record in self:
            record._check_supervised_workflow_actor()
            if record.state not in ("draft", "active"):
                raise ValidationError(
                    "Only draft or active internship programs can be cancelled."
                )
            record._write_workflow_state("cancelled")

    def action_reset_to_draft(self):
        for record in self:
            record._check_supervised_workflow_actor()
            if record.state != "cancelled":
                raise ValidationError(
                    "Only cancelled internship programs can be reset to draft."
                )
            record._write_workflow_state("draft")


    def action_view_daily_entries(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Daily Entries",
            "res_model": "internship.daily.entry",
            "view_mode": "list,form",
            "domain": [
                ("program_id", "=", self.id),
            ],
            "context": {
                "default_program_id": self.id,
            },
        }
