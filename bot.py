import asyncio
import logging
from datetime import datetime

import aiosqlite
from openpyxl import Workbook

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


# =========================
#  SOZLAMALAR
# =========================
import os
from aiogram import Bot, Dispatcher
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "837458333").split(",") if x.strip().isdigit()}

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN yo'q! Railway Variables ga qo'ying.")


# ✅ Adminlar ro'yxati (Siz + shogird)
ADMIN_IDS = {114677843, 5458639295}

DB_PATH = "orders.db"

STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"


# =========================
#  FSM (FORMA)
# =========================
class OrderForm(StatesGroup):
    service = State()
    name = State()
    phone = State()
    problem = State()
    location = State()


# =========================
#  KEYBOARDS
# =========================
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="➕ Yangi buyurtma")]],
        resize_keyboard=True
    )


def service_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💻 Kompyuter"), KeyboardButton(text="📱 Telefon")],
            [KeyboardButton(text="🌐 Internet"), KeyboardButton(text="📷 Kamera")],
            [KeyboardButton(text="🖨 Printer")],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True
    )


def contact_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📞 Telefon raqam yuborish", request_contact=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True
    )


def admin_controls_kb(order_id: int) -> InlineKeyboardMarkup:
    # Qattiq tartib: avval assign, keyin status
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Men oldim", callback_data=f"as:{order_id}")],
        [
            InlineKeyboardButton(text="▶️ In progress", callback_data=f"st:{order_id}:{STATUS_IN_PROGRESS}"),
            InlineKeyboardButton(text="✅ Done", callback_data=f"st:{order_id}:{STATUS_DONE}")
        ],
        [InlineKeyboardButton(text="🆕 New", callback_data=f"st:{order_id}:{STATUS_NEW}")]
    ])


def rating_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:{order_id}:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:{order_id}:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:{order_id}:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:{order_id}:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:{order_id}:5"),
        ]
    ])


def status_label(st: str) -> str:
    if st == STATUS_NEW:
        return "🆕 new"
    if st == STATUS_IN_PROGRESS:
        return "▶️ in_progress"
    if st == STATUS_DONE:
        return "✅ done"
    return st


def location_hint_text() -> str:
    return (
        "📍 Telefon bo‘lsa lokatsiya yuboring.\n"
        "💻 Desktop bo‘lsa manzilni matn ko‘rinishida yozing.\n\n"
        "Masalan: A-Bino, 32-xona, yoki bo'lim nomini kiriting."
    )


def admin_id_to_name(admin_id: int) -> str:
    # Oddiy ko'rinish. Xohlasangiz alohida nom berib qo'yamiz.
    if admin_id == 114677843:
        return "Ako (admin)"
    if admin_id == 5458639295:
        return "Shogird (admin)"
    return str(admin_id)


# =========================
#  DB FUNKSIYALAR
# =========================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Minimal schema (eski baza bilan moslashish)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                service TEXT,
                name TEXT,
                phone TEXT,
                problem TEXT,
                address TEXT,
                tg_username TEXT,
                tg_user_id INTEGER
            )
        """)
        await db.commit()

        cursor = await db.execute("PRAGMA table_info(orders)")
        cols = [row[1] for row in await cursor.fetchall()]

        if "status" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
            await db.commit()

        if "assigned_to" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN assigned_to INTEGER")
            await db.commit()

        if "rating" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN rating INTEGER")
            await db.commit()

        if "rated_admin_id" not in cols:
            await db.execute("ALTER TABLE orders ADD COLUMN rated_admin_id INTEGER")
            await db.commit()


async def save_order(data: dict, address: str, tg_username: str, tg_user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO orders (
                created_at, status, assigned_to, rating, rated_admin_id,
                service, name, phone, problem, address, tg_username, tg_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            STATUS_NEW,
            None,
            None,
            None,
            data.get("service", ""),
            data.get("name", ""),
            data.get("phone", ""),
            data.get("problem", ""),
            address,
            tg_username,
            tg_user_id
        ))
        await db.commit()
        return cursor.lastrowid


async def assign_order(order_id: int, admin_id: int) -> bool:
    """Bir marta biriktiriladi (assigned_to NULL bo'lsa)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE orders SET assigned_to = ? WHERE id = ? AND assigned_to IS NULL",
            (admin_id, order_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_order_status(order_id: int, new_status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        await db.commit()
        return cursor.rowcount > 0


async def set_order_rating(order_id: int, rating: int, rated_admin_id: int | None) -> bool:
    """Rating faqat 1 marta yoziladi (rating NULL bo'lsa)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE orders SET rating = ?, rated_admin_id = ? WHERE id = ? AND (rating IS NULL)",
            (rating, rated_admin_id, order_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_order(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT
                id, created_at, status, assigned_to, rating, rated_admin_id,
                service, name, phone, problem, address, tg_username, tg_user_id
            FROM orders
            WHERE id = ?
        """, (order_id,))
        return await cursor.fetchone()


async def export_to_excel(filepath="orders.xlsx"):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT
                id, created_at, status, assigned_to, rating, rated_admin_id,
                service, name, phone, problem, address, tg_username, tg_user_id
            FROM orders
            ORDER BY id DESC
        """)
        rows = await cursor.fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "Orders"

    ws.append([
        "ID", "CreatedAt", "Status", "AssignedTo", "Rating", "RatedAdminID",
        "Service", "Name", "Phone", "Problem", "Address", "TG Username", "TG User ID"
    ])
    for r in rows:
        ws.append(list(r))

    wb.save(filepath)
    return filepath


# =========================
#  BOT
# =========================
async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    await init_db()

    # -------- /start --------
    @dp.message(CommandStart())
    async def start(message: types.Message, state: FSMContext):
        await state.clear()
        await message.answer(
            "Assalomu alaykum! 🔧\n"
            "Texnik yordam botiga xush kelibsiz.\n\n"
            "Buyurtma berish uchun pastdagi tugmani bosing 👇",
            reply_markup=main_menu_kb()
        )

    # -------- /id --------
    @dp.message(Command("id"))
    async def my_id(message: types.Message):
        await message.answer(f"Sizning ID: {message.from_user.id}")

    # -------- Cancel --------
    @dp.message(Command("cancel"))
    @dp.message(lambda m: m.text and m.text.lower() in ["❌ bekor qilish", "bekor qilish"])
    async def cancel(message: types.Message, state: FSMContext):
        await state.clear()
        await message.answer("Bekor qilindi ✅", reply_markup=main_menu_kb())

    # -------- Start order (/order yoki tugma) --------
    @dp.message(Command("order"))
    @dp.message(lambda m: m.text == "➕ Yangi buyurtma")
    async def order_start(message: types.Message, state: FSMContext):
        await state.clear()
        await state.set_state(OrderForm.service)
        await message.answer("🧰 Xizmat turini tanlang:", reply_markup=service_kb())

    # 1) Service
    @dp.message(OrderForm.service)
    async def get_service(message: types.Message, state: FSMContext):
        text = (message.text or "").strip()
        allowed = {"💻 Kompyuter", "📱 Telefon", "🌐 Internet", "📷 Kamera", "🖨 Printer"}

        if text not in allowed:
            await message.answer("Iltimos, xizmat turini tugmadan tanlang:", reply_markup=service_kb())
            return

        await state.update_data(service=text)
        await state.set_state(OrderForm.name)
        await message.answer("👤 Ismingizni kiriting:", reply_markup=ReplyKeyboardRemove())

    # 2) Name
    @dp.message(OrderForm.name)
    async def get_name(message: types.Message, state: FSMContext):
        name = (message.text or "").strip()
        if len(name) < 2:
            await message.answer("Ism juda qisqa. Qayta kiriting:")
            return

        await state.update_data(name=name)
        await state.set_state(OrderForm.phone)
        await message.answer("📞 Telefon raqamingizni yuboring:", reply_markup=contact_kb())

    # 3) Phone contact
    @dp.message(OrderForm.phone, lambda m: m.contact is not None)
    async def get_phone_contact(message: types.Message, state: FSMContext):
        phone = (message.contact.phone_number or "").strip()
        await state.update_data(phone=phone)
        await state.set_state(OrderForm.problem)
        await message.answer("📝 Muammo tavsifini yozing:", reply_markup=ReplyKeyboardRemove())

    # 3b) Phone text (desktop fallback)
    @dp.message(OrderForm.phone)
    async def get_phone_text(message: types.Message, state: FSMContext):
        phone = (message.text or "").strip()
        if len(phone) < 7:
            await message.answer("Telefonni tugma orqali yuboring yoki to‘g‘ri raqam kiriting:", reply_markup=contact_kb())
            return

        await state.update_data(phone=phone)
        await state.set_state(OrderForm.problem)
        await message.answer("📝 Muammo tavsifini yozing:", reply_markup=ReplyKeyboardRemove())

    # 4) Problem
    @dp.message(OrderForm.problem)
    async def get_problem(message: types.Message, state: FSMContext):
        problem = (message.text or "").strip()
        if len(problem) < 5:
            await message.answer("Tavsif juda qisqa. Biroz batafsilroq yozing:")
            return

        await state.update_data(problem=problem)
        await state.set_state(OrderForm.location)
        await message.answer(location_hint_text(), reply_markup=ReplyKeyboardRemove())

    # 5) Location or address text
    @dp.message(OrderForm.location)
    async def get_location(message: types.Message, state: FSMContext):
        data = await state.get_data()

        if message.location:
            address = f"{message.location.latitude}, {message.location.longitude}"
            location_text = f"Lokatsiya: {address}"
        else:
            if not message.text:
                await message.answer("Manzilni matn ko‘rinishida yozing (Desktop) yoki telefondan lokatsiya yuboring.")
                return

            address = message.text.strip()
            if len(address) < 8:
                await message.answer("Manzil juda qisqa. Batafsilroq yozing: Shahar, tuman, ko‘cha, uy.")
                return

            location_text = f"Manzil: {address}"

        user = message.from_user
        tg_username = f"@{user.username}" if user.username else ""
        tg_user_id = user.id

        order_id = await save_order(data, address=address, tg_username=tg_username, tg_user_id=tg_user_id)

        admin_text = (
            "🆕 Yangi buyurtma!\n\n"
            f"🆔 Order ID: {order_id}\n"
            f"📌 Status: {status_label(STATUS_NEW)}\n"
            f"👨‍🔧 Assigned: (yo‘q)\n"
            f"⭐ Rating: (yo‘q)\n\n"
            f"🧰 Xizmat: {data.get('service','-')}\n"
            f"👤 Ism: {data.get('name','-')}\n"
            f"📞 Telefon: {data.get('phone','-')}\n"
            f"📝 Muammo: {data.get('problem','-')}\n"
            f"📍 {location_text}\n"
            f"👤 Telegram: {tg_username or '(username yo‘q)'}\n"
            f"🆔 User ID: {tg_user_id}\n"
        )

        # ✅ buyurtmani hamma adminlarga yuboramiz
        for admin_id in ADMIN_IDS:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_controls_kb(order_id))
            if message.location:
                await bot.send_location(admin_id, message.location.latitude, message.location.longitude)

        await state.clear()
        await message.answer(
            "✅ Buyurtmangiz qabul qilindi.\n"
            "Yana buyurtma bermoqchi bo‘lsangiz, pastdagi tugmani bosing 👇",
            reply_markup=main_menu_kb()
        )

    # -------- Assign callback (Qattiq tartib) --------
    @dp.callback_query(lambda c: c.data and c.data.startswith("as:"))
    async def cb_assign(callback: types.CallbackQuery):
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Faqat admin.", show_alert=True)
            return

        try:
            _, order_id_str = callback.data.split(":", 1)
            order_id = int(order_id_str)
        except Exception:
            await callback.answer("Xato.", show_alert=True)
            return

        ok = await assign_order(order_id, callback.from_user.id)
        if not ok:
            # allaqachon biriktirilgan
            row = await get_order(order_id)
            if row:
                assigned_to = row[3]
                await callback.answer(
                    f"Bu buyurtma allaqachon {admin_id_to_name(assigned_to)} ga biriktirilgan ✅",
                    show_alert=True
                )
            else:
                await callback.answer("Buyurtma topilmadi.", show_alert=True)
            return

        await callback.answer("Sizga biriktirildi ✅")

        # O'zidagi xabarni yangilab qo'yamiz
        row = await get_order(order_id)
        if not row:
            return

        (oid, created_at, status, assigned_to, rating, rated_admin_id,
         service, name, phone, problem, address, tg_username, tg_user_id) = row

        updated_text = (
            "🧾 Buyurtma (biriktirildi)\n\n"
            f"🆔 Order ID: {oid}\n"
            f"📌 Status: {status_label(status)}\n"
            f"👨‍🔧 Assigned: {admin_id_to_name(assigned_to)}\n"
            f"⭐ Rating: {rating if rating is not None else '(yo‘q)'}\n\n"
            f"🧰 Xizmat: {service}\n"
            f"👤 Ism: {name}\n"
            f"📞 Telefon: {phone}\n"
            f"📝 Muammo: {problem}\n"
            f"📍 Manzil/Lokatsiya: {address}\n"
        )
        await callback.message.edit_text(updated_text, reply_markup=admin_controls_kb(oid))

    # -------- Status callback (Qattiq tartib) --------
    @dp.callback_query(lambda c: c.data and c.data.startswith("st:"))
    async def cb_set_status(callback: types.CallbackQuery):
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Faqat admin o‘zgartira oladi.", show_alert=True)
            return

        try:
            _, order_id_str, new_status = callback.data.split(":", 2)
            order_id = int(order_id_str)
        except Exception:
            await callback.answer("Xato callback.", show_alert=True)
            return

        if new_status not in {STATUS_NEW, STATUS_IN_PROGRESS, STATUS_DONE}:
            await callback.answer("Status noto‘g‘ri.", show_alert=True)
            return

        row = await get_order(order_id)
        if not row:
            await callback.answer("Order topilmadi.", show_alert=True)
            return

        (oid, created_at, status, assigned_to, rating, rated_admin_id,
         service, name, phone, problem, address, tg_username, tg_user_id) = row

        # ✅ QATTIQ QOIDA:
        if assigned_to is None:
            await callback.answer("Avval 📌 Men oldim ni bosing.", show_alert=True)
            return

        if callback.from_user.id != assigned_to:
            await callback.answer("Bu buyurtma boshqa ustaga biriktirilgan.", show_alert=True)
            return

        ok = await update_order_status(order_id, new_status)
        if not ok:
            await callback.answer("Status yangilanmadi.", show_alert=True)
            return

        row2 = await get_order(order_id)
        if not row2:
            await callback.answer("Order topilmadi.", show_alert=True)
            return

        (oid, created_at, status, assigned_to, rating, rated_admin_id,
         service, name, phone, problem, address, tg_username, tg_user_id) = row2

        updated_text = (
            "🧾 Buyurtma yangilandi!\n\n"
            f"🆔 Order ID: {oid}\n"
            f"🕒 Vaqt: {created_at}\n"
            f"📌 Status: {status_label(status)}\n"
            f"👨‍🔧 Assigned: {admin_id_to_name(assigned_to)}\n"
            f"⭐ Rating: {rating if rating is not None else '(yo‘q)'}\n\n"
            f"🧰 Xizmat: {service}\n"
            f"👤 Ism: {name}\n"
            f"📞 Telefon: {phone}\n"
            f"📝 Muammo: {problem}\n"
            f"📍 Manzil/Lokatsiya: {address}\n"
        )

        await callback.message.edit_text(updated_text, reply_markup=admin_controls_kb(oid))
        await callback.answer("Status yangilandi ✅")

        # Done bo'lsa — buyurtmachiga xabar + rating
        if new_status == STATUS_DONE:
            try:
                await callback.bot.send_message(
                    tg_user_id,
                    "✅ Buyurtmangiz muvaffaqiyatli yakunlandi.\n"
                    "Sizga xizmat qilganimizdan mamnunmiz! 🙏\n\n"
                    "Iltimos, xizmatimizni 5 ballik tizimda baholang 👇",
                    reply_markup=rating_kb(oid)
                )
            except Exception:
                pass

    # -------- Rating callback (user) --------
    @dp.callback_query(lambda c: c.data and c.data.startswith("rate:"))
    async def cb_rate(callback: types.CallbackQuery):
        try:
            _, order_id_str, rating_str = callback.data.split(":", 2)
            order_id = int(order_id_str)
            rating = int(rating_str)
        except Exception:
            await callback.answer("Xato.", show_alert=True)
            return

        if rating < 1 or rating > 5:
            await callback.answer("Baholash noto‘g‘ri.", show_alert=True)
            return

        row = await get_order(order_id)
        if not row:
            await callback.answer("Buyurtma topilmadi.", show_alert=True)
            return

        (oid, created_at, status, assigned_to, old_rating, rated_admin_id,
         service, name, phone, problem, address, tg_username, tg_user_id) = row

        # faqat o‘sha buyurtmachining o'zi baholasin
        if callback.from_user.id != tg_user_id:
            await callback.answer("Bu baholash siz uchun emas.", show_alert=True)
            return

        # qaysi admin baholanyapti? — assigned_to
        saved = await set_order_rating(order_id, rating, rated_admin_id=assigned_to)
        if not saved:
            await callback.answer("Siz allaqachon baholagansiz ✅", show_alert=True)
            return

        # Userga tasdiq
        await callback.message.edit_text(
            f"Rahmat! Siz {rating} ⭐ baho berdingiz ✅\n\n"
            "Yana buyurtma bermoqchi bo‘lsangiz pastdagi tugmani bosing 👇"
        )
        await callback.bot.send_message(callback.from_user.id, "➕ Yangi buyurtma:", reply_markup=main_menu_kb())
        await callback.answer("Rahmat! ✅")

        # Adminlarga xabar
        admin_note = (
            "⭐ Buyurtma baholandi!\n\n"
            f"🆔 Order ID: {oid}\n"
            f"📌 Status: {status_label(status)}\n"
            f"👨‍🔧 Usta: {admin_id_to_name(assigned_to)}\n"
            f"⭐ Rating: {rating}/5\n"
            f"🧰 Xizmat: {service}\n"
            f"👤 Buyurtmachi: {name}\n"
            f"👤 Telegram: {tg_username or '(username yo‘q)'} | 🆔 {tg_user_id}\n"
        )
        for admin_id in ADMIN_IDS:
            try:
                await callback.bot.send_message(admin_id, admin_note)
            except Exception:
                pass

    # -------- Export (admin only) --------
    @dp.message(Command("export"))
    async def export_cmd(message: types.Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("Bu buyruq faqat admin uchun.")
            return

        file_path = await export_to_excel("orders.xlsx")
        await message.answer_document(types.FSInputFile(file_path), caption="📦 Buyurtmalar Excel eksporti")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
