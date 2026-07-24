from urllib.parse import urlparse

from odoo import Command, http
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalInternshipOnboarding(HttpCase):
    PASSWORD = "Portal-onboarding-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True, student=True):
        groups = [
            self.env.ref(
                "internship_logbook.group_internship_portal_intern"
                if dedicated
                else "base.group_portal"
            ).id
        ]
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Onboarding {suffix}",
            "login": f"portal-onboarding-{suffix}@example.test",
            "email": f"portal-onboarding-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set(groups)],
        })
        student_record = self.env["internship.student"]
        if student:
            student_record = self.env["internship.student"].create({
                "name": user.name,
                "student_number": f"PORTAL-{suffix.upper()}",
                "email": user.email,
                "user_id": user.id,
            })
        return user, student_record

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _valid_form(self, **overrides):
        values = {
            "company_name": "Portal Test Company",
            "department": "Software Engineering",
            "start_date": "2027-09-01",
            "end_date": "2027-09-30",
            "workflow_mode": "independent",
            "csrf_token": http.Request.csrf_token(self),
        }
        values.update(overrides)
        return values

    def _programs_for(self, student):
        return self.env["internship.program"].search(
            [("student_id", "=", student.id)]
        )

    def test_eligible_portal_intern_can_open_onboarding(self):
        user, _student = self._create_portal_user("eligible")
        self._authenticate(user)

        response = self.url_open("/my/internship/create")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Create Your First Internship", response.text)
        self.assertIn('name="csrf_token"', response.text)
        self.assertIn('value="independent"', response.text)

    def test_public_and_ineligible_accounts_cannot_open_onboarding(self):
        self.authenticate(None, None)
        public_response = self.url_open(
            "/my/internship/create",
            allow_redirects=False,
        )
        self.assertIn(public_response.status_code, (302, 303))
        self.assertIn("/web/login", public_response.headers["Location"])

        normal_portal, _student = self._create_portal_user(
            "normal-portal",
            dedicated=False,
        )
        self._authenticate(normal_portal)
        role_response = self.url_open(
            "/my/internship/create",
            allow_redirects=False,
        )
        self.assertIn(role_response.status_code, (302, 303))
        self.assertEqual(
            urlparse(role_response.headers["Location"]).path,
            "/my/internship",
        )
        role_post = self.url_open(
            "/my/internship/create",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertEqual(role_post.status_code, 303)
        self.assertEqual(
            urlparse(role_post.headers["Location"]).path,
            "/my/internship",
        )

        no_student, _student = self._create_portal_user(
            "no-student",
            student=False,
        )
        self._authenticate(no_student)
        profile_response = self.url_open(
            "/my/internship/create",
            allow_redirects=False,
        )
        self.assertIn(profile_response.status_code, (302, 303))
        self.assertEqual(
            urlparse(profile_response.headers["Location"]).path,
            "/my/internship",
        )
        profile_post = self.url_open(
            "/my/internship/create",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertEqual(profile_post.status_code, 303)
        self.assertEqual(
            urlparse(profile_post.headers["Location"]).path,
            "/my/internship",
        )

    def test_valid_submission_creates_one_owned_program_and_redirects(self):
        user, student = self._create_portal_user("valid")
        other_user, other_student = self._create_portal_user("valid-other")
        self._authenticate(user)

        response = self.url_open(
            "/my/internship/create",
            data=self._valid_form(
                student_id=str(other_student.id),
                user_id=str(other_user.id),
                program_id="999999",
                supervisor_id=str(other_user.id),
                state="completed",
            ),
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            urlparse(response.headers["Location"]).path,
            "/my/internship",
        )
        programs = self._programs_for(student)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs.student_id, student)
        self.assertEqual(programs.workflow_mode, "independent")
        self.assertEqual(programs.state, "draft")
        self.assertFalse(programs.supervisor_id)
        self.assertFalse(self._programs_for(other_student))
        self.assertTrue(user.share)
        self.assertFalse(user._is_internal())

    def test_validation_errors_create_no_program_and_preserve_values(self):
        user, student = self._create_portal_user("validation")
        self._authenticate(user)
        invalid_cases = (
            (
                {"company_name": ""},
                "Company is required.",
            ),
            (
                {"department": "   "},
                "Department is required.",
            ),
            (
                {"start_date": "2027-10-02", "end_date": "2027-10-01"},
                "End date cannot be earlier than start date.",
            ),
            (
                {"workflow_mode": "supervised"},
                "Select a valid internship mode.",
            ),
        )

        for overrides, expected_error in invalid_cases:
            with self.subTest(overrides=overrides):
                submitted = self._valid_form(**overrides)
                response = self.url_open(
                    "/my/internship/create",
                    data=submitted,
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_error, response.text)
                self.assertIn(submitted["start_date"], response.text)
                self.assertFalse(self._programs_for(student))

    def test_dashboard_displays_created_program(self):
        user, student = self._create_portal_user("dashboard")
        self._authenticate(user)
        self.url_open(
            "/my/internship/create",
            data=self._valid_form(
                company_name="Dashboard Company",
                department="Research and Development",
            ),
        )

        response = self.url_open("/my/internship")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Current Internship", response.text)
        self.assertIn("Dashboard Company", response.text)
        self.assertIn("Research and Development", response.text)
        self.assertIn("Independent", response.text)
        self.assertEqual(len(self._programs_for(student)), 1)

    def test_existing_program_blocks_form_and_repeated_post(self):
        user, student = self._create_portal_user("duplicate")
        self._authenticate(user)
        first_response = self.url_open(
            "/my/internship/create",
            data=self._valid_form(),
            allow_redirects=False,
        )
        self.assertEqual(first_response.status_code, 303)
        self.assertEqual(len(self._programs_for(student)), 1)

        get_response = self.url_open(
            "/my/internship/create",
            allow_redirects=False,
        )
        repeated_response = self.url_open(
            "/my/internship/create",
            data=self._valid_form(),
            allow_redirects=False,
        )

        self.assertIn(get_response.status_code, (302, 303))
        self.assertEqual(
            urlparse(get_response.headers["Location"]).path,
            "/my/internship",
        )
        self.assertEqual(repeated_response.status_code, 303)
        self.assertEqual(
            urlparse(repeated_response.headers["Location"]).path,
            "/my/internship",
        )
        self.assertEqual(len(self._programs_for(student)), 1)

    def test_portal_cannot_use_generic_create_or_view_another_program(self):
        user, student = self._create_portal_user("ownership")
        _other_user, other_student = self._create_portal_user(
            "ownership-other"
        )
        other_program = self.env["internship.program"].create({
            "name": "Private Other Internship",
            "student_id": other_student.id,
            "company_name": "Other Intern Private Company",
            "department": "Private Department",
            "workflow_mode": "independent",
            "start_date": "2027-11-01",
            "end_date": "2027-11-30",
        })

        portal_programs = self.env["internship.program"].with_user(user)
        with self.assertRaises(AccessError):
            portal_programs.create({
                "name": "Blocked Generic Create",
                "student_id": student.id,
                "company_name": "Blocked",
                "department": "Blocked",
                "workflow_mode": "independent",
                "start_date": "2027-12-01",
                "end_date": "2027-12-31",
            })
        with self.assertRaises(AccessError):
            other_program.with_user(user).check_access("read")

        self._authenticate(user)
        dashboard = self.url_open("/my/internship")
        self.assertNotIn("Other Intern Private Company", dashboard.text)

    def test_private_service_rejects_second_program(self):
        user, student = self._create_portal_user("service-invariant")
        values = {
            "company_name": "First Program Company",
            "department": "Engineering",
            "start_date": "2028-01-01",
            "end_date": "2028-01-31",
            "workflow_mode": "independent",
        }
        Program = self.env["internship.program"].sudo()

        first = Program._portal_create_first_program(user.id, values)
        with self.assertRaises(UserError):
            Program._portal_create_first_program(user.id, values)

        self.assertEqual(first.student_id, student)
        self.assertEqual(len(self._programs_for(student)), 1)
