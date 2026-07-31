import os
import html
import re
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

def remove_chinese(text: str) -> str:
    if not text:
        return text
    # Remove CJK characters
    cleaned = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf]', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def get_clean_name(user) -> str:
    name = user.full_name or user.first_name or "User"
    cleaned = remove_chinese(name)
    if not cleaned:
        cleaned = "User"
    return html.escape(cleaned)

# Set up Keyboard
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("Start Work"), KeyboardButton("Off Work")],
        [KeyboardButton("Eat"), KeyboardButton("Toilet"), KeyboardButton("Smoke"), KeyboardButton("Other")],
        [KeyboardButton("Back to Seat")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, selective=True)

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

def format_hhmmss(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_user_header(user) -> str:
    display_name = get_clean_name(user)
    user_link = f'<a href="tg://user?id={user.id}">{display_name}</a>'
    return (
        f"<b>user:</b> {user_link} .\n"
        f"<b>user id:</b> {user.id}."
    )

GROUP_CHAT_ID_FILE = "group_chat_id.txt"

def save_group_chat_id(chat_id: int):
    try:
        with open(GROUP_CHAT_ID_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception as e:
        print(f"Error saving group chat ID: {e}")

def get_group_chat_id() -> int:
    env_id = os.getenv("GROUP_CHAT_ID")
    if env_id:
        try:
            return int(env_id)
        except ValueError:
            pass
            
    if os.path.exists(GROUP_CHAT_ID_FILE):
        try:
            with open(GROUP_CHAT_ID_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None

async def broadcast_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode="Markdown"):
    if update.message and update.message.chat.type in ["group", "supergroup"]:
        # Save the group chat ID for future use
        save_group_chat_id(update.message.chat_id)
        # Action already happened IN the group — no need to re-send, just return
        return

    # Action came from private chat → broadcast to group
    group_id = get_group_chat_id()
    if group_id:
        try:
            await context.bot.send_message(chat_id=group_id, text=text, parse_mode=parse_mode)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to broadcast to group {group_id}: {e}")

async def reply_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode="HTML"):
    if not update.message:
        return
    await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=get_main_keyboard())

# Helper to check if user is authorized (Admin is always authorized & auto-registered)
# If the user is in the database or a member of the group, they are authorized.
async def is_authorized(db, user, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if user.id == admin_id:
        crud.get_or_create_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name
        )
        return True
        
    db_user = db.query(crud.User).filter(crud.User.telegram_id == user.id).first()
    if db_user:
        if db_user.username != user.username or db_user.first_name != user.first_name:
            db_user.username = user.username
            db_user.first_name = user.first_name
            db.commit()
        return True
        
    # Check if they are in the group chat
    group_id = get_group_chat_id()
    if group_id:
        try:
            chat_member = await context.bot.get_chat_member(chat_id=group_id, user_id=user.id)
            if chat_member.status in ["creator", "administrator", "member"]:
                crud.get_or_create_user(
                    db,
                    telegram_id=user.id,
                    username=user.username,
                    first_name=user.first_name or "Member"
                )
                return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to check group membership for user {user.id}: {e}")
            
    return False

# Start Command
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.chat.type in ["group", "supergroup"]:
        save_group_chat_id(update.message.chat_id)
        
    user = update.effective_user
    with SessionLocal() as db:
        authorized = await is_authorized(db, user, context)
    
    if not authorized:
        text = (
            f"{get_user_header(user)}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            "<b>Status:</b> ❌ Registration Required!\n"
            "<b>Reason:</b> You are not a registered user. Please ask the Admin to add you for tracking.\n"
            "- - - - - - - - - - - - - - - - - - - - - - -"
        )
        await update.message.reply_text(text, parse_mode="HTML")
        return
        
    text = get_user_header(user)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())

# Core Tracking Actions
async def start_work_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not await is_authorized(db, user, context):
            await reply_or_send(
                update,
                context,
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Registration Required!\n"
                "<b>Reason:</b> You are not a registered user. Please ask the Admin to add you for tracking.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -",
                parse_mode="HTML"
            )
            return
        active_session = crud.get_active_session(db, user.id)
        if active_session:
            last_start_time_str = active_session.start_time.strftime("%m/%d %H:%M:%S")
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Start Work Check-In Failed!\n"
                "<b>Reason:</b> You have not Off Work yet. Please Off Work first.\n"
                f"<b>Last Start Work Check-In Time:</b> {last_start_time_str}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Off Work:</b> /offwork\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        # Start new session
        session, created = crud.start_work_session(db, user.id)
        start_time_str = session.start_time.strftime("%m/%d %H:%M:%S")
        text = (
            f"{get_user_header(user)}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            f"✅ <b>Check-In Succeeded:</b> Start Work - {start_time_str}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            "<b>Hint:</b> Remember to check in when Off Work arrives.\n"
            "- - - - - - - - - - - - - - - - - - - - - - -"
        )
        await reply_or_send(update, context, text, parse_mode="HTML")
        await broadcast_to_group(update, context, text, parse_mode="HTML")

async def break_action(update: Update, context: ContextTypes.DEFAULT_TYPE, break_type: str):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not await is_authorized(db, user, context):
            await reply_or_send(
                update,
                context,
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Registration Required!\n"
                "<b>Reason:</b> You are not a registered user. Please ask the Admin to add you for tracking.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -",
                parse_mode="HTML"
            )
            return
        active_session = crud.get_active_session(db, user.id)
        if not active_session:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                f"<b>Status:</b> ❌ {break_type} Check-In Failed!\n"
                "<b>Reason:</b> You have not checked in / started work yet. Please click 'Start Work' first.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Start Work:</b> /work\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        active_break = crud.get_active_break(db, active_session.id)
        if active_break:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                f"<b>Status:</b> ❌ {break_type} Check-In Failed!\n"
                f"<b>Reason:</b> You are already on a break ({active_break.break_type}). Please check in Back to Seat first.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Back to Seat:</b> /back\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        # Start break
        new_break = crud.start_break(db, active_session.id, break_type)
        start_time_str = new_break.start_time.strftime("%m/%d %H:%M:%S")
        
        limits_sec = get_break_limit(break_type)
        limits_min = int(limits_sec // 60) if limits_sec >= 60 else limits_sec
        unit = "minute" if limits_sec >= 60 else "second"
        
        if break_type in ["Eat", "Toilet", "Smoke", "Other"]:
            from models import BreakLog
            break_count = db.query(BreakLog).filter(
                BreakLog.session_id == active_session.id,
                BreakLog.break_type == break_type
            ).count()
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                f"✅ <b>Check-In Succeeded:</b> {break_type} - {start_time_str}\n"
                f"<b>Attention:</b> This is your <b>{break_count}</b> time {break_type}.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                f"<b>Time Limit for This Activity:</b> {limits_min} {unit}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Tip:</b> Please check in Back to Seat after completing the activity.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Back to Seat:</b> /back\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            await broadcast_to_group(update, context, text, parse_mode="HTML")
        else:
            await reply_or_send(
                update,
                context,
                f"☕ Break Started: {break_type} - {start_time_str}\n"
                f"Time Limit: {limits_min} {unit}(s).",
                parse_mode="HTML"
            )

async def back_to_seat_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not await is_authorized(db, user, context):
            await reply_or_send(
                update,
                context,
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Registration Required!\n"
                "<b>Reason:</b> You are not a registered user. Please ask the Admin to add you for tracking.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -",
                parse_mode="HTML"
            )
            return
        active_session = crud.get_active_session(db, user.id)
        if not active_session:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Back to Seat Check-In Failed!\n"
                "<b>Reason:</b> You have not checked in / started work yet. Please click 'Start Work' first.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Start Work:</b> /work\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        active_break = crud.get_active_break(db, active_session.id)
        if not active_break:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Back to Seat Check-In Failed!\n"
                "<b>Reason:</b> You are not engaged in any activities.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>You can--</b>\n"
                "Eat\n"
                "Toilet\n"
                "Smoke\n"
                "Other\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        # End break
        ended_break = crud.end_break(db, active_session.id)
        duration_sec = (ended_break.end_time - ended_break.start_time).total_seconds()
        end_time_str = ended_break.end_time.strftime("%m/%d %H:%M:%S")
        
        # Calculate statistics for the active session
        from models import BreakLog
        breaks = db.query(BreakLog).filter(BreakLog.session_id == active_session.id).all()
        
        total_break_seconds = 0.0
        break_seconds = {"Eat": 0.0, "Toilet": 0.0, "Smoke": 0.0, "Other": 0.0}
        break_counts = {"Eat": 0, "Toilet": 0, "Smoke": 0, "Other": 0}
        
        for brk in breaks:
            end = brk.end_time or ended_break.end_time
            duration = (end - brk.start_time).total_seconds()
            btype = brk.break_type
            if btype in break_seconds:
                break_seconds[btype] += duration
                break_counts[btype] += 1
            total_break_seconds += duration
        # Format the statistics strings
        duration_str = format_hhmmss(duration_sec)
        total_break_type_time_str = format_hhmmss(break_seconds.get(ended_break.break_type, 0.0))
        total_activities_time_str = format_hhmmss(total_break_seconds)
        
        counts_list = []
        for btype in ["Eat", "Toilet", "Smoke", "Other"]:
            cnt = break_counts.get(btype, 0)
            if cnt > 0:
                counts_list.append(f"<b>Today's {btype}:</b> {cnt}  times")
        counts_list_joined = "\n".join(counts_list)
        
        text = (
            f"{get_user_header(user)}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            f"✅ {end_time_str} <b>Back to Seat</b>\n"
            f"<b>Check-In Succeeded:</b> {ended_break.break_type}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            "<b>Hint:</b> This activity's time has been settled.\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            "<b>Time Used for This Activity:</b>\n"
            f"{duration_str}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            f"<b>Total {ended_break.break_type} time today:</b> {total_break_type_time_str}\n"
            "<b>Total time for all activities today:</b>\n"
            f"{total_activities_time_str}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -\n"
            f"{counts_list_joined}\n"
            "- - - - - - - - - - - - - - - - - - - - - - -"
        )
        
        await reply_or_send(update, context, text, parse_mode="HTML")
        await broadcast_to_group(update, context, text, parse_mode="HTML")

async def off_work_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user = update.effective_user
    with SessionLocal() as db:
        if not await is_authorized(db, user, context):
            await reply_or_send(
                update,
                context,
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Registration Required!\n"
                "<b>Reason:</b> You are not a registered user. Please ask the Admin to add you for tracking.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -",
                parse_mode="HTML"
            )
            return
        active_session = crud.get_active_session(db, user.id)
        if not active_session:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Off Work Check-In Failed!\n"
                "<b>Reason:</b> You have not checked in / started work yet. Please click 'Start Work' first.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Start Work:</b> /work\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
            
        active_break = crud.get_active_break(db, active_session.id)
        if active_break:
            text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Off Work Check-In Failed!\n"
                f"<b>Reason:</b> You are still on a break ({active_break.break_type}). Please check in Back to Seat first.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Back to Seat:</b> /back\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await reply_or_send(update, context, text, parse_mode="HTML")
            return
        
        # End session (will auto end active break if any)
        session_id = active_session.id
        ended_session = crud.end_work_session(db, user.id)
        end_time_str = ended_session.end_time.strftime("%m/%d %H:%M:%S")
        
        # Query all breaks for statistics
        from models import BreakLog
        breaks = db.query(BreakLog).filter(BreakLog.session_id == session_id).all()
        
        total_session_seconds = (ended_session.end_time - ended_session.start_time).total_seconds()
        
        break_seconds = {"Eat": 0.0, "Toilet": 0.0, "Smoke": 0.0, "Other": 0.0}
        break_counts = {"Eat": 0, "Toilet": 0, "Smoke": 0, "Other": 0}
        
        total_break_seconds = 0.0
        for brk in breaks:
            start = brk.start_time
            end = brk.end_time or ended_session.end_time
            duration = (end - start).total_seconds()
            btype = brk.break_type
            if btype in break_seconds:
                break_seconds[btype] += duration
                break_counts[btype] += 1
            total_break_seconds += duration
            
        actual_work_seconds = total_session_seconds - total_break_seconds
        if actual_work_seconds < 0:
            actual_work_seconds = 0
            
        # Target work hours
        target_hours = float(os.getenv("TARGET_WORK_HOURS", "8"))
        target_seconds = target_hours * 3600
        
        warning_block = ""
        if total_session_seconds < target_seconds:
            early_leave_sec = target_seconds - total_session_seconds
            early_leave_duration_str = format_hhmmss(early_leave_sec)
            warning_block = (
                "⚠️ <b>Warning:</b> You have left early!\n"
                "<b>Duration of Leaving Early:</b>\n"
                f"{early_leave_duration_str}\n"
                "<b>Tip:</b> This instance of leaving early has been recorded.\n"
            )
            
        # Format session times
        total_session_str = format_hhmmss(total_session_seconds)
        pure_work_str = format_hhmmss(actual_work_seconds)
        total_break_str = format_hhmmss(total_break_seconds)
        
        message_parts = [
            f"{get_user_header(user)}",
            "- - - - - - - - - - - - - - - - - - - - - - -",
        ]
        if warning_block:
            message_parts.append(warning_block.strip())
            
        message_parts.extend([
            f"✅ <b>Check-In Succeeded:</b> Off Work - {end_time_str}",
            "- - - - - - - - - - - - - - - - - - - - - - -",
            "<b>Hint:</b> Today's work time has been settled.",
            "- - - - - - - - - - - - - - - - - - - - - - -",
            f"<b>Total work time today:</b> {total_session_str}",
            f"<b>Pure work time:</b> {pure_work_str}",
            "- - - - - - - - - - - - - - - - - - - - - - -",
            "<b>Total time for all activities today:</b>",
            f"{total_break_str}"
        ])
        
        # Add details for each break type with count > 0
        for btype in ["Eat", "Toilet", "Smoke", "Other"]:
            cnt = break_counts.get(btype, 0)
            dur = break_seconds.get(btype, 0.0)
            if cnt > 0:
                dur_str = format_hhmmss(dur)
                message_parts.append(f"<b>Total {btype} count today:</b> {cnt}  times")
                message_parts.append(f"<b>Total {btype} time today:</b> {dur_str}")
                
        message_parts.append("- - - - - - - - - - - - - - - - - - - - - - -")
        
        text = "\n".join(message_parts)
        await reply_or_send(update, context, text, parse_mode="HTML")
        await broadcast_to_group(update, context, text, parse_mode="HTML")

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
        await update.message.reply_text("❌ You are not an Admin.")
        return
        
    await update.message.reply_text(
        "🛠️ **Admin Control Panel - Member Management**\n\n"
        "To add a member to tracking (3 Easy Ways):\n"
        "1️⃣ Reply `/add` to any member's message in group.\n"
        "2️⃣ Forward a member's message with `/add`.\n"
        "3️⃣ Type `/add <telegram_id> <first_name> [username]`\n\n"
        "To remove a member:\n"
        "👉 Reply `/kick` to any member's message.\n"
        "👉 Or type `/kick <telegram_id>`\n\n"
        "Bot Helpline: /admin",
        parse_mode="Markdown"
    )

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    sender = update.effective_user
    admin_id = int(os.getenv("ADMIN_ID", "8595628652"))
    if sender.id != admin_id:
        await update.message.reply_text("❌ Only Admin can add or register users.")
        return
        
    target_user = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    elif update.message.forward_from:
        target_user = update.message.forward_from

    if target_user:
        target_id = target_user.id
        first_name = remove_chinese(target_user.first_name or target_user.full_name or "Member")
        if not first_name:
            first_name = "Member"
        username = target_user.username
        with SessionLocal() as db:
            user = crud.get_or_create_user(db, telegram_id=target_id, username=username, first_name=first_name)
            await update.message.reply_text(
                f"✅ Member successfully registered:\n"
                f"👤 Name: {user.first_name}\n"
                f"🆔 ID: `{user.telegram_id}`\n"
                f"🏷️ Username: @{user.username if user.username else 'N/A'}",
                parse_mode="Markdown"
            )
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ *How to Add Member (3 Ways):*\n\n"
            "1️⃣ *Reply Method:* Reply `/add` to any member's message in group.\n"
            "2️⃣ *Forward Method:* Forward any member's message here with `/add`.\n"
            "3️⃣ *Manual Method:* `/add <telegram_id> <first_name> [username]`",
            parse_mode="Markdown"
        )
        return
        
    try:
        target_id = int(context.args[0])
        first_name = remove_chinese(context.args[1])
        if not first_name:
            first_name = "Member"
        username = context.args[2] if len(context.args) > 2 else None
        
        if username and username.startswith('@'):
            username = username[1:]
            
        with SessionLocal() as db:
            user = crud.get_or_create_user(db, telegram_id=target_id, username=username, first_name=first_name)
            await update.message.reply_text(
                f"✅ Member successfully registered:\n"
                f"👤 Name: {user.first_name}\n"
                f"🆔 ID: `{user.telegram_id}`\n"
                f"🏷️ Username: @{user.username if user.username else 'N/A'}",
                parse_mode="Markdown"
            )
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
        await update.message.reply_text("❌ Only Admin can kick or remove users.")
        return
        
    target_id = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Error: ID must be an integer.")
            return

    if not target_id:
        await update.message.reply_text("⚠️ Usage: Reply `/kick` to a member's message or type `/kick <telegram_id>`", parse_mode="Markdown")
        return
        
    try:
        # Kick user from the Telegram group if bot has permission
        group_id = get_group_chat_id() or update.message.chat_id
        if group_id:
            try:
                await context.bot.ban_chat_member(chat_id=group_id, user_id=target_id)
                await context.bot.unban_chat_member(chat_id=group_id, user_id=target_id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to kick user {target_id} from Telegram group {group_id}: {e}")

        with SessionLocal() as db:
            success = crud.delete_user(db, target_id)
            if success:
                await update.message.reply_text(f"✅ User with ID `{target_id}` has been removed from tracking.", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ User with ID `{target_id}` not found in database.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error occurred: {e}")

# Text Message Router
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.message.chat.type in ["group", "supergroup"]:
        save_group_chat_id(update.message.chat_id)
        
    text = update.message.text
    user = update.effective_user
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received text message: '{text}' from user {user.id} ({user.first_name}) in chat {update.message.chat_id} ({update.message.chat.type})")
    
    if text.startswith("/"):
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        context.args = parts[1:]
        
        if cmd in ["/work", "/start_work"]:
            await start_work_action(update, context)
        elif cmd in ["/off", "/off_work", "/offwork"]:
            await off_work_action(update, context)
        elif cmd == "/eat":
            await break_action(update, context, "Eat")
        elif cmd == "/toilet":
            await break_action(update, context, "Toilet")
        elif cmd == "/smoke":
            await break_action(update, context, "Smoke")
        elif cmd == "/other":
            await break_action(update, context, "Other")
        elif cmd in ["/back", "/back_to_seat"]:
            await back_to_seat_action(update, context)
        elif cmd == "/admin":
            await admin_command(update, context)
        elif cmd == "/add":
            await add_user_command(update, context)
        elif cmd == "/kick":
            await kick_user_command(update, context)
        return

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
            error_text = (
                f"{get_user_header(user)}\n"
                "- - - - - - - - - - - - - - - - - - - - - - -\n"
                "<b>Status:</b> ❌ Check-In Failed!\n"
                "<b>Reason:</b> Please use the custom keyboard buttons to interact.\n"
                "- - - - - - - - - - - - - - - - - - - - - - -"
            )
            await update.message.reply_text(error_text, parse_mode="HTML")

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

# Auto-register new group members
async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    
    with SessionLocal() as db:
        for member in update.message.new_chat_members:
            if member.is_bot:
                continue
            first_name = remove_chinese(member.first_name or member.full_name or "Member")
            if not first_name:
                first_name = "Member"
            
            # Register user
            crud.get_or_create_user(
                db,
                telegram_id=member.id,
                username=member.username,
                first_name=first_name
            )
            
            # Send confirmation
            await update.message.reply_text(
                f"✅ Member successfully registered:\n"
                f"👤 Name: {first_name}\n"
                f"🆔 ID: `{member.id}`\n"
                f"🏷️ Username: @{member.username if member.username else 'N/A'}",
                parse_mode="HTML"
            )

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
    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(filters.TEXT, text_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))
