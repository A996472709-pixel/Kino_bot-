import os
import sqlite3
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== SOZLAMALAR ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",")
    if x
]
DB_PATH = os.environ.get("DB_PATH", "kino.db")

# Kino qo'shish jarayonining bosqichlari
ASK_CODE, ASK_NAME, ASK_VIDEO = range(3)


# ==================== BAZA ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            file_id TEXT NOT NULL,
            added_by INTEGER
        )
        """
    )
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH)


def add_movie(code, name, file_id, added_by):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO movies (code, name, file_id, added_by) VALUES (?, ?, ?, ?)",
        (code, name, file_id, added_by),
    )
    conn.commit()
    conn.close()


def get_movie_by_code(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, name, file_id FROM movies WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return row


def search_movies_by_name(query, limit=10):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT code, name FROM movies WHERE name LIKE ? LIMIT ?",
        (f"%{query}%", limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_movie(code):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM movies WHERE code = ?", (code,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def count_movies():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM movies")
    n = cur.fetchone()[0]
    conn.close()
    return n


# ==================== YORDAMCHI ====================
def is_admin(user_id):
    return user_id in ADMIN_IDS


# ==================== ODDIY FOYDALANUVCHI ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom! 🎬 Kino botiga xush kelibsiz.\n\n"
        "— Kino kodini yuboring (masalan: 101)\n"
        "— Yoki kino nomini yozing, men qidirib beraman.\n\n"
        f"Bazada hozircha {count_movies()} ta kino bor."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Kod bo'yicha qidirish (faqat raqamlardan iborat bo'lsa)
    if text.isdigit():
        movie = get_movie_by_code(text)
        if movie:
            code, name, file_id = movie
            await update.message.reply_video(
                video=file_id, caption=f"🎬 {name}\nKod: {code}"
            )
        else:
            await update.message.reply_text(
                "Bu kod bo'yicha kino topilmadi. Nomini yozib ko'ring."
            )
        return

    # Nom bo'yicha qidirish
    results = search_movies_by_name(text)
    if not results:
        await update.message.reply_text("Hech narsa topilmadi 😔")
        return

    if len(results) == 1:
        code, name = results[0]
        movie = get_movie_by_code(code)
        _, name, file_id = movie
        await update.message.reply_video(
            video=file_id, caption=f"🎬 {name}\nKod: {code}"
        )
        return

    buttons = [
        [InlineKeyboardButton(f"{name} (#{code})", callback_data=f"get:{code}")]
        for code, name in results
    ]
    await update.message.reply_text(
        "Topilgan kinolar:", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("get:"):
        code = query.data.split(":", 1)[1]
        movie = get_movie_by_code(code)
        if movie:
            _, name, file_id = movie
            await query.message.reply_video(
                video=file_id, caption=f"🎬 {name}\nKod: {code}"
            )
        else:
            await query.message.reply_text("Kino topilmadi, o'chirilgan bo'lishi mumkin.")


# ==================== ADMIN: KINO QO'SHISH ====================
async def addmovie_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return ConversationHandler.END

    await update.message.reply_text("Kino uchun kod kiriting (masalan: 101):")
    return ASK_CODE


async def addmovie_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if not code.isdigit():
        await update.message.reply_text("Kod faqat raqamlardan iborat bo'lsin. Qayta kiriting:")
        return ASK_CODE

    if get_movie_by_code(code):
        await update.message.reply_text(
            f"⚠️ {code} kodi band. Bu kodni ishlatsangiz eski kino almashadi. "
            "Boshqa kod kiriting yoki shu kodni qayta yuboring (tasdiqlash uchun)."
        )
    context.user_data["new_code"] = code
    await update.message.reply_text("Endi kino nomini kiriting:")
    return ASK_NAME


async def addmovie_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_name"] = update.message.text.strip()
    await update.message.reply_text("Endi kino videosini (yoki faylini) yuboring:")
    return ASK_VIDEO


async def addmovie_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_id = None
    if msg.video:
        file_id = msg.video.file_id
    elif msg.document:
        file_id = msg.document.file_id

    if not file_id:
        await update.message.reply_text("Iltimos, video yoki fayl yuboring.")
        return ASK_VIDEO

    code = context.user_data["new_code"]
    name = context.user_data["new_name"]
    add_movie(code, name, file_id, update.effective_user.id)

    await update.message.reply_text(
        f"✅ Qo'shildi!\nKod: {code}\nNomi: {name}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def addmovie_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


# ==================== ADMIN: O'CHIRISH VA STATISTIKA ====================
async def delmovie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return

    if not context.args:
        await update.message.reply_text("Foydalanish: /delmovie <kod>")
        return

    code = context.args[0]
    deleted = delete_movie(code)
    if deleted:
        await update.message.reply_text(f"🗑 {code} o'chirildi.")
    else:
        await update.message.reply_text("Bunday kod topilmadi.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(f"Bazada {count_movies()} ta kino bor.")


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning Telegram ID: {update.effective_user.id}")


# ==================== MAIN ====================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable o'rnatilmagan!")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("addmovie", addmovie_start)],
        states={
            ASK_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addmovie_code)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addmovie_name)],
            ASK_VIDEO: [MessageHandler((filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND, addmovie_video)],
        },
        fallbacks=[CommandHandler("cancel", addmovie_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("delmovie", delmovie))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
