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
    if approval.task_type not in {"gmail_reply", "gmail_compose"}:
        raise ApprovalPayloadError("Approval is not a supported Gmail send action.")

    mode = str(payload.get("mode", "reply")).strip().casefold() or "reply"
    required = ["recipient", "subject", "draft_body"]
    if mode == "reply":
        required.extend(["thread_id", "source_message_id"])
    elif mode != "compose":
        raise ApprovalPayloadError("Stored Gmail approval mode is invalid.")

    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise ApprovalPayloadError(
            "Stored Gmail approval payload is missing required fields: " + ", ".join(missing)
        )

    if str(payload.get("draft_body", "")) != approval.preview_content:
        raise ApprovalPayloadError(
            "Stored Gmail draft no longer matches the approved preview. Refusing to send."
        )
    if str(payload.get("recipient", "")) != approval.target:
        raise ApprovalPayloadError(
            "Stored Gmail recipient no longer matches the approved target. Refusing to send."
        )


def _create_gmail_approval(
    draft: dict[str, str],
    *,
    task_type: Literal["gmail_reply", "gmail_compose"],
    spoken_language: str,
    db: Session | None = None,
) -> Approval:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        recipient = str(draft.get("to", "")).strip()
        subject = str(draft.get("subject", "")).strip()
        body = str(draft.get("body", "")).strip()
        mode = str(draft.get("mode", "reply" if task_type == "gmail_reply" else "compose")).strip()
        thread_id = str(draft.get("thread_id", "")).strip()
        source_message_id = str(draft.get("source_message_id", "")).strip()

        if not all((recipient, subject, body)):
            raise ApprovalPayloadError("Gmail draft is incomplete and cannot be approved.")
        if mode == "reply" and not all((thread_id, source_message_id)):
            raise ApprovalPayloadError("Gmail reply draft is incomplete and cannot be approved.")
        if mode not in {"reply", "compose"}:
            raise ApprovalPayloadError("Gmail draft mode is invalid.")

        payload = {
            "mode": mode,
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
            task_type=task_type,
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


def create_gmail_reply_approval(
    draft: dict[str, str],
    *,
    spoken_language: str,
    db: Session | None = None,
) -> Approval:
    """Persist the exact Gmail reply snapshot that the human will approve."""
    return _create_gmail_approval(
        draft,
        task_type="gmail_reply",
        spoken_language=spoken_language,
        db=db,
    )


def create_gmail_compose_approval(
    draft: dict[str, str],
    *,
    spoken_language: str,
    db: Session | None = None,
) -> Approval:
    """Persist the exact standalone Gmail message that the human will approve."""
    return _create_gmail_approval(
        draft,
        task_type="gmail_compose",
        spoken_language=spoken_language,
        db=db,
    )


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
    """The ONLY production Gmail send boundary for approved reply/compose actions."""
    with SessionLocal() as db:
        existing = db.get(Approval, approval_id)
        if existing is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if existing.task_type not in {"gmail_reply", "gmail_compose"}:
            raise ApprovalConflictError("This approval is not a Gmail send action.")
        if existing.status != "approved":
            raise ApprovalConflictError(
                f"Gmail send requires status=approved; current status is {existing.status}."
            )

        payload = _payload(existing)
        _validate_gmail_snapshot(existing, payload)
        snapshot = dict(payload)

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
                    message="This approved Gmail message was already sent. No duplicate was created.",
                )
            if current.execution_state == "executing":
                return ApprovalExecutionResult(
                    approval=current,
                    outcome="already_processing",
                    message="This approved Gmail message is already being processed.",
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
                    message="The approved Gmail message previously failed and was not retried automatically.",
                )
            raise ApprovalConflictError("This Gmail approval cannot acquire execution ownership.")

        _reload(db, approval_id)

    try:
        gmail_result = _send_reply_payload(snapshot)
    except (GmailAuthorizationError, GmailConfigurationError, GmailRateLimitError) as exc:
        failed = _mark_execution_failure(approval_id, state="failed", error=str(exc))
        return ApprovalExecutionResult(failed, "failed", str(exc))
    except GmailSendUncertainError as exc:
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(unknown, "unknown", str(exc))
    except GmailServiceError as exc:
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(
            unknown,
            "unknown",
            "Gmail did not provide a safe send confirmation. Bunnelby will not retry automatically because that could create a duplicate.",
        )
    except Exception as exc:
        logger.exception("Unexpected Gmail send failure for approval_id=%s", approval_id)
        unknown = _mark_execution_failure(
            approval_id,
            state="unknown",
            error=f"{type(exc).__name__}: {exc}",
        )
        return ApprovalExecutionResult(
            unknown,
            "unknown",
            "The Gmail send result is uncertain. Bunnelby will not retry automatically because that could create a duplicate.",
        )

    message_id = str(gmail_result.get("id", "")).strip()
    thread_id = str(gmail_result.get("threadId", snapshot.get("thread_id", ""))).strip()
    is_compose = str(snapshot.get("mode", "reply")).strip().casefold() == "compose"
    success_message = "Email sent successfully." if is_compose else "Reply sent successfully."
    completion = {
        "message": success_message,
        "gmail_message_id": message_id,
        "gmail_thread_id": thread_id,
    }

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
                    current,
                    "unknown",
                    "Gmail reported success, but local completion recording was inconsistent. Bunnelby will not send again automatically.",
                )
            current = _reload(db, approval_id)
            return ApprovalExecutionResult(current, "sent", success_message)
    except Exception:
        logger.exception("Gmail sent but local finalization failed for approval_id=%s", approval_id)
        try:
            current = _mark_execution_failure(
                approval_id,
                state="unknown",
                error="Gmail reported success but local completion finalization failed.",
            )
        except Exception:
            current = get_approval(approval_id)
        return ApprovalExecutionResult(
            current,
            "unknown",
            "Gmail reported success, but local confirmation could not be finalized. Bunnelby will not retry automatically.",
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

    return send_approved_email(approval_id)


def reject_approval(approval_id: int) -> ApprovalExecutionResult:
    """Atomically reject only a still-pending action."""
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")

        label = "Gmail message" if approval.task_type == "gmail_compose" else "Gmail reply"
        if approval.status == "rejected":
            return ApprovalExecutionResult(
                approval=approval,
                outcome="rejected",
                message=f"The {label} remains rejected. Nothing was sent.",
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
                    message=f"The {label} was rejected. Nothing was sent.",
                )
            raise ApprovalConflictError("This approval could not be rejected safely.")

        current = _reload(db, approval_id)
        return ApprovalExecutionResult(
            approval=current,
            outcome="rejected",
            message=f"The {label} was rejected. Nothing was sent.",
        )
