import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from database import SessionLocal
import crud

# Set up Keyboard
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("Start Work"), KeyboardButton("Off Work")],
        [KeyboardButton("Eat"), KeyboardButton("Toilet"), KeyboardButton("Smoke"), KeyboardButton("Other")],
        [KeyboardButton("Back to Seat")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Helper to format duration in seconds to a nice string
def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 or h > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

# Start Command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with SessionLocal() as db:
        crud.get_or_create_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name
        )
    
    await update.message.reply_text(
        f"Assalamu Alaikum {user.first_name}! Welcome to the Office Work Tracking Bot.\n"
        "Please use the buttons below to log your work status.",
        reply_markup=get_main_keyboard()
    )

# Text Message Router
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    # 1. Start Work Handler
    if text == "Start Work":
        with SessionLocal() as db:
            active_session = crud.get_active_session(db, user.id)
            if active_session:
                await update.message.reply_text("Apni already Start button-e click korchen.")
                return
            
            # Start new session
            session, created = crud.start_work_session(db, user.id)
            start_time_str = session.start_time.strftime("%m/%d %H:%M:%S")
            await update.message.reply_text(
                f"✅ Check-In Succeeded: Start Work - {start_time_str}\n"
                "------------------------------------\n"
                "Hint: Remember to check in when Off Work arrives."
            )

    # 2. Break Handlers (Eat, Toilet, Smoke, Other)
    elif text in ["Eat", "Toilet", "Smoke", "Other"]:
        with SessionLocal() as db:
            active_session = crud.get_active_session(db, user.id)
            if not active_session:
                await update.message.reply_text("Apni ekhono check-in/Start Work korenni. Prothome Start Work-e click korun!")
                return
            
            active_break = crud.get_active_break(db, active_session.id)
            if active_break:
                await update.message.reply_text(
                    f"Apni already ekta break-e achen ({active_break.break_type}). "
                    "Prothome 'Back to Seat'-e click korun!"
                )
                return
            
            # Start break
            new_break = crud.start_break(db, active_session.id, text)
            start_time_str = new_break.start_time.strftime("%m/%d %H:%M:%S")
            
            limits_sec = get_break_limit(text)
            limits_min = int(limits_sec // 60) if limits_sec >= 60 else limits_sec
            unit = "minute" if limits_sec >= 60 else "second"
            
            await update.message.reply_text(
                f"☕ Break Started: {text} - {start_time_str}\n"
                f"Time Limit: {limits_min} {unit}(s)."
            )

    # 3. Back to Seat Handler
    elif text == "Back to Seat":
        with SessionLocal() as db:
            active_session = crud.get_active_session(db, user.id)
            if not active_session:
                await update.message.reply_text("Apni ekhono check-in/Start Work korenni.")
                return
            
            active_break = crud.get_active_break(db, active_session.id)
            if not active_break:
                await update.message.reply_text("Apni ekhon seat-ei achen working state-e!")
                return
            
            # End break
            ended_break = crud.end_break(db, active_session.id)
            duration_sec = (ended_break.end_time - ended_break.start_time).total_seconds()
            end_time_str = ended_break.end_time.strftime("%m/%d %H:%M:%S")
            
            await update.message.reply_text(
                f"💻 Back to Seat: {end_time_str}\n"
                f"Break Type: {ended_break.break_type}\n"
                f"Break Duration: {format_duration(duration_sec)}"
            )

    # 4. Off Work Handler
    elif text == "Off Work":
        with SessionLocal() as db:
            active_session = crud.get_active_session(db, user.id)
            if not active_session:
                await update.message.reply_text("Apni check-in korenni.")
                return
            
            # End session (will auto end active break if any)
            session_id = active_session.id
            ended_session = crud.end_work_session(db, user.id)
            end_time_str = ended_session.end_time.strftime("%m/%d %H:%M:%S")
            
            # Query all breaks for statistics
            from models import BreakLog
            breaks = db.query(BreakLog).filter(BreakLog.session_id == session_id).all()
            
            total_session_seconds = (ended_session.end_time - ended_session.start_time).total_seconds()
            
            break_seconds = {
                "Eat": 0.0,
                "Toilet": 0.0,
                "Smoke": 0.0,
                "Other": 0.0
            }
            
            total_break_seconds = 0.0
            for brk in breaks:
                start = brk.start_time
                end = brk.end_time or ended_session.end_time  # fallback if end_time is null (though crud ends it)
                duration = (end - start).total_seconds()
                if brk.break_type in break_seconds:
                    break_seconds[brk.break_type] += duration
                total_break_seconds += duration
                
            actual_work_seconds = total_session_seconds - total_break_seconds
            if actual_work_seconds < 0:
                actual_work_seconds = 0
            
            await update.message.reply_text(
                f"🔴 Check-Out Succeeded: Off Work - {end_time_str}\n"
                "------------------------------------\n"
                "📊 Work Session Summary:\n"
                f"⏱️ Total Time Checked In: {format_duration(total_session_seconds)}\n"
                f"💻 Actual Work Time: {format_duration(actual_work_seconds)}\n"
                f"☕ Total Break Time: {format_duration(total_break_seconds)}\n\n"
                "Break Details:\n"
                f"🍔 Eat: {format_duration(break_seconds['Eat'])}\n"
                f"🚾 Toilet: {format_duration(break_seconds['Toilet'])}\n"
                f"🚬 Smoke: {format_duration(break_seconds['Smoke'])}\n"
                f"⚙️ Other: {format_duration(break_seconds['Other'])}"
            )
    else:
        await update.message.reply_text("Please use the custom keyboard buttons to interact.")

def get_break_limit(break_type: str) -> float:
    """Returns break limit in seconds."""
    test_mode = os.getenv("TEST_MODE", "False").lower() in ("true", "1", "yes")
    
    # limits in seconds
    limits = {
        "Eat": 30 if test_mode else 30 * 60,
        "Toilet": 15 if test_mode else 15 * 60,
        "Smoke": 10 if test_mode else 10 * 60,
        "Other": 10 if test_mode else 10 * 60,
    }
    return float(limits.get(break_type, 10 * 60))

# Initialize Application
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
    # Fallback to empty if not configured yet, so it won't crash on start until configured
    bot_token = ""

application = None
if bot_token:
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
