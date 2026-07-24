import hashlib
import hmac
import secrets
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_normalize


class InternshipSelfRegistration(models.Model):
    _name = "internship.self.registration"
    _description = "Internship Self Registration"
    _order = "create_date desc, id desc"

    _email_unique = models.Constraint(
        "UNIQUE(email_normalized)",
        "A registration already exists for this email address.",
    )
    _selector_unique = models.Constraint(
        "UNIQUE(token_selector)",
        "The verification token selector must be unique.",
    )
    _user_unique = models.Constraint(
        "UNIQUE(user_id)",
        "A user can be linked to only one registration.",
    )
    _student_unique = models.Constraint(
        "UNIQUE(student_id)",
        "A student can be linked to only one registration.",
    )

    name = fields.Char(required=True)
    email = fields.Char(required=True)
    email_normalized = fields.Char(required=True, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("verified", "Verified"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    token_selector = fields.Char(index=True, copy=False)
    token_digest = fields.Char(copy=False, groups="base.group_system")
    token_expires_at = fields.Datetime(copy=False)
    verified_at = fields.Datetime(copy=False)
    user_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    student_id = fields.Many2one(
        "internship.student",
        readonly=True,
        ondelete="restrict",
    )
    last_email_sent_at = fields.Datetime(copy=False)
    verification_attempt_count = fields.Integer(default=0, copy=False)
    active = fields.Boolean(default=True)

    _TOKEN_LIFETIME = timedelta(hours=24)
    _RESEND_COOLDOWN = timedelta(minutes=2)
    _MAX_ATTEMPTS = 5

    @api.model
    def _normalize_email(self, value):
        value = (value or "").strip()
        normalized = email_normalize(value)
        if not normalized:
            raise ValidationError(_("Please enter a valid email address."))
        return normalized.lower()

    @api.constrains("email", "email_normalized")
    def _check_normalized_email(self):
        for registration in self:
            if (
                registration.email_normalized
                != registration._normalize_email(registration.email)
            ):
                raise ValidationError(
                    _("The normalized email does not match the email address.")
                )

    @api.model
    def _email_lock(self, normalized):
        lock_value = int.from_bytes(
            hashlib.sha256(normalized.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_value])

    @api.model
    def _new_token(self):
        selector = secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return selector, secret, digest

    def _rotate_token(self):
        self.ensure_one()
        selector, secret, digest = self._new_token()
        self.write({
            "state": "pending",
            "token_selector": selector,
            "token_digest": digest,
            "token_expires_at": fields.Datetime.now() + self._TOKEN_LIFETIME,
            "verification_attempt_count": 0,
        })
        return secret

    @api.model
    def _account_already_exists(self, normalized):
        users = self.env["res.users"].with_context(active_test=False)
        if users.search_count(
            ["|", ("login", "=ilike", normalized), ("email", "=ilike", normalized)],
            limit=1,
        ):
            return True
        if self.env["internship.student"].with_context(active_test=False).search_count(
            [("email", "=ilike", normalized)],
            limit=1,
        ):
            return True
        partners = self.env["res.partner"].with_context(active_test=False).search(
            [("email", "=ilike", normalized)],
            limit=1,
        )
        return bool(partners.user_ids)

    @api.model
    @api.private
    def _submit_registration(self, name, email):
        """Create/refresh a pending request; never expose account existence."""
        name = (name or "").strip()
        if not name:
            raise ValidationError(_("Please enter your full name."))
        normalized = self._normalize_email(email)
        self._email_lock(normalized)

        if self._account_already_exists(normalized):
            return {"status": "accepted"}

        registration = self.search(
            [("email_normalized", "=", normalized)],
            limit=1,
        )
        now = fields.Datetime.now()
        if (
            registration
            and registration.last_email_sent_at
            and registration.last_email_sent_at + self._RESEND_COOLDOWN > now
        ):
            return {"status": "cooldown"}

        if not registration:
            registration = self.create({
                "name": name,
                "email": normalized,
                "email_normalized": normalized,
            })
        elif registration.state == "verified":
            return {"status": "accepted"}
        else:
            registration.write({"name": name, "email": normalized, "active": True})

        secret = registration._rotate_token()
        registration._send_verification_email(secret)
        registration.last_email_sent_at = now
        return {"status": "sent"}

    def _send_verification_email(self, secret):
        self.ensure_one()
        template = self.env.ref(
            "internship_logbook.mail_template_self_registration_verify",
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_("The verification email could not be prepared."))
        base_url = self.get_base_url().rstrip("/")
        verification_url = (
            f"{base_url}/internship/verify/{self.token_selector}"
            f"#token={secret}"
        )
        # The queued mail briefly contains the delivery URL. auto_delete on the
        # template minimizes persistence; access remains restricted to mail admins.
        template.with_context(verification_url=verification_url).send_mail(
            self.id,
            force_send=False,
            email_values={"email_to": self.email},
        )

    @api.model
    @api.private
    def _resend(self, email):
        normalized = self._normalize_email(email)
        self._email_lock(normalized)
        registration = self.search(
            [("email_normalized", "=", normalized)],
            limit=1,
        )
        if not registration or registration.state == "verified":
            return {"status": "accepted"}
        return self._submit_registration(registration.name, normalized)

    @api.model
    def _verification_row(self, selector):
        selector = (selector or "").strip()
        if not selector:
            raise UserError(_("The verification link is invalid or expired."))
        registration = self.search([("token_selector", "=", selector)], limit=1)
        if not registration:
            raise UserError(_("The verification link is invalid or expired."))
        self.env.cr.execute(
            "SELECT id FROM internship_self_registration "
            "WHERE id = %s FOR UPDATE",
            [registration.id],
        )
        registration.invalidate_recordset()
        return registration

    def _register_failed_attempt(self):
        self.ensure_one()
        attempts = self.verification_attempt_count + 1
        values = {"verification_attempt_count": attempts}
        if attempts >= self._MAX_ATTEMPTS:
            values.update({
                "state": "expired",
                "token_digest": False,
                "token_expires_at": False,
            })
        self.write(values)

    @api.model
    @api.private
    def _verify(self, selector, secret, password, password_confirmation):
        if not secret or not password:
            raise UserError(_("The verification link is invalid or expired."))
        if password != password_confirmation:
            raise UserError(_("Passwords do not match."))

        registration = self._verification_row(selector)
        if (
            registration.state != "pending"
            or not registration.token_digest
            or not registration.token_expires_at
        ):
            raise UserError(_("The verification link is invalid or expired."))
        if registration.token_expires_at <= fields.Datetime.now():
            registration.write({
                "state": "expired",
                "token_digest": False,
                "token_expires_at": False,
            })
            raise UserError(_("The verification link is invalid or expired."))

        supplied_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(
            supplied_digest,
            registration.token_digest,
        ):
            registration._register_failed_attempt()
            raise UserError(_("The verification link is invalid or expired."))

        if self._account_already_exists(registration.email_normalized):
            raise UserError(_("This account cannot be activated."))

        # The controller deliberately catches safe errors so failed-attempt
        # counters can be committed by the request transaction. Keep only the
        # successful provisioning steps in a savepoint so a later failure
        # cannot leave a user or student without a verified registration.
        with self.env.cr.savepoint():
            portal_group = self.env.ref(
                "internship_logbook.group_internship_portal_intern"
            )
            user = self.env["res.users"].with_context(
                no_reset_password=True,
            ).create({
                "name": registration.name,
                "login": registration.email_normalized,
                "email": registration.email_normalized,
                "password": password,
                "group_ids": [Command.set([portal_group.id])],
                "active": True,
            })
            student = self.env["internship.student"].create({
                "name": registration.name,
                "email": registration.email_normalized,
                "user_id": user.id,
            })
            registration.write({
                "state": "verified",
                "token_digest": False,
                "token_expires_at": False,
                "verified_at": fields.Datetime.now(),
                "user_id": user.id,
                "student_id": student.id,
            })
        return user, student
