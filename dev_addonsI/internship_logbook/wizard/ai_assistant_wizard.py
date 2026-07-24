from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.ai_provider import AIProviderService


class InternshipAIAssistantWizard(models.TransientModel):
    _name = "internship.ai.assistant.wizard"
    _description = "Internship AI Writing Assistant"

    _ACTION_TARGET_FIELDS = {
        "improve": "work_description",
        "suggestions": "work_description",
        "missing_details": "work_description",
        "revision": "work_description",
        "improve_learned_topics": "learned_topics",
        "improve_challenges": "challenges",
    }

    entry_id = fields.Many2one(
        comodel_name="internship.daily.entry",
        string="Entry",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    action_type = fields.Selection(
        selection=[
            ("improve", "Improve Writing"),
            ("suggestions", "Give Suggestions"),
            ("missing_details", "Find Missing Details"),
            ("revision", "Revision Assistant"),
            ("improve_learned_topics", "Improve What I Learned"),
            ("improve_challenges", "Improve Problems and Solutions"),
        ],
        string="Action Type",
        required=True,
        readonly=True,
    )
    target_field = fields.Selection(
        selection=[
            ("work_description", "Work Description"),
            ("learned_topics", "What I Learned"),
            ("challenges", "Problems and Solutions"),
        ],
        string="Target Field",
        required=True,
        readonly=True,
        default="work_description",
    )
    original_text = fields.Text(
        string="Original Text",
        required=True,
        readonly=True,
    )
    supervisor_comment = fields.Text(
        string="Supervisor Revision Comment",
        readonly=True,
    )
    suggested_text = fields.Text(
        string="AI Suggested Text",
        readonly=True,
    )
    feedback = fields.Text(
        string="AI Feedback / Explanation",
        readonly=True,
    )
    warnings = fields.Text(
        string="AI Warnings",
        readonly=True,
    )

    @api.private
    def open_for_entry(self, entry, action_type):
        entry.ensure_one()
        self._validate_entry_access(entry, "read")
        self._validate_action_state(entry, action_type)

        result = self._generate(entry, action_type)
        wizard = self.create(
            self._prepare_wizard_values(entry, action_type, result)
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Writing Assistant"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_regenerate(self):
        self.ensure_one()
        entry = self.entry_id
        self._validate_entry_access(entry, "read")
        self._validate_action_state(entry, self.action_type)
        result = self._generate(
            entry,
            self.action_type,
            response_variant="regenerated",
        )
        values = self._prepare_wizard_values(entry, self.action_type, result)
        values.pop("entry_id", None)
        values.pop("action_type", None)
        values.pop("target_field", None)
        self.write(values)
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Writing Assistant"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_apply_suggestion(self):
        self.ensure_one()
        if self.action_type not in (
            "improve",
            "revision",
            "improve_learned_topics",
            "improve_challenges",
        ):
            raise ValidationError(
                _("This AI action provides feedback only and cannot be applied.")
            )
        if not (self.suggested_text or "").strip():
            raise ValidationError(_("There is no AI suggestion to apply."))

        entry = self.entry_id
        self._validate_entry_access(entry, "write")
        self._validate_action_state(entry, self.action_type)
        target_field = self._target_field_for_action(self.action_type)
        if self.target_field != target_field:
            raise ValidationError(_("The AI Assistant target field is invalid."))
        if (entry[target_field] or "") != self.original_text:
            raise UserError(
                _(
                    "The daily entry changed after this suggestion was generated. "
                    "Regenerate the suggestion before applying it."
                )
            )

        entry.write({target_field: self.suggested_text.strip()})
        entry.message_post(
            body=(
                _("Daily entry text was updated using an AI-assisted suggestion.")
                if target_field == "work_description"
                else _(
                    "Daily entry field was updated using an AI-assisted suggestion."
                )
            )
        )
        return {"type": "ir.actions.act_window_close"}

    def _generate(self, entry, action_type, response_variant="initial"):
        target_field = self._target_field_for_action(action_type)
        return AIProviderService(self.env).generate(
            action_type=action_type,
            title=entry.title,
            original_text=entry[target_field] or "",
            revision_comment=(
                entry.supervisor_comment if action_type == "revision" else None
            ),
            response_variant=response_variant,
            work_description=(
                entry.work_description
                if target_field != "work_description"
                else None
            ),
        )

    def _prepare_wizard_values(self, entry, action_type, result):
        target_field = self._target_field_for_action(action_type)
        return {
            "entry_id": entry.id,
            "action_type": action_type,
            "target_field": target_field,
            "original_text": entry[target_field] or "",
            "supervisor_comment": (
                entry.supervisor_comment if action_type == "revision" else False
            ),
            "suggested_text": result["suggested_text"] or False,
            "feedback": result["feedback"] or False,
            "warnings": "\n".join(
                f"- {warning}" for warning in result.get("warnings", [])
            ) or False,
        }

    def _validate_entry_access(self, entry, operation):
        entry.check_access(operation)
        user = self.env.user
        is_manager = user.has_group(
            "internship_logbook.group_internship_manager"
        )
        is_owning_intern = user.has_group(
            "internship_logbook.group_internship_intern"
        ) and entry.student_id.user_id == user
        if not (is_manager or is_owning_intern):
            raise AccessError(
                _("You are not allowed to use AI Assistant on this daily entry.")
            )

    def _validate_action_state(self, entry, action_type):
        if action_type not in dict(self._fields["action_type"].selection):
            raise ValidationError(_("Unsupported AI Assistant action."))
        if entry.program_id.workflow_mode == "independent":
            if entry.state != "draft":
                raise ValidationError(
                    _("AI suggestions can only be used on draft independent entries.")
                )
            if action_type == "revision":
                raise ValidationError(
                    _("Revision Assistant is not available for independent internships.")
                )
            return
        if entry.state not in ("draft", "revision"):
            raise ValidationError(
                _("AI suggestions can only be used on draft or revision-requested entries.")
            )
        if action_type == "revision":
            if entry.state != "revision":
                raise ValidationError(
                    _("Revision Assistant is only available when a revision is requested.")
                )
            if not (entry.supervisor_comment or "").strip():
                raise ValidationError(
                    _("A supervisor revision comment is required for Revision Assistant.")
                )

    def _target_field_for_action(self, action_type):
        target_field = self._ACTION_TARGET_FIELDS.get(action_type)
        if not target_field:
            raise ValidationError(_("Unsupported AI Assistant action."))
        return target_field
