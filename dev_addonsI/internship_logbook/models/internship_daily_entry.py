import math

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

class InternshipDailyEntry(models.Model):
    _name = "internship.daily.entry"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]
    _description = "Internship Daily Entry"
    _order = "entry_date desc, id desc"
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
                revision_activities = entry.activity_ids.filtered(
                    lambda activity:
                        activity.user_id == self.env.user
                        and activity.summary == "Revise Daily Internship Entry"
                )

                if revision_activities:
                    revision_activities.action_feedback(
                        feedback=(
                            "Daily internship entry revised and resubmitted."
                        )
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

                # Create review activity for supervisor
                entry.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=entry.supervisor_id.id,
                    summary="Review Daily Internship Entry",
                    note=(
                        "Please review the submitted daily internship entry."
                    ),
                )

                template = self.env.ref(
                    "internship_logbook.mail_template_daily_entry_submitted",
                    raise_if_not_found=False,
                )

                if template:
                    template.send_mail(
                        entry.id,
                        force_send=False,
                    )

    def action_approve(self):
        if not self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        ) and not self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        ):
            raise AccessError(
                "Only internship supervisors or managers "
                "can approve daily entries."
            )

        for entry in self:
            if entry.workflow_mode == "independent":
                raise UserError(
                    _("Independent daily entries cannot be approved.")
                )
            if entry.state != "submitted":
                raise ValidationError(
                    "Only submitted entries can be approved."
                )

            entry._write_workflow_state("approved")

            template = self.env.ref(
                "internship_logbook.mail_template_daily_entry_approved",
                raise_if_not_found=False,
            )

            if template:
                template.send_mail(
                    entry.id,
                    force_send=False,
                )

            # Add message to Chatter
            entry.message_post(
                body="Daily internship entry approved."
            )

            # Complete supervisor's review activity
            activities = entry.activity_ids.filtered(
                lambda activity:
                    activity.user_id == self.env.user
                    and activity.summary == "Review Daily Internship Entry"
            )

            if activities:
                activities.action_feedback(
                    feedback="Daily internship entry reviewed and approved."
                )


    def action_request_revision(self):
        if not self.env.user.has_group(
            "internship_logbook.group_internship_supervisor"
        ) and not self.env.user.has_group(
            "internship_logbook.group_internship_manager"
        ):
            raise AccessError(
                "Only internship supervisors or managers "
                "can request a revision."
            )

        for entry in self:
            if entry.workflow_mode == "independent":
                raise UserError(
                    _("Revisions cannot be requested for independent "
                      "daily entries.")
                )
            if entry.state != "submitted":
                raise ValidationError(
                    "A revision can only be requested for "
                    "a submitted entry."
                )

            entry._write_workflow_state("revision")

            entry.message_post(
                body=(
                    "Revision requested by the internship supervisor."
                )
            )


        activities = entry.activity_ids.filtered(
            lambda activity:
                activity.user_id == self.env.user
                and activity.summary == "Review Daily Internship Entry"
        )


        if not entry.supervisor_comment:
            raise ValidationError(
                "Please enter a supervisor comment before requesting a revision."
            )

        if activities:
            activities.action_feedback(
                feedback="Daily internship entry reviewed. Revision requested."
            )

        student_user = entry.student_id.user_id

        if student_user:
            entry.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=student_user.id,
                summary="Revise Daily Internship Entry",
                note=(
                    "Your supervisor requested a revision "
                    "for this daily internship entry."
                ),
            )

            template = self.env.ref(
                "internship_logbook.mail_template_daily_entry_revision",
                raise_if_not_found=False,
            )

            if template:
                template.send_mail(
                    entry.id,
                    force_send=False,
                )

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
