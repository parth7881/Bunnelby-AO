from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import update
from sqlalchemy.orm import Session

from .database import SessionLocal
from .gmail_service import (
    GmailAuthorizationError,
    GmailConfigurationError,
    GmailRateLimitError,
    GmailSendUncertainError,
    GmailServiceError,
    _send_reply_payload,
)
from .models import Approval

logger = logging.getLogger(__name__)

ApprovalOutcome = Literal[
    "sent",
    "rejected",
    "already_sent",
    "already_processing",
    "failed",
    "unknown",
]


class ApprovalError(RuntimeError):
    """Base exception for durable human-approval actions."""


class ApprovalNotFoundError(ApprovalError):
    """Raised when an approval id does not exist."""


class ApprovalConflictError(ApprovalError):
    """Raised when an approval decision cannot transition from its current state."""


class ApprovalPayloadError(ApprovalError):
    """Raised when an immutable approval snapshot is malformed or inconsistent."""


@dataclass(frozen=True)
class ApprovalExecutionResult:
    approval: Approval
    outcome: ApprovalOutcome
    message: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(approval: Approval) -> dict[str, Any]:
    try:
        value = json.loads(approval.payload_json)
    except json.JSONDecodeError as exc:
        raise ApprovalPayloadError("Stored approval payload is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ApprovalPayloadError("Stored approval payload is not an object.")
    return value


def _validate_gmail_snapshot(approval: Approval, payload: dict[str, Any]) -> None:
    if approval.task_type != "gmail_reply":
        raise ApprovalPayloadError("Approval is not a Gmail reply action.")

    required = ("thread_id", "source_message_id", "recipient", "subject", "draft_body")
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise ApprovalPayloadError(
            "Stored Gmail approval payload is missing required fields: " + ", ".join(missing)
        )

    # The preview displayed to the human is the exact body that must cross the send boundary.
    if str(payload.get("draft_body", "")) != approval.preview_content:
        raise ApprovalPayloadError(
            "Stored Gmail draft no longer matches the approved preview. Refusing to send."
        )
    if str(payload.get("recipient", "")) != approval.target:
        raise ApprovalPayloadError(
            "Stored Gmail recipient no longer matches the approved target. Refusing to send."
        )


def create_gmail_reply_approval(
    draft: dict[str, str],
    *,
    spoken_language: str,
    db: Session | None = None,
) -> Approval:
    """Persist the exact Gmail draft snapshot that the human will approve."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        recipient = str(draft.get("to", "")).strip()
        subject = str(draft.get("subject", "")).strip()
        body = str(draft.get("body", "")).strip()
        thread_id = str(draft.get("thread_id", "")).strip()
        source_message_id = str(draft.get("source_message_id", "")).strip()
        if not all((recipient, subject, body, thread_id, source_message_id)):
            raise ApprovalPayloadError("Gmail draft is incomplete and cannot be approved.")

        payload = {
            "thread_id": thread_id,
            "source_message_id": source_message_id,
            "source_rfc_message_id": str(draft.get("source_rfc_message_id", "")).strip(),
            "references": str(draft.get("references", "")).strip(),
            "recipient": recipient,
            "recipient_display": str(draft.get("recipient_display", "")).strip(),
            "subject": subject,
            "draft_body": body,
            "instruction": str(draft.get("instruction", "")).strip(),
            "spoken_language": "hi" if spoken_language == "hi" else "en",
        }

        approval = Approval(
            task_type="gmail_reply",
            preview_content=body,
            target=recipient,
            status="pending",
            payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            execution_state="not_started",
            idempotency_key=str(uuid.uuid4()),
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        return approval
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def get_approval(approval_id: int, *, db: Session | None = None) -> Approval:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if owns_session:
            session.expunge(approval)
        return approval
    finally:
        if owns_session:
            session.close()


def approval_spoken_language(approval: Approval) -> str:
    try:
        payload = _payload(approval)
    except ApprovalPayloadError:
        return "en"
    return "hi" if str(payload.get("spoken_language", "")).strip() == "hi" else "en"


def approval_public_dict(approval: Approval) -> dict[str, Any]:
    payload: dict[str, Any]
    try:
        payload = _payload(approval)
    except ApprovalPayloadError:
        payload = {}

    result_message = None
    if approval.execution_result:
        try:
            result_payload = json.loads(approval.execution_result)
            if isinstance(result_payload, dict):
                result_message = str(result_payload.get("message") or "").strip() or None
        except json.JSONDecodeError:
            result_message = None

    return {
        "id": approval.id,
        "task_type": approval.task_type,
        "preview_content": approval.preview_content,
        "target": approval.target,
        "status": approval.status,
        "execution_state": approval.execution_state,
        "recipient": str(payload.get("recipient", "")).strip() or None,
        "subject": str(payload.get("subject", "")).strip() or None,
        "created_at": approval.created_at,
        "resolved_at": approval.resolved_at,
        "executed_at": approval.executed_at,
        "result_message": result_message,
    }


def _reload(session: Session, approval_id: int) -> Approval:
    session.expire_all()
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
    return approval


def _mark_execution_failure(
    approval_id: int,
    *,
    state: Literal["failed", "unknown"],
    error: str,
) -> Approval:
    with SessionLocal() as db:
        db.execute(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.status == "approved",
                Approval.execution_state == "executing",
            )
            .values(
                execution_state=state,
                execution_error=error[:2000],
            )
        )
        db.commit()
        return _reload(db, approval_id)


def send_approved_email(approval_id: int) -> ApprovalExecutionResult:
    """The ONLY production Gmail send boundary.

    SECURITY ENFORCEMENT:
    1) the approval row must still have status='approved';
    2) execution_state must atomically transition not_started -> executing;
    3) executed_at must still be NULL;
    4) the immutable stored payload must match the preview and target.

    Only after all four conditions pass is gmail_service._send_reply_payload() called.
    Duplicate or concurrent calls cannot acquire the same execution claim twice.
    """
    with SessionLocal() as db:
        existing = db.get(Approval, approval_id)
        if existing is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if existing.task_type != "gmail_reply":
            raise ApprovalConflictError("This approval is not a Gmail reply action.")
        if existing.status != "approved":
            raise ApprovalConflictError(
                f"Gmail send requires status=approved; current status is {existing.status}."
            )

        # Validate the immutable human-reviewed snapshot before acquiring execution ownership.
        payload = _payload(existing)
        _validate_gmail_snapshot(existing, payload)
        snapshot = dict(payload)

        # SECURITY + IDEMPOTENCY BOUNDARY: one transaction wins this conditional update.
        claim = db.execute(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.status == "approved",
                Approval.execution_state == "not_started",
                Approval.executed_at.is_(None),
            )
            .values(execution_state="executing")
        )
        db.commit()

        if claim.rowcount != 1:
            current = _reload(db, approval_id)
            if current.execution_state == "completed" or current.executed_at is not None:
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="already_sent",
                    message="This approved Gmail reply was already sent. No duplicate was created.",
                )
            if current.execution_state == "executing":
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="already_processing",
                    message="This approved Gmail reply is already being processed.",
                )
            if current.execution_state == "unknown":
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="unknown",
                    message=(
                        "The previous Gmail send result is uncertain. Bunnelby will not retry "
                        "automatically because that could create a duplicate."
                    ),
                )
            if current.execution_state == "failed":
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="failed",
                    message="The approved Gmail reply previously failed and was not retried automatically.",
                )
            raise ApprovalConflictError("This Gmail approval cannot acquire execution ownership.")

        _reload(db, approval_id)

    try:
        # NO Gmail send call exists before the status+claim+snapshot guards above.
        gmail_result = _send_reply_payload(snapshot)
    except (GmailAuthorizationError, GmailConfigurationError, GmailRateLimitError) as exc:
        failed = _mark_execution_failure(approval_id, state="failed", error=str(exc))
        return ApprovalExecutionResult(
            approval=failed,
            outcome="failed",
            message=str(exc),
        )
    except GmailSendUncertainError as exc:
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(
            approval=unknown,
            outcome="unknown",
            message=str(exc),
        )
    except GmailServiceError as exc:
        # Be conservative: after a generic Gmail send-path error, do not auto-retry.
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(
            approval=unknown,
            outcome="unknown",
            message=(
                "Gmail did not provide a safe send confirmation. Bunnelby will not retry "
                "automatically because that could create a duplicate."
            ),
        )
    except Exception as exc:
        logger.exception("Unexpected Gmail send failure for approval_id=%s", approval_id)
        unknown = _mark_execution_failure(
            approval_id,
            state="unknown",
            error=f"{type(exc).__name__}: {exc}",
        )
        return ApprovalExecutionResult(
            approval=unknown,
            outcome="unknown",
            message=(
                "The Gmail send result is uncertain. Bunnelby will not retry automatically "
                "because that could create a duplicate."
            ),
        )

    message_id = str(gmail_result.get("id", "")).strip()
    thread_id = str(gmail_result.get("threadId", snapshot.get("thread_id", ""))).strip()
    completion = {
        "message": "Reply sent successfully.",
        "gmail_message_id": message_id,
        "gmail_thread_id": thread_id,
    }

    # If this final DB write fails after Gmail accepted the message, the row remains
    # executing. That intentionally blocks automatic retries and therefore avoids double-send.
    try:
        with SessionLocal() as db:
            finalized = db.execute(
                update(Approval)
                .where(
                    Approval.id == approval_id,
                    Approval.status == "approved",
                    Approval.execution_state == "executing",
                    Approval.executed_at.is_(None),
                )
                .values(
                    execution_state="completed",
                    executed_at=utc_now(),
                    execution_result=json.dumps(completion, separators=(",", ":")),
                    execution_error=None,
                )
            )
            db.commit()
            if finalized.rowcount != 1:
                current = _reload(db, approval_id)
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="unknown",
                    message=(
                        "Gmail reported success, but local completion recording was inconsistent. "
                        "Bunnelby will not send again automatically."
                    ),
                )
            current = _reload(db, approval_id)
            return ApprovalExecutionResult(
                approval=current,
                outcome="sent",
                message="Reply sent successfully.",
            )
    except Exception:
        logger.exception("Gmail sent but local finalization failed for approval_id=%s", approval_id)
        # Do not issue another send. If possible leave/restore an unknown marker.
        try:
            current = _mark_execution_failure(
                approval_id,
                state="unknown",
                error="Gmail reported success but local completion finalization failed.",
            )
        except Exception:
            current = get_approval(approval_id)
        return ApprovalExecutionResult(
            approval=current,
            outcome="unknown",
            message=(
                "Gmail reported success, but local confirmation could not be finalized. "
                "Bunnelby will not retry automatically."
            ),
        )


def approve_and_execute(approval_id: int) -> ApprovalExecutionResult:
    """Atomically record human approval, then invoke the guarded send boundary."""
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if approval.status == "rejected":
            raise ApprovalConflictError("This action was rejected and cannot be approved later.")

        if approval.status == "pending":
            decision = db.execute(
                update(Approval)
                .where(Approval.id == approval_id, Approval.status == "pending")
                .values(status="approved", resolved_at=utc_now())
            )
            db.commit()
            if decision.rowcount != 1:
                approval = _reload(db, approval_id)
                if approval.status == "rejected":
                    raise ApprovalConflictError("This action was rejected before approval completed.")
        elif approval.status != "approved":
            raise ApprovalConflictError(f"Unsupported approval status: {approval.status}")

    # Safe even when two approve requests race: send_approved_email has the atomic claim.
    return send_approved_email(approval_id)


def reject_approval(approval_id: int) -> ApprovalExecutionResult:
    """Atomically reject only a still-pending action."""
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")

        if approval.status == "rejected":
            return ApprovalExecutionResult(
                approval=approval,
                outcome="rejected",
                message="The Gmail reply remains rejected. Nothing was sent.",
            )
        if approval.status == "approved":
            raise ApprovalConflictError("This action was already approved and cannot be rejected now.")

        decision = db.execute(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.status == "pending",
                Approval.execution_state == "not_started",
            )
            .values(status="rejected", resolved_at=utc_now())
        )
        db.commit()
        if decision.rowcount != 1:
            current = _reload(db, approval_id)
            if current.status == "approved":
                raise ApprovalConflictError("This action was approved before rejection completed.")
            if current.status == "rejected":
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="rejected",
                    message="The Gmail reply was rejected. Nothing was sent.",
                )
            raise ApprovalConflictError("This approval could not be rejected safely.")

        current = _reload(db, approval_id)
        return ApprovalExecutionResult(
            approval=current,
            outcome="rejected",
            message="The Gmail reply was rejected. Nothing was sent.",
        )
