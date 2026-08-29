from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app import approval_service, gmail_service, orchestrator
from services.api.app.approval_service import (
    ApprovalConflictError,
    ApprovalPayloadError,
    approve_and_execute,
    create_gmail_reply_approval,
    reject_approval,
    send_approved_email,
)
from services.api.app.database import Base
from services.api.app.models import Approval


DRAFT = {
    "thread_id": "thread-1",
    "source_message_id": "source-1",
    "source_rfc_message_id": "<source@example.com>",
    "references": "<older@example.com> <source@example.com>",
    "to": "rahul@example.com",
    "recipient_display": "Rahul <rahul@example.com>",
    "subject": "Re: Project update",
    "body": "Hi Rahul,\n\nI'll review the build tonight.\n\nBest,\nParth",
    "instruction": "Reply to Rahul's latest email and say I'll review the build tonight.",
    "provider": "gemini",
    "status": "draft",
}


class Prompt7ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "test.db"
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session_patch = patch.object(approval_service, "SessionLocal", self.Session)
        self.session_patch.start()

    def tearDown(self) -> None:
        self.session_patch.stop()
        self.engine.dispose()
        self.tempdir.cleanup()

    def _new_approval(self):
        return create_gmail_reply_approval(DRAFT, spoken_language="en")

    def test_draft_handler_creates_pending_approval_and_never_sends(self) -> None:
        fake_approval = Approval(
            id=7,
            task_type="gmail_reply",
            preview_content=DRAFT["body"],
            target=DRAFT["to"],
            status="pending",
            payload_json=json.dumps({
                "recipient": DRAFT["to"],
                "subject": DRAFT["subject"],
                "draft_body": DRAFT["body"],
            }),
            execution_state="not_started",
            idempotency_key="fixture",
        )
        with (
            patch.object(orchestrator, "draft_reply_from_request", return_value=DRAFT),
            patch.object(orchestrator, "create_gmail_reply_approval", return_value=fake_approval) as create,
            patch.object(orchestrator, "approval_public_dict", return_value={
                "id": 7,
                "task_type": "gmail_reply",
                "preview_content": DRAFT["body"],
                "target": DRAFT["to"],
                "status": "pending",
                "execution_state": "not_started",
                "recipient": DRAFT["to"],
                "subject": DRAFT["subject"],
                "created_at": "2026-08-30T00:00:00Z",
                "resolved_at": None,
                "executed_at": None,
                "result_message": None,
            }),
            patch.object(approval_service, "_send_reply_payload") as send,
        ):
            result = orchestrator.gmail_handler(
                "Reply to Rahul's latest email and tell him I'll review the build tonight."
            )

        self.assertEqual(create.call_count, 1)
        self.assertEqual(send.call_count, 0)
        self.assertEqual(result.action_type_override, "approval_required")
        self.assertEqual(result.approval["status"], "pending")
        self.assertIn("Nothing will be sent", result.reply)

    def test_direct_send_with_pending_approval_fails_closed(self) -> None:
        approval = self._new_approval()
        with patch.object(approval_service, "_send_reply_payload") as send:
            with self.assertRaises(ApprovalConflictError):
                send_approved_email(approval.id)
        send.assert_not_called()

    def test_approve_sends_exactly_once_and_second_approve_is_idempotent(self) -> None:
        approval = self._new_approval()
        sent_payloads = []

        def fake_send(payload):
            sent_payloads.append(dict(payload))
            return {"id": "gmail-sent-1", "threadId": "thread-1"}

        with patch.object(approval_service, "_send_reply_payload", side_effect=fake_send):
            first = approve_and_execute(approval.id)
            second = approve_and_execute(approval.id)

        self.assertEqual(first.outcome, "sent")
        self.assertEqual(second.outcome, "already_sent")
        self.assertEqual(len(sent_payloads), 1)
        self.assertEqual(sent_payloads[0]["recipient"], DRAFT["to"])
        self.assertEqual(sent_payloads[0]["draft_body"], DRAFT["body"])

    def test_two_concurrent_approvals_cannot_double_send(self) -> None:
        approval = self._new_approval()
        counter = 0
        lock = threading.Lock()

        def fake_send(_payload):
            nonlocal counter
            with lock:
                counter += 1
            return {"id": "gmail-sent-race", "threadId": "thread-1"}

        with patch.object(approval_service, "_send_reply_payload", side_effect=fake_send):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: approve_and_execute(approval.id), range(2)))

        self.assertEqual(counter, 1)
        self.assertIn("sent", {item.outcome for item in results})
        self.assertTrue({item.outcome for item in results} <= {"sent", "already_sent", "already_processing"})

    def test_rejected_approval_can_never_send(self) -> None:
        approval = self._new_approval()
        rejected = reject_approval(approval.id)
        self.assertEqual(rejected.outcome, "rejected")

        with patch.object(approval_service, "_send_reply_payload") as send:
            with self.assertRaises(ApprovalConflictError):
                approve_and_execute(approval.id)
            with self.assertRaises(ApprovalConflictError):
                send_approved_email(approval.id)
        send.assert_not_called()

    def test_immutable_preview_mismatch_blocks_send(self) -> None:
        approval = self._new_approval()
        with self.Session() as db:
            row = db.get(Approval, approval.id)
            row.status = "approved"
            row.preview_content = "Tampered preview"
            db.commit()

        with patch.object(approval_service, "_send_reply_payload") as send:
            with self.assertRaises(ApprovalPayloadError):
                send_approved_email(approval.id)
        send.assert_not_called()

    def test_approve_reject_race_has_one_decision_winner(self) -> None:
        approval = self._new_approval()

        with patch.object(
            approval_service,
            "_send_reply_payload",
            return_value={"id": "gmail-race", "threadId": "thread-1"},
        ) as send:
            def approve_call():
                try:
                    return ("approve", approve_and_execute(approval.id).outcome)
                except ApprovalConflictError:
                    return ("approve", "conflict")

            def reject_call():
                try:
                    return ("reject", reject_approval(approval.id).outcome)
                except ApprovalConflictError:
                    return ("reject", "conflict")

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda fn: fn(), (approve_call, reject_call)))

        with self.Session() as db:
            final = db.get(Approval, approval.id)
            self.assertIn(final.status, {"approved", "rejected"})
            if final.status == "rejected":
                self.assertEqual(send.call_count, 0)
                self.assertIsNone(final.executed_at)
            else:
                self.assertLessEqual(send.call_count, 1)
                self.assertNotEqual(final.execution_state, "not_started")
        self.assertIn("conflict", {value for _, value in results})

    def test_oauth_scope_upgrade_requires_send_scope(self) -> None:
        self.assertFalse(
            gmail_service._payload_has_required_scopes(
                {"scopes": [gmail_service.GMAIL_READONLY_SCOPE]}
            )
        )
        self.assertTrue(
            gmail_service._payload_has_required_scopes(
                {
                    "scopes": [
                        gmail_service.GMAIL_READONLY_SCOPE,
                        gmail_service.GMAIL_SEND_SCOPE,
                    ]
                }
            )
        )

    def test_reply_target_prefers_reply_to_header(self) -> None:
        name, address = gmail_service._reply_address({
            "from": "Notifications <no-reply@example.com>",
            "reply-to": "Rahul Team <rahul@example.com>",
        })
        self.assertEqual(name, "Rahul Team")
        self.assertEqual(address, "rahul@example.com")

    def test_reply_mime_preserves_thread_and_reply_headers(self) -> None:
        raw, thread_id = gmail_service._build_reply_raw({
            "recipient": DRAFT["to"],
            "subject": DRAFT["subject"],
            "draft_body": DRAFT["body"],
            "thread_id": DRAFT["thread_id"],
            "source_rfc_message_id": DRAFT["source_rfc_message_id"],
            "references": DRAFT["references"],
        })

        import base64
        from email import policy
        from email.parser import BytesParser

        padded = raw + "=" * (-len(raw) % 4)
        message = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(padded.encode("ascii"))
        )

        self.assertEqual(thread_id, DRAFT["thread_id"])
        self.assertEqual(message["To"], DRAFT["to"])
        self.assertEqual(message["Subject"], DRAFT["subject"])
        self.assertEqual(message["In-Reply-To"], DRAFT["source_rfc_message_id"])
        self.assertEqual(message["References"], DRAFT["references"])
        self.assertIn("I'll review the build tonight.", message.get_content())


if __name__ == "__main__":
    unittest.main()
