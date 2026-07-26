import unittest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import User, WorkSession, BreakLog
import crud
from scheduler import get_warning_message

# Setup in-memory sqlite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class TestOfficeTrackerLogic(unittest.TestCase):
    def setUp(self):
        # Create tables
        Base.metadata.create_all(bind=engine)
        self.db = TestingSessionLocal()
        
        # Create test user
        self.telegram_id = 123456789
        self.username = "test_user"
        self.first_name = "Test"
        crud.get_or_create_user(self.db, self.telegram_id, self.username, self.first_name)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=engine)

    def test_start_work_session(self):
        # First check-in
        session, created = crud.start_work_session(self.db, self.telegram_id)
        self.assertTrue(created)
        self.assertEqual(session.status, "working")
        self.assertIsNone(session.end_time)
        
        # Second check-in (should return existing, created = False)
        session2, created2 = crud.start_work_session(self.db, self.telegram_id)
        self.assertFalse(created2)
        self.assertEqual(session.id, session2.id)

    def test_breaks_logic(self):
        # Check-in
        session, _ = crud.start_work_session(self.db, self.telegram_id)
        
        # Start Eat break
        brk = crud.start_break(self.db, session.id, "Eat")
        self.assertEqual(brk.break_type, "Eat")
        self.assertIsNone(brk.end_time)
        self.assertFalse(brk.notified)
        
        # Get active break
        active_break = crud.get_active_break(self.db, session.id)
        self.assertIsNotNone(active_break)
        self.assertEqual(active_break.id, brk.id)
        
        # End break (Back to Seat)
        ended_break = crud.end_break(self.db, session.id)
        self.assertIsNotNone(ended_break.end_time)
        
        # Verify no active break now
        active_break_after = crud.get_active_break(self.db, session.id)
        self.assertIsNone(active_break_after)

    def test_off_work_stats(self):
        # Check-in
        session, _ = crud.start_work_session(self.db, self.telegram_id)
        
        # Override start_time to 1 hour ago
        session.start_time = datetime.now() - timedelta(hours=1)
        self.db.commit()
        
        # Add a break of 20 minutes
        brk = crud.start_break(self.db, session.id, "Toilet")
        brk.start_time = datetime.now() - timedelta(minutes=20)
        self.db.commit()
        
        # End break
        crud.end_break(self.db, session.id)
        
        # Off Work
        ended_session = crud.end_work_session(self.db, self.telegram_id)
        self.assertEqual(ended_session.status, "completed")
        self.assertIsNotNone(ended_session.end_time)
        
        # Verify durations in DB
        breaks = self.db.query(BreakLog).filter(BreakLog.session_id == session.id).all()
        total_session_seconds = (ended_session.end_time - ended_session.start_time).total_seconds()
        
        # Session duration should be approx 1 hour (3600s)
        self.assertAlmostEqual(total_session_seconds, 3600, delta=10)
        
        # Break duration should be approx 20 mins (1200s)
        total_break_seconds = sum((b.end_time - b.start_time).total_seconds() for b in breaks)
        self.assertAlmostEqual(total_break_seconds, 1200, delta=10)
        
        actual_work_seconds = total_session_seconds - total_break_seconds
        # Actual work should be approx 40 mins (2400s)
        self.assertAlmostEqual(actual_work_seconds, 2400, delta=10)

    def test_warning_message_selection(self):
        self.assertEqual(get_warning_message("Eat"), "Apnar 30 minute time shesh hoye geche")
        self.assertEqual(get_warning_message("Toilet"), "Apnar 15 minute time shesh")
        self.assertEqual(get_warning_message("Smoke"), "Apnar time shesh")
        self.assertEqual(get_warning_message("Other"), "Apnar time shesh")

if __name__ == "__main__":
    unittest.main()
