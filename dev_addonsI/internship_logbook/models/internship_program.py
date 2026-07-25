import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


class InternshipProgram(models.Model):
    _name = 'internship.program'
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = 'Internship Program'
    _order = 'start_date desc, id desc'
    _missing_activity_summary = "Missing Daily Entries"
    _ending_activity_summary = "Internship Program Ending Soon"

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

    student_university = fields.Char(
        related="student_id.university",
        string="University",
        store=True,
        index=True,
        readonly=True,
    )

    student_number = fields.Char(
        related="student_id.student_number",
        string="Student Number",
        readonly=True,
    )

    student_department = fields.Char(
        related="student_id.department",
        string="Student Department",
        readonly=True,
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

    submitted_entry_count = fields.Integer(
        string="Pending Review",
        compute="_compute_daily_entry_statistics",
    )

    revision_entry_count = fields.Integer(
        string="Revision Requested",
        compute="_compute_daily_entry_statistics",
    )

    missing_day_count = fields.Integer(
        string="Missing Days",
        compute="_compute_missing_day_count",
    )

    has_missing_days = fields.Boolean(
        string="Has Missing Days",
        compute="_compute_missing_day_count",
        search="_search_has_missing_days",
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
            submitted_entries = entries.filtered(
                lambda entry: entry.state == "submitted"
            )
            revision_entries = entries.filtered(
                lambda entry: entry.state == "revision"
            )

            # Number of approved entries
            program.approved_entry_count = len(approved_entries)
            program.completed_entry_count = len(completed_entries)
            program.submitted_entry_count = len(submitted_entries)
            program.revision_entry_count = len(revision_entries)

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

    def _missing_day_counts(self, *, today=None):
        """Return elapsed calendar dates without an active daily entry.

        The SQL query is restricted to the caller-accessible recordset. It
        mirrors the portal calendar-day definition without reading portal
        routes or bypassing record rules.
        """
        today = fields.Date.to_date(today or fields.Date.context_today(self))
        programs = self.filtered(
            lambda program: (
                program.active
                and program.workflow_mode == "supervised"
                and program.state == "active"
                and program.start_date
                and program.end_date
                and program.end_date >= program.start_date
                and program.start_date <= today
            )
        )
        if not programs:
            return {}

        programs.flush_recordset([
            "active",
            "workflow_mode",
            "state",
            "start_date",
            "end_date",
        ])
        self.env["internship.daily.entry"].flush_model([
            "program_id",
            "entry_date",
            "active",
        ])
        self.env.cr.execute(
            """
                SELECT
                    program.id,
                    GREATEST(
                        (
                            LEAST(program.end_date, %s::date)
                            - program.start_date
                            + 1
                        )
                        - COUNT(DISTINCT entry.entry_date)::integer,
                        0
                    )::integer
                  FROM internship_program AS program
                  LEFT JOIN internship_daily_entry AS entry
                    ON entry.program_id = program.id
                   AND entry.entry_date >= program.start_date
                   AND entry.entry_date <= LEAST(
                       program.end_date,
                       %s::date
                   )
                   AND entry.active = TRUE
                 WHERE program.id = ANY(%s)
                 GROUP BY
                    program.id,
                    program.start_date,
                    program.end_date
            """,
            [today, today, programs.ids],
        )
        return dict(self.env.cr.fetchall())

    def _compute_missing_day_count(self):
        counts = self._missing_day_counts()
        for program in self:
            program.missing_day_count = counts.get(program.id, 0)
            program.has_missing_days = bool(program.missing_day_count)

    @api.model
    def _search_has_missing_days(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(
                _("The Missing Days filter supports only true/false values.")
            )
        programs = self.search([
            ("active", "=", True),
            ("workflow_mode", "=", "supervised"),
            ("state", "=", "active"),
        ])
        missing_ids = list(programs._missing_day_counts())
        wants_missing = value if operator == "=" else not value
        return [
            ("id", "in" if wants_missing else "not in", missing_ids)
        ]

    @api.model
    def _find_missing_entries(self, today=None, limit=None, domain=None):
        """Return caller-visible active supervised programs with missing days."""
        search_domain = [
            ("active", "=", True),
            ("workflow_mode", "=", "supervised"),
            ("state", "=", "active"),
        ]
        if domain:
            search_domain.extend(domain)
        programs = self.search(
            search_domain, order="end_date asc, id asc", limit=limit
        )
        missing_counts = programs._missing_day_counts(today=today)
        missing_ids = {
            program_id
            for program_id, count in missing_counts.items()
            if count > 0
        }
        return programs.filtered(lambda program: program.id in missing_ids)

    @api.model
    def _find_programs_ending_soon(
        self, days=7, today=None, limit=None, domain=None
    ):
        """Return caller-visible active programs ending in the date window."""
        if not isinstance(days, int) or days < 0:
            raise ValidationError(_("Reminder days must be a positive integer."))
        today = fields.Date.to_date(today or fields.Date.context_today(self))
        search_domain = [
            ("active", "=", True),
            ("state", "=", "active"),
            ("end_date", ">=", today),
            ("end_date", "<=", fields.Date.add(today, days=days)),
        ]
        if domain:
            search_domain.extend(domain)
        return self.search(
            search_domain, order="end_date asc, id asc", limit=limit
        )

    @api.model
    def _cron_manager_context_allowed(self):
        return not self.env.su and self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )

    def _program_reminder_activities(self, summary, user=None):
        activities = self.activity_ids.filtered(
            lambda activity: activity.summary == summary
        )
        if user:
            activities = activities.filtered(
                lambda activity: activity.user_id == user
            )
        return activities

    def _schedule_unique_program_reminder(self, user, summary, note):
        self.ensure_one()
        if not user or self._program_reminder_activities(summary, user=user):
            return self.env["mail.activity"]
        return self.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=user.id,
            summary=summary,
            note=note,
        )

    def _valid_program_reminder_assignee(self, user):
        self.ensure_one()
        if not user or not user.active or user.share:
            return False
        try:
            self.with_user(user).check_access("read")
        except AccessError:
            return False
        return True

    def _missing_entry_reminder_assignee(self):
        self.ensure_one()
        student_user = self.student_id.user_id
        if (
            student_user.has_group(
                "internship_logbook.group_internship_intern"
            )
            and self._valid_program_reminder_assignee(student_user)
        ):
            return student_user
        if self._valid_program_reminder_assignee(self.supervisor_id):
            return self.supervisor_id
        return self.env["res.users"]

    def _ending_soon_reminder_assignee(self):
        self.ensure_one()
        if self._valid_program_reminder_assignee(self.supervisor_id):
            return self.supervisor_id
        return self.env["res.users"]

    @api.model
    def _cleanup_stale_program_reminders(
        self, summary, today=None, days=7, batch_limit=200
    ):
        model_id = self.env["ir.model"]._get_id(self._name)
        activities = self.env["mail.activity"].search([
            ("res_model_id", "=", model_id),
            ("summary", "=", summary),
        ], order="id asc", limit=batch_limit)
        programs = self.search([("id", "in", activities.mapped("res_id"))])
        if summary == self._missing_activity_summary:
            counts = programs._missing_day_counts(today=today)
            eligible_ids = {
                program_id
                for program_id, count in counts.items()
                if count > 0
            }
        else:
            today = fields.Date.to_date(
                today or fields.Date.context_today(self)
            )
            end_date = fields.Date.add(today, days=days)
            eligible_ids = set(programs.filtered(lambda program: (
                program.active
                and program.state == "active"
                and program.end_date
                and today <= program.end_date <= end_date
            )).ids)
        stale = activities.filtered(
            lambda activity: activity.res_id not in eligible_ids
        )
        if stale:
            stale.action_feedback(
                feedback=_("Automated reminder is no longer applicable.")
            )
        return len(stale)

    @api.model
    def _process_missing_entry_reminders(
        self, today=None, domain=None, batch_limit=200
    ):
        stats = {
            "found": 0,
            "created": 0,
            "existing": 0,
            "skipped": 0,
            "failed": 0,
            "cleaned": 0,
        }
        programs = self._find_missing_entries(
            today=today, limit=batch_limit, domain=domain
        )
        stats["found"] = len(programs)
        stats["cleaned"] = self._cleanup_stale_program_reminders(
            self._missing_activity_summary,
            today=today,
            batch_limit=batch_limit,
        )
        missing_counts = programs._missing_day_counts(today=today)
        for program in programs:
            try:
                with self.env.cr.savepoint():
                    assignee = program._missing_entry_reminder_assignee()
                    if not assignee:
                        stats["skipped"] += 1
                        _logger.warning(
                            "Missing entry reminder skipped: program_id=%s "
                            "reason=no_internal_assignee",
                            program.id,
                        )
                        continue
                    if program._program_reminder_activities(
                        program._missing_activity_summary,
                        user=assignee,
                    ):
                        stats["existing"] += 1
                        continue
                    program._schedule_unique_program_reminder(
                        assignee,
                        program._missing_activity_summary,
                        _(
                            "Review %(program)s and complete the missing "
                            "daily entries. Current missing-day count: %(count)s.",
                            program=program.display_name,
                            count=missing_counts.get(program.id, 0),
                        ),
                    )
                    stats["created"] += 1
            except (AccessError, UserError, ValidationError) as error:
                stats["skipped"] += 1
                _logger.warning(
                    "Missing entry reminder skipped: program_id=%s "
                    "error_type=%s",
                    program.id,
                    type(error).__name__,
                )
            except Exception:
                stats["failed"] += 1
                _logger.exception(
                    "Missing entry reminder failed: program_id=%s",
                    program.id,
                )
        return stats

    @api.model
    def _process_ending_soon_reminders(
        self, days=7, today=None, domain=None, batch_limit=200
    ):
        stats = {
            "found": 0,
            "created": 0,
            "existing": 0,
            "skipped": 0,
            "failed": 0,
            "cleaned": 0,
        }
        programs = self._find_programs_ending_soon(
            days=days, today=today, limit=batch_limit, domain=domain
        )
        stats["found"] = len(programs)
        stats["cleaned"] = self._cleanup_stale_program_reminders(
            self._ending_activity_summary,
            today=today,
            days=days,
            batch_limit=batch_limit,
        )
        for program in programs:
            try:
                with self.env.cr.savepoint():
                    assignee = program._ending_soon_reminder_assignee()
                    if not assignee:
                        stats["skipped"] += 1
                        _logger.warning(
                            "Ending-soon reminder skipped: program_id=%s "
                            "reason=no_internal_supervisor",
                            program.id,
                        )
                        continue
                    if program._program_reminder_activities(
                        program._ending_activity_summary,
                        user=assignee,
                    ):
                        stats["existing"] += 1
                        continue
                    program._schedule_unique_program_reminder(
                        assignee,
                        program._ending_activity_summary,
                        _(
                            "Internship program %(program)s ends on %(date)s. "
                            "Please review its current progress.",
                            program=program.display_name,
                            date=program.end_date,
                        ),
                    )
                    stats["created"] += 1
            except (AccessError, UserError, ValidationError) as error:
                stats["skipped"] += 1
                _logger.warning(
                    "Ending-soon reminder skipped: program_id=%s "
                    "error_type=%s",
                    program.id,
                    type(error).__name__,
                )
            except Exception:
                stats["failed"] += 1
                _logger.exception(
                    "Ending-soon reminder failed: program_id=%s",
                    program.id,
                )
        return stats

    @api.model
    def _cron_remind_missing_entries(self, batch_limit=200):
        if not self._cron_manager_context_allowed():
            stats = {
                "found": 0, "created": 0, "existing": 0,
                "skipped": 0, "failed": 1, "cleaned": 0,
            }
            _logger.error(
                "Missing entry reminders refused: cron user must be an "
                "internal Internship Manager and must not be superuser"
            )
            return stats
        stats = self._process_missing_entry_reminders(
            batch_limit=batch_limit
        )
        _logger.info(
            "Missing entry reminders: found=%s created=%s existing=%s "
            "skipped=%s failed=%s cleaned=%s",
            stats["found"], stats["created"], stats["existing"],
            stats["skipped"], stats["failed"], stats["cleaned"],
        )
        return stats

    @api.model
    def _cron_remind_programs_ending_soon(
        self, days=7, batch_limit=200
    ):
        if not self._cron_manager_context_allowed():
            stats = {
                "found": 0, "created": 0, "existing": 0,
                "skipped": 0, "failed": 1, "cleaned": 0,
            }
            _logger.error(
                "Ending-soon reminders refused: cron user must be an "
                "internal Internship Manager and must not be superuser"
            )
            return stats
        stats = self._process_ending_soon_reminders(
            days=days, batch_limit=batch_limit
        )
        _logger.info(
            "Ending-soon reminders: found=%s created=%s existing=%s "
            "skipped=%s failed=%s cleaned=%s",
            stats["found"], stats["created"], stats["existing"],
            stats["skipped"], stats["failed"], stats["cleaned"],
        )
        return stats


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

    def _complete_daily_entry_workflow_activities(self, feedback):
        entries = self.daily_entry_ids
        entries._complete_workflow_activities(
            entries._review_activity_summary,
            feedback,
        )
        entries._complete_workflow_activities(
            entries._revision_activity_summary,
            feedback,
        )

    def _complete_program_reminder_activities(self, feedback):
        reminders = self.activity_ids.filtered(
            lambda activity: activity.summary in {
                self._missing_activity_summary,
                self._ending_activity_summary,
            }
        )
        if reminders:
            reminders.action_feedback(feedback=feedback)

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
            record._complete_daily_entry_workflow_activities(
                _("Internship program completed."),
            )
            record._complete_program_reminder_activities(
                _("Internship program completed."),
            )

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
            record._complete_daily_entry_workflow_activities(
                _("Internship program cancelled."),
            )
            record._complete_program_reminder_activities(
                _("Internship program cancelled."),
            )

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

    def action_view_review_queue(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Review Queue"),
            "res_model": "internship.daily.entry",
            "view_mode": "list,form,pivot,graph",
            "views": [
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
            "domain": [
                ("program_id", "=", self.id),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "submitted"),
            ],
        }

    def action_view_missing_days(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Program Missing Days"),
            "res_model": "internship.program",
            "view_mode": "list,form",
            "domain": [("id", "=", self.id)],
            "context": {"search_default_filter_missing_days": 1},
        }

    def action_view_student_overview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Student Overview"),
            "res_model": "internship.student",
            "res_id": self.student_id.id,
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "internship_logbook.view_internship_student_form"
                ).id,
                "form",
            )],
        }

    def action_view_analytics(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "internship_logbook.action_internship_daily_entry_analytics"
        )
        action["domain"] = [("program_id", "=", self.id)]
        return action

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "internship_logbook.action_report_internship_logbook"
        ).report_action(self)
