from lxml import html

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestPortalDailyEntryDetail(HttpCase):
    PASSWORD = "Portal-daily-detail-passphrase-2026!"

    def _create_portal_user(self, suffix, *, dedicated=True):
        group = self.env.ref(
            "internship_logbook.group_internship_portal_intern"
            if dedicated
            else "base.group_portal"
        )
        user = self.env["res.users"].with_context(
            no_reset_password=True,
        ).create({
            "name": f"Portal Detail {suffix}",
            "login": f"portal-detail-{suffix}@example.test",
            "email": f"portal-detail-{suffix}@example.test",
            "password": self.PASSWORD,
            "group_ids": [Command.set([group.id])],
        })
        student = self.env["internship.student"]
        if dedicated:
            student = self.env["internship.student"].create({
                "name": user.name,
                "student_number": f"DETAIL-{suffix.upper()}",
                "email": user.email,
                "user_id": user.id,
            })
        return user, student

    def _create_program(self, student, suffix, *, workflow_mode="independent"):
        values = {
            "name": f"Detail Program {suffix}",
            "student_id": student.id,
            "company_name": f"Detail Company {suffix}",
            "department": "Engineering",
            "workflow_mode": workflow_mode,
            "start_date": "2028-07-01",
            "end_date": "2028-07-31",
            "state": "active",
        }
        if workflow_mode == "supervised":
            supervisor_group = self.env.ref(
                "internship_logbook.group_internship_supervisor"
            )
            supervisor = self.env["res.users"].with_context(
                no_reset_password=True,
            ).create({
                "name": f"Detail Supervisor {suffix}",
                "login": f"detail-supervisor-{suffix}@example.test",
                "group_ids": [Command.set([supervisor_group.id])],
            })
            values["supervisor_id"] = supervisor.id
        return self.env["internship.program"].create(values)

    def _create_entry(self, program, suffix, **overrides):
        values = {
            "program_id": program.id,
            "title": f"Detail Entry {suffix}",
            "entry_date": "2028-07-10",
            "work_hours": 7.5,
            "work_description": f"Safe detail description {suffix}.",
            "technologies": "Odoo, PostgreSQL",
            "learned_topics": "Learned safe portal rendering.",
            "challenges": "Resolved a documented test challenge.",
        }
        values.update(overrides)
        return self.env["internship.daily.entry"].create(values)

    def _authenticate(self, user):
        self.authenticate(user.login, self.PASSWORD)

    def _detail_url(self, entry):
        return f"/my/internship/daily/{entry.id}"

    def _document(self, response):
        return html.fromstring(response.content)

    def _frontend_css(self, response):
        links = self._document(response).xpath(
            "//link[contains(@href, '/web/assets/') "
            "and contains(@href, '.css')]/@href"
        )
        self.assertTrue(links)
        styles = []
        for link in links:
            asset = self.url_open(link)
            self.assertEqual(asset.status_code, 200)
            styles.append(asset.text)
        return "\n".join(styles)

    def test_owner_detail_renders_safe_fields_semantics_and_assets(self):
        user, student = self._create_portal_user("owner")
        program = self._create_program(student, "owner")
        entry = self._create_entry(program, "Owner")
        self._authenticate(user)

        response = self.url_open(self._detail_url(entry))

        self.assertEqual(response.status_code, 200)
        self.assertIn(entry.title, response.text)
        self.assertIn(entry.work_description, response.text)
        self.assertIn(entry.technologies, response.text)
        self.assertIn(entry.learned_topics, response.text)
        self.assertIn(entry.challenges, response.text)
        self.assertIn("Draft", response.text)
        document = self._document(response)
        self.assertEqual(document.xpath("count(//main//h1)"), 1.0)
        self.assertEqual(
            document.xpath(
                "count(//main[contains(@class, "
                "'o_internship_daily_detail')]//article)"
            ),
            1.0,
        )
        self.assertIn(
            ".o_internship_saas.o_internship_daily_detail",
            self._frontend_css(response),
        )
        debug_response = self.url_open(
            f"{self._detail_url(entry)}?debug=assets"
        )
        self.assertEqual(debug_response.status_code, 200)
        self.assertIn(
            ".o_internship_saas.o_internship_daily_detail",
            self._frontend_css(debug_response),
        )

    def test_anonymous_ordinary_portal_and_foreign_access(self):
        owner, owner_student = self._create_portal_user("access-owner")
        program = self._create_program(owner_student, "access-owner")
        entry = self._create_entry(program, "Private Unique Content")

        self.authenticate(None, None)
        anonymous = self.url_open(
            self._detail_url(entry),
            allow_redirects=False,
        )
        self.assertIn(anonymous.status_code, (302, 303))
        self.assertIn("/web/login", anonymous.headers["Location"])

        ordinary, _student = self._create_portal_user(
            "ordinary",
            dedicated=False,
        )
        self._authenticate(ordinary)
        ordinary_response = self.url_open(self._detail_url(entry))
        self.assertEqual(ordinary_response.status_code, 403)

        foreign, _foreign_student = self._create_portal_user("foreign")
        self._authenticate(foreign)
        foreign_response = self.url_open(self._detail_url(entry))
        self.assertEqual(foreign_response.status_code, 404)
        self.assertNotIn("Private Unique Content", foreign_response.text)

    def test_edit_and_submit_actions_follow_existing_helpers(self):
        user, student = self._create_portal_user("actions")
        independent = self._create_program(student, "actions")
        entry = self._create_entry(independent, "Actions")
        self._authenticate(user)

        draft = self.url_open(self._detail_url(entry))
        self.assertIn(
            f'/my/internship/daily/{entry.id}/edit',
            draft.text,
        )
        self.assertIn(
            f'/my/internship/daily/{entry.id}/submit-confirm',
            draft.text,
        )

        entry.action_complete()
        completed = self.url_open(self._detail_url(entry))
        self.assertNotIn(
            f'/my/internship/daily/{entry.id}/edit',
            completed.text,
        )
        self.assertNotIn(
            f'/my/internship/daily/{entry.id}/submit-confirm',
            completed.text,
        )
        self.assertIn("Completed", completed.text)

    def test_supervised_states_and_revision_feedback_are_safe(self):
        user, student = self._create_portal_user("states")
        program = self._create_program(
            student,
            "states",
            workflow_mode="supervised",
        )
        entries = {}
        for index, state in enumerate(
            ("draft", "submitted", "revision", "approved"),
            start=1,
        ):
            entries[state] = self._create_entry(
                program,
                state,
                entry_date=f"2028-07-{index + 10:02d}",
                state=state,
                supervisor_comment=(
                    "Please revise <script>alert('unsafe')</script> safely."
                    if state == "revision"
                    else False
                ),
            )
        self._authenticate(user)

        labels = {
            "draft": "Draft",
            "submitted": "Submitted",
            "revision": "Revision Requested",
            "approved": "Approved",
        }
        for state, entry in entries.items():
            with self.subTest(state=state):
                response = self.url_open(self._detail_url(entry))
                self.assertEqual(response.status_code, 200)
                self.assertIn(labels[state], response.text)
                self.assertNotIn("<script>alert", response.text)
                if state == "revision":
                    self.assertIn("Supervisor Feedback", response.text)
                    self.assertIn("&lt;script&gt;", response.text)

    def test_missing_entry_is_not_found(self):
        user, _student = self._create_portal_user("missing")
        self._authenticate(user)

        response = self.url_open("/my/internship/daily/999999999")

        self.assertEqual(response.status_code, 404)
