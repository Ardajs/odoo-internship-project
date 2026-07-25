import logging

from markupsafe import Markup, escape

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


class InternshipCommunicationService(models.AbstractModel):
    _name = "internship.communication.service"
    _description = "Internship Communication Service"

    _specifications = {
        "entry_submitted": {
            "label": "Daily Entry Submitted",
            "model": "internship.daily.entry",
            "template": "internship_logbook.mail_template_daily_entry_submitted",
            "subtype": "internship_logbook.mt_communication_entry_submitted",
        },
        "revision_requested": {
            "label": "Revision Requested",
            "model": "internship.daily.entry",
            "template": "internship_logbook.mail_template_daily_entry_revision",
            "subtype": "internship_logbook.mt_communication_revision_requested",
        },
        "entry_approved": {
            "label": "Daily Entry Approved",
            "model": "internship.daily.entry",
            "template": "internship_logbook.mail_template_daily_entry_approved",
            "subtype": "internship_logbook.mt_communication_entry_approved",
        },
        "pending_review": {
            "label": "Pending Review Reminder",
            "model": "internship.daily.entry",
            "template": "internship_logbook.mail_template_pending_review_reminder",
            "subtype": "internship_logbook.mt_communication_pending_review",
        },
        "missing_entries": {
            "label": "Missing Daily Entry Reminder",
            "model": "internship.program",
            "template": "internship_logbook.mail_template_missing_entries_reminder",
            "subtype": "internship_logbook.mt_communication_missing_entries",
        },
        "program_ending": {
            "label": "Program Ending Soon Reminder",
            "model": "internship.program",
            "template": "internship_logbook.mail_template_program_ending_reminder",
            "subtype": "internship_logbook.mt_communication_program_ending",
        },
    }

    @api.model
    def _check_operator(self):
        if not (
            self.env.user.has_group(
                "internship_logbook.group_internship_supervisor"
            )
            or self.env.user.has_group(
                "internship_logbook.group_internship_manager"
            )
        ):
            raise AccessError(_("You cannot use the Communication Center."))

    @api.model
    def _specification(self, category):
        specification = self._specifications.get(category)
        if not specification:
            raise ValidationError(_("Unsupported communication type."))
        return specification

    @api.model
    def _record(self, category, model_name, record_id):
        self._check_operator()
        specification = self._specification(category)
        if model_name != specification["model"]:
            raise ValidationError(_("Invalid communication record type."))
        record = self.env[model_name].browse(int(record_id)).exists()
        if not record or len(record) != 1:
            raise AccessError(_("The communication record is unavailable."))
        record.check_access("read")
        return record, specification

    @api.model
    def _recipient_user(self, category, record):
        if category in {"entry_submitted", "pending_review"}:
            return record.supervisor_id
        if category in {"revision_requested", "entry_approved"}:
            return record.student_id.user_id
        if category == "missing_entries":
            return record._missing_entry_reminder_assignee()
        if category == "program_ending":
            return record._ending_soon_reminder_assignee()
        return self.env["res.users"]

    @api.model
    def _validate_semantics(self, category, record):
        if category in {"entry_submitted", "pending_review"}:
            valid = (
                record.active
                and record.workflow_mode == "supervised"
                and record.program_state == "active"
                and record.state == "submitted"
            )
        elif category == "revision_requested":
            valid = (
                record.active
                and record.workflow_mode == "supervised"
                and record.state == "revision"
            )
        elif category == "entry_approved":
            valid = (
                record.active
                and record.workflow_mode == "supervised"
                and record.state == "approved"
            )
        elif category == "missing_entries":
            valid = (
                record.active
                and record.workflow_mode == "supervised"
                and record.state == "active"
                and bool(record._missing_day_counts().get(record.id))
            )
        elif category == "program_ending":
            eligible = self.env["internship.program"]._find_programs_ending_soon(
                days=7, domain=[("id", "=", record.id)]
            )
            valid = record in eligible
        else:
            valid = False
        if not valid:
            raise ValidationError(
                _("This communication is not valid for the current record state.")
            )

    @api.model
    def _template(self, specification, record):
        template = self.env.ref(
            specification["template"], raise_if_not_found=False
        )
        if not template or template.model != record._name:
            raise ValidationError(_("The approved communication template is unavailable."))
        template.check_access("read")
        return template

    @api.model
    @api.model
    def _related_messages(self, category, record, limit=20):
        specification = self._specification(category)
        subtype = self.env.ref(specification["subtype"])
        return self.env["mail.message"].search(
            [
                ("model", "=", record._name),
                ("res_id", "=", record.id),
                ("subtype_id", "=", subtype.id),
            ],
            order="date desc, id desc",
            limit=limit,
        )

    @api.model
    def _render_history(self, messages, recipient):
        if not messages:
            return Markup("<p class='text-muted'>%s</p>") % escape(
                _("No manual communication has been queued.")
            )
        rows = []
        for message in messages:
            rows.append(
                Markup("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>")
                % (
                    escape(message.date or ""),
                    escape(message.subject or ""),
                    escape(recipient.email or ""),
                    escape(_("Queued by Odoo")),
                )
            )
        return Markup(
            "<table class='table table-sm'><thead><tr>"
            "<th>Date</th><th>Subject</th><th>Recipient</th><th>Status</th>"
            "</tr></thead><tbody>%s</tbody></table>"
        ) % Markup("".join(str(row) for row in rows))

    @api.model
    def prepare(self, category, model_name, record_id):
        record, specification = self._record(category, model_name, record_id)
        self._validate_semantics(category, record)
        recipient = self._recipient_user(category, record)
        if not recipient or not recipient.active:
            raise ValidationError(_("No active related recipient could be resolved."))
        if not recipient.email:
            raise ValidationError(_("The intended recipient does not have an email address."))
        template = self._template(specification, record)
        try:
            subject = template._render_field("subject", [record.id])[record.id]
            body = template._render_field("body_html", [record.id])[record.id]
        except Exception as error:
            _logger.exception(
                "Communication preview rendering failed: category=%s model=%s record_id=%s error_type=%s",
                category,
                record._name,
                record.id,
                type(error).__name__,
            )
            raise UserError(
                _("The communication preview could not be rendered.")
            ) from error
        messages = self._related_messages(category, record)
        return {
            "record": record,
            "category_label": _(specification["label"]),
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "history": self._render_history(messages, recipient),
            "already_sent": bool(messages),
            "last_communication_date": messages[:1].date,
            "delivery_state": "outgoing" if messages else "not_sent",
        }

    @api.model
    def send(self, category, model_name, record_id, allow_resend=False):
        values = self.prepare(category, model_name, record_id)
        record = values["record"]
        specification = self._specification(category)
        existing = self._related_messages(category, record, limit=1)
        if existing and not allow_resend:
            raise UserError(
                _("This communication was already queued. Use Send Again to resend it explicitly.")
            )
        template = self._template(specification, record)
        subtype = self.env.ref(specification["subtype"])
        recipient = values["recipient"]
        return template.send_mail(
            record.id,
            force_send=False,
            raise_exception=True,
            email_values={
                "email_to": recipient.email,
                "recipient_ids": [(6, 0, [recipient.partner_id.id])],
                "subtype_id": subtype.id,
            },
        )
