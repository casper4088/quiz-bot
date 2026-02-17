# test.py
# Telegram Quiz Bot: answers check + save to SQLite + export to Excel + leaderboard/rank
# pip install -U aiogram aiosqlite openpyxl

import asyncio
import re
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

# =========================
# 1) CONFIG
# =========================

import os
from aiogram import Bot, Dispatcher

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher()




DB_NAME = "quiz.db"
QUIZ_ID = "quiz_001"

# To'g'ri javoblar (misol: 20 ta savol)
ANSWER_KEY = {
    1: "A",
    2: "C",
    3: "B",
    4: "D",
    5: "A",
    6: "B",
    7: "C",
    8: "D",
    9: "A",
    10: "C",
    11: "D",
    12: "D",
    13: "D",
    14: "D",
    15: "D",
    16: "D",
    17: "D",
    18: "D",
    19: "D",
    20: "D",}
TOTAL = len(ANSWER_KEY)

HELP_TEXT = (
    "📝 Test bot\n\n"
    "Buyruqlar:\n"
    "  /test — testni boshlash\n"
    "  /help — yordam\n\n"
    "Admin buyruqlar:\n"
    "  /export — Excel (.xlsx) eksport\n"
    "  /stats — statistika\n\n"
    "Javob yuborish formatlari:\n"
    "  1A 2C 3B 4D ...\n"
    "yoki\n"
    "  1:A 2:C 3:B ...\n"
)

# User holati (oddiy)
WAITING_USERS = set()

# =========================
# 2) DB FUNCTIONS
# =========================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    full_name TEXT,
    username TEXT,
    quiz_id TEXT,
    answers TEXT,
    score INTEGER,
    total INTEGER,
    created_at TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(CREATE_TABLE_SQL)
        await db.commit()

async def save_result(user_id: int, full_name: str, username: str, quiz_id: str,
                      answers: str, score: int, total: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            INSERT INTO results (user_id, full_name, username, quiz_id, answers, score, total, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, full_name, username, quiz_id, answers, score, total, datetime.now().isoformat(timespec="seconds"))
        )
        await db.commit()

async def fetch_results(limit: int = 20000):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM results ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = await cur.fetchall()
        return rows

async def fetch_leaderboard():
    """
    Reyting: har user uchun eng yaxshi natija MAX(score).
    Tiebreaker: eng yaxshi natijaga erishilgan eng erta vaqt (min created_at).
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row

        # Unikal ishtirokchilar + eng yaxshi natija
        cur = await db.execute(
            """
            SELECT
                user_id,
                COALESCE(MAX(NULLIF(full_name,'')), '') AS full_name,
                COALESCE(MAX(NULLIF(username,'')), '') AS username,
                MAX(score) AS best_score,
                MAX(total) AS total,
                MIN(created_at) AS first_time,
                MIN(CASE WHEN score = (SELECT MAX(score) FROM results r2 WHERE r2.user_id = results.user_id)
                         THEN created_at END) AS best_time
            FROM results
            WHERE quiz_id = ?
            GROUP BY user_id
            """,
            (QUIZ_ID,)
        )
        rows = await cur.fetchall()

    # best_time None bo'lib qolsa, first_time ni ishlatamiz
    prepared = []
    for r in rows:
        best_time = r["best_time"] or r["first_time"]
        prepared.append({
            "user_id": r["user_id"],
            "full_name": r["full_name"] or "",
            "username": r["username"] or "",
            "best_score": int(r["best_score"] or 0),
            "total": int(r["total"] or TOTAL),
            "best_time": best_time or "9999-12-31T23:59:59",
        })

    # Sort: score desc, best_time asc
    prepared.sort(key=lambda x: (-x["best_score"], x["best_time"]))
    return prepared

# =========================
# 3) EXCEL EXPORT
# =========================

def export_results_to_xlsx(rows, filename="results.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    headers = ["ID", "UserID", "Full name", "Username", "QuizID", "Answers", "Score", "Total", "CreatedAt"]
    ws.append(headers)

    for r in rows:
        ws.append([
            r["id"], r["user_id"], r["full_name"], r["username"], r["quiz_id"],
            r["answers"], r["score"], r["total"], r["created_at"]
        ])

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18

    wb.save(filename)
    return filename

# =========================
# 4) QUIZ LOGIC
# =========================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def parse_answers(text: str):
    """
    Qabul qilinadigan:
      1A 2C 3B
      1:A 2:C 3:B
      1-A 2-C ...
      1)A 2)C ...
    """
    t = (text or "").strip().upper()
    pattern = r"(\d{1,4})\s*[:\-\)\.]*\s*([ABCD])"
    found = re.findall(pattern, t)
    if not found:
        return None

    answers = {}
    for q_str, opt in found:
        q = int(q_str)
        answers[q] = opt
    return answers

def answers_to_string(answers: dict):
    items = []
    for q in sorted(answers.keys()):
        items.append(f"{q}:{answers[q]}")
    return ",".join(items)

def grade(answers: dict):
    score = 0
    details = []
    for q, correct in ANSWER_KEY.items():
        got = answers.get(q)
        if got == correct:
            score += 1
            details.append(f"{q}:{got} ✅")
        elif got is None:
            details.append(f"{q}:— ❌ (to‘g‘ri: {correct})")
        else:
            details.append(f"{q}:{got} ❌ (to‘g‘ri: {correct})")
    return score, "\n".join(details)

def short_name(full_name: str, username: str):
    full_name = (full_name or "").strip()
    username = (username or "").strip()
    if username:
        return f"{full_name} (@{username})" if full_name else f"@{username}"
    return full_name if full_name else "Noma'lum"

def format_top5(leaderboard):
    top = leaderboard[:5]
    if not top:
        return "Hozircha reyting yo‘q."
    lines = []
    for i, r in enumerate(top, start=1):
        lines.append(f"{i}) {short_name(r['full_name'], r['username'])} — {r['best_score']}/{r['total']}")
    return "\n".join(lines)

def get_user_rank(leaderboard, user_id: int):
    for i, r in enumerate(leaderboard, start=1):
        if r["user_id"] == user_id:
            return i, r
    return None, None

# =========================
# 5) BOT
# =========================

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("❌ BOT_TOKEN qo'yilmagan. test.py ichida BOT_TOKEN ni kiriting!")

    await init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(m: Message):
        await m.answer("Assalomu alaykum!\n\n" + HELP_TEXT)

    @dp.message(Command("help"))
    async def help_cmd(m: Message):
        await m.answer(HELP_TEXT)

    @dp.message(Command("test"))
    async def test_cmd(m: Message):
        WAITING_USERS.add(m.from_user.id)
        await m.answer(
            "✅ Test boshlandi.\n\n"
            f"Javoblarni bitta xabarda yuboring.\n"
            f"Masalan: 1A 2B 3C 4D ... (1 dan {TOTAL} gacha)\n\n"
            "Yuborganingizdan so‘ng men tekshiraman."
        )

    @dp.message(Command("stats"))
    async def stats_cmd(m: Message):
        if not is_admin(m.from_user.id):
            return await m.answer("⛔ Bu buyruq faqat admin uchun.")

        leaderboard = await fetch_leaderboard()
        if not leaderboard:
            return await m.answer("Hozircha natija yo‘q.")

        total_users = len(leaderboard)
        avg = sum(x["best_score"] for x in leaderboard) / total_users
        best = leaderboard[0]

        await m.answer(
            "📊 Statistika (eng yaxshi natijalar bo‘yicha)\n\n"
            f"Ishtirokchilar: {total_users}\n"
            f"O‘rtacha ball: {avg:.2f}/{TOTAL}\n"
            f"1-o‘rin: {short_name(best['full_name'], best['username'])} — {best['best_score']}/{best['total']}"
        )

    @dp.message(Command("export"))
    async def export_cmd(m: Message):
        if not is_admin(m.from_user.id):
            return await m.answer("⛔ Bu buyruq faqat admin uchun.")

        rows = await fetch_results(limit=20000)
        if not rows:
            return await m.answer("Hozircha natija yo‘q, eksport qilolmayman.")

        filename = export_results_to_xlsx(rows, filename="results.xlsx")
        await m.answer_document(
            document=open(filename, "rb"),
            caption="📁 Excel natijalar (results.xlsx)"
        )

    @dp.message(F.text)
    async def on_text(m: Message):
        if m.from_user.id not in WAITING_USERS:
            return

        parsed = parse_answers(m.text)
        if parsed is None:
            return await m.answer(
                "❗ Format noto‘g‘ri.\n"
                f"Masalan: 1A 2B 3C 4D ... (1 dan {TOTAL} gacha)\n"
                "Qayta yuboring."
            )

        score, details = grade(parsed)
        WAITING_USERS.discard(m.from_user.id)

        full_name = (m.from_user.full_name or "").strip()
        username = (m.from_user.username or "").strip()

        await save_result(
            user_id=m.from_user.id,
            full_name=full_name,
            username=username,
            quiz_id=QUIZ_ID,
            answers=answers_to_string(parsed),
            score=score,
            total=TOTAL,
        )

        # ===== LEADERBOARD / RANK INFO =====
        leaderboard = await fetch_leaderboard()
        total_users = len(leaderboard)
        rank, myrow = get_user_rank(leaderboard, m.from_user.id)

        top5_text = format_top5(leaderboard)
        my_rank_text = (
            f"🏁 Sizning o‘rningiz: {rank}/{total_users} — {myrow['best_score']}/{myrow['total']}"
            if rank is not None else
            "🏁 Sizning o‘rningiz: aniqlanmadi."
        )

        await m.answer(
            f"✅ Tekshirildi!\n\n"
            f"Natija: {score}/{TOTAL}\n\n"
            f"{details}\n\n"
            f"👥 Ishtirokchilar: {total_users}\n"
            f"🏆 Top 5:\n{top5_text}\n\n"
            f"{my_rank_text}"
        )

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())










