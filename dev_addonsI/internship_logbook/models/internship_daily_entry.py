from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

class InternshipDailyEntry(models.Model):
    _name = "internship.daily.entry"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]
    _description = "Internship Daily Entry"
    _order = "entry_date desc, id desc"

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
            entry.state = "submitted"

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
            if entry.state != "submitted":
                raise ValidationError(
                    "Only submitted entries can be approved."
                )

            entry.state = "approved"

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
            if entry.state != "submitted":
                raise ValidationError(
                    "A revision can only be requested for "
                    "a submitted entry."
                )

            entry.state = "revision"

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
            if entry.state != "revision":
                raise ValidationError(
                    "Only revision-requested entries can be "
                    "reset to draft."
                )

            entry.state = "draft"

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
