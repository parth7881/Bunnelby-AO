from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app import approval_service, gmail_service, message_dispatch
from services.api.app.approval_service import (
    approve_and_execute,
    create_gmail_compose_approval,
    reject_approval,
)
from services.api.app.database import Base


class GmailComposeApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "compose-test.db"
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

    def test_hinglish_address_command_is_detected_as_new_email(self) -> None:
        command = (
            "trj11114@gmail.com es email pr mail kro ki mera automation project "
            "successful create ho gaya hai and apni taraf se long email create kro english me and send kro"
        )
        self.assertTrue(message_dispatch._standalone_email_requested(command))

    def test_compose_draft_keeps_explicit_recipient_and_uses_provider_output(self) -> None:
        fake = SimpleNamespace(
            text=json.dumps({
                "subject": "Automation Project Successfully Completed",
                "body": "Hello,\n\nI’m pleased to share that my automation project has been completed successfully.\n\nBest regards,\nParth",
            }),
            provider="groq",
            model="fixture",
        )
        with patch.object(gmail_service, "generate_gemini_text", return_value=fake):
            draft = gmail_service.draft_new_email_from_request(
                "Send a long professional email to trj11114@gmail.com saying my automation project was completed successfully."
            )

        self.assertEqual(draft["mode"], "compose")
        self.assertEqual(draft["to"], "trj11114@gmail.com")
        self.assertEqual(draft["provider"], "groq")
        self.assertIn("Automation Project", draft["subject"])
        self.assertIn("completed successfully", draft["body"])

    def test_compose_requires_exactly_one_explicit_recipient(self) -> None:
        with self.assertRaises(gmail_service.GmailDraftError):
            gmail_service.draft_new_email_from_request("Write and send a professional project update email.")

        with self.assertRaises(gmail_service.GmailDraftError):
            gmail_service.draft_new_email_from_request(
                "Send this to first@example.com and second@example.com."
            )

    def test_compose_approval_never_sends_before_approval_and_sends_once_after(self) -> None:
        draft = {
            "mode": "compose",
            "thread_id": "",
            "source_message_id": "",
            "source_rfc_message_id": "",
            "references": "",
            "to": "trj11114@gmail.com",
            "recipient_display": "trj11114@gmail.com",
            "subject": "Automation Project Successfully Completed",
            "body": "The automation project has been completed successfully.",
            "instruction": "Send an automation project completion update.",
            "provider": "groq",
            "status": "draft",
        }
        approval = create_gmail_compose_approval(draft, spoken_language="en")

        sent = []
        with patch.object(approval_service, "_send_reply_payload", side_effect=lambda payload: sent.append(dict(payload)) or {"id": "m1", "threadId": "t1"}):
            self.assertEqual(sent, [])
            first = approve_and_execute(approval.id)
            second = approve_and_execute(approval.id)

        self.assertEqual(first.outcome, "sent")
        self.assertEqual(second.outcome, "already_sent")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["mode"], "compose")
        self.assertEqual(sent[0]["recipient"], "trj11114@gmail.com")

    def test_rejected_compose_can_never_send(self) -> None:
        draft = {
            "mode": "compose",
            "thread_id": "",
            "source_message_id": "",
            "source_rfc_message_id": "",
            "references": "",
            "to": "trj11114@gmail.com",
            "recipient_display": "trj11114@gmail.com",
            "subject": "Project update",
            "body": "A safe draft.",
            "instruction": "Draft a project update.",
            "provider": "groq",
            "status": "draft",
        }
        approval = create_gmail_compose_approval(draft, spoken_language="en")
        result = reject_approval(approval.id)
        self.assertEqual(result.outcome, "rejected")

        with patch.object(approval_service, "_send_reply_payload") as send:
            with self.assertRaises(approval_service.ApprovalConflictError):
                approve_and_execute(approval.id)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
