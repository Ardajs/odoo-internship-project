from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from psycopg2 import IntegrityError

from odoo import Command, fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import HttpCase, TransactionCase

from ..models.self_registration import InternshipSelfRegistration
from ..models.internship_student import InternshipStudent


@tagged("post_install", "-at_install")
class TestInternshipSelfRegistration(TransactionCase):
    TEST_PASSWORD = "Local-test-passphrase-2026!"

    def setUp(self):
        super().setUp()
        self.Registration = self.env[
            "internship.self.registration"
        ].sudo()
        self.email = f"registration-{self._testMethodName}@example.test"

    def _pending(self, email=None, name="Portal Intern"):
        normalized = self.Registration._normalize_email(email or self.email)
        selector, secret, digest = self.Registration._new_token()
        registration = self.Registration.create({
            "name": name,
            "email": normalized,
            "email_normalized": normalized,
            "token_selector": selector,
            "token_digest": digest,
            "token_expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        return registration, secret

    def _verify(self, registration, secret):
        return self.Registration._verify(
            registration.token_selector,
            secret,
            self.TEST_PASSWORD,
            self.TEST_PASSWORD,
        )

    def test_email_normalization_and_validation(self):
        self.assertEqual(
            self.Registration._normalize_email("  Mixed.Case@Example.TEST "),
            "mixed.case@example.test",
        )
        with self.assertRaises(ValidationError):
            self.Registration._normalize_email("not-an-email")
        self.assertNotIn(
            "password",
            self.Registration._fields,
            "The pending model must never persist a password.",
        )

    def test_registration_stores_only_digest_and_no_user_before_verification(self):
        captured = {}

        def capture_email(record, secret):
            captured["secret"] = secret

        with patch.object(
            InternshipSelfRegistration,
            "_send_verification_email",
            capture_email,
        ):
            result = self.Registration._submit_registration(
                "New Portal Intern",
                self.email,
            )
        registration = self.Registration.search(
            [("email_normalized", "=", self.email)],
        )
        self.assertEqual(result["status"], "sent")
        self.assertTrue(registration.token_digest)
        self.assertNotEqual(registration.token_digest, captured["secret"])
        self.assertNotIn(captured["secret"], registration.token_digest)
        self.assertFalse(registration.user_id)
        self.assertFalse(registration.student_id)
        self.assertFalse(
            self.env["res.users"].with_context(active_test=False).search(
                [("login", "=", self.email)]
            )
        )

    def test_expired_invalid_and_used_tokens_cannot_activate(self):
        expired, expired_secret = self._pending()
        expired.token_expires_at = fields.Datetime.now() - timedelta(seconds=1)
        with self.assertRaises(UserError):
            self._verify(expired, expired_secret)
        self.assertFalse(expired.user_id)

        invalid, _secret = self._pending("invalid-token@example.test")
        with self.assertRaises(UserError):
            self._verify(invalid, "wrong-secret")
        self.assertFalse(invalid.user_id)

        valid, secret = self._pending("single-use@example.test")
        user, student = self._verify(valid, secret)
        self.assertTrue(user and student)
        self.assertFalse(valid.token_digest)
        with self.assertRaises(UserError):
            self._verify(valid, secret)
        self.assertEqual(
            self.env["res.users"].search_count([("id", "=", user.id)]),
            1,
        )
        self.assertEqual(
            self.env["internship.student"].search_count(
                [("user_id", "=", user.id)]
            ),
            1,
        )

    def test_resend_rotates_token_and_obeys_cooldown(self):
        captured = []

        def capture_email(record, secret):
            captured.append(secret)

        with patch.object(
            InternshipSelfRegistration,
            "_send_verification_email",
            capture_email,
        ):
            first = self.Registration._submit_registration(
                "Portal Intern",
                self.email,
            )
            registration = self.Registration.search(
                [("email_normalized", "=", self.email)]
            )
            old_selector = registration.token_selector
            old_digest = registration.token_digest
            cooldown = self.Registration._resend(self.email.upper())
            registration.last_email_sent_at = (
                fields.Datetime.now() - timedelta(minutes=3)
            )
            resent = self.Registration._resend(self.email.upper())

        self.assertEqual(first["status"], "sent")
        self.assertEqual(cooldown["status"], "cooldown")
        self.assertEqual(resent["status"], "sent")
        self.assertNotEqual(registration.token_selector, old_selector)
        self.assertNotEqual(registration.token_digest, old_digest)
        self.assertEqual(len(captured), 2)

    def test_case_variant_reuses_one_pending_registration(self):
        with patch.object(
            InternshipSelfRegistration,
            "_send_verification_email",
            lambda record, secret: None,
        ):
            self.Registration._submit_registration(
                "First Name",
                self.email.upper(),
            )
            registration = self.Registration.search(
                [("email_normalized", "=", self.email)]
            )
            registration.last_email_sent_at = (
                fields.Datetime.now() - timedelta(minutes=3)
            )
            self.Registration._submit_registration(
                "Updated Name",
                f" {self.email} ",
            )
        registrations = self.Registration.search(
            [("email_normalized", "=", self.email)]
        )
        self.assertEqual(len(registrations), 1)
        self.assertEqual(registrations.name, "Updated Name")

    def test_existing_user_is_handled_without_enumeration(self):
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": "Existing Account",
            "login": self.email,
        })
        with patch.object(
            InternshipSelfRegistration,
            "_send_verification_email",
        ) as send:
            result = self.Registration._submit_registration(
                "Existing Account",
                self.email.upper(),
            )
        self.assertTrue(user.active)
        self.assertEqual(result, {"status": "accepted"})
        send.assert_not_called()
        self.assertFalse(
            self.Registration.search(
                [("email_normalized", "=", self.email)]
            )
        )

    def test_successful_provisioning_has_exact_external_groups(self):
        registration, secret = self._pending()
        users_before = self.env["res.users"].search_count([])
        partners_before = self.env["res.partner"].search_count([])
        programs_before = self.env["internship.program"].search_count([])

        user, student = self._verify(registration, secret)

        self.assertEqual(
            self.env["res.users"].search_count([]),
            users_before + 1,
        )
        self.assertEqual(
            self.env["res.partner"].search_count([]),
            partners_before + 1,
        )
        self.assertEqual(
            self.env["internship.program"].search_count([]),
            programs_before,
        )
        self.assertEqual(student.user_id, user)
        self.assertEqual(student.email, self.email)
        self.assertRegex(student.student_number, r"^INT-\d{6}$")
        self.assertTrue(user.share)
        self.assertFalse(user._is_internal())
        self.assertTrue(user.has_group("base.group_portal"))
        self.assertTrue(
            user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        )
        for forbidden_group in (
            "base.group_user",
            "base.group_system",
            "internship_logbook.group_internship_intern",
            "internship_logbook.group_internship_supervisor",
            "internship_logbook.group_internship_manager",
        ):
            self.assertFalse(user.has_group(forbidden_group))

    def test_provisioning_failure_rolls_back_user_and_student(self):
        registration, secret = self._pending()
        users_before = self.env["res.users"].search_count([])
        students_before = self.env["internship.student"].search_count([])

        with patch.object(
            InternshipStudent,
            "create",
            side_effect=ValidationError("Simulated student creation failure"),
        ), self.assertRaises(ValidationError):
            self._verify(registration, secret)

        self.assertEqual(
            self.env["res.users"].search_count([]),
            users_before,
        )
        self.assertEqual(
            self.env["internship.student"].search_count([]),
            students_before,
        )
        self.assertEqual(registration.state, "pending")
        self.assertFalse(registration.user_id)
        self.assertFalse(registration.student_id)

    def test_one_user_cannot_have_two_student_profiles(self):
        registration, secret = self._pending()
        user, _student = self._verify(registration, secret)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["internship.student"].create({
                "name": "Duplicate Student",
                "student_number": "DUPLICATE-USER-001",
                "user_id": user.id,
            })

    def test_portal_ownership_rules_and_pending_model_access(self):
        registration, secret = self._pending()
        portal_user, own_student = self._verify(registration, secret)
        other_user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": "Other Portal Intern",
            "login": "other-portal-intern@example.test",
            "group_ids": [Command.set([
                self.env.ref(
                    "internship_logbook.group_internship_portal_intern"
                ).id
            ])],
        })
        other_student = self.env["internship.student"].create({
            "name": "Other Portal Intern",
            "student_number": "PORTAL-OTHER-001",
            "email": other_user.login,
            "user_id": other_user.id,
        })
        other_program = self.env["internship.program"].create({
            "name": "Other Portal Program",
            "student_id": other_student.id,
            "company_name": "Portal Test Company",
            "department": "Engineering",
            "workflow_mode": "independent",
            "start_date": "2027-04-01",
            "end_date": "2027-04-30",
            "state": "active",
        })
        other_entry = self.env["internship.daily.entry"].create({
            "title": "Other Portal Daily Entry",
            "program_id": other_program.id,
            "entry_date": "2027-04-02",
            "work_hours": 8,
            "work_description": "Other intern private work.",
        })

        self.assertEqual(
            self.env["internship.student"].with_user(portal_user).search([]),
            own_student,
        )
        with self.assertRaises(AccessError):
            other_student.with_user(portal_user).check_access("read")
        with self.assertRaises(AccessError):
            other_student.with_user(portal_user).write({"name": "Blocked"})
        with self.assertRaises(AccessError):
            registration.with_user(portal_user).check_access("read")
        with self.assertRaises(AccessError):
            other_program.with_user(portal_user).check_access("read")
        with self.assertRaises(AccessError):
            other_entry.with_user(portal_user).check_access("read")


@tagged("post_install", "-at_install")
class TestInternshipSelfRegistrationHttp(HttpCase):
    def test_public_registration_pages_and_csrf(self):
        self.authenticate(None, None)
        response = self.url_open("/internship/register")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Create your Internship Logbook account", response.text)
        self.assertNotIn('name="password"', response.text)
        self.assertIn('name="csrf_token"', response.text)

        invalid_csrf = self.url_open(
            "/internship/register",
            data={"name": "Test", "email": "test-http@example.test"},
        )
        self.assertEqual(invalid_csrf.status_code, 400)

    def test_generic_confirmation_for_new_and_existing_accounts(self):
        self.authenticate(None, None)
        csrf_token = http.Request.csrf_token(self)
        self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Existing HTTP User",
            "login": "existing-http@example.test",
        })
        with patch.object(
            InternshipSelfRegistration,
            "_send_verification_email",
            lambda record, secret: None,
        ), patch.object(
            self.env.registry["ir.http"],
            "_verify_request_recaptcha_token",
            lambda instance, captcha: None,
        ):
            new_response = self.url_open(
                "/internship/register",
                data={
                    "name": "New HTTP User",
                    "email": "new-http@example.test",
                    "password": "must-be-ignored",
                    "groups_id": "1",
                    "state": "verified",
                    "redirect": "https://example.invalid",
                    "csrf_token": csrf_token,
                },
            )
            existing_response = self.url_open(
                "/internship/register",
                data={
                    "name": "Existing HTTP User",
                    "email": "existing-http@example.test",
                    "csrf_token": csrf_token,
                },
            )
        self.assertTrue(new_response.url.endswith("/internship/register/sent"))
        self.assertTrue(
            existing_response.url.endswith("/internship/register/sent")
        )
        pending = self.env["internship.self.registration"].sudo().search(
            [("email_normalized", "=", "new-http@example.test")]
        )
        self.assertEqual(pending.state, "pending")
        self.assertNotIn("password", pending._fields)
        self.assertFalse(pending.user_id)

    def test_verification_get_does_not_consume_selector(self):
        Registration = self.env["internship.self.registration"].sudo()
        selector, _secret, digest = Registration._new_token()
        pending = Registration.create({
            "name": "Verification Page User",
            "email": "verify-page@example.test",
            "email_normalized": "verify-page@example.test",
            "token_selector": selector,
            "token_digest": digest,
            "token_expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        response = self.url_open(f"/internship/verify/{selector}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(pending.token_digest, digest)
        self.assertFalse(pending.user_id)
        self.assertNotIn("#token=", response.url)

    def test_failed_verification_attempts_persist_and_expire_token(self):
        self.authenticate(None, None)
        Registration = self.env["internship.self.registration"].sudo()
        selector, _secret, digest = Registration._new_token()
        pending = Registration.create({
            "name": "Failed Attempt User",
            "email": "failed-attempt-http@example.test",
            "email_normalized": "failed-attempt-http@example.test",
            "token_selector": selector,
            "token_digest": digest,
            "token_expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        csrf_token = http.Request.csrf_token(self)

        for attempt in range(1, Registration._MAX_ATTEMPTS + 1):
            response = self.url_open(
                "/internship/verify",
                data={
                    "selector": selector,
                    "secret": "invalid-secret",
                    "password": "HTTP-local-passphrase-2026!",
                    "password_confirmation": "HTTP-local-passphrase-2026!",
                    "csrf_token": csrf_token,
                },
            )
            self.assertEqual(response.status_code, 200)
            pending.invalidate_recordset()
            self.assertEqual(pending.verification_attempt_count, attempt)

        self.assertEqual(pending.state, "expired")
        self.assertFalse(pending.token_digest)
        self.assertFalse(pending.user_id)

    def test_unauthenticated_portal_route_redirects_to_login(self):
        self.authenticate(None, None)
        response = self.url_open("/my/internship", allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn("/web/login", response.headers["Location"])

    def test_valid_verification_uses_fixed_portal_redirect(self):
        self.authenticate(None, None)
        Registration = self.env["internship.self.registration"].sudo()
        selector, secret, digest = Registration._new_token()
        Registration.create({
            "name": "HTTP Verified Portal Intern",
            "email": "verified-http@example.test",
            "email_normalized": "verified-http@example.test",
            "token_selector": selector,
            "token_digest": digest,
            "token_expires_at": fields.Datetime.now() + timedelta(hours=1),
        })
        response = self.url_open(
            "/internship/verify",
            data={
                "selector": selector,
                "secret": secret,
                "password": "HTTP-local-passphrase-2026!",
                "password_confirmation": "HTTP-local-passphrase-2026!",
                "redirect": "https://example.invalid/steal",
                "groups_id": "1",
                "csrf_token": http.Request.csrf_token(self),
            },
            allow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            urlparse(response.headers["Location"]).path,
            "/my/internship",
        )
        self.assertNotIn(secret, response.headers["Location"])
        user = self.env["res.users"].search(
            [("login", "=", "verified-http@example.test")]
        )
        self.assertTrue(
            user.has_group(
                "internship_logbook.group_internship_portal_intern"
            )
        )
        self.assertFalse(user.has_group("base.group_system"))

    def test_portal_dashboard_and_dedicated_group_gate(self):
        password = "Portal-local-passphrase-2026!"
        portal_group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
        )
        dedicated_user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": "Dashboard Portal Intern",
            "login": "dashboard-portal@example.test",
            "password": password,
            "group_ids": [Command.set([portal_group.id])],
        })
        self.env["internship.student"].create({
            "name": dedicated_user.name,
            "student_number": "PORTAL-DASHBOARD-001",
            "email": dedicated_user.login,
            "user_id": dedicated_user.id,
        })
        normal_portal = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": "Normal Portal User",
            "login": "normal-portal@example.test",
            "password": password,
            "group_ids": [Command.set([
                self.env.ref("base.group_portal").id
            ])],
        })

        self.authenticate(dedicated_user.login, password)
        allowed = self.url_open("/my/internship")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("Account verified.", allowed.text)
        self.assertIn("No internship program has been created yet.", allowed.text)
        self.assertFalse(
            self.env["internship.program"].search(
                [("student_id.user_id", "=", dedicated_user.id)]
            )
        )

        self.authenticate(normal_portal.login, password)
        denied = self.url_open("/my/internship")
        self.assertEqual(denied.status_code, 403)
