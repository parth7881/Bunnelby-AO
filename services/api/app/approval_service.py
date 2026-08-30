from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import update
from sqlalchemy.orm import Session

from .calendar_service import (
    CalendarAuthorizationError,
    CalendarConfigurationError,
    CalendarExecutionUncertainError,
    CalendarRateLimitError,
    CalendarServiceError,
    create_event,
)
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
    "created",
    "rejected",
    "already_sent",
    "already_created",
    "already_processing",
    "failed",
    "unknown",
]


class ApprovalError(RuntimeError):
    pass


class ApprovalNotFoundError(ApprovalError):
    pass


class ApprovalConflictError(ApprovalError):
    pass


class ApprovalPayloadError(ApprovalError):
    pass


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
        raise ApprovalPayloadError("Stored Gmail draft no longer matches the approved preview. Refusing to send.")
    if str(payload.get("recipient", "")) != approval.target:
        raise ApprovalPayloadError("Stored Gmail recipient no longer matches the approved target. Refusing to send.")


def _validate_calendar_snapshot(approval: Approval, payload: dict[str, Any]) -> None:
    if approval.task_type != "calendar_event":
        raise ApprovalPayloadError("Approval is not a Calendar event action.")
    required = ("title", "start", "end", "timezone", "calendar_id")
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing:
        raise ApprovalPayloadError(
            "Stored Calendar approval payload is missing required fields: " + ", ".join(missing)
        )
    attendees = payload.get("attendees", [])
    if not isinstance(attendees, list):
        raise ApprovalPayloadError("Stored Calendar attendee list is invalid.")
    expected_preview = _calendar_preview(payload)
    if approval.preview_content != expected_preview:
        raise ApprovalPayloadError("Stored Calendar event no longer matches the reviewed preview. Refusing to create it.")
    if approval.target != str(payload.get("calendar_id")):
        raise ApprovalPayloadError("Stored Calendar target no longer matches the approved calendar.")


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


def create_gmail_reply_approval(draft: dict[str, str], *, spoken_language: str, db: Session | None = None) -> Approval:
    return _create_gmail_approval(draft, task_type="gmail_reply", spoken_language=spoken_language, db=db)


def create_gmail_compose_approval(draft: dict[str, str], *, spoken_language: str, db: Session | None = None) -> Approval:
    return _create_gmail_approval(draft, task_type="gmail_compose", spoken_language=spoken_language, db=db)


def _calendar_preview(payload: dict[str, Any]) -> str:
    attendees = payload.get("attendees") or []
    attendee_text = ", ".join(str(item) for item in attendees) if attendees else "None"
    return (
        f"Title: {payload.get('title', '')}\n"
        f"Start: {payload.get('start', '')}\n"
        f"End: {payload.get('end', '')}\n"
        f"Timezone: {payload.get('timezone', '')}\n"
        f"Attendees: {attendee_text}"
    )


def create_calendar_event_approval(
    proposal: dict[str, Any],
    *,
    spoken_language: str,
    db: Session | None = None,
) -> Approval:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        payload = {
            "title": str(proposal.get("title", "")).strip(),
            "start": str(proposal.get("start", "")).strip(),
            "end": str(proposal.get("end", "")).strip(),
            "timezone": str(proposal.get("timezone", "")).strip(),
            "attendees": list(proposal.get("attendees") or []),
            "calendar_id": str(proposal.get("calendar_id", "primary")).strip() or "primary",
            "duration_minutes": int(proposal.get("duration_minutes", 0) or 0),
            "assumed_duration": bool(proposal.get("assumed_duration", False)),
            "spoken_language": "hi" if spoken_language == "hi" else "en",
        }
        if not all((payload["title"], payload["start"], payload["end"], payload["timezone"], payload["calendar_id"])):
            raise ApprovalPayloadError("Calendar event proposal is incomplete and cannot be approved.")
        preview = _calendar_preview(payload)
        approval = Approval(
            task_type="calendar_event",
            preview_content=preview,
            target=payload["calendar_id"],
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
    try:
        payload = _payload(approval)
    except ApprovalPayloadError:
        payload = {}
    result_message = None
    if approval.execution_result:
        try:
            parsed = json.loads(approval.execution_result)
            if isinstance(parsed, dict):
                result_message = str(parsed.get("message") or "").strip() or None
        except json.JSONDecodeError:
            pass
    result = {
        "id": approval.id,
        "task_type": approval.task_type,
        "preview_content": approval.preview_content,
        "target": approval.target,
        "status": approval.status,
        "execution_state": approval.execution_state,
        "recipient": str(payload.get("recipient", "")).strip() or None,
        "subject": str(payload.get("subject", "")).strip() or None,
        "title": str(payload.get("title", "")).strip() or None,
        "start": str(payload.get("start", "")).strip() or None,
        "end": str(payload.get("end", "")).strip() or None,
        "timezone": str(payload.get("timezone", "")).strip() or None,
        "attendees": payload.get("attendees") if isinstance(payload.get("attendees"), list) else None,
        "calendar_id": str(payload.get("calendar_id", "")).strip() or None,
        "created_at": approval.created_at,
        "resolved_at": approval.resolved_at,
        "executed_at": approval.executed_at,
        "result_message": result_message,
    }
    return result


def _reload(session: Session, approval_id: int) -> Approval:
    session.expire_all()
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
    return approval


def _mark_execution_failure(approval_id: int, *, state: Literal["failed", "unknown"], error: str) -> Approval:
    with SessionLocal() as db:
        db.execute(
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.status == "approved",
                Approval.execution_state == "executing",
            )
            .values(execution_state=state, execution_error=error[:2000])
        )
        db.commit()
        return _reload(db, approval_id)


def _claim_execution(approval_id: int, *, allowed_task_types: set[str]) -> tuple[Approval, dict[str, Any]]:
    with SessionLocal() as db:
        existing = db.get(Approval, approval_id)
        if existing is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if existing.task_type not in allowed_task_types:
            raise ApprovalConflictError("This approval is not valid for the requested execution path.")
        if existing.status != "approved":
            raise ApprovalConflictError(f"Execution requires status=approved; current status is {existing.status}.")
        payload = _payload(existing)
        if existing.task_type == "calendar_event":
            _validate_calendar_snapshot(existing, payload)
        else:
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
                return current, {}
            if current.execution_state == "executing":
                return current, {"_already_processing": True}
            if current.execution_state in {"failed", "unknown"}:
                return current, {"_blocked_state": current.execution_state}
            raise ApprovalConflictError("This approval cannot acquire execution ownership.")
        return _reload(db, approval_id), snapshot


def _finalize_success(approval_id: int, completion: dict[str, Any]) -> Approval:
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
            raise ApprovalConflictError("External action succeeded, but local completion recording was inconsistent.")
        return _reload(db, approval_id)


def send_approved_email(approval_id: int) -> ApprovalExecutionResult:
    current, snapshot = _claim_execution(
        approval_id,
        allowed_task_types={"gmail_reply", "gmail_compose"},
    )
    if not snapshot:
        if current.execution_state == "completed":
            return ApprovalExecutionResult(current, "already_sent", "This Gmail message was already sent. No duplicate was created.")
        if current.execution_state == "executing":
            return ApprovalExecutionResult(current, "already_processing", "This Gmail message is already being processed.")
        outcome: ApprovalOutcome = "unknown" if current.execution_state == "unknown" else "failed"
        return ApprovalExecutionResult(current, outcome, "This Gmail action is blocked from automatic retry.")

    try:
        gmail_result = _send_reply_payload(snapshot)
    except (GmailAuthorizationError, GmailConfigurationError, GmailRateLimitError) as exc:
        failed = _mark_execution_failure(approval_id, state="failed", error=str(exc))
        return ApprovalExecutionResult(failed, "failed", str(exc))
    except (GmailSendUncertainError, GmailServiceError) as exc:
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(unknown, "unknown", "Gmail send confirmation is uncertain. Bunnelby will not retry automatically.")

    is_compose = str(snapshot.get("mode", "reply")).strip().casefold() == "compose"
    message = "Email sent successfully." if is_compose else "Reply sent successfully."
    try:
        done = _finalize_success(
            approval_id,
            {
                "message": message,
                "gmail_message_id": str(gmail_result.get("id", "")).strip(),
                "gmail_thread_id": str(gmail_result.get("threadId", snapshot.get("thread_id", ""))).strip(),
            },
        )
        return ApprovalExecutionResult(done, "sent", message)
    except Exception:
        unknown = _mark_execution_failure(approval_id, state="unknown", error="Gmail succeeded but local finalization failed.")
        return ApprovalExecutionResult(unknown, "unknown", "Gmail reported success, but local confirmation could not be finalized. Bunnelby will not retry automatically.")


def create_approved_calendar_event(approval_id: int) -> ApprovalExecutionResult:
    current, snapshot = _claim_execution(approval_id, allowed_task_types={"calendar_event"})
    if not snapshot:
        if current.execution_state == "completed":
            return ApprovalExecutionResult(current, "already_created", "This Calendar event was already created. No duplicate was created.")
        if current.execution_state == "executing":
            return ApprovalExecutionResult(current, "already_processing", "This Calendar event is already being processed.")
        outcome: ApprovalOutcome = "unknown" if current.execution_state == "unknown" else "failed"
        return ApprovalExecutionResult(current, outcome, "This Calendar action is blocked from automatic retry.")

    event_id = hashlib.sha256(current.idempotency_key.encode("utf-8")).hexdigest()[:32]
    try:
        result = create_event(
            snapshot["title"],
            snapshot["start"],
            snapshot["end"],
            snapshot.get("attendees") or [],
            calendar_id=snapshot.get("calendar_id") or "primary",
            timezone_name=snapshot.get("timezone") or None,
            event_id=event_id,
        )
    except (CalendarAuthorizationError, CalendarConfigurationError, CalendarRateLimitError) as exc:
        failed = _mark_execution_failure(approval_id, state="failed", error=str(exc))
        return ApprovalExecutionResult(failed, "failed", str(exc))
    except (CalendarExecutionUncertainError, CalendarServiceError) as exc:
        unknown = _mark_execution_failure(approval_id, state="unknown", error=str(exc))
        return ApprovalExecutionResult(unknown, "unknown", "Calendar creation confirmation is uncertain. Bunnelby will not retry automatically.")

    try:
        done = _finalize_success(
            approval_id,
            {
                "message": "Event created successfully.",
                "calendar_event_id": str(result.get("id", "")).strip(),
                "calendar_html_link": str(result.get("htmlLink", "")).strip(),
            },
        )
        return ApprovalExecutionResult(done, "created", "Event created successfully.")
    except Exception:
        unknown = _mark_execution_failure(approval_id, state="unknown", error="Calendar succeeded but local finalization failed.")
        return ApprovalExecutionResult(unknown, "unknown", "Google Calendar reported success, but local confirmation could not be finalized. Bunnelby will not retry automatically.")


def approve_and_execute(approval_id: int) -> ApprovalExecutionResult:
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if approval.status == "rejected":
            raise ApprovalConflictError("This action was rejected and cannot be approved later.")
        task_type = approval.task_type
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

    if task_type == "calendar_event":
        return create_approved_calendar_event(approval_id)
    if task_type in {"gmail_reply", "gmail_compose"}:
        return send_approved_email(approval_id)
    raise ApprovalConflictError(f"Unsupported approval task type: {task_type}")


def reject_approval(approval_id: int) -> ApprovalExecutionResult:
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval {approval_id} was not found.")
        if approval.status == "rejected":
            return ApprovalExecutionResult(approval, "rejected", "The action remains rejected. Nothing was executed.")
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
                return ApprovalExecutionResult(current, "rejected", "The action was rejected. Nothing was executed.")
            raise ApprovalConflictError("This approval could not be rejected safely.")
        current = _reload(db, approval_id)
        return ApprovalExecutionResult(current, "rejected", "The action was rejected. Nothing was executed.")
