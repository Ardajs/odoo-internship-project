import logging
import re


_logger = logging.getLogger(__name__)


class MockAIProvider:
    """Deterministic local provider for manual development testing only."""

    def generate(
        self,
        action_type,
        title,
        original_text,
        revision_comment=None,
        response_variant="initial",
    ):
        _logger.info(
            "Internship AI local mock provider used for action %s",
            action_type,
        )
        normalized_text = self._normalize_text(original_text)
        regenerated = response_variant == "regenerated"

        if action_type == "improve":
            feedback = (
                "The writing, spacing, and punctuation were reviewed again. "
                "The original facts were preserved."
                if regenerated
                else
                "The writing, spacing, and punctuation were reviewed. "
                "The original facts were preserved."
            )
            return {
                "suggested_text": normalized_text,
                "feedback": feedback,
                "warnings": [],
            }

        if action_type == "suggestions":
            prefix = "Second review:" if regenerated else "Suggestions:"
            return {
                "suggested_text": "",
                "feedback": (
                    f"{prefix}\n"
                    "- Clarify the purpose of the task if it is not already clear.\n"
                    "- Explain the process or method used, but only if it was actually followed.\n"
                    "- State the learning outcome in the user's own words."
                ),
                "warnings": [],
            }

        if action_type == "missing_details":
            prefix = "Second review:" if regenerated else "Details checklist:"
            return {
                "suggested_text": "",
                "feedback": (
                    f"{prefix}\n"
                    "- Yapılan görev: Görevin amacı ve kapsamı açık mı kontrol edin.\n"
                    "- Teknoloji/araç: Gerçekte kullanılan araçları belirtin.\n"
                    "- Süreç/yöntem: İzlenen adımları, doğruysa, açıklayın.\n"
                    "- Problem: Karşılaşılan bir problem varsa ekleyin.\n"
                    "- Çözüm: Uygulanan çözüm varsa nasıl çalıştığını açıklayın.\n"
                    "- Öğrenilen kazanım: Edinilen bilgiyi kendi sözlerinizle yazın."
                ),
                "warnings": [],
            }

        if action_type == "revision":
            review_text = (
                "The supervisor request was reviewed again"
                if regenerated
                else
                "The supervisor requests a revision"
            )
            return {
                "suggested_text": normalized_text,
                "feedback": (
                    f'{review_text}: "{(revision_comment or "").strip()}". '
                    "Update only the requested details that are true; the suggested "
                    "text preserves the original entry facts."
                ),
                "warnings": [],
            }

        if action_type == "improve_learned_topics":
            return {
                "suggested_text": self._rewrite_learning_summary(
                    normalized_text
                ),
                "feedback": (
                    "The learning summary was reviewed again for clarity and "
                    "professional tone; no new learning outcome was added."
                    if regenerated
                    else
                    "The learning summary was reviewed for clarity and professional "
                    "tone; no new learning outcome was added."
                ),
                "warnings": [],
            }

        if action_type == "improve_challenges":
            return {
                "suggested_text": self._rewrite_challenge_summary(
                    normalized_text
                ),
                "feedback": (
                    "The problem-to-solution explanation was reviewed again while "
                    "preserving only the supplied facts."
                    if regenerated
                    else
                    "The problem-to-solution explanation was reviewed while "
                    "preserving only the supplied facts."
                ),
                "warnings": [],
            }

        raise ValueError("Unsupported mock AI action")

    @staticmethod
    def _normalize_text(original_text):
        text = " ".join((original_text or "").split())
        if not text:
            return ""
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?":
            text += "."
        return text

    @staticmethod
    def _rewrite_learning_summary(normalized_text):
        learned_about = re.fullmatch(
            r"I learned about (.+?)[.!?]?",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if learned_about:
            topic = learned_about.group(1).rstrip(".!?")
            return (
                "During this internship activity, I developed a clearer "
                f"understanding of {topic}."
            )
        return (
            "During this internship activity, I reflected on the following "
            f"learning outcome: {normalized_text}"
        )

    @staticmethod
    def _rewrite_challenge_summary(normalized_text):
        problem_and_fix = re.fullmatch(
            r"I (?:had|encountered) (.+?) and (?:fixed|resolved) it[.!?]?",
            normalized_text,
            flags=re.IGNORECASE,
        )
        if problem_and_fix:
            problem = problem_and_fix.group(1).rstrip(".!?")
            return (
                f"I encountered {problem}. "
                "I investigated the issue and resolved it."
            )
        return (
            "I documented the encountered problem and its resolution as "
            f"follows: {normalized_text}"
        )
