import asyncio
import logging
from datetime import datetime
from database import SessionLocal
from models import BreakLog, WorkSession, User
from bot import get_break_limit

logger = logging.getLogger(__name__)

def get_warning_message(break_type: str) -> str:
    if break_type == "Eat":
        return "Your 30-minute break time is up!"
    elif break_type == "Toilet":
        return "Your 15-minute break time is up!"
    elif break_type in ["Smoke", "Other"]:
        return "Your break time is up!"
    return "Your break time is up!"

async def run_scheduler_loop(bot_app):
    if not bot_app:
        logger.warning("Bot application not initialized. Scheduler loop is inactive.")
        return
        
    logger.info("Starting background scheduler loop...")
    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            with SessionLocal() as db:
                # Query active breaks that haven't been notified yet
                active_breaks = db.query(BreakLog).join(WorkSession).filter(
                    BreakLog.end_time.is_(None),
                    BreakLog.notified.is_(False)
                ).all()
                
                for brk in active_breaks:
                    limit = get_break_limit(brk.break_type)
                    duration = (datetime.now() - brk.start_time).total_seconds()
                    
                    if duration > limit:
                        telegram_id = brk.session.telegram_id
                        msg = get_warning_message(brk.break_type)
                        
                        try:
                            logger.info(f"Sending warning to {telegram_id} for {brk.break_type} break exceeding limit.")
                            await bot_app.bot.send_message(chat_id=telegram_id, text=msg)
                            # Mark as notified
                            brk.notified = True
                            db.commit()
                        except Exception as e:
                            logger.error(f"Failed to send message to user {telegram_id}: {e}")
                            # Mark as notified to prevent infinite retry loops on blocked chats
                            brk.notified = True
                            db.commit()
                            
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            await asyncio.sleep(5)  # Sleep on errors to prevent log flooding
