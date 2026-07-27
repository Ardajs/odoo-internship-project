import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


class InternshipCommunicationCenterWizard(models.TransientModel):
    _name = "internship.communication.center.wizard"
    _description = "Internship Communication Center"

    communication_type = fields.Selection(
        selection=[
            ("entry_submitted", "Daily Entry Submitted"),
            ("revision_requested", "Revision Requested"),
            ("entry_approved", "Daily Entry Approved"),
            ("pending_review", "Pending Review Reminder"),
            ("missing_entries", "Missing Daily Entry Reminder"),
            ("program_ending", "Program Ending Soon Reminder"),
        ],
        required=True,
    )
    res_model = fields.Selection(
        selection=[
            ("internship.daily.entry", "Daily Entry"),
            ("internship.program", "Internship Program"),
        ],
        required=True,
        readonly=True,
    )
    res_id = fields.Integer(required=True, readonly=True)
    recipient_name = fields.Char(readonly=True)
    recipient_email = fields.Char(readonly=True)
    subject_preview = fields.Char(readonly=True)
    body_preview = fields.Html(readonly=True, sanitize=True)
    history_preview = fields.Html(readonly=True, sanitize=True)
    last_communication_date = fields.Datetime(readonly=True)
    delivery_state = fields.Selection(
        selection=[
            ("not_sent", "Not Sent"),
            ("outgoing", "Queued"),
            ("sent", "Sent by Odoo"),
            ("exception", "Delivery Failed"),
            ("cancel", "Cancelled"),
            ("received", "Received"),
        ],
        readonly=True,
    )
    already_sent = fields.Boolean(readonly=True)
    preview_error = fields.Char(readonly=True)
    can_send = fields.Boolean(readonly=True)

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        model_name = self.env.context.get("active_model")
        record_id = self.env.context.get("active_id")
        if model_name not in {"internship.daily.entry", "internship.program"}:
            raise UserError(_("Open the Communication Center from a supported record."))
        values.update({"res_model": model_name, "res_id": record_id})
        return values

    def _refresh_preview(self, raise_on_error=False):
        self.ensure_one()
        self.update({
            "recipient_name": False,
            "recipient_email": False,
            "subject_preview": False,
            "body_preview": False,
            "history_preview": False,
            "last_communication_date": False,
            "delivery_state": "not_sent",
            "already_sent": False,
            "preview_error": False,
            "can_send": False,
        })
        if not self.communication_type:
            return
        try:
            values = self.env["internship.communication.service"].prepare(
                self.communication_type, self.res_model, self.res_id
            )
        except (AccessError, UserError, ValidationError) as error:
            if raise_on_error:
                raise
            self.preview_error = str(error)
            return
        self.update({
            "recipient_name": values["recipient"].name,
            "recipient_email": values["recipient"].email,
            "subject_preview": values["subject"],
            "body_preview": values["body"],
            "history_preview": values["history"],
            "last_communication_date": values["last_communication_date"],
            "delivery_state": values["delivery_state"],
            "already_sent": values["already_sent"],
            "can_send": True,
        })

    @api.onchange("communication_type")
    def _onchange_communication_type(self):
        self._refresh_preview()

    def action_refresh_preview(self):
        self._refresh_preview(raise_on_error=True)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _send(self, allow_resend=False):
        self.ensure_one()
        self.env["internship.communication.service"].send(
            self.communication_type,
            self.res_model,
            self.res_id,
            allow_resend=allow_resend,
        )
        return {"type": "ir.actions.act_window_close"}

    def action_send(self):
        return self._send(allow_resend=False)

    def action_send_again(self):
        return self._send(allow_resend=True)
