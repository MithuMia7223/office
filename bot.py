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

# Helper to check if user is authorized (Admin is always authorized & auto-registered)
def is_authorized(db, user) -> bool:
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if user.id == admin_id:
        crud.get_or_create_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name
        )
        return True
    
    from models import User
    db_user = db.query(User).filter(User.telegram_id == user.id).first()
    if db_user:
        # Update username/first_name if they changed
        if db_user.username != user.username or db_user.first_name != user.first_name:
            db_user.username = user.username
            db_user.first_name = user.first_name
            db.commit()
        return True
        
    return False

# Start Command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        authorized = is_authorized(db, user)
    
    if not authorized:
        await update.message.reply_text(
            f"Assalamu Alaikum {user.first_name}!\n"
            "❌ Apni ekhono register korenni. Tracking korar jonno Admin-ke bolun apnake add korte.\n"
            f"Apnar Chat ID: `{user.id}`",
            parse_mode="Markdown"
        )
        return
        
    await update.message.reply_text(
        f"Assalamu Alaikum {user.first_name}! Welcome to the Office Work Tracking Bot.\n"
        "Please use the buttons below to log your work status.",
        reply_markup=get_main_keyboard()
    )

# Core Tracking Actions
async def start_work_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not is_authorized(db, user):
            await update.message.reply_text(
                "❌ Apni registered user na. Tracking korar jonno Admin-ke bolun apnake add korte.\n"
                f"Apnar Chat ID: `{user.id}`",
                parse_mode="Markdown"
            )
            return
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

async def break_action(update: Update, context: ContextTypes.DEFAULT_TYPE, break_type: str):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not is_authorized(db, user):
            await update.message.reply_text(
                "❌ Apni registered user na. Tracking korar jonno Admin-ke bolun apnake add korte.\n"
                f"Apnar Chat ID: `{user.id}`",
                parse_mode="Markdown"
            )
            return
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
        new_break = crud.start_break(db, active_session.id, break_type)
        start_time_str = new_break.start_time.strftime("%m/%d %H:%M:%S")
        
        limits_sec = get_break_limit(break_type)
        limits_min = int(limits_sec // 60) if limits_sec >= 60 else limits_sec
        unit = "minute" if limits_sec >= 60 else "second"
        
        await update.message.reply_text(
            f"☕ Break Started: {break_type} - {start_time_str}\n"
            f"Time Limit: {limits_min} {unit}(s)."
        )

async def back_to_seat_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not is_authorized(db, user):
            await update.message.reply_text(
                "❌ Apni registered user na. Tracking korar jonno Admin-ke bolun apnake add korte.\n"
                f"Apnar Chat ID: `{user.id}`",
                parse_mode="Markdown"
            )
            return
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

async def off_work_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not is_authorized(db, user):
            await update.message.reply_text(
                "❌ Apni registered user na. Tracking korar jonno Admin-ke bolun apnake add korte.\n"
                f"Apnar Chat ID: `{user.id}`",
                parse_mode="Markdown"
            )
            return
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
            end = brk.end_time or ended_session.end_time  # fallback if end_time is null
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

# Command wrappers
async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_work_action(update, context)

async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await off_work_action(update, context)

async def eat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await break_action(update, context, "Eat")

async def toilet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await break_action(update, context, "Toilet")

async def smoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await break_action(update, context, "Smoke")

async def other_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await break_action(update, context, "Other")

async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await back_to_seat_action(update, context)

# Admin Commands
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    sender = update.effective_user
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if sender.id != admin_id:
        await update.message.reply_text("❌ Apni Admin non.")
        return
        
    await update.message.reply_text(
        "🛠️ **Admin Control Panel**\n\n"
        "নতুন মেম্বার অ্যাড করতে:\n"
        "👉 `/add <telegram_id> <first_name> [username]` (যেমন: `/add 12345678 Rahim`)\n\n"
        "কোনো মেম্বার রিমুভ/কিক করতে:\n"
        "👉 `/kick <telegram_id>` (যেমন: `/kick 12345678`)\n\n"
        "বটের হেল্পলাইন গাইড পেতে:\n"
        "👉 /admin",
        parse_mode="Markdown"
    )

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    sender = update.effective_user
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if sender.id != admin_id:
        await update.message.reply_text("❌ Sudhu Admin-i user add/register korte parben.")
        return
        
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ Usage: /add <telegram_id> <first_name> [username]")
        return
        
    try:
        target_id = int(context.args[0])
        first_name = context.args[1]
        username = context.args[2] if len(context.args) > 2 else None
        
        if username and username.startswith('@'):
            username = username[1:]
            
        with SessionLocal() as db:
            user = crud.get_or_create_user(db, telegram_id=target_id, username=username, first_name=first_name)
            await update.message.reply_text(f"✅ User successfully added:\n👤 Name: {user.first_name}\n🆔 ID: {user.telegram_id}")
    except ValueError:
        await update.message.reply_text("❌ Error: Invalid Telegram ID. ID must be an integer.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error occurred: {e}")

async def kick_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    sender = update.effective_user
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if sender.id != admin_id:
        await update.message.reply_text("❌ Sudhu Admin-i user kick/remove korte parben.")
        return
        
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /kick <telegram_id>")
        return
        
    try:
        target_id = int(context.args[0])
        with SessionLocal() as db:
            success = crud.delete_user(db, target_id)
            if success:
                await update.message.reply_text(f"✅ User with ID {target_id} has been kicked/removed from the bot.")
            else:
                await update.message.reply_text(f"❌ User with ID {target_id} not found in database.")
    except ValueError:
        await update.message.reply_text("❌ Error: ID must be an integer.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error occurred: {e}")

# Text Message Router
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    if text == "Start Work":
        await start_work_action(update, context)
    elif text in ["Eat", "Toilet", "Smoke", "Other"]:
        await break_action(update, context, text)
    elif text == "Back to Seat":
        await back_to_seat_action(update, context)
    elif text == "Off Work":
        await off_work_action(update, context)
    else:
        # Avoid spamming group chats with warnings about unrecognized messages
        if update.message.chat.type == "private":
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

# Global Error Handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and notify the user if possible."""
    import logging
    err_logger = logging.getLogger(__name__)
    err_logger.error("Exception while handling an update:", exc_info=context.error)
    
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred in the bot. Please try again later or contact the admin."
            )
    except Exception as e:
        err_logger.error(f"Failed to send error message to user: {e}")

# Initialize Application
bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
    # Fallback to empty if not configured yet, so it won't crash on start until configured
    bot_token = ""

application = None
if bot_token:
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler(["work", "start_work"], work_command))
    application.add_handler(CommandHandler(["off", "off_work"], off_command))
    application.add_handler(CommandHandler("eat", eat_command))
    application.add_handler(CommandHandler("toilet", toilet_command))
    application.add_handler(CommandHandler("smoke", smoke_command))
    application.add_handler(CommandHandler("other", other_command))
    application.add_handler(CommandHandler(["back", "back_to_seat"], back_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("add", add_user_command))
    application.add_handler(CommandHandler("kick", kick_user_command))
    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
