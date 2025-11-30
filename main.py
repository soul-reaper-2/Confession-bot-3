"""
Advanced Confession Bot with SQLite (professional schema)

Features:
- Confession flow: send confession -> asked for tags (or Skip)
- Admins: MAIN_ADMIN (hardcoded) + secondary admins managed in-bot
- Channels: add/remove/list channels; bot will post confessions to saved channels
- Auto-approve toggle
- Broadcasting to users or channels (text/photo/video)
- Anonymous comments: Add/View via private chat (no user ids saved)
- View sender by confession number (admin-only)
- SQLite DB file: database.db (auto-created)
- Uses pyTelegramBotAPI (telebot)
"""

import os
import sqlite3
import time
from datetime import datetime
import telebot
from telebot import types

# -------------------------
# CONFIG: token & main admin
# -------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "YOURTOKENHERE"
MAIN_ADMIN = int(os.environ.get("MAIN_ADMIN") or YOURIDHERE)  # change to your id
# Note: Confessions will be posted to channels stored in DB. No single CHANNEL_ID here.

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# -------------------------
# DB: connect and init
# -------------------------
DB_PATH = "database.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    # professional schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,      -- telegram user id
        first_seen TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS confessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        content TEXT,
        tags TEXT,                  -- comma separated
        status TEXT,                -- pending / approved / declined
        created_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        confession_id INTEGER,
        text TEXT,
        created_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY,     -- admin user id
        added_by INTEGER,
        added_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY,     -- channel chat id (may be negative)
        username TEXT,
        added_by INTEGER,
        added_at TEXT
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    # Ensure MAIN_ADMIN is present in admins table as main (we'll keep main admin separate logic)
    conn.commit()

init_db()

# -------------------------
# Helpers: settings, admins, users
# -------------------------
def get_setting(key, default=None):
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    return row[0] if row else default

def set_setting(key, value):
    cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

def is_auto_approve():
    val = get_setting("auto_approve", "0")
    return val == "1"

def set_auto_approve(on: bool):
    set_setting("auto_approve", "1" if on else "0")

def add_user_if_missing(user_id):
    cursor.execute("SELECT id FROM users WHERE id=?", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (id, first_seen) VALUES (?, ?)", (user_id, datetime.utcnow().isoformat()))
        conn.commit()

def get_all_user_ids():
    cursor.execute("SELECT id FROM users")
    return [r[0] for r in cursor.fetchall()]

def add_secondary_admin(admin_id, added_by):
    cursor.execute("SELECT id FROM admins WHERE id=?", (admin_id,))
    if cursor.fetchone():
        return False
    cursor.execute("INSERT INTO admins (id, added_by, added_at) VALUES (?, ?, ?)", (admin_id, added_by, datetime.utcnow().isoformat()))
    conn.commit()
    return True

def remove_secondary_admin(admin_id):
    cursor.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    conn.commit()

def list_secondary_admins():
    cursor.execute("SELECT id, added_by, added_at FROM admins")
    return cursor.fetchall()

def is_admin(user_id):
    if user_id == MAIN_ADMIN:
        return True
    cursor.execute("SELECT 1 FROM admins WHERE id=?", (user_id,))
    return cursor.fetchone() is not None

# -------------------------
# Confession helpers
# -------------------------
def create_confession(user_id, content, tags_list, status="pending"):
    tags_str = ",".join(tags_list) if tags_list else ""
    cursor.execute(
        "INSERT INTO confessions (user_id, content, tags, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, content, tags_str, status, datetime.utcnow().isoformat())
    )
    conn.commit()
    return cursor.lastrowid

def get_confession_by_id(conf_id):
    cursor.execute("SELECT id, user_id, content, tags, status, created_at FROM confessions WHERE id=?", (conf_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "content": row[2],
        "tags": row[3].split(",") if row[3] else [],
        "status": row[4],
        "created_at": row[5]
    }

def set_confession_status(conf_id, status):
    cursor.execute("UPDATE confessions SET status=? WHERE id=?", (status, conf_id))
    conn.commit()

def get_pending_confessions():
    cursor.execute("SELECT id, user_id, content, tags, created_at FROM confessions WHERE status='pending' ORDER BY id ASC")
    return cursor.fetchall()

# -------------------------
# Comments helpers (anonymous)
# -------------------------
def add_comment(confession_id, text):
    cursor.execute("INSERT INTO comments (confession_id, text, created_at) VALUES (?, ?, ?)",
                   (confession_id, text, datetime.utcnow().isoformat()))
    conn.commit()
    return cursor.lastrowid

def get_comments_for_conf(confession_id, limit=50, offset=0):
    cursor.execute("SELECT id, text, created_at FROM comments WHERE confession_id=? ORDER BY id ASC LIMIT ? OFFSET ?",
                   (confession_id, limit, offset))
    return cursor.fetchall()

def count_comments(confession_id):
    cursor.execute("SELECT COUNT(*) FROM comments WHERE confession_id=?", (confession_id,))
    return cursor.fetchone()[0]

# -------------------------
# Channels helpers
# -------------------------
def add_channel(chat_id, username, added_by):
    cursor.execute("SELECT id FROM channels WHERE id=?", (chat_id,))
    if cursor.fetchone():
        return False
    cursor.execute("INSERT INTO channels (id, username, added_by, added_at) VALUES (?, ?, ?, ?)",
                   (chat_id, username or "", added_by, datetime.utcnow().isoformat()))
    conn.commit()
    return True

def remove_channel(chat_id):
    cursor.execute("DELETE FROM channels WHERE id=?", (chat_id,))
    conn.commit()

def list_channels():
    cursor.execute("SELECT id, username, added_by, added_at FROM channels")
    return cursor.fetchall()

# -------------------------
# Utility: format
# -------------------------
def format_confession_text(conf):
    tags_line = ""
    if conf["tags"]:
        tags_line = "\n\n" + " ".join(f"#{t}" for t in conf["tags"])
    return f"📢 Confession #{conf['id']}\n{conf['content']}{tags_line}"

# -------------------------
# In-memory pending flows
# -------------------------
# pending_confessions[user_id] = {"content": "...", "step":"awaiting_tags"}
pending_confessions = {}
# pending_add_comment[user_id] = confession_id they are adding a comment to
pending_add_comment = {}
# pagination state for viewing comments: view_comments_state[user_id] = {"confession_id": id, "page": n}
view_comments_state = {}

# -------------------------
# Handlers
# -------------------------
@bot.message_handler(commands=['start'])
def cmd_start(m):
    add_user_if_missing(m.from_user.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📝 Confess")
    if is_admin(m.from_user.id):
        markup.add("⚙ Admin Panel")
    bot.send_message(m.chat.id, "Welcome. Tap 'Confess' to send an anonymous confession.", reply_markup=markup)

# ---- CONFESSION FLOW ----
@bot.message_handler(func=lambda msg: msg.text == "📝 Confess")
def start_confess(msg):
    add_user_if_missing(msg.from_user.id)
    bot.send_message(msg.chat.id, "Send your confession text. After sending you'll be asked to add up to 4 tag words (or Skip).")
    bot.register_next_step_handler(msg, receive_confession_text)

def receive_confession_text(msg):
    text = (msg.text or "").strip()
    if not text:
        bot.send_message(msg.chat.id, "Confession cannot be empty. Try /start or press Confess again.")
        return
    # store pending
    user_id = msg.from_user.id
    pending_confessions[user_id] = {"content": text}
    # ask for tags with Skip button
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏭ Skip", callback_data=f"skip_tags"))
    bot.send_message(msg.chat.id, "Now send up to 4 tag words separated by spaces (e.g., trauma school friends). Or press Skip.", reply_markup=markup)
    bot.register_next_step_handler(msg, receive_confession_tags)

def receive_confession_tags(msg):
    user_id = msg.from_user.id
    if user_id not in pending_confessions:
        bot.send_message(msg.chat.id, "No pending confession. Press Confess to start.")
        return
    if msg.text is None:
        bot.send_message(msg.chat.id, "Please send text tags or press Skip.")
        return
    raw = msg.text.strip()
    words = raw.split()[:4]
    tags = [w.strip().replace("#", "") for w in words if w.strip()]
    content = pending_confessions[user_id]["content"]
    # create confession
    add_user_if_missing(user_id)
    auto = is_auto_approve()
    status = "approved" if auto else "pending"
    conf_id = create_confession(user_id, content, tags, status=status)
    conf = get_confession_by_id(conf_id)
    # post if auto
    if auto:
        # post to all saved channels
        chans = list_channels()
        if not chans:
            bot.send_message(user_id, "No channels configured. Admin will be notified.")
        else:
            for ch in chans:
                ch_id = ch[0]
                try:
                    # include comment button
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💬 Comment", callback_data=f"comment|{conf_id}"))
                    bot.send_message(ch_id, format_confession_text(conf), reply_markup=markup)
                except Exception as e:
                    print("Post error:", e)
        bot.send_message(user_id, "Your confession was posted anonymously ✅")
    else:
        # send to admins for approval
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve|{conf_id}"),
                   types.InlineKeyboardButton("❌ Decline", callback_data=f"decline|{conf_id}"))
        # notify main admin and secondary admins
        try:
            bot.send_message(MAIN_ADMIN, f"<b>New confession #{conf_id} awaiting approval</b>:\n\n{content}\n\nTags: {' '.join(tags) if tags else 'None'}", reply_markup=markup)
        except Exception:
            pass
        for row in list_secondary_admins():
            aid = row[0]
            try:
                bot.send_message(aid, f"<b>New confession #{conf_id} awaiting approval</b>:\n\n{content}\n\nTags: {' '.join(tags) if tags else 'None'}", reply_markup=markup)
            except Exception:
                pass
        bot.send_message(user_id, "Your confession was sent for admin review ✅")
    # cleanup
    pending_confessions.pop(user_id, None)

# Handle Skip tags via callback
@bot.callback_query_handler(func=lambda c: c.data == "skip_tags")
def handle_skip_tags(call):
    user_id = call.from_user.id
    if user_id not in pending_confessions:
        bot.answer_callback_query(call.id, "No pending confession.")
        return
    content = pending_confessions[user_id]["content"]
    add_user_if_missing(user_id)
    auto = is_auto_approve()
    status = "approved" if auto else "pending"
    conf_id = create_confession(user_id, content, [], status=status)
    conf = get_confession_by_id(conf_id)
    if auto:
        chans = list_channels()
        if not chans:
            bot.send_message(user_id, "No channels configured. Admin will be notified.")
        else:
            for ch in chans:
                ch_id = ch[0]
                try:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💬 Comment", callback_data=f"comment|{conf_id}"))
                    bot.send_message(ch_id, format_confession_text(conf), reply_markup=markup)
                except Exception:
                    pass
        bot.send_message(user_id, "Your confession was posted anonymously ✅")
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve|{conf_id}"),
                   types.InlineKeyboardButton("❌ Decline", callback_data=f"decline|{conf_id}"))
        try:
            bot.send_message(MAIN_ADMIN, f"<b>New confession #{conf_id} awaiting approval</b>:\n\n{content}\n\nTags: None", reply_markup=markup)
        except Exception:
            pass
        for row in list_secondary_admins():
            aid = row[0]
            try:
                bot.send_message(aid, f"<b>New confession #{conf_id} awaiting approval</b>:\n\n{content}\n\nTags: None", reply_markup=markup)
            except Exception:
                pass
        bot.send_message(user_id, "Your confession was sent for admin review ✅")
    pending_confessions.pop(user_id, None)
    bot.answer_callback_query(call.id, "Skipped tags — confession saved.")

# ---- CALLBACKS: approve/decline/comment ----
@bot.callback_query_handler(func=lambda call: call.data and ("|" in call.data))
def handle_callback(call):
    data = call.data
    action, sid = data.split("|", 1)
    try:
        conf_id = int(sid)
    except:
        bot.answer_callback_query(call.id, "Invalid ID.")
        return

    if action in ("approve", "decline"):
        # Only admins
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Not authorized.")
            return
        conf = get_confession_by_id(conf_id)
        if not conf:
            bot.answer_callback_query(call.id, "Confession not found.")
            return
        if action == "approve":
            # mark approved and post to channels
            set_confession_status(conf_id, "approved")
            conf = get_confession_by_id(conf_id)
            chans = list_channels()
            if not chans:
                bot.send_message(call.from_user.id, "No channels configured. Add a channel in Admin Panel.")
            else:
                for ch in chans:
                    ch_id = ch[0]
                    try:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("💬 Comment", callback_data=f"comment|{conf_id}"))
                        bot.send_message(ch_id, format_confession_text(conf), reply_markup=markup)
                    except Exception as e:
                        print("Posting error", e)
            bot.edit_message_text(f"Confession #{conf_id} approved & posted.", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Approved.")
        else:
            set_confession_status(conf_id, "declined")
            bot.edit_message_text(f"Confession #{conf_id} declined.", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Declined.")
        return

    if action == "comment":
        # open private chat flow: show two options View/Add
        # send the user a private message with the options
        conf = get_confession_by_id(conf_id)
        if not conf:
            bot.answer_callback_query(call.id, "Confession not found.")
            return
        bot.answer_callback_query(call.id, "Open your private chat with the bot to comment.")
        user = call.from_user
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📜 View Comments", callback_data=f"viewcomments|{conf_id}"),
                   types.InlineKeyboardButton("➕ Add Comment", callback_data=f"addcomment|{conf_id}"))
        try:
            bot.send_message(user.id, f"You clicked comment for Confession #{conf_id}. Choose an option:", reply_markup=markup)
        except Exception as e:
            # if bot cannot send private messages (user not started), instruct them
            bot.send_message(call.message.chat.id, f"@{user.username or user.first_name}, please open the bot and press /start so you can comment privately.")
        return

    if action == "addcomment":
        conf = get_confession_by_id(conf_id)
        if not conf:
            bot.answer_callback_query(call.id, "Confession not found.")
            return
        # instruct user to send comment privately
        try:
            bot.send_message(call.from_user.id, f"Send your anonymous comment for Confession #{conf_id} or send /cancel to cancel.")
            pending_add_comment[call.from_user.id] = conf_id
            bot.answer_callback_query(call.id, "Send your comment in private chat.")
        except Exception:
            bot.answer_callback_query(call.id, "Open private chat with the bot first (/start).")

    if action == "viewcomments":
        conf = get_confession_by_id(conf_id)
        if not conf:
            bot.answer_callback_query(call.id, "Confession not found.")
            return
        # show first page of comments (10)
        rows = get_comments_for_conf(conf_id, limit=10, offset=0)
        if not rows:
            try:
                bot.send_message(call.from_user.id, "No comments yet for this confession.")
            except Exception:
                bot.answer_callback_query(call.id, "Open private chat with the bot first (/start).")
            return
        # send formatted list with simple paging buttons
        text = f"Comments for Confession #{conf_id} (showing 1-{len(rows)}):\n\n"
        for r in rows:
            text += f"- {r[1]} ({r[2][:19]})\n"
        markup = types.InlineKeyboardMarkup()
        # if more comments exist, add Next button
        total = count_comments(conf_id)
        if total > 10:
            markup.add(types.InlineKeyboardButton("Next ▶", callback_data=f"viewpage|{conf_id}|1"))
        try:
            bot.send_message(call.from_user.id, text, reply_markup=markup)
        except Exception:
            bot.answer_callback_query(call.id, "Open private chat with the bot first (/start).")
        return

    if action == "viewpage":
        # callback structure: viewpage|conf_id|page_index
        parts = call.data.split("|")
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "Invalid page.")
            return
        conf_id = int(parts[1])
        page = int(parts[2])  # page 1 => offset 10
        per = 10
        offset = page * per
        rows = get_comments_for_conf(conf_id, limit=per, offset=offset)
        if not rows:
            bot.answer_callback_query(call.id, "No more comments.")
            return
        text = f"Comments for Confession #{conf_id} (showing {offset+1}-{offset+len(rows)}):\n\n"
        for r in rows:
            text += f"- {r[1]} ({r[2][:19]})\n"
        markup = types.InlineKeyboardMarkup()
        total = count_comments(conf_id)
        if offset + per < total:
            markup.add(types.InlineKeyboardButton("Next ▶", callback_data=f"viewpage|{conf_id}|{page+1}"))
        if page > 0:
            prev_page = page - 1
            markup.add(types.InlineKeyboardButton("◀ Prev", callback_data=f"viewpage|{conf_id}|{prev_page}"))
        try:
            bot.send_message(call.from_user.id, text, reply_markup=markup)
        except Exception:
            bot.answer_callback_query(call.id, "Open private chat with the bot first (/start).")
        return

# ---- PRIVATE MESSAGE HANDLERS: adding comment or cancel ----
@bot.message_handler(func=lambda m: m.chat.type == "private" and m.from_user.id in pending_add_comment.keys())
def handle_user_comment(m):
    user_id = m.from_user.id
    if m.text and m.text.strip().lower() == "/cancel":
        pending_add_comment.pop(user_id, None)
        bot.send_message(user_id, "Comment cancelled.")
        return
    # accept any text as comment
    conf_id = pending_add_comment.get(user_id)
    if not conf_id:
        bot.send_message(user_id, "No pending comment. Use the Comment button from a post.")
        return
    text = (m.text or "").strip()
    if not text:
        bot.send_message(user_id, "Empty comment. Send text or /cancel.")
        return
    add_comment(conf_id, text)
    pending_add_comment.pop(user_id, None)
    bot.send_message(user_id, "Anonymous comment added ✅")

# ---- ADMIN PANEL ----
@bot.message_handler(func=lambda m: m.text == "⚙ Admin Panel" and is_admin(m.from_user.id))
def admin_panel(m):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Toggle Auto-Approve")
    markup.add("Broadcast to Users", "Broadcast to Channels")
    markup.add("View Sender by Confession #")
    markup.add("Manage Channels")
    if m.from_user.id == MAIN_ADMIN:
        markup.add("Add Admin", "Remove Admin")
    markup.add("Back")
    bot.send_message(m.chat.id, "Admin Panel:", reply_markup=markup)

# Toggle auto-approve
@bot.message_handler(func=lambda m: m.text == "Toggle Auto-Approve" and is_admin(m.from_user.id))
def toggle_auto(m):
    current = is_auto_approve()
    set_auto_approve(not current)
    bot.send_message(m.chat.id, f"Auto-approve is now {'ON' if not current else 'OFF'}.")

# Broadcast to users
@bot.message_handler(func=lambda m: m.text == "Broadcast to Users" and is_admin(m.from_user.id))
def broadcast_to_users_prompt(m):
    bot.send_message(m.chat.id, "Send the message (text/photo/video) you want to broadcast to all users. It will be forwarded to every known user.")
    bot.register_next_step_handler(m, handle_broadcast_to_users)

def handle_broadcast_to_users(m):
    users = get_all_user_ids()
    sent = 0
    for uid in users:
        try:
            if m.content_type == "text":
                bot.send_message(uid, f"📢 Broadcast:\n\n{m.text}")
            elif m.content_type == "photo":
                file_id = m.photo[-1].file_id
                bot.send_photo(uid, file_id, caption=m.caption or "")
            elif m.content_type == "video":
                file_id = m.video.file_id
                bot.send_video(uid, file_id, caption=m.caption or "")
            sent += 1
        except Exception:
            continue
    bot.send_message(m.chat.id, f"Broadcast attempted to {sent} users.")

# Broadcast to channels
@bot.message_handler(func=lambda m: m.text == "Broadcast to Channels" and is_admin(m.from_user.id))
def broadcast_to_channels_prompt(m):
    bot.send_message(m.chat.id, "Send the message (text/photo/video) to broadcast to all saved channels.")
    bot.register_next_step_handler(m, handle_broadcast_to_channels)

def handle_broadcast_to_channels(m):
    chans = list_channels()
    posted = 0
    for ch in chans:
        ch_id = ch[0]
        try:
            if m.content_type == "text":
                bot.send_message(ch_id, f"📢 Broadcast:\n\n{m.text}")
            elif m.content_type == "photo":
                file_id = m.photo[-1].file_id
                bot.send_photo(ch_id, file_id, caption=m.caption or "")
            elif m.content_type == "video":
                file_id = m.video.file_id
                bot.send_video(ch_id, file_id, caption=m.caption or "")
            posted += 1
        except Exception as e:
            print("broadcast channel error", e)
            continue
    bot.send_message(m.chat.id, f"Broadcast posted to {posted} channels.")

# View sender by confession #
@bot.message_handler(func=lambda m: m.text == "View Sender by Confession #" and is_admin(m.from_user.id))
def prompt_view_sender(m):
    bot.send_message(m.chat.id, "Send the confession number to lookup the sender:")
    bot.register_next_step_handler(m, handle_view_sender)

def handle_view_sender(m):
    try:
        num = int(m.text.strip())
    except:
        bot.send_message(m.chat.id, "Invalid number.")
        return
    conf = get_confession_by_id(num)
    if not conf:
        bot.send_message(m.chat.id, "Confession not found.")
        return
    bot.send_message(m.chat.id, f"Confession #{num} was sent by user id: <code>{conf['user_id']}</code>")

# Manage channels
@bot.message_handler(func=lambda m: m.text == "Manage Channels" and is_admin(m.from_user.id))
def manage_channels_menu(m):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("➕ Add Channel", "➖ Remove Channel")
    markup.add("📋 List Channels", "Check Channel Status")
    markup.add("Back")
    bot.send_message(m.chat.id, "Channel Manager:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "➕ Add Channel" and is_admin(m.from_user.id))
def add_channel_prompt(m):
    bot.send_message(m.chat.id, "Send the channel @username (like @mychannel) or numeric chat id (-100...) to add. Make sure the bot is an admin in that channel.")
    bot.register_next_step_handler(m, handle_add_channel)

def handle_add_channel(m):
    raw = m.text.strip()
    try:
        # if starts with @, use get_chat to resolve
        if raw.startswith("@"):
            chat = bot.get_chat(raw)
            chat_id = chat.id
            username = raw
        else:
            chat_id = int(raw)
            chat = bot.get_chat(chat_id)
            username = getattr(chat, "username", "") or ""
        # check bot admin status
        # get chat member for bot
        me = bot.get_me()
        try:
            member = bot.get_chat_member(chat_id, me.id)
            # check status
            if member.status not in ("administrator", "creator"):
                bot.send_message(m.chat.id, "Bot is not an admin in that channel. Make it admin and try again.")
                return
        except Exception:
            bot.send_message(m.chat.id, "Unable to verify bot is admin. Ensure bot is added and has rights.")
            return
        success = add_channel(chat_id, username, m.from_user.id)
        if success:
            bot.send_message(m.chat.id, f"Channel added: {chat_id} ({username})")
        else:
            bot.send_message(m.chat.id, "Channel already exists in database.")
    except Exception as e:
        bot.send_message(m.chat.id, "Invalid channel identifier or I cannot access that channel.")

@bot.message_handler(func=lambda m: m.text == "➖ Remove Channel" and is_admin(m.from_user.id))
def remove_channel_prompt(m):
    bot.send_message(m.chat.id, "Send the numeric chat id of the channel to remove (e.g., -1001234567890).")
    bot.register_next_step_handler(m, handle_remove_channel)

def handle_remove_channel(m):
    try:
        cid = int(m.text.strip())
        remove_channel(cid)
        bot.send_message(m.chat.id, f"Channel removed if it existed: {cid}")
    except:
        bot.send_message(m.chat.id, "Invalid id.")

@bot.message_handler(func=lambda m: m.text == "📋 List Channels" and is_admin(m.from_user.id))
def list_channels_cmd(m):
    rows = list_channels()
    if not rows:
        bot.send_message(m.chat.id, "No channels configured.")
        return
    text = "Configured channels:\n"
    for r in rows:
        text += f"- {r[0]} {('('+r[1]+')') if r[1] else ''} (added_by {r[2]})\n"
    bot.send_message(m.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "Check Channel Status" and is_admin(m.from_user.id))
def check_channel_status_prompt(m):
    bot.send_message(m.chat.id, "Send numeric channel id to check (e.g., -1001234567890):")
    bot.register_next_step_handler(m, handle_check_channel_status)

def handle_check_channel_status(m):
    try:
        cid = int(m.text.strip())
        me = bot.get_me()
        try:
            member = bot.get_chat_member(cid, me.id)
            bot.send_message(m.chat.id, f"Bot's status in that channel: {member.status}")
        except Exception:
            bot.send_message(m.chat.id, "Cannot access channel or bot is not a member/admin.")
    except:
        bot.send_message(m.chat.id, "Invalid id.")

# Add/Remove admin (MAIN_ADMIN ONLY)
@bot.message_handler(func=lambda m: m.text == "Add Admin" and m.from_user.id == MAIN_ADMIN)
def add_admin_prompt(m):
    bot.send_message(m.chat.id, "Send the Telegram ID of the user to add as secondary admin:")
    bot.register_next_step_handler(m, handle_add_admin)

def handle_add_admin(m):
    try:
        new_id = int(m.text.strip())
        if new_id == MAIN_ADMIN:
            bot.send_message(m.chat.id, "That's the main admin already.")
            return
        success = add_secondary_admin(new_id, MAIN_ADMIN)
        if success:
            bot.send_message(m.chat.id, f"Added admin: {new_id}")
        else:
            bot.send_message(m.chat.id, "User is already a secondary admin.")
    except:
        bot.send_message(m.chat.id, "Invalid id.")

@bot.message_handler(func=lambda m: m.text == "Remove Admin" and m.from_user.id == MAIN_ADMIN)
def remove_admin_prompt(m):
    bot.send_message(m.chat.id, "Send Telegram ID of the secondary admin to remove:")
    bot.register_next_step_handler(m, handle_remove_admin)

def handle_remove_admin(m):
    try:
        rid = int(m.text.strip())
        remove_secondary_admin(rid)
        bot.send_message(m.chat.id, f"Removed admin if existed: {rid}")
    except:
        bot.send_message(m.chat.id, "Invalid id.")

# Back button
@bot.message_handler(func=lambda m: m.text == "Back" and is_admin(m.from_user.id))
def back_to_start(m):
    cmd_start(m)

# ---- simple command to list pending confessions (admin convenience) ----
@bot.message_handler(commands=['pending'])
def cmd_pending(m):
    if not is_admin(m.from_user.id):
        bot.send_message(m.chat.id, "Not authorized.")
        return
    rows = get_pending_confessions()
    if not rows:
        bot.send_message(m.chat.id, "No pending confessions.")
        return
    text = "Pending confessions:\n"
    for r in rows:
        conf_id, uid, content, tags, created_at = r
        tags_str = tags if tags else "None"
        text += f"#{conf_id} by <code>{uid}</code>: {content[:50]}... Tags: {tags_str}\n"
    bot.send_message(m.chat.id, text)

# -------------------------
# START BOT
# -------------------------
if __name__ == "__main__":
    print("Bot starting...")
    # Ensure auto_approve setting exists
    if get_setting("auto_approve", None) is None:
        set_auto_approve(False)
    bot.infinity_polling(timeout=60, long_polling_timeout = 60)
