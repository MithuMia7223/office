from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    sessions = relationship("WorkSession", back_populates="user")

class WorkSession(Base):
    __tablename__ = "work_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    telegram_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    start_time = Column(DateTime, default=datetime.now, nullable=False)
    end_time = Column(DateTime, nullable=True)
    status = Column(String, default="working")  # working, completed

    user = relationship("User", back_populates="sessions")
    breaks = relationship("BreakLog", back_populates="session")

class BreakLog(Base):
    __tablename__ = "break_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("work_sessions.id"), nullable=False)
    break_type = Column(String, nullable=False)  # Eat, Toilet, Smoke, Other
    start_time = Column(DateTime, default=datetime.now, nullable=False)
    end_time = Column(DateTime, nullable=True)
    notified = Column(Boolean, default=False, nullable=False)

    session = relationship("WorkSession", back_populates="breaks")
