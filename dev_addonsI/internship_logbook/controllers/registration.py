import logging

from werkzeug.exceptions import NotFound

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)


class InternshipSelfRegistrationController(http.Controller):
    @http.route(
        "/internship/register",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        sitemap=True,
    )
    def registration_form(self, **_ignored):
        return request.render(
            "internship_logbook.self_registration_form",
            {"name": "", "email": ""},
        )

    @http.route(
        "/internship/register",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        captcha="signup",
        sitemap=False,
    )
    def registration_submit(self, **post):
        # Explicit allowlist: no submitted ORM/security value is forwarded.
        name = post.get("name")
        email = post.get("email")
        try:
            request.env[
                "internship.self.registration"
            ].sudo()._submit_registration(
                name,
                email,
            )
        except (UserError, ValidationError) as error:
            return request.render(
                "internship_logbook.self_registration_form",
                {
                    "name": (name or "").strip(),
                    "email": (email or "").strip(),
                    "error": error.args[0],
                },
            )
        return request.redirect("/internship/register/sent", code=303)

    @http.route(
        "/internship/register/sent",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def registration_sent(self, **_ignored):
        return request.render(
            "internship_logbook.self_registration_sent",
        )

    @http.route(
        "/internship/verify/<string:selector>",
        type="http",
        auth="public",
        website=True,
        methods=["GET"],
        sitemap=False,
    )
    def verification_form(self, selector, **_ignored):
        if not selector or len(selector) > 128:
            raise NotFound()
        return request.render(
            "internship_logbook.self_registration_verify",
            {"selector": selector},
        )

    @http.route(
        "/internship/verify",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def verification_submit(self, **post):
        selector = post.get("selector")
        secret = post.get("secret")
        password = post.get("password")
        password_confirmation = post.get("password_confirmation")
        try:
            user, _student = (
                request.env["internship.self.registration"]
                .sudo()
                ._verify(
                    selector,
                    secret,
                    password,
                    password_confirmation,
                )
            )
            # Authentication requires the newly committed credentials. This is
            # the only fixed post-verification destination.
            request.env.cr.commit()
            credential = {
                "login": user.login,
                "password": password,
                "type": "password",
            }
            request.session.authenticate(request.env, credential)
            return request.redirect("/my/internship", code=303)
        except (UserError, ValidationError) as error:
            return request.render(
                "internship_logbook.self_registration_verify",
                {
                    "selector": selector,
                    "error": error.args[0],
                },
            )
        except Exception:
            # Do not expose credentials, raw tokens, or internal exceptions.
            _logger.exception(
                "Internship self-registration verification failed"
            )
            return request.render(
                "internship_logbook.self_registration_verify",
                {
                    "selector": selector,
                    "error": _(
                        "The account could not be activated. "
                        "Please request a new verification email."
                    ),
                },
            )

    @http.route(
        "/internship/register/resend",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def registration_resend(self, **post):
        email = post.get("email")
        try:
            request.env["internship.self.registration"].sudo()._resend(email)
        except (UserError, ValidationError):
            # Deliberately indistinguishable from a successful resend.
            pass
        return request.redirect("/internship/register/sent", code=303)
