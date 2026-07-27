import logging
import math

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)

class InternshipDailyEntry(models.Model):
    _name = "internship.daily.entry"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]
    _description = "Internship Daily Entry"
    _order = "entry_date desc, id desc"
    _review_activity_summary = "Review Daily Internship Entry"
    _revision_activity_summary = "Revise Daily Internship Entry"
    _intern_content_fields = {
        "title",
        "entry_date",
        "work_hours",
        "technologies",
        "work_description",
        "learned_topics",
        "challenges",
        "active",
    }

    _program_entry_date_unique = models.Constraint(
        "UNIQUE(program_id, entry_date)",
        "Only one daily entry can be created for the same "
        "internship program and date.",
    )

    title = fields.Char(
        string="Work Title",
        required=True,
    )

    program_id = fields.Many2one(
        comodel_name="internship.program",
        string="Internship Program",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    student_id = fields.Many2one(
        comodel_name="internship.student",
        string="Student",
        related="program_id.student_id",
        store=True,
        readonly=True,
    )

    supervisor_id = fields.Many2one(
        comodel_name="res.users",
        string="Supervisor",
        related="program_id.supervisor_id",
        store=True,
        readonly=True,
    )

    company_name = fields.Char(
        related="program_id.company_name",
        string="Company",
        store=True,
        index=True,
        readonly=True,
    )

    program_department = fields.Char(
        related="program_id.department",
        string="Department",
        readonly=True,
    )

    student_university = fields.Char(
        related="student_id.university",
        string="University",
        store=True,
        index=True,
        readonly=True,
    )

    workflow_mode = fields.Selection(
        related="program_id.workflow_mode",
        string="Workflow Mode",
        readonly=True,
    )

    program_state = fields.Selection(
        related="program_id.state",
        string="Program Status",
        readonly=True,
    )

    entry_date = fields.Date(
        string="Entry Date",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
    )

    day_number = fields.Integer(
        string="Day Number",
        compute="_compute_day_number",
        store=True,
    )

    work_hours = fields.Float(
        string="Work Hours",
        required=True,
        default=8.0,
        tracking=True,
    )

    technologies = fields.Char(
        string="Technologies Used",
    )

    work_description = fields.Text(
        string="Work Description",
        required=True,
    )

    learned_topics = fields.Text(
        string="What I Learned",
    )

    challenges = fields.Text(
        string="Problems and Solutions",
    )

    supervisor_comment = fields.Text(
        string="Supervisor Comment",
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("revision", "Revision Requested"),
            ("approved", "Approved"),
            ("completed", "Completed"),
        ],
        string="Status",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    @api.depends("program_id", "entry_date", "program_id.start_date")
    def _compute_day_number(self):
        for entry in self:
            if (
                entry.program_id
                and entry.program_id.start_date
                and entry.entry_date
            ):
                entry.day_number = (
                    entry.entry_date - entry.program_id.start_date
                ).days + 1
            else:
                entry.day_number = 0

    @api.constrains("program_id", "entry_date")
    def _check_entry_date(self):
        for entry in self:
            if not entry.program_id or not entry.entry_date:
                continue

            if (
                entry.program_id.start_date
                and entry.entry_date < entry.program_id.start_date
            ):
                raise ValidationError(
                    "The daily entry date cannot be earlier than "
                    "the internship start date."
                )

            if (
                entry.program_id.end_date
                and entry.entry_date > entry.program_id.end_date
            ):
                raise ValidationError(
                    "The daily entry date cannot be later than "
                    "the internship end date."
                )


    @api.constrains("work_hours")
    def _check_work_hours(self):
        for entry in self:
            if entry.work_hours <= 0:
                raise ValidationError(
                    "Work hours must be greater than zero."
                )

            if entry.work_hours > 24:
                raise ValidationError(
                    "Work hours cannot be greater than 24."
                )

    @api.constrains("program_id", "state")
    def _check_workflow_state_compatibility(self):
        for entry in self:
            if not entry.program_id:
                continue
            if (
                entry.program_id.workflow_mode == "supervised"
                and entry.state == "completed"
            ):
                raise ValidationError(
                    "Supervised daily entries cannot use the completed state."
                )
            if (
                entry.program_id.workflow_mode == "independent"
                and entry.state in ("submitted", "revision", "approved")
            ):
                raise ValidationError(
                    "Independent daily entries can only be draft or completed."
                )

    @api.model_create_multi
    def create(self, values_list):
        is_manager = self._is_internship_manager()
        if not is_manager:
            for values in values_list:
                if values.get("state", "draft") != "draft":
                    raise AccessError(
                        "Daily entries must be created in draft state."
                    )
                program = self.env["internship.program"].browse(
                    values.get("program_id")
                ).exists()
                if not program:
                    raise ValidationError(
                        "A valid internship program is required."
                    )
                program.check_access("read")
                if not self._is_owning_intern(program=program):
                    raise AccessError(
                        "Interns can only create daily entries for "
                        "their own internship programs."
                    )
        return super().create(values_list)

    def write(self, values):
        self.check_access("write")
        if self._is_internship_manager():
            return super().write(values)

        user = self.env.user
        is_intern = user.has_group(
            "internship_logbook.group_internship_intern"
        )
        is_supervisor = user.has_group(
            "internship_logbook.group_internship_supervisor"
        )

        for entry in self:
            if is_intern and self._is_owning_intern(entry=entry):
                if {
                    "program_id",
                    "student_id",
                    "supervisor_id",
                    "workflow_mode",
                    "program_state",
                    "supervisor_comment",
                }.intersection(values):
                    raise AccessError(
                        "Interns cannot change the internship assignment "
                        "or supervisor evaluation."
                    )
                if "state" in values:
                    raise AccessError(
                        "Daily entry state changes must use an authorized "
                        "workflow action."
                    )
                if self._intern_content_fields.intersection(values):
                    editable_states = (
                        ("draft",)
                        if entry.workflow_mode == "independent"
                        else ("draft", "revision")
                    )
                    if entry.state not in editable_states:
                        raise AccessError(
                            "This daily entry is not editable in its "
                            "current state."
                        )
                continue

            if is_supervisor:
                if entry.workflow_mode != "supervised":
                    raise AccessError(
                        "Supervisors cannot modify independent daily entries."
                    )
                if self._intern_content_fields.intersection(values):
                    raise AccessError(
                        "Supervisors cannot modify intern-authored daily "
                        "entry content."
                    )
                if "state" in values:
                    raise AccessError(
                        "Daily entry state changes must use an authorized "
                        "workflow action."
                    )
                continue

            raise AccessError(
                "You are not allowed to modify this daily entry."
            )

        return super().write(values)

    def _is_internship_manager(self):
        return self.env.su or self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )

    @api.model
    @api.private
    def _portal_prepare_daily_entry_values(self, values):
        """Normalize the scalar values accepted by portal create/edit."""
        allowed_fields = {
            "entry_date",
            "title",
            "work_description",
            "work_hours",
        }
        if set(values) - allowed_fields:
            raise AccessError(_("Unsupported daily entry values."))

        title = (values.get("title") or "").strip()
        work_description = (
            values.get("work_description") or ""
        ).strip()
        try:
            entry_date = fields.Date.to_date(values.get("entry_date"))
        except (TypeError, ValueError):
            entry_date = False
        try:
            work_hours = float(values.get("work_hours"))
        except (TypeError, ValueError):
            work_hours = 0.0

        if not title or not work_description or not entry_date:
            raise ValidationError(
                _("Complete all required daily entry fields.")
            )
        if len(title) > 200 or len(work_description) > 10000:
            raise ValidationError(
                _("The daily entry text exceeds the allowed length.")
            )
        if (
            not math.isfinite(work_hours)
            or work_hours <= 0
            or work_hours > 24
        ):
            raise ValidationError(
                _("Work hours must be greater than zero and at most 24.")
            )
        return {
            "entry_date": entry_date,
            "title": title,
            "work_description": work_description,
            "work_hours": work_hours,
        }

    @api.model
    @api.private
    def _portal_create_draft_entry(self, user_id, program_id, values):
        """Create one owned portal draft after repeating all trust checks."""
        prepared_values = self._portal_prepare_daily_entry_values(values)

        user = self.env["res.users"].browse(user_id).exists()
        if (
            len(user) != 1
            or not user.share
            or not user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        ):
            raise AccessError(
                _("This account cannot create portal daily entries.")
            )

        students = self.env["internship.student"].search(
            [("user_id", "=", user.id), ("active", "=", True)],
            limit=2,
        )
        if len(students) != 1:
            raise AccessError(
                _("A valid student profile is required.")
            )
        student = students

        eligible_programs = self.env["internship.program"].search([
            ("student_id", "=", student.id),
            ("workflow_mode", "=", "independent"),
            ("state", "=", "active"),
            ("active", "=", True),
        ], limit=2)
        program = eligible_programs.filtered(
            lambda candidate: candidate.id == program_id
        )
        if len(eligible_programs) != 1 or len(program) != 1:
            raise AccessError(
                _("Exactly one active independent internship is required.")
            )

        with self.env.cr.savepoint():
            self.env.cr.execute(
                "SELECT id FROM internship_program WHERE id = %s FOR UPDATE",
                [program.id],
            )
            if self.with_context(active_test=False).search_count([
                ("program_id", "=", program.id),
                ("entry_date", "=", prepared_values["entry_date"]),
            ], limit=1):
                raise UserError(
                    _("A daily entry already exists for this date.")
                )
            entry = self.create({
                "program_id": program.id,
                **prepared_values,
                "state": "draft",
            })
            if entry.student_id != student:
                raise AccessError(
                    _("The daily entry ownership could not be verified.")
                )
            return entry

    @api.model
    @api.private
    def _portal_update_draft_entry(self, user_id, entry_id, values):
        """Update one owned draft through a narrow portal-only service."""
        prepared_values = self._portal_prepare_daily_entry_values(values)

        user = self.env["res.users"].browse(user_id).exists()
        if (
            len(user) != 1
            or not user.share
            or not user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        ):
            raise AccessError(
                _("This account cannot edit portal daily entries.")
            )

        students = self.env["internship.student"].search(
            [("user_id", "=", user.id), ("active", "=", True)],
            limit=2,
        )
        if len(students) != 1:
            raise AccessError(_("A valid student profile is required."))
        student = students

        entry = self.with_context(active_test=False).search([
            ("id", "=", entry_id),
            ("student_id", "=", student.id),
            ("program_id.student_id", "=", student.id),
        ], limit=1)
        if not entry:
            raise AccessError(_("The daily entry could not be found."))

        program = entry.program_id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "SELECT id FROM internship_program "
                    "WHERE id = %s FOR UPDATE",
                    [program.id],
                )
                self.env.cr.execute(
                    "SELECT id FROM internship_daily_entry "
                    "WHERE id = %s FOR UPDATE",
                    [entry.id],
                )
                program.invalidate_recordset(["state", "active"])
                entry.invalidate_recordset()
                entry = self.with_context(active_test=False).search([
                    ("id", "=", entry_id),
                    ("student_id", "=", student.id),
                    ("program_id", "=", program.id),
                    ("program_id.student_id", "=", student.id),
                ], limit=1)
                if not entry:
                    raise AccessError(
                        _("The daily entry could not be found.")
                    )
                if (
                    entry.state != "draft"
                    or not entry.program_id.active
                    or entry.program_id.state != "active"
                ):
                    raise UserError(
                        _(
                            "Only draft entries in an active internship "
                            "can be edited."
                        )
                    )

                if self.with_context(active_test=False).search_count([
                    ("program_id", "=", program.id),
                    ("entry_date", "=", prepared_values["entry_date"]),
                    ("id", "!=", entry.id),
                ], limit=1):
                    raise UserError(
                        _("A daily entry already exists for this date.")
                    )

                entry.write(prepared_values)
                entry.invalidate_recordset()
                if (
                    entry.student_id != student
                    or entry.program_id != program
                    or entry.state != "draft"
                ):
                    raise AccessError(
                        _("The daily entry update could not be verified.")
                    )
                return entry
        except IntegrityError as error:
            if (
                error.diag.constraint_name
                != "internship_daily_entry_program_entry_date_unique"
            ):
                raise
            raise UserError(
                _("A daily entry already exists for this date.")
            ) from None

    @api.model
    @api.private
    def _portal_submit_draft_entry(self, user_id, entry_id):
        """Complete one owned Independent draft through its real workflow."""
        user = self.env["res.users"].browse(user_id).exists()
        if (
            len(user) != 1
            or not user.share
            or not user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        ):
            raise AccessError(
                _("This account cannot submit portal daily entries.")
            )

        students = self.env["internship.student"].search(
            [("user_id", "=", user.id), ("active", "=", True)],
            limit=2,
        )
        if len(students) != 1:
            raise AccessError(_("A valid student profile is required."))
        student = students

        entry = self.with_context(active_test=False).search([
            ("id", "=", entry_id),
            ("student_id", "=", student.id),
            ("program_id.student_id", "=", student.id),
        ], limit=1)
        if not entry:
            raise AccessError(_("The daily entry could not be found."))
        program = entry.program_id

        with self.env.cr.savepoint():
            self.env.cr.execute(
                "SELECT id FROM internship_program "
                "WHERE id = %s FOR UPDATE",
                [program.id],
            )
            self.env.cr.execute(
                "SELECT id FROM internship_daily_entry "
                "WHERE id = %s FOR UPDATE",
                [entry.id],
            )
            program.invalidate_recordset(
                ["active", "state", "workflow_mode", "student_id"]
            )
            entry.invalidate_recordset()
            entry = self.with_context(active_test=False).search([
                ("id", "=", entry_id),
                ("student_id", "=", student.id),
                ("program_id", "=", program.id),
                ("program_id.student_id", "=", student.id),
            ], limit=1)
            if not entry:
                raise AccessError(_("The daily entry could not be found."))
            if (
                entry.program_id != program
                or program.student_id != student
            ):
                raise AccessError(
                    _("The daily entry ownership could not be verified.")
                )
            if (
                not program.active
                or program.state != "active"
                or program.workflow_mode != "independent"
            ):
                raise UserError(
                    _(
                        "Daily entries can be submitted only while the "
                        "independent internship program is active."
                    )
                )
            if entry.state != "draft":
                raise UserError(
                    _(
                        "This daily entry is no longer available "
                        "for submission."
                    )
                )

            self._portal_prepare_daily_entry_values({
                "entry_date": entry.entry_date,
                "title": entry.title,
                "work_description": entry.work_description,
                "work_hours": entry.work_hours,
            })
            if (
                entry.entry_date < program.start_date
                or entry.entry_date > program.end_date
            ):
                raise ValidationError(
                    _(
                        "The daily entry date must be within the "
                        "internship period."
                    )
                )
            if self.with_context(active_test=False).search_count([
                ("program_id", "=", program.id),
                ("entry_date", "=", entry.entry_date),
                ("id", "!=", entry.id),
            ], limit=1):
                raise ValidationError(
                    _("A daily entry already exists for this date.")
                )

            entry.action_complete()
            entry.invalidate_recordset()
            if (
                entry.state != "completed"
                or entry.student_id != student
                or entry.program_id != program
            ):
                raise AccessError(
                    _("The daily entry submission could not be verified.")
                )
            return entry

    def _is_owning_intern(self, entry=None, program=None):
        target_program = program or entry.program_id
        return self.env.user.has_group(
            "internship_logbook.group_internship_intern"
        ) and target_program.student_id.user_id == self.env.user

    @api.private
    def _write_workflow_state(self, state):
        return super(InternshipDailyEntry, self).write({"state": state})

    def _check_independent_actor(self):
        self.check_access("write")
        if self._is_internship_manager():
            return
        if not self._is_owning_intern(entry=self):
            raise AccessError(
                "Only the owning intern or an internship manager can "
                "use the independent internship workflow."
            )

    def _workflow_activities(self, summary, user=None):
        activities = self.activity_ids.filtered(
            lambda activity: activity.summary == summary
        )
        if user:
            activities = activities.filtered(
                lambda activity: activity.user_id == user
            )
        return activities

    def _schedule_unique_workflow_activity(self, user, summary, note):
        self.ensure_one()
        if not user or self._workflow_activities(summary, user=user):
            return self.env["mail.activity"]
        return self.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=user.id,
            summary=summary,
            note=note,
        )

    def _complete_workflow_activities(self, summary, feedback, user=None):
        activities = self._workflow_activities(summary, user=user)
        if activities:
            activities.action_feedback(feedback=feedback)

    def _send_workflow_notification(self, template_xmlid):
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=False)

    def action_open_communication_center(self):
        self.ensure_one()
        self.check_access("read")
        self.env["internship.communication.service"]._check_operator()
        return {
            "type": "ir.actions.act_window",
            "name": _("Communication Center"),
            "res_model": "internship.communication.center.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": self._name,
                "active_id": self.id,
            },
        }

    @api.model
    def _find_pending_reviews(self, domain=None, limit=None):
        """Return caller-visible supervised entries awaiting review."""
        search_domain = [
            ("active", "=", True),
            ("workflow_mode", "=", "supervised"),
            ("program_state", "=", "active"),
            ("state", "=", "submitted"),
        ]
        if domain:
            search_domain.extend(domain)
        return self.search(
            search_domain,
            order="write_date asc, entry_date asc, id asc",
            limit=limit,
        )

    @api.model
    def _cron_manager_context_allowed(self):
        return not self.env.su and self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        )

    @api.model
    def _process_pending_review_reminders(
        self, domain=None, batch_limit=200
    ):
        stats = {
            "found": 0,
            "created": 0,
            "existing": 0,
            "skipped": 0,
            "failed": 0,
        }
        entries = self._find_pending_reviews(
            domain=domain, limit=batch_limit
        )
        stats["found"] = len(entries)
        for entry in entries:
            try:
                with self.env.cr.savepoint():
                    supervisor = entry.supervisor_id
                    if (
                        not supervisor
                        or not supervisor.active
                        or supervisor.share
                    ):
                        stats["skipped"] += 1
                        _logger.warning(
                            "Pending review reminder skipped: entry_id=%s "
                            "reason=no_internal_supervisor",
                            entry.id,
                        )
                        continue
                    entry.with_user(supervisor).check_access("read")
                    if entry._workflow_activities(
                        entry._review_activity_summary,
                        user=supervisor,
                    ):
                        stats["existing"] += 1
                        continue
                    entry._schedule_unique_workflow_activity(
                        supervisor,
                        entry._review_activity_summary,
                        _("Please review the submitted daily internship entry."),
                    )
                    stats["created"] += 1
            except (AccessError, UserError, ValidationError) as error:
                stats["skipped"] += 1
                _logger.warning(
                    "Pending review reminder skipped: entry_id=%s "
                    "error_type=%s",
                    entry.id,
                    type(error).__name__,
                )
            except Exception:
                stats["failed"] += 1
                _logger.exception(
                    "Pending review reminder failed: entry_id=%s",
                    entry.id,
                )
        return stats

    @api.model
    def _cron_remind_pending_reviews(self, batch_limit=200):
        if not self._cron_manager_context_allowed():
            stats = {
                "found": 0,
                "created": 0,
                "existing": 0,
                "skipped": 0,
                "failed": 1,
            }
            _logger.error(
                "Pending review reminders refused: cron user must be an "
                "internal Internship Manager and must not be superuser"
            )
            return stats
        stats = self._process_pending_review_reminders(
            batch_limit=batch_limit
        )
        _logger.info(
            "Pending review reminders: found=%s created=%s existing=%s "
            "skipped=%s failed=%s",
            stats["found"],
            stats["created"],
            stats["existing"],
            stats["skipped"],
            stats["failed"],
        )
        return stats

    def action_submit(self):
        if not self.env.user.has_group(
            "internship_logbook.group_internship_intern"
        ) and not self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        ):
            raise AccessError(
                "Only interns or managers can submit daily entries."
            )

        for entry in self:
            if entry.workflow_mode == "independent":
                raise UserError(
                    _("Independent daily entries cannot be submitted.")
                )
            if entry.state not in ("draft", "revision"):
                raise ValidationError(
                    "Only draft or revision-requested entries "
                    "can be submitted."
                )

            if entry.program_id.state != "active":
                raise ValidationError(
                    "Daily entries can only be submitted while "
                    "the internship program is active."
                )

            # Store the previous state before changing it
            previous_state = entry.state

            # Change state to submitted
            entry._write_workflow_state("submitted")

            # If this entry was previously in revision state,
            # close the intern's revision activity
            if previous_state == "revision":
                entry._complete_workflow_activities(
                    entry._revision_activity_summary,
                    _("Daily internship entry revised and resubmitted."),
                    user=entry.student_id.user_id,
                )

            # Post a message to chatter
            entry.message_post(
                body="Daily entry submitted for supervisor review."
            )

            # Schedule activity for supervisor
            if entry.supervisor_id:

                # Add supervisor as follower
                entry.message_subscribe(
                    partner_ids=[
                        entry.supervisor_id.partner_id.id
                    ]
                )

                entry._schedule_unique_workflow_activity(
                    entry.supervisor_id,
                    entry._review_activity_summary,
                    _("Please review the submitted daily internship entry."),
                )
                entry._send_workflow_notification(
                    "internship_logbook.mail_template_daily_entry_submitted",
                )

    def action_approve(self):
        self.ensure_one()
        self._lock_and_validate_supervised_review()
        self._validate_reviewable_content()

        self._write_workflow_state("approved")

        self._complete_supervisor_review_activities(
            "Daily internship entry reviewed and approved."
        )
        self.message_post(body=_("Daily internship entry approved."))
        self._send_workflow_notification(
            "internship_logbook.mail_template_daily_entry_approved"
        )
        if self.env.context.get("skip_review_navigation"):
            return False
        return self._action_open_next_review()


    def action_request_revision(self):
        self.ensure_one()
        self._lock_and_validate_supervised_review()
        comment = (self.supervisor_comment or "").strip()
        if not comment:
            raise ValidationError(
                _(
                    "Please enter a meaningful supervisor comment before "
                    "requesting a revision."
                )
            )
        if comment != self.supervisor_comment:
            self.write({"supervisor_comment": comment})

        self._write_workflow_state("revision")
        self.message_post(
            body="Revision requested by the internship supervisor."
        )
        self._complete_supervisor_review_activities(
            "Daily internship entry reviewed. Revision requested."
        )

        student_user = self.student_id.user_id
        if student_user:
            self._schedule_unique_workflow_activity(
                student_user,
                self._revision_activity_summary,
                _(
                    "Your supervisor requested a revision for this daily "
                    "internship entry."
                ),
            )
            self._send_workflow_notification(
                "internship_logbook.mail_template_daily_entry_revision",
            )
        if self.env.context.get("skip_review_navigation"):
            return False
        return self._action_open_next_review()

    def _bulk_review_notification(self, results, operation):
        success_label = (
            _("Approved")
            if operation == "approve"
            else _("Revision Requested")
        )
        labels = (
            ("success", success_label),
            ("rejected", _("Rejected")),
            ("approved", _("Already Approved")),
            ("revision", _("Already Revision Requested")),
            ("unauthorized", _("Unauthorized")),
            ("independent", _("Independent Workflow")),
            ("other", _("Other Errors")),
        )
        lines = []
        for key, label in labels:
            names = results[key]
            line = _("%(label)s: %(count)s", label=label, count=len(names))
            if names and key != "unauthorized":
                line += " — " + ", ".join(names[:5])
                if len(names) > 5:
                    line += _(" and %(count)s more", count=len(names) - 5)
            lines.append(line)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bulk Review Summary"),
                "message": "\n".join(lines),
                "type": "success" if results["success"] else "warning",
                "sticky": bool(
                    results["rejected"]
                    or results["unauthorized"]
                    or results["independent"]
                    or results["other"]
                ),
                "next": self.env["ir.actions.actions"]._for_xml_id(
                    "internship_logbook."
                    "action_internship_supervisor_review_queue"
                ),
            },
        }

    def _action_bulk_review(self, operation):
        if not self:
            raise UserError(_("Select at least one daily entry to review."))
        if not self._is_internship_manager() and not self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        ):
            raise AccessError(
                _("Only internship supervisors or managers can review entries.")
            )
        results = {
            key: []
            for key in (
                "success",
                "rejected",
                "approved",
                "revision",
                "unauthorized",
                "independent",
                "other",
            )
        }
        for entry in self.sorted("id"):
            try:
                entry.check_access("write")
                entry.invalidate_recordset(
                    ["state", "workflow_mode", "title"]
                )
                name = entry.display_name
                if entry.workflow_mode == "independent":
                    results["independent"].append(name)
                    continue
                if entry.state == "approved":
                    results["approved"].append(name)
                    continue
                if entry.state == "revision":
                    results["revision"].append(name)
                    continue
                if entry.state != "submitted":
                    results["rejected"].append(name)
                    continue
                try:
                    with self.env.cr.savepoint():
                        review_entry = entry.with_context(
                            skip_review_navigation=True
                        )
                        if operation == "approve":
                            review_entry.action_approve()
                        else:
                            review_entry.action_request_revision()
                except AccessError:
                    entry.invalidate_recordset()
                    results["unauthorized"].append(str(entry.id))
                except (UserError, ValidationError):
                    entry.invalidate_recordset()
                    results["rejected"].append(name)
                except Exception:
                    entry.invalidate_recordset()
                    _logger.exception(
                        "Unexpected bulk review error for daily entry id=%s",
                        entry.id,
                    )
                    results["other"].append(name)
                else:
                    results["success"].append(name)
            except AccessError:
                results["unauthorized"].append(str(entry.id))
        return self._bulk_review_notification(results, operation)

    def action_bulk_approve(self):
        return self._action_bulk_review("approve")

    def action_bulk_request_revision(self):
        return self._action_bulk_review("revision")

    def _lock_and_validate_supervised_review(self):
        """Lock and re-check one form review without bypassing access rules."""
        self.ensure_one()
        is_manager = self._is_internship_manager()
        is_supervisor = self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        )
        if not is_manager and not is_supervisor:
            raise AccessError(
                _(
                    "Only internship supervisors or managers can review "
                    "daily entries."
                )
            )
        self.check_access("write")
        self.env.cr.execute(
            "SELECT id FROM internship_daily_entry WHERE id = %s FOR UPDATE",
            [self.id],
        )
        if not self.env.cr.fetchone():
            raise AccessError(_("The daily entry is no longer available."))
        self.invalidate_recordset()
        if not self.active or not self.program_id.active:
            raise UserError(_("Only active daily entries can be reviewed."))
        if self.workflow_mode != "supervised":
            raise UserError(
                _("Independent daily entries cannot use supervisor review.")
            )
        if self.state != "submitted":
            raise UserError(
                _("This daily entry is no longer pending supervisor review.")
            )
        if self.program_id.state != "active":
            raise UserError(
                _("Daily entries can be reviewed only in an active program.")
            )
        if not is_manager and self.supervisor_id != self.env.user:
            raise AccessError(
                _("Supervisors can review only their assigned daily entries.")
            )
        if self.student_id != self.program_id.student_id:
            raise ValidationError(
                _("The daily entry and internship program do not match.")
            )

    def _validate_reviewable_content(self):
        self.ensure_one()
        if not (self.title or "").strip() or not (
            self.work_description or ""
        ).strip():
            raise ValidationError(
                _("The daily entry must contain a title and work description.")
            )
        if not math.isfinite(self.work_hours) or not 0 < self.work_hours <= 24:
            raise ValidationError(
                _("Work hours must be greater than zero and at most 24.")
            )
        program = self.program_id
        if (
            not self.entry_date
            or not program.start_date
            or not program.end_date
            or self.entry_date < program.start_date
            or self.entry_date > program.end_date
        ):
            raise ValidationError(
                _("The daily entry date must be within the internship period.")
            )

    def _complete_supervisor_review_activities(self, feedback):
        self.ensure_one()
        self._complete_workflow_activities(
            self._review_activity_summary,
            feedback,
            user=self.supervisor_id,
        )

    def _action_open_next_review(self):
        self.ensure_one()
        next_entry = self.search(
            [
                ("id", "!=", self.id),
                ("workflow_mode", "=", "supervised"),
                ("state", "=", "submitted"),
            ],
            order="write_date desc, entry_date desc, id desc",
            limit=1,
        )
        if next_entry:
            return {
                "type": "ir.actions.act_window",
                "name": _("Review Daily Entry"),
                "res_model": self._name,
                "res_id": next_entry.id,
                "view_mode": "form",
                "views": [(
                    self.env.ref(
                        "internship_logbook.view_internship_daily_entry_form"
                    ).id,
                    "form",
                )],
                "target": "current",
            }
        return self.env["ir.actions.actions"]._for_xml_id(
            "internship_logbook.action_internship_supervisor_review_queue"
        )

    def action_review_next(self):
        self.ensure_one()
        if not self._is_internship_manager() and not self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        ):
            raise AccessError(
                _("Only internship supervisors or managers can review entries.")
            )
        self.check_access("read")
        return self._action_open_next_review()

    def action_open_student(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Student"),
            "res_model": "internship.student",
            "res_id": self.student_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_program(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Internship Program"),
            "res_model": "internship.program",
            "res_id": self.program_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_reset_to_draft(self):
        for entry in self:
            if entry.workflow_mode == "independent":
                raise UserError(
                    _("Independent daily entries do not use the revision "
                      "reset workflow.")
                )
            if entry.state != "revision":
                raise ValidationError(
                    "Only revision-requested entries can be "
                    "reset to draft."
                )

            entry._write_workflow_state("draft")
            entry._complete_workflow_activities(
                entry._revision_activity_summary,
                _("Revision request reset to draft."),
                user=entry.student_id.user_id,
            )
            entry.message_post(
                body=_("Daily internship entry reset to draft."),
            )

    def action_complete(self):
        for entry in self:
            if entry.workflow_mode != "independent":
                raise UserError(
                    _("Only independent daily entries can be completed.")
                )
            entry._check_independent_actor()
            if entry.state != "draft":
                raise ValidationError(
                    _("Only draft independent daily entries can be completed.")
                )
            if entry.program_state != "active":
                raise ValidationError(
                    _("Independent daily entries can only be completed while "
                      "the internship program is active.")
                )
            entry._write_workflow_state("completed")
            entry.message_post(
                body=_("Independent daily entry marked as completed.")
            )

    def action_reopen(self):
        for entry in self:
            if entry.workflow_mode != "independent":
                raise UserError(
                    _("Only independent daily entries can be reopened.")
                )
            entry._check_independent_actor()
            if entry.state != "completed":
                raise ValidationError(
                    _("Only completed independent daily entries can be reopened.")
                )
            if entry.program_state != "active":
                raise ValidationError(
                    _("Independent daily entries can only be reopened while "
                      "the internship program is active.")
                )
            entry._write_workflow_state("draft")
            entry.message_post(
                body=_("Independent daily entry reopened for editing.")
            )

    def _action_open_ai_assistant(self, action_type):
        self.ensure_one()
        return self.env["internship.ai.assistant.wizard"].open_for_entry(
            self,
            action_type,
        )

    def action_ai_improve_writing(self):
        return self._action_open_ai_assistant("improve")

    def action_ai_give_suggestions(self):
        return self._action_open_ai_assistant("suggestions")

    def action_ai_find_missing_details(self):
        return self._action_open_ai_assistant("missing_details")

    def action_ai_revision_assistant(self):
        return self._action_open_ai_assistant("revision")

    def action_ai_improve_learned_topics(self):
        return self._action_open_ai_assistant("improve_learned_topics")

    def action_ai_improve_challenges(self):
        return self._action_open_ai_assistant("improve_challenges")
