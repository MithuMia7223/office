from datetime import datetime
from sqlalchemy.orm import Session
from models import User, WorkSession, BreakLog

def get_or_create_user(db: Session, telegram_id: int, username: str = None, first_name: str = None):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Update username or first name if they changed
        if user.username != username or user.first_name != first_name:
            user.username = username
            user.first_name = first_name
            db.commit()
            db.refresh(user)
    return user

def get_active_session(db: Session, telegram_id: int):
    return db.query(WorkSession).filter(
        WorkSession.telegram_id == telegram_id,
        WorkSession.end_time.is_(None)
    ).first()

def start_work_session(db: Session, telegram_id: int):
    active = get_active_session(db, telegram_id)
    if active:
        return active, False  # Already exists
    
    session = WorkSession(telegram_id=telegram_id, status="working")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, True

def get_active_break(db: Session, session_id: int):
    return db.query(BreakLog).filter(
        BreakLog.session_id == session_id,
        BreakLog.end_time.is_(None)
    ).first()

def start_break(db: Session, session_id: int, break_type: str):
    # Close existing break if any (safety fallback)
    active_break = get_active_break(db, session_id)
    if active_break:
        active_break.end_time = datetime.now()
        db.commit()
    
    new_break = BreakLog(session_id=session_id, break_type=break_type)
    db.add(new_break)
    db.commit()
    db.refresh(new_break)
    return new_break

def end_break(db: Session, session_id: int):
    active_break = get_active_break(db, session_id)
    if not active_break:
        return None
    active_break.end_time = datetime.now()
    db.commit()
    db.refresh(active_break)
    return active_break

def end_work_session(db: Session, telegram_id: int):
    active = get_active_session(db, telegram_id)
    if not active:
        return None
    
    # End any active break first
    active_break = get_active_break(db, active.id)
    if active_break:
        active_break.end_time = datetime.now()
        
    active.end_time = datetime.now()
    active.status = "completed"
    db.commit()
    db.refresh(active)
    return active

def delete_user(db: Session, telegram_id: int) -> bool:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return False
    
    # Delete all break logs and sessions using ORM delete
    for session in list(user.sessions):
        for brk in list(session.breaks):
            db.delete(brk)
        db.delete(session)
        
    # Delete the user
    db.delete(user)
    db.commit()
    return True
