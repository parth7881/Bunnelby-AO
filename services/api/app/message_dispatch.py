from __future__ import annotations

import logging
import re

from .acknowledgments import detect_spoken_language
from .approval_service import approval_public_dict, create_gmail_compose_approval
from .gmail_service import (
    GmailAuthorizationError,
    GmailConfigurationError,
    GmailDraftError,
    GmailRateLimitError,
    GmailServiceError,
    draft_new_email_from_request,
)
from .orchestrator import OrchestratorResult, handle_message_result as _base_handle_message_result

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_REPLY_RE = re.compile(r"\b(?:reply|respond|jawab)\b", re.IGNORECASE)
_COMPOSE_ACTION_RE = re.compile(
    r"\b(?:send|compose|write|draft|create|email|mail|message|bhejo|bhejna|karo|kro|likho|likhna)\b",
    re.IGNORECASE,
)


def _standalone_email_requested(user_message: str) -> bool:
    """Recognize explicit one-recipient new-email commands, including common Hinglish phrasing."""
    return bool(
        _EMAIL_RE.search(user_message)
        and _COMPOSE_ACTION_RE.search(user_message)
        and not _REPLY_RE.search(user_message)
    )


def _result(
    reply: str,
    *,
    spoken_reply: str,
    action_type: str,
    approval: dict | None = None,
) -> OrchestratorResult:
    return OrchestratorResult(
        reply=reply,
        action_type=action_type,
        memory_content=f"{reply}\nRoute: gmail\nWhy: explicit standalone email compose request",
        spoken_reply=spoken_reply,
        approval=approval,
    )


def handle_message_result(user_message: str) -> OrchestratorResult:
    """Intercept safe standalone email compose requests; delegate every other turn unchanged."""
    if not _standalone_email_requested(user_message):
        return _base_handle_message_result(user_message)

    language = detect_spoken_language(user_message)
    try:
        draft = draft_new_email_from_request(user_message)
        approval = create_gmail_compose_approval(draft, spoken_language=language)
        public = approval_public_dict(approval)

        # The current desktop UI recognizes the established Gmail approval surface by
        # this compatibility value. The durable database row still records gmail_compose.
        public["task_type"] = "gmail_reply"

        return _result(
            (
                f"I drafted a new email to {draft['to']}. Review the exact recipient, subject, "
                "and message below. Nothing will be sent until you explicitly approve it."
            ),
            spoken_reply=(
                "मैंने नया ईमेल ड्राफ्ट तैयार कर दिया है। भेजने से पहले आपकी मंज़ूरी चाहिए।"
                if language == "hi"
                else "I've drafted the new email. Review it before I send anything."
            ),
            action_type="approval_required",
            approval=public,
        )
    except GmailDraftError as exc:
        return _result(
            f"I couldn't create the new Gmail draft: {exc}",
            spoken_reply="I couldn't prepare that new email. Nothing was sent.",
            action_type="error",
        )
    except GmailConfigurationError as exc:
        return _result(
            f"Bunnelby Gmail setup is incomplete: {exc}",
            spoken_reply="Gmail setup is incomplete. Nothing was sent.",
            action_type="error",
        )
    except GmailAuthorizationError as exc:
        return _result(
            f"Bunnelby could not authorize Gmail: {exc}",
            spoken_reply="Gmail authorization is required. Nothing was sent.",
            action_type="error",
        )
    except GmailRateLimitError:
        return _result(
            "Gmail API rate limit reached. Please retry in a moment.",
            spoken_reply="Gmail is temporarily rate-limited. Nothing was sent.",
            action_type="error",
        )
    except GmailServiceError as exc:
        logger.warning("Standalone Gmail compose failed: %s", exc)
        return _result(
            f"Bunnelby could not prepare the new Gmail message: {exc}",
            spoken_reply="I couldn't prepare that email. Nothing was sent.",
            action_type="error",
        )
