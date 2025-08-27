import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import threading

from flask import Flask
import telebot
from telebot import types
import google.generativeai as genai

# ================== CONFIG ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

TIMEZONE = ZoneInfo("Asia/Dhaka")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

# Gemini setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
# ============================================

# ========== USER & MESSAGE TRACKING ==========
USERS_FILE = "users.csv"
MESSAGES_FILE = "messages.csv"

def save_user(user):
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            if str(user.id) in f.read():
                return
    except FileNotFoundError:
        pass

    with open(USERS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([user.id, user.username, user.first_name])

def log_message(user, message_text):
    save_user(user)
    with open(MESSAGES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now(), user.id, user.username, user.first_name, message_text])
    try:
        bot.send_message(
            ADMIN_ID,
            f"👤 {user.first_name} (@{user.username})\n🆔 ID: {user.id}\n💬 Message: {message_text}"
        )
    except Exception:
        pass

def load_users():
    users_info = {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 3:
                    user_id = row[0]
                    users_info[user_id] = {"username": row[1], "name": row[2]}
    except FileNotFoundError:
        pass
    return users_info

@bot.message_handler(commands=["users"])
def list_users(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.chat.id, "⚠️ You are not allowed to see this.")
        return
    users_info = load_users()
    if not users_info:
        bot.send_message(message.chat.id, "No users registered yet.")
        return
    lines = ["Registered users:"]
    for user_id, info in users_info.items():
        lines.append(f"{info['name']} (@{info.get('username', 'no username')}) - {user_id}")
    bot.send_message(message.chat.id, "\n".join(lines))

# ========== DATA LOADING ==========
DATA_PATH = os.path.join(os.path.dirname(__file__), "data.json")

def load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

data = load_data()
COURSE_CODES = list(data.get("notes", {}).keys()) or ["FBL","DIC","IEE","IEEL","MED","GE","PF","PFL","CFE"]
DAYS_ORDER = ["Saturday","Sunday","Monday","Tuesday","Wednesday","Thursday","Friday"]

# ========== HELPERS ==========
def today_dayname():
    now = datetime.now(TIMEZONE)
    return now.strftime("%A")

def build_week_schedule_text():
    out = ["🗓 Weekly Class Schedule:\n"]
    for day in DAYS_ORDER:
        entries = data.get("schedule", {}).get(day, [])
        if not entries:
            out.append(f"{day}: OFF\n")
            continue
        out.append(f"{day}:")
        for cls in entries:
            course = cls.get("course", "?")
            room = cls.get("room", "?")
            time = cls.get("time", "?")
            out.append(f"  • {course} — {room} — {time}")
        out.append("")
    return "\n".join(out).strip()

def build_day_schedule_text(day_name: str):
    entries = data.get("schedule", {}).get(day_name, [])
    if not entries:
        return f"{day_name}: OFF"
    out = [f"{day_name}:"]
    for cls in entries:
        out.append(f"  • {cls['course']} — {cls['room']} — {cls['time']}")
    return "\n".join(out)

# ========== COMMANDS ==========
@bot.message_handler(commands=["start", "help"])
def start(message):
    log_message(message.from_user, "/start")
    bot.reply_to(
        message,
        (
            "👋 Hey bro! I’m your Uni Assistant (Gemini powered).\n\n"
            "What I can do:\n"
            "📘 /notes — Get course notes\n"
            "📚 /books — Book PDFs\n"
            "🗓 /schedule — Weekly schedule\n"
            "📅 /today — Today’s classes\n"
            "📢 /notice — Latest notice\n\n"
            "💬 Just type anything to chat with AI."
        ),
    )

@bot.message_handler(commands=["notes"])
def notes(message):
    log_message(message.from_user, "/notes")
    markup = types.InlineKeyboardMarkup()
    for code in COURSE_CODES:
        markup.add(types.InlineKeyboardButton(code, callback_data=f"note_{code}"))
    bot.send_message(message.chat.id, "Choose a course:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("note_"))
def on_note_click(call):
    log_message(call.from_user, f"Clicked note: {call.data}")
    code = call.data.replace("note_", "")
    link = data.get("notes", {}).get(code)
    if link and not link.startswith("ADD_"):
        bot.send_message(call.message.chat.id, f"{code} notes:\n{link}")
    else:
        bot.send_message(call.message.chat.id, f"No note link set yet for {code}. (Update data.json)")

@bot.message_handler(commands=["books"])
def books(message):
    log_message(message.from_user, "/books")
    books_map = data.get("books", {})
    if not books_map:
        bot.send_message(message.chat.id, "No books added yet. (Update data.json)")
        return
    lines = ["📚 Books:"]
    for name, link in books_map.items():
        lines.append(f"• {name}: {link}")
    bot.send_message(message.chat.id, "\n".join(lines))

@bot.message_handler(commands=["schedule"])
def schedule_cmd(message):
    log_message(message.from_user, "/schedule")
    bot.send_message(message.chat.id, build_week_schedule_text())

@bot.message_handler(commands=["today"])
def today_cmd(message):
    log_message(message.from_user, "/today")
    bot.send_message(message.chat.id, build_day_schedule_text(today_dayname()))

@bot.message_handler(commands=["notice"])
def notice_cmd(message):
    log_message(message.from_user, "/notice")
    bot.send_message(message.chat.id, f"📢 Notice:\n{data.get('notice','No notice yet.')}")

@bot.message_handler(commands=["syllabus"])
def syllabus_cmd(message):
    log_message(message.from_user, "/syllabus")
    markup = types.InlineKeyboardMarkup()
    for code in COURSE_CODES:
        markup.add(types.InlineKeyboardButton(code, callback_data=f"syllabus_{code}"))
    bot.send_message(message.chat.id, "📘 Choose a course for syllabus:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("syllabus_"))
def on_syllabus_click(call):
    log_message(call.from_user, f"Clicked syllabus: {call.data}")
    code = call.data.replace("syllabus_", "")
    link = data.get("syllabus", {}).get(code)
    if link:
        bot.send_message(call.message.chat.id, f"{code} syllabus:\n{link}")
    else:
        bot.send_message(call.message.chat.id, f"No syllabus link set yet for {code}. (Update data.json)")

@bot.message_handler(commands=["questions"])
def questions_cmd(message):
    log_message(message.from_user, "/questions")
    markup = types.InlineKeyboardMarkup()
    for code in COURSE_CODES:
        markup.add(types.InlineKeyboardButton(code, callback_data=f"question_{code}"))
    bot.send_message(message.chat.id, "❓ Choose a course for previous questions:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("question_"))
def on_question_click(call):
    log_message(call.from_user, f"Clicked question: {call.data}")
    code = call.data.replace("question_", "")
    link = data.get("questions", {}).get(code)
    if link:
        bot.send_message(call.message.chat.id, f"{code} previous questions:\n{link}")
    else:
        bot.send_message(call.message.chat.id, f"No question link set yet for {code}. (Update data.json)")

# ========== AI CHAT (fallback) ==========
@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def ai_chat(message):
    log_message(message.from_user, message.text)
    try:
        prompt = (
            "You are a friendly Bangladeshi university assistant bot. Keep replies concise, helpful, and respectful. "
            "If user asks about notes/books/schedule/notice, guide them to the right commands too.\n\n"
            f"User: {message.text}"
        )
        resp = model.generate_content(prompt)
        bot.send_message(message.chat.id, resp.text.strip() if resp.text else "Couldn't generate a reply.")
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ AI error: {e}")

# ========== FLASK SERVER ==========
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ UniBot is running on Render!"

def run_bot():
    print("🤖 Bot is running…")
    bot.polling(none_stop=True, timeout=60)

if __name__ == "__main__":
    # Run bot in a separate thread
    threading.Thread(target=run_bot).start()
    # Start Flask server
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
