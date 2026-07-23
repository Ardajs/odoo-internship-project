import json
import os
from unittest.mock import Mock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services import gemini_provider
from ..services.ai_provider import AIProviderService
from ..services.gemini_provider import GeminiAIProvider
from ..services.mock_provider import MockAIProvider


@tagged("post_install", "-at_install")
class TestGeminiAIProvider(TransactionCase):
    TEST_API_KEY = "TEST_ONLY_CREDENTIAL"
    GEMINI_ENVIRONMENT = {
        "INTERNSHIP_AI_ENABLED": "True",
        "INTERNSHIP_AI_PROVIDER": "gemini",
        "INTERNSHIP_AI_API_KEY": TEST_API_KEY,
        "INTERNSHIP_AI_MODEL": "gemini-test-model",
        "INTERNSHIP_AI_GEMINI_ENDPOINT": GeminiAIProvider.DEFAULT_ENDPOINT,
        "INTERNSHIP_AI_TIMEOUT": "30",
        "INTERNSHIP_AI_MAX_INPUT_CHARS": "8000",
        "INTERNSHIP_AI_MAX_OUTPUT_TOKENS": "1000",
        "INTERNSHIP_AI_MAX_OUTPUT_CHARS": "12000",
    }
    IMPROVE_RESULT = {
        "suggested_text": "The entry was improved without changing its facts.",
        "feedback": "Grammar and clarity were improved.",
        "warnings": None,
    }

    def _http_response(
        self,
        result=None,
        status_code=200,
        interaction_status="completed",
        output_text=None,
    ):
        response = Mock(status_code=status_code)
        if output_text is None and result is not None:
            output_text = json.dumps(result)
        steps = []
        if output_text is not None:
            steps = [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": output_text}],
                }
            ]
        response.json.return_value = {
            "object": "interaction",
            "status": interaction_status,
            "steps": steps,
        }
        return response

    def _generate(
        self,
        action_type,
        result=None,
        revision_comment=None,
        response=None,
        original_text="I implemented and tested an assigned Odoo model.",
        work_description=None,
    ):
        service = AIProviderService(self.env)
        http_response = response or self._http_response(result=result)
        with patch.dict(
            os.environ,
            self.GEMINI_ENVIRONMENT,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
            return_value=http_response,
        ) as http_post:
            generated = service.generate(
                action_type=action_type,
                title="Odoo model work",
                original_text=original_text,
                revision_comment=revision_comment,
                work_description=work_description,
            )
        return generated, http_post

    def test_gemini_provider_routing(self):
        service = AIProviderService(self.env)
        internal_result = {
            "suggested_text": self.IMPROVE_RESULT["suggested_text"],
            "feedback": self.IMPROVE_RESULT["feedback"],
            "warnings": [],
        }
        with patch.dict(
            os.environ,
            self.GEMINI_ENVIRONMENT,
            clear=False,
        ), patch.object(
            GeminiAIProvider,
            "generate",
            return_value=internal_result,
        ) as gemini_generate, patch.object(
            service,
            "_call_openai_compatible",
        ) as openai_call:
            result = service.generate(
                "improve",
                "Title",
                "Original entry text.",
            )

        gemini_generate.assert_called_once()
        openai_call.assert_not_called()
        self.assertEqual(result, internal_result)

    def test_mock_provider_routing_is_unchanged(self):
        service = AIProviderService(self.env)
        environment = {
            **self.GEMINI_ENVIRONMENT,
            "INTERNSHIP_AI_PROVIDER": "mock",
        }
        internal_result = {
            "suggested_text": "Mock suggestion.",
            "feedback": "Mock feedback.",
            "warnings": [],
        }
        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ), patch.object(
            MockAIProvider,
            "generate",
            return_value=internal_result,
        ) as mock_generate, patch.object(
            GeminiAIProvider,
            "generate",
        ) as gemini_generate, patch.object(
            service,
            "_call_openai_compatible",
        ) as openai_call:
            result = service.generate("improve", "Title", "Entry text.")

        mock_generate.assert_called_once()
        gemini_generate.assert_not_called()
        openai_call.assert_not_called()
        self.assertEqual(result, internal_result)

    def test_openai_provider_routing_is_unchanged(self):
        service = AIProviderService(self.env)
        environment = {
            **self.GEMINI_ENVIRONMENT,
            "INTERNSHIP_AI_PROVIDER": "openai",
            "INTERNSHIP_AI_ENDPOINT": AIProviderService.DEFAULT_ENDPOINT,
        }
        openai_response = {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({
                                "suggested_text": "OpenAI suggestion.",
                                "feedback": "OpenAI feedback.",
                                "warnings": [],
                            }),
                        }
                    ]
                }
            ],
        }
        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ), patch.object(
            service,
            "_call_openai_compatible",
            return_value=openai_response,
        ) as openai_call, patch.object(
            GeminiAIProvider,
            "generate",
        ) as gemini_generate:
            result = service.generate("improve", "Title", "Entry text.")

        openai_call.assert_called_once()
        gemini_generate.assert_not_called()
        self.assertEqual(result["suggested_text"], "OpenAI suggestion.")

    def test_request_uses_header_model_endpoint_and_minimum_context(self):
        result, http_post = self._generate(
            "improve",
            result=self.IMPROVE_RESULT,
        )

        request_args, request_kwargs = http_post.call_args
        self.assertEqual(request_args[0], GeminiAIProvider.DEFAULT_ENDPOINT)
        self.assertEqual(
            request_kwargs["headers"]["x-goog-api-key"],
            self.TEST_API_KEY,
        )
        self.assertNotIn("key", request_args[0].lower())
        payload = request_kwargs["json"]
        self.assertEqual(payload["model"], "gemini-test-model")
        self.assertFalse(payload["store"])
        self.assertEqual(
            payload["response_format"]["mime_type"],
            "application/json",
        )
        self.assertEqual(
            payload["generation_config"]["max_output_tokens"],
            1000,
        )
        self.assertNotIn(self.TEST_API_KEY, json.dumps(payload))
        self.assertNotIn("student_name", json.dumps(payload))
        self.assertNotIn("email", json.dumps(payload))
        self.assertNotIn("attachment", json.dumps(payload))
        self.assertFalse(request_kwargs["allow_redirects"])
        self.assertEqual(result["warnings"], [])

    def test_api_key_is_not_exposed_on_authentication_error(self):
        service = AIProviderService(self.env)
        response = self._http_response(status_code=403)
        with patch.dict(
            os.environ,
            self.GEMINI_ENVIRONMENT,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
            return_value=response,
        ), patch.object(
            gemini_provider._logger,
            "warning",
        ) as warning_log, self.assertRaises(UserError) as raised:
            service.generate("improve", "Title", "Entry text.")

        self.assertNotIn(self.TEST_API_KEY, str(raised.exception))
        self.assertNotIn(self.TEST_API_KEY, str(warning_log.call_args_list))

    def test_improve_writing_response_parsing(self):
        result, _http_post = self._generate(
            "improve",
            result=self.IMPROVE_RESULT,
        )
        self.assertTrue(result["suggested_text"])
        self.assertTrue(result["feedback"])
        self.assertEqual(result["warnings"], [])

    def test_suggestions_are_feedback_only(self):
        result, _http_post = self._generate(
            "suggestions",
            result={
                "suggested_text": None,
                "feedback": "- Clarify the task purpose.",
                "warnings": None,
            },
        )
        self.assertFalse(result["suggested_text"])
        self.assertTrue(result["feedback"])

    def test_missing_details_are_feedback_only(self):
        result, _http_post = self._generate(
            "missing_details",
            result={
                "suggested_text": None,
                "feedback": "The process and learning outcome are unclear.",
                "warnings": "Add only details that are true.",
            },
        )
        self.assertFalse(result["suggested_text"])
        self.assertEqual(result["warnings"], ["Add only details that are true."])

    def test_revision_response_uses_supervisor_comment(self):
        revision_comment = "Explain the testing method in more detail."
        result, http_post = self._generate(
            "revision",
            revision_comment=revision_comment,
            result={
                "suggested_text": "Revised entry text.",
                "feedback": "The supervisor requests more testing detail.",
                "warnings": None,
            },
        )
        payload = http_post.call_args.kwargs["json"]
        self.assertIn(revision_comment, payload["input"])
        self.assertTrue(result["suggested_text"])

    def test_new_field_actions_send_only_allowed_context(self):
        cases = (
            (
                "improve_learned_topics",
                "I learned how Odoo record rules are evaluated.",
                "what_i_learned",
            ),
            (
                "improve_challenges",
                "I corrected a failing record rule domain.",
                "problems_and_solutions",
            ),
        )
        work_description = "I implemented and tested an Odoo record rule."
        for action_type, target_text, target_key in cases:
            with self.subTest(action_type=action_type):
                result, http_post = self._generate(
                    action_type,
                    result=self.IMPROVE_RESULT,
                    original_text=target_text,
                    work_description=work_description,
                )
                payload_context = json.loads(
                    http_post.call_args.kwargs["json"]["input"]
                )

                self.assertEqual(
                    set(payload_context),
                    {"title", "work_description", target_key},
                )
                self.assertEqual(
                    payload_context["work_description"],
                    work_description,
                )
                self.assertEqual(payload_context[target_key], target_text)
                self.assertNotIn("student", payload_context)
                self.assertNotIn("email", payload_context)
                self.assertNotIn("attachment", payload_context)
                self.assertNotIn("supervisor_revision_comment", payload_context)
                self.assertTrue(result["suggested_text"])

    def test_new_field_prompts_require_active_rewrite_without_fabrication(self):
        cases = (
            (
                "improve_learned_topics",
                "I learned about Odoo models.",
                (
                    "professional learning-outcome editor",
                    "normally differ materially",
                    "semantically restate",
                    "Major structural changes",
                    "new technology",
                ),
            ),
            (
                "improve_challenges",
                "I had a database connection problem and fixed it.",
                (
                    "professional technical-incident editor",
                    "logically and chronologically",
                    "Substantial structural rewriting is expected",
                    "normally differ materially",
                    "neutral wording",
                    "Do not invent a command",
                ),
            ),
        )
        for action_type, source_text, required_phrases in cases:
            with self.subTest(action_type=action_type):
                _result, http_post = self._generate(
                    action_type,
                    result=self.IMPROVE_RESULT,
                    original_text=source_text,
                    work_description="Related daily work context.",
                )
                instructions = http_post.call_args.kwargs["json"][
                    "system_instruction"
                ]
                for phrase in required_phrases:
                    self.assertIn(phrase.lower(), instructions.lower())
                self.assertIn(
                    "Never invent",
                    instructions,
                )

    def test_professional_editor_prompt_handles_messy_turkish_incident(self):
        messy_turkish_note = (
            "Karşılaşılan Problem:\n\n"
            "odoo servisi baslatmaya calısırken veritabanı sunucuna baglanamadı "
            "dıye hata aldım psycopg2.OperationalError could not connect to "
            "server felan yazıyodu ekranda veritabanına erişim saglanamıyor "
            "dedi.\n\n"
            "Çözüm:\n\n"
            "baktım postgresql servisi arkada calısmıyor mus onu fark ettim "
            "sonra servisi baslattım odoo conf dosyasının ıcıne girip db "
            "kullanıcı adı ile sifre yerlerini deiştirdim güncelledim yani "
            "sonra baglantı hatası cözüldü serviste sorunsuz sekilde çalıstı."
        )
        _result, http_post = self._generate(
            "improve_challenges",
            result=self.IMPROVE_RESULT,
            original_text=messy_turkish_note,
            work_description="Odoo servis başlatma ve yapılandırma çalışması.",
        )
        payload = http_post.call_args.kwargs["json"]
        instructions = payload["system_instruction"]
        context = json.loads(payload["input"])

        required_editor_instructions = (
            "Preserve facts, not sentence structure.",
            "Substantial rewriting is allowed and expected",
            "correct grammar, spelling",
            "organize supported information logically and chronologically",
            "professional internship-logbook",
            "Turkish input must remain natural, professional Turkish",
            "Do not return the original",
        )
        for instruction in required_editor_instructions:
            self.assertIn(instruction.lower(), instructions.lower())

        prohibited_inventions = (
            "commands",
            "ports",
            "software versions",
            "root causes",
        )
        for prohibited_item in prohibited_inventions:
            self.assertIn(prohibited_item, instructions.lower())

        self.assertEqual(
            set(context),
            {"title", "work_description", "problems_and_solutions"},
        )
        self.assertEqual(
            context["problems_and_solutions"],
            messy_turkish_note,
        )
        self.assertNotIn(messy_turkish_note, instructions)

    def test_general_improve_prompt_preserves_facts_not_bad_writing(self):
        _result, http_post = self._generate(
            "improve",
            result=self.IMPROVE_RESULT,
            original_text="bug fixledim sonra test yaptım hersey calıstı",
        )
        instructions = http_post.call_args.kwargs["json"]["system_instruction"]

        for required_instruction in (
            "Preserve facts, not sentence structure.",
            "Major structural changes are permitted",
            "reconstruct fragments",
            "Do not return the original wording",
            "Keep the rewritten text in the same language",
        ):
            self.assertIn(required_instruction.lower(), instructions.lower())

    def test_new_field_actions_allow_feedback_only_when_facts_are_insufficient(self):
        for action_type in (
            "improve_learned_topics",
            "improve_challenges",
        ):
            with self.subTest(action_type=action_type):
                result, _http_post = self._generate(
                    action_type,
                    result={
                        "suggested_text": None,
                        "feedback": (
                            "More user-provided facts are required before a faithful "
                            "revision can be suggested."
                        ),
                        "warnings": "Do not add details that did not occur.",
                    },
                    original_text="More detail is needed.",
                    work_description="Daily work context.",
                )
                self.assertFalse(result["suggested_text"])
                self.assertTrue(result["feedback"])
                self.assertTrue(result["warnings"])

    def test_openai_compatible_provider_supports_new_field_actions(self):
        service = AIProviderService(self.env)
        environment = {
            **self.GEMINI_ENVIRONMENT,
            "INTERNSHIP_AI_PROVIDER": "openai",
            "INTERNSHIP_AI_ENDPOINT": AIProviderService.DEFAULT_ENDPOINT,
        }
        openai_response = {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({
                                **self.IMPROVE_RESULT,
                                "warnings": [],
                            }),
                        }
                    ]
                }
            ],
        }
        for action_type, target_key in (
            ("improve_learned_topics", "what_i_learned"),
            ("improve_challenges", "problems_and_solutions"),
        ):
            with self.subTest(action_type=action_type), patch.dict(
                os.environ,
                environment,
                clear=False,
            ), patch.object(
                service,
                "_call_openai_compatible",
                return_value=openai_response,
            ) as openai_call:
                result = service.generate(
                    action_type=action_type,
                    title="Odoo model work",
                    original_text="Target field text.",
                    work_description="Daily work description.",
                )

                prompt = openai_call.call_args.args[1]
                payload_context = json.loads(prompt["input"])
                self.assertEqual(
                    set(payload_context),
                    {"title", "work_description", target_key},
                )
                self.assertTrue(result["suggested_text"])

    def test_timeout_is_user_friendly(self):
        service = AIProviderService(self.env)
        with patch.dict(
            os.environ,
            self.GEMINI_ENVIRONMENT,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
            side_effect=requests.Timeout,
        ), self.assertRaisesRegex(UserError, "timed out"):
            service.generate("improve", "Title", "Entry text.")

    def test_connection_error_is_user_friendly(self):
        service = AIProviderService(self.env)
        with patch.dict(
            os.environ,
            self.GEMINI_ENVIRONMENT,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
            side_effect=requests.ConnectionError,
        ), self.assertRaisesRegex(UserError, "temporarily unavailable"):
            service.generate("improve", "Title", "Entry text.")

    def test_authentication_http_errors(self):
        for status_code in (401, 403):
            with self.subTest(status_code=status_code), self.assertRaisesRegex(
                UserError,
                "authentication",
            ):
                self._generate(
                    "improve",
                    response=self._http_response(status_code=status_code),
                )

    def test_quota_http_error(self):
        with self.assertRaisesRegex(UserError, "usage limit"):
            self._generate(
                "improve",
                response=self._http_response(status_code=429),
            )

    def test_model_not_found_http_error(self):
        with self.assertRaisesRegex(UserError, "model is unavailable"):
            self._generate(
                "improve",
                response=self._http_response(status_code=404),
            )

    def test_generic_client_http_error(self):
        response = self._http_response(status_code=400)
        response.json.return_value = {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "Sensitive provider detail must not be logged.",
            }
        }
        with patch.object(
            gemini_provider._logger,
            "warning",
        ) as warning_log, self.assertRaisesRegex(
            UserError,
            "could not be completed",
        ):
            self._generate(
                "improve",
                response=response,
            )
        warning_log.assert_called_once_with(
            "Gemini API request failed: http_status=%s "
            "gemini_code=%s gemini_status=%s",
            400,
            400,
            "INVALID_ARGUMENT",
        )
        self.assertNotIn(
            "Sensitive provider detail",
            str(warning_log.call_args_list),
        )

    def test_http_error_logging_does_not_leak_raw_content_or_secret(self):
        sensitive_values = (
            self.TEST_API_KEY,
            "PRIVATE DAILY ENTRY TEXT",
            "PRIVATE SUPERVISOR COMMENT",
        )
        response = self._http_response(status_code=400)
        response.json.return_value = {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": " | ".join(sensitive_values),
            }
        }

        with patch.object(
            gemini_provider._logger,
            "warning",
        ) as warning_log, self.assertRaises(UserError):
            self._generate("improve", response=response)

        logged_values = str(warning_log.call_args_list)
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, logged_values)

    def test_unparseable_http_error_logs_unknown_metadata(self):
        response = self._http_response(status_code=400)
        response.json.side_effect = ValueError("invalid json")

        with patch.object(
            gemini_provider._logger,
            "warning",
        ) as warning_log, self.assertRaisesRegex(
            UserError,
            "could not be completed",
        ):
            self._generate("improve", response=response)

        warning_log.assert_called_once_with(
            "Gemini API request failed: http_status=%s "
            "gemini_code=%s gemini_status=%s",
            400,
            "unknown",
            "unknown",
        )

    def test_server_http_errors(self):
        for status_code in (500, 503):
            with self.subTest(status_code=status_code), self.assertRaisesRegex(
                UserError,
                "temporarily unavailable",
            ):
                self._generate(
                    "improve",
                    response=self._http_response(status_code=status_code),
                )

    def test_invalid_http_json_is_rejected(self):
        response = self._http_response()
        response.json.side_effect = ValueError("invalid json")
        with self.assertRaisesRegex(UserError, "invalid response"):
            self._generate("improve", response=response)

    def test_invalid_structured_json_is_rejected(self):
        response = self._http_response(output_text="not-json")
        with self.assertRaisesRegex(UserError, "invalid response"):
            self._generate("improve", response=response)

    def test_malformed_structured_response_is_rejected(self):
        response = self._http_response(
            result={
                "suggested_text": "Suggestion.",
                "feedback": ["Not a string"],
                "warnings": None,
            }
        )
        with self.assertRaisesRegex(UserError, "invalid response"):
            self._generate("improve", response=response)

    def test_safety_or_failed_response_is_rejected(self):
        response = self._http_response(
            interaction_status="failed",
            output_text="provider detail must not be shown",
        )
        with self.assertRaisesRegex(UserError, "could not help") as raised:
            self._generate("improve", response=response)
        self.assertNotIn("provider detail", str(raised.exception))

    def test_incomplete_response_is_rejected(self):
        response = self._http_response(
            interaction_status="incomplete",
            output_text=json.dumps(self.IMPROVE_RESULT),
        )
        with self.assertRaisesRegex(UserError, "incomplete"):
            self._generate("improve", response=response)

    def test_empty_response_is_rejected(self):
        response = self._http_response()
        with self.assertRaisesRegex(UserError, "empty response"):
            self._generate("improve", response=response)

    def test_non_google_endpoint_is_rejected_before_http(self):
        service = AIProviderService(self.env)
        environment = {
            **self.GEMINI_ENVIRONMENT,
            "INTERNSHIP_AI_GEMINI_ENDPOINT": "https://example.invalid/v1beta/interactions",
        }
        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
        ) as http_post, self.assertRaisesRegex(UserError, "not allowed"):
            service.generate("improve", "Title", "Entry text.")
        http_post.assert_not_called()

    def test_missing_gemini_api_key_is_configuration_error(self):
        service = AIProviderService(self.env)
        environment = {
            **self.GEMINI_ENVIRONMENT,
            "INTERNSHIP_AI_API_KEY": "",
        }
        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ), patch.object(
            gemini_provider.requests,
            "post",
        ) as http_post, self.assertRaisesRegex(
            UserError,
            "AI Assistant is not configured",
        ):
            service.generate("improve", "Title", "Entry text.")
        http_post.assert_not_called()
