#!/usr/bin/env python3
"""
TaxiAutoPost Bot
Faqat 3 ta foydalanuvchi uchun. Har biri o'z akkauntlaridan guruhlariga post tashlaydi.
"""
import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import db
from handlers import router
from scheduler import CampaignScheduler

os.makedirs("data", exist_ok=True)
os.makedirs("sessions", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler("data/bot.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN or not config.API_ID or not config.API_HASH:
        logger.error("❌ .env faylini to'ldiring!")
        sys.exit(1)

    db.init_db()
    logger.info("✅ Database tayyor")

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    scheduler = CampaignScheduler(bot)

    async def on_startup():
        me = await bot.get_me()
        logger.info(f"✅ Bot: @{me.username}")
        asyncio.create_task(scheduler.run())

    async def on_shutdown():
        scheduler.stop()
        await scheduler.close_sessions()
        await bot.session.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
