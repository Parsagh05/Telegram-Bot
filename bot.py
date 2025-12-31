import datetime
import sqlite3
import random
import pytz
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIGURATION ---
TOKEN = '8082494615:AAF9w6UB8QebTOZe-KZHV986mbTvVOLR6nE'
GROUP_CHAT_ID = -4923261559  
ADMIN_ID = 812165996  # Only Parsa can use /alert
tehran_tz = pytz.timezone('Asia/Tehran')

# Member Names
MEMBERS_MAP = {
    812165996: "Parsa",
    5409010079: "Reza",
    878762217: "Parham",
    898068240: "Alireza"
}
MAIN_MEMBERS = list(MEMBERS_MAP.keys())

# Global State
daily_votes = {}
meal_solved = False
finalization_scheduled = False # Tracks if the 5-minute timer is running
current_meal_title = "Meal" 

# Set up logging to print to console (Terminal)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('food_bot.db')
    c = conn.cursor()
    # Reset database on startup
    c.execute('DROP TABLE IF EXISTS food_stats')
    c.execute('''CREATE TABLE food_stats 
                 (user_id INTEGER PRIMARY KEY, username TEXT, total_foods INTEGER DEFAULT 0)''')
    # Initial Data Seeding
    initial_data = [
        (812165996, 'Parsa', 2), (5409010079, 'Reza', 2), 
        (878762217, 'Parham', 3), (898068240, 'Alireza', 0)
    ]
    for uid, name, count in initial_data:
        c.execute("INSERT INTO food_stats (user_id, username, total_foods) VALUES (?, ?, ?)", (uid, name, count))
    conn.commit()
    conn.close()

# --- OPTION MENU SETUP ---
async def post_init(application: Application):
    """Adds commands to the Telegram menu button"""
    commands = [
        BotCommand("start", "Check bot status"),
        BotCommand("help", "See schedule and rules"),
        BotCommand("stats", "Check food counts"),
        BotCommand("alert", "Set custom alert (Admin)"),
        BotCommand("stop_warning", "Stop the spam alarm"),
        BotCommand("donate", "Support the bot!")
    ]
    await application.bot.set_my_commands(commands)

# --- DONATE COMMAND ---
async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🙏 *Support the Bot!*\n\n"
        "If you enjoy using this bot and want to support its development, you can donate using the card below.\n\n"
        "💳 *Card Number:* `6221 0612 3974 4339`\n"
        "👤 *Name:* Parsa Gholami\n\n"
        "Thank you for your support! 💙"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Active!\n\n📅 Schedules loaded for\n🍽️ Dinner (Sat-Wed)\n🥗 Lunch (Thu).")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Standard Schedule* (Tehran Time):\n"
        "🍽️ *DINNER* (Sat-Wed): Ask 17:00 → Deadline 19:45\n"
        "🥗 *LUNCH* (Thu): Ask 11:00 → Deadline 13:45\n"
        "🕌 *Friday*: No automatic alerts.\n\n"
        "👮‍♂️ *Admin Alert*: \n"
        "`/alert <day> <start> <end> <msg>`\n"
        "_Ex: /alert friday 13:00 17:00 Kabob Time!_\n\n"
        "🧠 *Logic*: \n"
        "- If someone says *YES*, I wait 5 minutes then pick the winner.\n"
        "- If deadline hits and no one said YES, I spam. 🚨"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('food_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, total_foods FROM food_stats")
    rows = {r[0]: r[1] for r in c.fetchall()}
    conn.close()
    
    msg = "📊 *Food Counts:*\n"
    for uid, name in MEMBERS_MAP.items():
        msg += f"👤 {name}: {rows.get(uid, 0)} 🍱\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- CUSTOM ALERT LOGIC ---
async def set_custom_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Access Denied. Only Parsa can set alerts.")
        return

    try:
        # Expected: /alert friday 13:00 17:00 Message here
        args = context.args
        if len(args) < 4: raise ValueError

        target_day_str = args[0].lower()
        start_time_str = args[1]
        end_time_str = args[2]
        message = " ".join(args[3:])

        days_map = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        if target_day_str not in days_map:
            await update.message.reply_text("❌ Invalid day. Use: monday, tuesday, etc.")
            return
        
        target_weekday = days_map.index(target_day_str)
        now = datetime.datetime.now(tehran_tz)
        
        # Calculate Date
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0: days_ahead += 7 
        target_date = now + datetime.timedelta(days=days_ahead)
        
        # Parse Times
        s_h, s_m = map(int, start_time_str.split(':'))
        e_h, e_m = map(int, end_time_str.split(':'))
        
        start_dt = target_date.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
        end_dt = target_date.replace(hour=e_h, minute=e_m, second=0, microsecond=0)

        # If time passed today, assume next week
        if start_dt < now:
            start_dt += datetime.timedelta(days=7)
            end_dt += datetime.timedelta(days=7)

        # Schedule the Ask and the Deadline
        context.job_queue.run_once(trigger_custom_ask, when=start_dt, data=message, chat_id=GROUP_CHAT_ID)
        context.job_queue.run_once(trigger_deadline, when=end_dt, chat_id=GROUP_CHAT_ID)

        await update.message.reply_text(
            f"✅ *Alert Scheduled!*\n"
            f"🗓️ Day: {target_day_str.capitalize()}\n"
            f"⏰ Start: {start_time_str}\n"
            f"⏳ Deadline: {end_time_str}\n"
            f"📢 Event: {message}",
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text("⚠️ Format Error:\nUse: /alert friday 13:00 17:00 Message")

async def trigger_custom_ask(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    msg = job.data
    # This triggers the exact same logic as normal meals
    await start_voting_session(context, title=f"SPECIAL: {msg}")

# --- CORE LOGIC ---

async def ask_standard_meal(context: ContextTypes.DEFAULT_TYPE):
    current_hour = datetime.datetime.now(tehran_tz).hour
    meal_name = "LUNCH" if current_hour < 14 else "DINNER"
    await start_voting_session(context, title=f"{meal_name} CHECK")

async def start_voting_session(context, title):
    global daily_votes, meal_solved, current_meal_title, finalization_scheduled
    daily_votes = {}       
    meal_solved = False
    finalization_scheduled = False
    current_meal_title = title    
    stop_spam_jobs(context) 
    
    keyboard = [[InlineKeyboardButton("✅ Yes", callback_data='get_yes'),
                 InlineKeyboardButton("❌ No", callback_data='get_no')]]
    markup = InlineKeyboardMarkup(keyboard)
    
    # DM members
    for uid in MAIN_MEMBERS:
        try:
            await context.bot.send_message(
                chat_id=uid, 
                text=f"🍽️ {title}\n\nCan you get the food today?", 
                reply_markup=markup
            )
        except: pass
    
    # Announce in Group
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"📢 Attention: Voting started for *{title}*!", parse_mode="Markdown")

async def trigger_deadline(context: ContextTypes.DEFAULT_TYPE):
    global meal_solved, finalization_scheduled
    # Only spam if the meal isn't solved AND we aren't currently waiting for the 5-min timer
    if not meal_solved and not finalization_scheduled:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"⏰ *DEADLINE EXPIRED* for *{current_meal_title}*!", parse_mode="Markdown")
        context.job_queue.run_repeating(spam_warning, interval=300, first=1, name="spam_job")

# --- VOTING HANDLER ---
async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global meal_solved, finalization_scheduled
    query = update.callback_query
    uid = query.from_user.id
    
    if uid not in MAIN_MEMBERS: return
    
    # LOGGING: Print to console
    user_name = MEMBERS_MAP.get(uid, "Unknown")
    vote_str = "YES" if query.data == 'get_yes' else "NO"
    # This prints to your terminal/Koyeb logs
    logging.info(f"VOTE LOG: User {user_name} (ID: {uid}) voted {vote_str}")

    daily_votes[uid] = (query.data == 'get_yes')
    await query.answer("🗳️ Vote recorded.")
    await query.edit_message_text(f"Response: {'✅ Yes' if daily_votes[uid] else '❌ No'}")

    # LOGIC: Check for YES
    if query.data == 'get_yes':
        # If this is the FIRST yes and we haven't started the timer yet
        if not finalization_scheduled:
            finalization_scheduled = True
            stop_spam_jobs(context) # Prevent/Stop spamming immediately
            
            # Schedule finalization in 5 minutes (300 seconds)
            context.job_queue.run_once(finalize_voting, 300, chat_id=GROUP_CHAT_ID)
            
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID, 
                text=f"🎉 {user_name} voted *YES*! Finalizing selection in 5 minutes...",
                parse_mode="Markdown"
            )
    
    # Logic: Check if EVERYONE said NO (Immediate Spam)
    elif query.data == 'get_no':
        if len(daily_votes) == len(MAIN_MEMBERS):
            if not any(daily_votes.values()) and not meal_solved and not finalization_scheduled:
                context.job_queue.run_repeating(spam_warning, interval=300, first=1, name="spam_job")

async def finalize_voting(context: ContextTypes.DEFAULT_TYPE):
    """Runs 5 minutes after the first YES"""
    global meal_solved
    meal_solved = True
    
    # Get all YES voters
    yes_voters = [u for u, v in daily_votes.items() if v]
    
    if yes_voters:
        await pick_fair_member(context, yes_voters)
    else:
        # Should not happen unless everyone changed vote to NO during the 5 mins
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="⏳ Timer finished but no one has Yes votes now?")

async def pick_fair_member(context, yes_voters):
    conn = sqlite3.connect('food_bot.db')
    c = conn.cursor()
    placeholders = ', '.join(['?'] * len(yes_voters))
    c.execute(f"SELECT user_id, total_foods FROM food_stats WHERE user_id IN ({placeholders})", yes_voters)
    results = c.fetchall()
    
    min_count = min(r[1] for r in results)
    candidates = [r[0] for r in results if r[1] == min_count]
    winner_id = random.choice(candidates)
    
    c.execute("UPDATE food_stats SET total_foods = total_foods + 1 WHERE user_id = ?", (winner_id,))
    conn.commit()
    conn.close()
    
    winner_name = MEMBERS_MAP[winner_id]
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, 
        text=f"🏆 *Assignment Complete!*\n\n🥇 {winner_name} gets the food!\n\n📈 Stats update: {min_count} → {min_count+1}",
        parse_mode="Markdown"
    )

# --- UTILITIES ---
async def spam_warning(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="🚨 *NO ONE IS GETTING FOOD!*\nPlease decide now!", parse_mode="Markdown")

def stop_spam_jobs(context):
    for job in context.job_queue.get_jobs_by_name("spam_job"):
        job.schedule_removal()

async def stop_warning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Access Denied. Only Parsa can stop the alarm.")
        return
    stop_spam_jobs(context)
    await update.message.reply_text("🔕 Alarm stopped.")

# --- MAIN RUNNER ---
if __name__ == '__main__':
    init_db()
    
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    jq = app.job_queue
    
    # --- SCHEDULES ---
    # Day Mapping: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    
    # 1. DINNER (Sat, Sun, Mon, Tue, Wed)
    DINNER_DAYS = (5, 6, 0, 1, 2)
    jq.run_daily(ask_standard_meal, time=datetime.time(17, 0, tzinfo=tehran_tz), days=DINNER_DAYS)
    jq.run_daily(trigger_deadline, time=datetime.time(19, 45, tzinfo=tehran_tz), days=DINNER_DAYS)

    # 2. LUNCH (Thursday Only)
    LUNCH_DAYS = (3,)
    jq.run_daily(ask_standard_meal, time=datetime.time(11, 0, tzinfo=tehran_tz), days=LUNCH_DAYS)
    jq.run_daily(trigger_deadline, time=datetime.time(13, 45, tzinfo=tehran_tz), days=LUNCH_DAYS)

    # 3. MONDAY REMINDER
    jq.run_daily(
        lambda ctx: ctx.bot.send_message(chat_id=GROUP_CHAT_ID, text="Monday Reminder: Reserve food for next week!"),
        time=datetime.time(18, 0, tzinfo=tehran_tz), 
        days=(0,)
    )

    # --- HANDLERS ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", get_stats))
    app.add_handler(CommandHandler("stop_warning", stop_warning_cmd))
    app.add_handler(CommandHandler("alert", set_custom_alert)) 
    app.add_handler(CallbackQueryHandler(handle_vote))
    app.add_handler(CommandHandler("donate", donate_command))
    
    print("Bot is running...")
    app.run_polling()