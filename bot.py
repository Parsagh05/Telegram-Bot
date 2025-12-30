import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# CONFIGURATION
TOKEN = 'YOUR_BOT_TOKEN'
MAIN_MEMBERS = [111, 222, 333, 444] # REPLACE WITH REAL USER IDs
GROUP_CHAT_ID = -100123456789       # REPLACE WITH YOUR GROUP ID

# Initialize Database
def init_db():
    conn = sqlite3.connect('food_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS food_stats 
                 (user_id INTEGER PRIMARY KEY, username TEXT, total_foods INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

# Store temporary daily responses
daily_votes = {} # {user_id: True/False}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Food Reminder Bot Active!")

async def monday_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="🚨 MONDAY REMINDER: Reserve your food for the week!")

async def daily_lunch_ask(context: ContextTypes.DEFAULT_TYPE):
    global daily_votes
    daily_votes = {} # Reset
    keyboard = [[InlineKeyboardButton("Yes, I'm getting it", callback_data='get_yes'),
                 InlineKeyboardButton("No, I'm not", callback_data='get_no')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for uid in MAIN_MEMBERS:
        try:
            await context.bot.send_message(chat_id=uid, text="Are you getting lunch today?", reply_markup=reply_markup)
        except:
            pass

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    
    if uid not in MAIN_MEMBERS: return
    
    daily_votes[uid] = (data == 'get_yes')
    await query.answer("Vote recorded!")
    await query.edit_message_text(f"Recorded: {'Yes' if daily_votes[uid] else 'No'}")

    # Check if everyone voted
    if len(daily_votes) == len(MAIN_MEMBERS):
        if not any(daily_votes.values()): # If all are False
            # Start spamming logic
            context.job_queue.run_repeating(spam_warning, interval=10, first=1, name="spam_job")
        else:
            # Update database for those who said YES
            conn = sqlite3.connect('food_bot.db')
            c = conn.cursor()
            for user_id, voted_yes in daily_votes.items():
                if voted_yes:
                    c.execute("INSERT OR IGNORE INTO food_stats (user_id) VALUES (?)", (user_id,))
                    c.execute("UPDATE food_stats SET total_foods = total_foods + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()

async def spam_warning(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="🚨 NO ONE IS GETTING FOOD! DO SOMETHING!!! 🚨")

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('food_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id, total_foods FROM food_stats")
    rows = c.fetchall()
    msg = "📊 Food Stats:\n" + "\n".join([f"User {r[0]}: {r[1]} foods" for r in rows])
    await update.message.reply_text(msg)
    conn.close()

if __name__ == '__main__':
    init_db()
    app = Application.builder().token(TOKEN).build()
    
    # Schedulers
    job_queue = app.job_queue
    job_queue.run_daily(monday_reminder, time=9, days=(0,)) # Monday is 0
    job_queue.run_daily(daily_lunch_ask, time=11) # Daily at 11:00

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", get_stats))
    app.add_handler(CallbackQueryHandler(handle_vote))
    
    app.run_polling()