"""
Bot handlerlari — faqat ruxsat etilgan 3 ta user uchun.
"""
import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import db
from sessions_mgr import session_manager

logger = logging.getLogger(__name__)
router = Router()

# ── Ruxsat filtri ─────────────────────────────────────────────────────────────

def allowed(user_id: int) -> bool:
    return user_id in config.ALLOWED_USERS


def access_denied():
    return "⛔ Sizga ruxsat yo'q."


# ── FSM States ────────────────────────────────────────────────────────────────

class LoginStates(StatesGroup):
    waiting_phone = State()
    waiting_code  = State()
    waiting_pass  = State()

class GroupStates(StatesGroup):
    waiting_identifier = State()

class CampaignStates(StatesGroup):
    waiting_name     = State()
    waiting_text     = State()
    waiting_interval = State()
    choosing_accounts = State()
    choosing_groups   = State()

class EditStates(StatesGroup):
    waiting_new_text     = State()
    waiting_new_interval = State()


# ── Klaviatura ────────────────────────────────────────────────────────────────

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Akkauntlar"), KeyboardButton(text="👥 Guruhlar")],
            [KeyboardButton(text="📢 Kampaniyalar"), KeyboardButton(text="ℹ️ Holat")],
        ],
        resize_keyboard=True,
    )


def ik(*buttons: tuple) -> InlineKeyboardMarkup:
    """Inline keyboard yasash: [(text, callback), ...]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c)] for t, c in buttons]
    )


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message):
    if not allowed(msg.from_user.id):
        await msg.answer(access_denied())
        return
    await msg.answer(
        "✅ <b>AutoPost Bot</b>\n\n"
        "Akkauntlaringizni ulab, guruhlar va kampaniyalar yarating.\n"
        "Bot har belgilangan vaqtda avtomatik xabar yuboradi.",
        reply_markup=main_kb(),
    )


# ── AKKAUNTLAR ────────────────────────────────────────────────────────────────

@router.message(F.text == "📱 Akkauntlar")
async def menu_accounts(msg: Message):
    if not allowed(msg.from_user.id):
        return
    uid = msg.from_user.id
    accs = db.get_accounts(uid)
    count = len(accs)

    text = f"<b>📱 Akkauntlar</b> ({count}/{config.MAX_ACCOUNTS_PER_USER})\n\n"
    if accs:
        for a in accs:
            text += f"• {a['name'] or a['phone']} — <code>{a['phone']}</code>\n"
    else:
        text += "Hali akkaunt ulanmagan.\n"

    buttons = []
    if count < config.MAX_ACCOUNTS_PER_USER:
        buttons.append(("➕ Akkaunt ulash", "acc_add"))
    if accs:
        buttons.append(("🗑 Akkaunt o'chirish", "acc_del_list"))
    await msg.answer(text, reply_markup=ik(*buttons) if buttons else None)


@router.callback_query(F.data == "acc_add")
async def acc_add_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    await cq.message.answer("📞 Telefon raqamingizni kiriting (+998901234567):")
    await state.set_state(LoginStates.waiting_phone)
    await cq.answer()


@router.message(LoginStates.waiting_phone)
async def login_phone(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    phone = msg.text.strip()
    if not re.match(r"^\+\d{9,15}$", phone):
        await msg.answer("❌ Noto'g'ri format. +998901234567 shaklida kiriting:")
        return

    uid = msg.from_user.id
    if db.count_accounts(uid) >= config.MAX_ACCOUNTS_PER_USER:
        await msg.answer(f"❌ Maksimal {config.MAX_ACCOUNTS_PER_USER} ta akkaunt.")
        await state.clear()
        return

    session_name = f"user{uid}_acc{phone.replace('+','').replace(' ','')}"
    await state.update_data(phone=phone, session_name=session_name)

    wait_msg = await msg.answer("⏳ Kod yuborilmoqda...")
    try:
        client = await session_manager.fresh_client(session_name)
        result = await client.send_code_request(phone)
        await state.update_data(phone_code_hash=result.phone_code_hash)
        await wait_msg.edit_text(
            f"✅ Kod yuborildi!\n\n"
            f"Telegramdan kelgan kodingizni kiriting (masalan: <code>12345</code>):"
        )
        await state.set_state(LoginStates.waiting_code)
    except Exception as e:
        logger.exception("Kod yuborishda xato")
        await wait_msg.edit_text(f"❌ Xato: {e}\n\nQayta urinib ko'ring.")
        await state.clear()


@router.message(LoginStates.waiting_code)
async def login_code(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    code = msg.text.strip()
    data = await state.get_data()
    phone = data["phone"]
    session_name = data["session_name"]
    phone_code_hash = data["phone_code_hash"]

    try:
        client = await session_manager.get_client(session_name)
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        db.add_account(msg.from_user.id, session_name, phone, name)
        await msg.answer(f"✅ <b>{name}</b> akkaunt muvaffaqiyatli ulandi!", reply_markup=main_kb())
        await state.clear()
    except Exception as e:
        err = str(e)
        if "SessionPasswordNeededError" in err or "password" in err.lower():
            await msg.answer("🔐 Ikki bosqichli himoya yoqilgan. Parolingizni kiriting:")
            await state.set_state(LoginStates.waiting_pass)
        else:
            await msg.answer(f"❌ Kod xato yoki eskirgan: {e}\n\nQayta /start bosing.")
            await state.clear()


@router.message(LoginStates.waiting_pass)
async def login_pass(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    data = await state.get_data()
    session_name = data["session_name"]
    phone = data["phone"]
    password = msg.text.strip()

    try:
        client = await session_manager.get_client(session_name)
        await client.sign_in(password=password)
        me = await client.get_me()
        name = f"{me.first_name or ''} {me.last_name or ''}".strip() or phone
        db.add_account(msg.from_user.id, session_name, phone, name)
        await msg.answer(f"✅ <b>{name}</b> muvaffaqiyatli ulandi!", reply_markup=main_kb())
    except Exception as e:
        await msg.answer(f"❌ Parol xato: {e}")
    await state.clear()


@router.callback_query(F.data == "acc_del_list")
async def acc_del_list(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    accs = db.get_accounts(cq.from_user.id)
    buttons = [(f"🗑 {a['name'] or a['phone']}", f"acc_del_{a['id']}") for a in accs]
    buttons.append(("◀️ Orqaga", "acc_back"))
    await cq.message.edit_text("O'chirmoqchi bo'lgan akkauntni tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("acc_del_") & ~F.data.startswith("acc_del_list"))
async def acc_del(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    acc_id = int(cq.data.split("_")[-1])
    acc = db.get_account(acc_id)
    if acc:
        try:
            await session_manager.logout(acc["session_name"])
        except Exception:
            pass
        db.delete_account(acc_id, cq.from_user.id)
        await cq.message.edit_text(f"✅ {acc['name'] or acc['phone']} o'chirildi.")
    await cq.answer()


@router.callback_query(F.data == "acc_back")
async def acc_back(cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer()


# ── GURUHLAR ──────────────────────────────────────────────────────────────────

@router.message(F.text == "👥 Guruhlar")
async def menu_groups(msg: Message):
    if not allowed(msg.from_user.id):
        return
    groups = db.get_groups(msg.from_user.id)
    text = f"<b>👥 Guruhlar</b> ({len(groups)} ta)\n\n"
    if groups:
        for g in groups:
            text += f"• {g['title'] or g['identifier']}\n  <code>{g['identifier']}</code>\n"
    else:
        text += "Hali guruh qo'shilmagan.\n"

    buttons = [("➕ Guruh qo'shish", "grp_add")]
    if groups:
        buttons.append(("🗑 Guruh o'chirish", "grp_del_list"))
    await msg.answer(text, reply_markup=ik(*buttons))


@router.callback_query(F.data == "grp_add")
async def grp_add_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    await cq.message.answer(
        "📋 Guruh yoki kanal identifikatorini kiriting:\n\n"
        "• Username: <code>@mygroupname</code>\n"
        "• ID: <code>-1001234567890</code>"
    )
    await state.set_state(GroupStates.waiting_identifier)
    await cq.answer()


@router.message(GroupStates.waiting_identifier)
async def grp_add_identifier(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    identifier = msg.text.strip()
    if not identifier:
        await msg.answer("❌ Bo'sh bo'lishi mumkin emas.")
        return

    # Identifikatorn tozalaymiz
    if not identifier.startswith("@") and not identifier.startswith("-") and not identifier.lstrip("-").isdigit():
        if not identifier.startswith("@"):
            identifier = "@" + identifier

    # Akkaunt orqali tekshirish
    accs = db.get_accounts(msg.from_user.id)
    title = identifier
    if accs:
        try:
            client = await session_manager.get_client(accs[0]["session_name"])
            if await client.is_user_authorized():
                entity = await client.get_entity(identifier)
                title = getattr(entity, "title", None) or getattr(entity, "username", identifier)
        except Exception as e:
            logger.warning("Guruh tekshirishda xato: %s", e)
            await msg.answer(
                f"⚠️ Guruhni tekshirib bo'lmadi: {e}\n"
                "Baribir qo'shishni xohlaysizmi?",
                reply_markup=ik(
                    ("✅ Ha, qo'sh", f"grp_force_{identifier}"),
                    ("❌ Yo'q", "grp_cancel"),
                )
            )
            await state.clear()
            return

    db.add_group(msg.from_user.id, identifier, title)
    await msg.answer(f"✅ <b>{title}</b> qo'shildi!", reply_markup=main_kb())
    await state.clear()


@router.callback_query(F.data.startswith("grp_force_"))
async def grp_force_add(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    identifier = cq.data[len("grp_force_"):]
    db.add_group(cq.from_user.id, identifier, identifier)
    await cq.message.edit_text(f"✅ <code>{identifier}</code> qo'shildi!")
    await cq.answer()


@router.callback_query(F.data == "grp_cancel")
async def grp_cancel(cq: CallbackQuery):
    await cq.message.edit_text("❌ Bekor qilindi.")
    await cq.answer()


@router.callback_query(F.data == "grp_del_list")
async def grp_del_list(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    groups = db.get_groups(cq.from_user.id)
    buttons = [(f"🗑 {g['title'] or g['identifier']}", f"grp_del_{g['id']}") for g in groups]
    buttons.append(("◀️ Orqaga", "grp_back"))
    await cq.message.edit_text("O'chirmoqchi bo'lgan guruhni tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("grp_del_"))
async def grp_del(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    gid = int(cq.data.split("_")[-1])
    g = db.get_group(gid)
    if g:
        db.delete_group(gid, cq.from_user.id)
        await cq.message.edit_text(f"✅ {g['title'] or g['identifier']} o'chirildi.")
    await cq.answer()


@router.callback_query(F.data == "grp_back")
async def grp_back(cq: CallbackQuery):
    await cq.message.delete()
    await cq.answer()


# ── KAMPANIYALAR ──────────────────────────────────────────────────────────────

@router.message(F.text == "📢 Kampaniyalar")
async def menu_campaigns(msg: Message):
    if not allowed(msg.from_user.id):
        return
    camps = db.get_campaigns(msg.from_user.id)
    text = f"<b>📢 Kampaniyalar</b> ({len(camps)} ta)\n\n"
    for c in camps:
        status = "✅ Aktiv" if c["is_active"] else "⏸ To'xtatilgan"
        text += f"• <b>{c['name']}</b> — har {c['interval_min']} daq. — {status}\n"
        if c["last_run"]:
            text += f"  Oxirgi: {c['last_run'][:16]}\n"

    if not camps:
        text += "Hali kampaniya yo'q.\n"

    buttons = [("➕ Yangi kampaniya", "camp_new")]
    if camps:
        buttons.append(("⚙️ Boshqarish", "camp_manage"))
    await msg.answer(text, reply_markup=ik(*buttons))


@router.callback_query(F.data == "camp_new")
async def camp_new_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    accs = db.get_accounts(cq.from_user.id)
    grps = db.get_groups(cq.from_user.id)
    if not accs:
        await cq.message.answer("❌ Avval akkaunt ulang!")
        return await cq.answer()
    if not grps:
        await cq.message.answer("❌ Avval guruh qo'shing!")
        return await cq.answer()
    await cq.message.answer("📝 Kampaniya nomini kiriting:")
    await state.set_state(CampaignStates.waiting_name)
    await cq.answer()


@router.message(CampaignStates.waiting_name)
async def camp_name(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    await state.update_data(name=msg.text.strip())
    await msg.answer("✉️ Kampaniya uchun xabar matnini kiriting (HTML formatida yozishingiz mumkin):")
    await state.set_state(CampaignStates.waiting_text)


@router.message(CampaignStates.waiting_text)
async def camp_text(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    await state.update_data(text=msg.text)
    await msg.answer(
        "⏱ Har necha minutda yuborsin?\n\n"
        "Masalan: <code>3</code>, <code>5</code>, <code>10</code>, <code>30</code>"
    )
    await state.set_state(CampaignStates.waiting_interval)


@router.message(CampaignStates.waiting_interval)
async def camp_interval(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting (masalan: 5):")
        return
    interval = int(text)
    await state.update_data(interval=interval)

    # Akkaunt tanlash
    uid = msg.from_user.id
    accs = db.get_accounts(uid)
    await state.update_data(selected_accounts=[], selected_groups=[])

    lines = ["<b>📱 Qaysi akkauntlardan yuborsin?</b>\n\nToggle qiling, keyin ✅ Tayyor bosing:\n"]
    for a in accs:
        lines.append(f"• {a['name'] or a['phone']}")
    await msg.answer("\n".join(lines))

    buttons = [(f"☐ {a['name'] or a['phone']}", f"ca_tog_{a['id']}") for a in accs]
    buttons.append(("✅ Tayyor", "ca_done"))
    await msg.answer("Akkauntlarni tanlang:", reply_markup=ik(*buttons))
    await state.set_state(CampaignStates.choosing_accounts)


@router.callback_query(F.data.startswith("ca_tog_"), CampaignStates.choosing_accounts)
async def camp_toggle_acc(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    acc_id = int(cq.data.split("_")[-1])
    data = await state.get_data()
    selected = data.get("selected_accounts", [])
    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.append(acc_id)
    await state.update_data(selected_accounts=selected)

    # Klaviaturani yangilaymiz
    accs = db.get_accounts(cq.from_user.id)
    buttons = []
    for a in accs:
        mark = "☑" if a["id"] in selected else "☐"
        buttons.append((f"{mark} {a['name'] or a['phone']}", f"ca_tog_{a['id']}"))
    buttons.append(("✅ Tayyor", "ca_done"))
    await cq.message.edit_reply_markup(reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data == "ca_done", CampaignStates.choosing_accounts)
async def camp_acc_done(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    selected = data.get("selected_accounts", [])
    if not selected:
        await cq.answer("⚠️ Kamida 1 ta akkaunt tanlang!", show_alert=True)
        return

    # Guruh tanlash
    grps = db.get_groups(cq.from_user.id)
    buttons = [(f"☐ {g['title'] or g['identifier']}", f"cg_tog_{g['id']}") for g in grps]
    buttons.append(("✅ Tayyor", "cg_done"))
    await cq.message.edit_text("👥 Qaysi guruhlarga yuborsin?", reply_markup=ik(*buttons))
    await state.set_state(CampaignStates.choosing_groups)
    await cq.answer()


@router.callback_query(F.data.startswith("cg_tog_"), CampaignStates.choosing_groups)
async def camp_toggle_grp(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    grp_id = int(cq.data.split("_")[-1])
    data = await state.get_data()
    selected = data.get("selected_groups", [])
    if grp_id in selected:
        selected.remove(grp_id)
    else:
        selected.append(grp_id)
    await state.update_data(selected_groups=selected)

    grps = db.get_groups(cq.from_user.id)
    buttons = []
    for g in grps:
        mark = "☑" if g["id"] in selected else "☐"
        buttons.append((f"{mark} {g['title'] or g['identifier']}", f"cg_tog_{g['id']}"))
    buttons.append(("✅ Tayyor", "cg_done"))
    await cq.message.edit_reply_markup(reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data == "cg_done", CampaignStates.choosing_groups)
async def camp_grp_done(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    data = await state.get_data()
    selected_grps = data.get("selected_groups", [])
    if not selected_grps:
        await cq.answer("⚠️ Kamida 1 ta guruh tanlang!", show_alert=True)
        return

    # Kampaniya yaratamiz
    uid = cq.from_user.id
    camp_id = db.create_campaign(uid, data["name"], data["text"], data["interval"])
    db.set_campaign_accounts(camp_id, data["selected_accounts"])
    db.set_campaign_groups(camp_id, selected_grps)

    await cq.message.edit_text(
        f"✅ <b>{data['name']}</b> kampaniyasi yaratildi!\n\n"
        f"⏱ Interval: har {data['interval']} daqiqa\n"
        f"📱 Akkauntlar: {len(data['selected_accounts'])} ta\n"
        f"👥 Guruhlar: {len(selected_grps)} ta\n\n"
        f"Bot darhol ishga tushadi."
    )
    await state.clear()
    await cq.answer()


# ── Kampaniya boshqaruvi ──────────────────────────────────────────────────────

@router.callback_query(F.data == "camp_manage")
async def camp_manage(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    camps = db.get_campaigns(cq.from_user.id)
    if not camps:
        await cq.message.edit_text("Kampaniya yo'q.")
        return await cq.answer()
    buttons = [(f"{'✅' if c['is_active'] else '⏸'} {c['name']}", f"camp_detail_{c['id']}") for c in camps]
    await cq.message.edit_text("Kampaniyani tanlang:", reply_markup=ik(*buttons))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_detail_"))
async def camp_detail(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if not c:
        await cq.answer("Topilmadi")
        return

    accs = db.get_campaign_accounts(cid)
    grps = db.get_campaign_groups(cid)
    status = "✅ Aktiv" if c["is_active"] else "⏸ To'xtatilgan"

    last_run_str = (c['last_run'] or "hali yo'q")[:16]
    next_run_str = (c['next_run'] or "hali yo'q")[:16]

    text = (
        f"<b>{c['name']}</b>\n\n"
        f"Holat: {status}\n"
        f"Interval: har {c['interval_min']} daq.\n"
        f"Akkauntlar: {len(accs)} ta\n"
        f"Guruhlar: {len(grps)} ta\n"
        f"Oxirgi: {last_run_str}\n"
        f"Keyingi: {next_run_str}\n\n"
        f"<b>Matn:</b>\n{c['message_text'][:200]}{'...' if len(c['message_text']) > 200 else ''}"
    )

    toggle_label = "⏸ To'xtatish" if c["is_active"] else "▶️ Ishga tushirish"
    await cq.message.edit_text(text, reply_markup=ik(
        (toggle_label, f"camp_toggle_{cid}"),
        ("✏️ Matnni o'zgartir", f"camp_edit_text_{cid}"),
        ("⏱ Intervalni o'zgartir", f"camp_edit_int_{cid}"),
        ("🗑 O'chirish", f"camp_delete_{cid}"),
        ("◀️ Orqaga", "camp_manage"),
    ))
    await cq.answer()


@router.callback_query(F.data.startswith("camp_toggle_"))
async def camp_toggle(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if not c:
        return await cq.answer()
    new_val = 0 if c["is_active"] else 1
    db.update_campaign_field(cid, "is_active", new_val)
    if new_val:
        # Darhol ishga tushirish uchun next_run ni NULL qilamiz
        db.update_campaign_field(cid, "next_run", None)
    status = "▶️ Ishga tushirildi" if new_val else "⏸ To'xtatildi"
    await cq.answer(status, show_alert=True)
    # Sahifani yangilaymiz
    await camp_detail(cq)


@router.callback_query(F.data.startswith("camp_edit_text_"))
async def camp_edit_text_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    await state.update_data(edit_camp_id=cid)
    await cq.message.answer("✏️ Yangi matnni kiriting:")
    await state.set_state(EditStates.waiting_new_text)
    await cq.answer()


@router.message(EditStates.waiting_new_text)
async def camp_edit_text_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    data = await state.get_data()
    cid = data["edit_camp_id"]
    db.update_campaign_field(cid, "message_text", msg.text)
    await msg.answer("✅ Matn yangilandi!", reply_markup=main_kb())
    await state.clear()


@router.callback_query(F.data.startswith("camp_edit_int_"))
async def camp_edit_int_start(cq: CallbackQuery, state: FSMContext):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    await state.update_data(edit_camp_id=cid)
    await cq.message.answer("⏱ Yangi interval (minutda, masalan 5):")
    await state.set_state(EditStates.waiting_new_interval)
    await cq.answer()


@router.message(EditStates.waiting_new_interval)
async def camp_edit_int_save(msg: Message, state: FSMContext):
    if not allowed(msg.from_user.id):
        return
    text = msg.text.strip()
    if not text.isdigit() or int(text) < 1:
        await msg.answer("❌ Musbat son kiriting:")
        return
    data = await state.get_data()
    cid = data["edit_camp_id"]
    db.update_campaign_field(cid, "interval_min", int(text))
    db.update_campaign_field(cid, "next_run", None)  # darhol qayta ishga tushirish
    await msg.answer(f"✅ Interval {text} daqiqaga o'zgartirildi!", reply_markup=main_kb())
    await state.clear()


@router.callback_query(F.data.startswith("camp_delete_"))
async def camp_delete(cq: CallbackQuery):
    if not allowed(cq.from_user.id):
        return await cq.answer()
    cid = int(cq.data.split("_")[-1])
    c = db.get_campaign(cid)
    if c:
        db.delete_campaign(cid, cq.from_user.id)
        await cq.message.edit_text(f"🗑 <b>{c['name']}</b> o'chirildi.")
    await cq.answer()


# ── HOLAT ─────────────────────────────────────────────────────────────────────

@router.message(F.text == "ℹ️ Holat")
async def menu_status(msg: Message):
    if not allowed(msg.from_user.id):
        return
    uid = msg.from_user.id
    accs = db.get_accounts(uid)
    grps = db.get_groups(uid)
    camps = db.get_campaigns(uid)
    active_camps = [c for c in camps if c["is_active"]]

    lines = [
        "<b>ℹ️ Holat</b>\n",
        f"📱 Akkauntlar: {len(accs)} ta",
        f"👥 Guruhlar: {len(grps)} ta",
        f"📢 Kampaniyalar: {len(camps)} ta ({len(active_camps)} aktiv)\n",
    ]

    if active_camps:
        lines.append("<b>Aktiv kampaniyalar:</b>")
        for c in active_camps:
            lines.append(f"• {c['name']} — har {c['interval_min']} daq.")
            if c["next_run"]:
                lines.append(f"  ⏰ Keyingi: {c['next_run'][:16]}")

    await msg.answer("\n".join(lines))
