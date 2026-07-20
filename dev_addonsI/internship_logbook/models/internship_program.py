from odoo import api, fields, models
from odoo.exceptions import ValidationError


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

    supervisor_id = fields.Many2one(
    comodel_name="res.users",
    string="Supervisor",
    required=True,
    default=lambda self: self.env.user,
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

    total_work_hours = fields.Float(
        string="Total Work Hours",
        compute="_compute_daily_entry_statistics",
    )

    approved_work_hours = fields.Float(
        string="Approved Work Hours",
        compute="_compute_daily_entry_statistics",
    )

    approval_percentage = fields.Float(
        string="Approval Percentage",
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

            # Number of approved entries
            program.approved_entry_count = len(approved_entries)

            # Work hours of all entries
            program.total_work_hours = sum(
                entries.mapped("work_hours")
            )

            # Work hours of approved entries only
            program.approved_work_hours = sum(
                approved_entries.mapped("work_hours")
            )

            # Approval percentage
            if program.daily_entry_count:
                program.approval_percentage = (
                    program.approved_entry_count
                    / program.daily_entry_count
                ) * 100
            else:
                program.approval_percentage = 0.0


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

    def action_start(self):
        for record in self:
            if record.state != "draft":
                raise ValidationError(
                    "Only draft internship programs can be started."
                )
            record.state = "active"

    def action_complete(self):
        for record in self:
            if record.state != "active":
                raise ValidationError(
                    "Only active internship programs can be completed."
                )

            unfinished_entries = record.daily_entry_ids.filtered(
                lambda entry: entry.state != "approved"
            )

            if unfinished_entries:
                raise ValidationError(
                    "The internship program cannot be completed while "
                    "there are daily entries that have not been approved."
                )

            if not record.daily_entry_ids:
                raise ValidationError(
                    "The internship program cannot be completed without "
                    "at least one daily entry."
                )

            record.state = "completed"

    def action_cancel(self):
        for record in self:
            if record.state not in ("draft", "active"):
                raise ValidationError(
                    "Only draft or active internship programs can be cancelled."
                )
            record.state = "cancelled"

    def action_reset_to_draft(self):
        for record in self:
            if record.state != "cancelled":
                raise ValidationError(
                    "Only cancelled internship programs can be reset to draft."
                )
            record.state = "draft"


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
