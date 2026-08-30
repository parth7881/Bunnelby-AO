from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app import memory_service
from services.api.app.database import Base
from services.api.app.models import Message


class ToolMemoryContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tempdir.name) / "memory.db"
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session_patch = patch.object(memory_service, "SessionLocal", self.Session)
        self.session_patch.start()
        self.profile_patch = patch.object(
            memory_service,
            "load_user_profile",
            return_value=memory_service.UserProfile(
                profile_id="test",
                preferred_name="Parth",
                assistant_name="Bunnelby",
            ),
        )
        self.profile_patch.start()

    def tearDown(self) -> None:
        self.profile_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()
        self.tempdir.cleanup()

    def _add_turn(self, user: str, assistant: str) -> None:
        with self.Session() as db:
            db.add(Message(role="user", content=user))
            db.add(Message(role="assistant", content=assistant))
            db.commit()

    def test_safe_calendar_result_survives_route_metadata_filter(self) -> None:
        self._add_turn(
            "Am I free tomorrow afternoon?",
            "You're free on Monday, August 31 from 12:00 PM to 5:00 PM.\n"
            "Route: calendar\nWhy: calendar free-busy lookup",
        )

        turns = memory_service._load_safe_turns()
        self.assertEqual(len(turns), 1)
        self.assertIn("You're free on Monday, August 31", turns[0].assistant)
        self.assertNotIn("Route:", turns[0].assistant)
        self.assertNotIn("Why:", turns[0].assistant)

    def test_latest_calendar_work_is_present_for_temporal_recall(self) -> None:
        self._add_turn(
            "What is RAG?",
            "RAG retrieves relevant information before answering.",
        )
        self._add_turn(
            "Schedule Bunnelby Calendar Test tomorrow at 3 PM for 30 minutes.",
            "I've prepared the calendar event. Review it before I create anything.\n"
            "Route: calendar\nWhy: calendar event requires explicit approval",
        )

        context = memory_service.build_memory_context("hamne last kya kaam kiya?")
        self.assertIn("Schedule Bunnelby Calendar Test", context)
        self.assertIn("I've prepared the calendar event", context)
        self.assertNotIn("Route: calendar", context)
        self.assertIn("newest recent turns first", context)

    def test_true_operational_stub_is_still_excluded(self) -> None:
        self._add_turn(
            "Check calendar",
            "This would call the calendar handler",
        )
        self.assertEqual(memory_service._load_safe_turns(), [])


if __name__ == "__main__":
    unittest.main()
