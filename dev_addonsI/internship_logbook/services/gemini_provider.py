import json
import logging
import re
from urllib.parse import urlparse

import requests

from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class GeminiAIProvider:
    """Google Gemini Interactions API adapter."""

    DEFAULT_ENDPOINT = (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    OFFICIAL_HOST = "generativelanguage.googleapis.com"
    INTERACTIONS_PATH_PATTERN = re.compile(
        r"/v1(?:beta\d*)?/interactions"
    )
    RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "suggested_text": {
                "type": ["string", "null"],
                "description": (
                    "Revised entry text, or null for feedback-only actions."
                ),
            },
            "feedback": {
                "type": "string",
                "description": "Professional, actionable feedback for the intern.",
            },
            "warnings": {
                "type": ["string", "null"],
                "description": (
                    "A concise warning when needed, otherwise null."
                ),
            },
        },
        "required": ["suggested_text", "feedback", "warnings"],
        "additionalProperties": False,
    }

    def __init__(self, env):
        self.env = env

    def generate(self, config, prompt):
        endpoint = self.validate_endpoint(
            config["gemini_endpoint"],
            self.env,
        )
        payload = {
            "model": config["model"],
            "system_instruction": prompt["instructions"],
            "input": prompt["input"],
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": self.RESPONSE_SCHEMA,
            },
            "generation_config": {
                "max_output_tokens": config["max_output_tokens"],
            },
            "store": False,
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": config["api_key"],
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=config["timeout"],
                allow_redirects=False,
            )
        except requests.Timeout as error:
            _logger.warning("Gemini provider request timed out")
            raise UserError(
                self.env._(
                    "The AI Assistant timed out. Please try again later."
                )
            ) from error
        except requests.ConnectionError as error:
            _logger.warning("Gemini provider connection could not be established")
            raise UserError(
                self.env._(
                    "The AI Assistant is temporarily unavailable. "
                    "Please try again later."
                )
            ) from error
        except requests.RequestException as error:
            _logger.warning("Gemini provider request could not be completed")
            raise UserError(
                self.env._(
                    "The AI Assistant request could not be completed. "
                    "Please try again later."
                )
            ) from error

        self._validate_http_status(response)
        try:
            response_data = response.json()
        except ValueError as error:
            _logger.warning("Gemini provider returned invalid JSON")
            raise UserError(
                self.env._(
                    "The AI Assistant returned an invalid response. "
                    "Please try again later."
                )
            ) from error

        return self._parse_response(response_data)

    @classmethod
    def validate_endpoint(cls, endpoint, env):
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError:
            cls._endpoint_error(env)

        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != cls.OFFICIAL_HOST
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not cls.INTERACTIONS_PATH_PATTERN.fullmatch(
                parsed.path.rstrip("/")
            )
        ):
            cls._endpoint_error(env)
        return endpoint.rstrip("/")

    def _validate_http_status(self, response):
        status_code = response.status_code
        if 200 <= status_code < 300:
            return

        gemini_code, gemini_status = self._safe_error_metadata(response)
        _logger.warning(
            "Gemini API request failed: http_status=%s "
            "gemini_code=%s gemini_status=%s",
            status_code,
            gemini_code,
            gemini_status,
        )

        if status_code in (401, 403):
            raise UserError(
                self.env._(
                    "The AI Assistant authentication is not configured correctly. "
                    "Please contact the administrator."
                )
            )
        if status_code == 404:
            raise UserError(
                self.env._(
                    "The configured AI model is unavailable. "
                    "Please contact the administrator."
                )
            )
        if status_code == 429:
            raise UserError(
                self.env._(
                    "The AI Assistant is busy or its usage limit was reached. "
                    "Please wait and try again."
                )
            )
        if status_code >= 500:
            raise UserError(
                self.env._(
                    "The AI Assistant provider is temporarily unavailable. "
                    "Please try again later."
                )
            )
        raise UserError(
            self.env._(
                "The AI Assistant request could not be completed. "
                "Please contact the administrator."
            )
        )

    @staticmethod
    def _safe_error_metadata(response):
        unknown = "unknown"
        try:
            response_data = response.json()
        except (TypeError, ValueError):
            return unknown, unknown

        if not isinstance(response_data, dict):
            return unknown, unknown
        error_data = response_data.get("error")
        if not isinstance(error_data, dict):
            return unknown, unknown

        code = error_data.get("code")
        if not isinstance(code, int) or isinstance(code, bool):
            code = unknown

        status = error_data.get("status")
        if not isinstance(status, str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,63}",
            status,
        ):
            status = unknown

        return code, status

    def _parse_response(self, response_data):
        if not isinstance(response_data, dict):
            self._invalid_response()

        status = response_data.get("status")
        if status == "incomplete":
            raise UserError(
                self.env._(
                    "The AI Assistant response was incomplete. "
                    "Please try again with shorter text."
                )
            )
        if status != "completed":
            _logger.warning("Gemini provider did not complete the request")
            raise UserError(
                self.env._("The AI Assistant could not help with this text.")
            )

        steps = response_data.get("steps")
        if not isinstance(steps, list):
            self._invalid_response()

        output_texts = []
        for step in steps:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content_items = step.get("content")
            if not isinstance(content_items, list):
                self._invalid_response()
            for content_item in content_items:
                if not isinstance(content_item, dict):
                    self._invalid_response()
                if content_item.get("type") == "text":
                    text = content_item.get("text")
                    if not isinstance(text, str):
                        self._invalid_response()
                    output_texts.append(text)

        raw_text = "".join(output_texts).strip()
        if not raw_text:
            raise UserError(
                self.env._(
                    "The AI Assistant returned an empty response. Please try again."
                )
            )

        try:
            result = json.loads(raw_text)
        except (TypeError, ValueError) as error:
            _logger.warning("Gemini structured output could not be parsed")
            raise UserError(
                self.env._(
                    "The AI Assistant returned an invalid response. "
                    "Please try again later."
                )
            ) from error
        if not isinstance(result, dict):
            self._invalid_response()

        suggested_text = result.get("suggested_text")
        warnings = result.get("warnings")
        if suggested_text is not None and not isinstance(suggested_text, str):
            self._invalid_response()
        if warnings is not None and not isinstance(warnings, str):
            self._invalid_response()

        return {
            "suggested_text": suggested_text or "",
            "feedback": result.get("feedback"),
            "warnings": [warnings] if warnings else [],
        }

    def _invalid_response(self):
        raise UserError(
            self.env._("The AI Assistant returned an invalid response.")
        )

    @staticmethod
    def _endpoint_error(env):
        raise UserError(
            env._(
                "The configured Gemini API endpoint is not allowed. "
                "Please contact the administrator."
            )
        )
