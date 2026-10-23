"""
Telegram sender — Telethon orqali xabar yuboradi.
Har bir xabarga ko'rinmas Unicode belgilar qo'shiladi (spam filtriga emas).
"""
import asyncio
import logging
import random

from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
    UserBannedInChannelError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    RPCError,
    ChatAdminRequiredError,
)

from sessions_mgr import session_manager

logger = logging.getLogger(__name__)

# Ko'rinmas zero-width belgilar (spam filtri bu xabarlarni boshqacha ko'radi)
_ZW_CHARS = [
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # zero width no-break space
]


def _make_invisible_watermark(length: int = 8) -> str:
    """Har yuborishda noyob ko'rinmas belgilar ketma-ketligi."""
    return "".join(random.choices(_ZW_CHARS, k=length))


def _invisibilize(text: str) -> str:
    """Xabarga ko'rinmas watermark qo'shadi — har yuborishda farqli."""
    wm = _make_invisible_watermark(random.randint(6, 12))
    # Xabar oxiriga va ba'zi joylariga qo'shiladi
    lines = text.split("\n")
    result_lines = []
    for i, line in enumerate(lines):
        if i > 0 and i % 3 == 0:
            result_lines.append(line + _make_invisible_watermark(3))
        else:
            result_lines.append(line)
    return "\n".join(result_lines) + wm


def _normalize_target(identifier: str):
    v = identifier.strip()
    if v.startswith("@"):
        return v
    try:
        return int(v)
    except ValueError:
        return v


class SendError(Exception):
    def __init__(self, reason: str, retryable: bool = False, wait_seconds: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.wait_seconds = wait_seconds


async def send_message(
    session_name: str,
    group_identifier: str,
    text: str,
) -> bool:
    """
    Xabar yuboradi. True — muvaffaqiyat. SendError — xato.
    """
    client = await session_manager.get_client(session_name)
    if not await client.is_user_authorized():
        raise SendError("Akkaunt avtorizatsiyadan o'tmagan", retryable=False)

    target = _normalize_target(group_identifier)
    invisib_text = _invisibilize(text)

    # Yuborishdan oldin kichik tasodifiy kechikish (1-4 soniya)
    await asyncio.sleep(random.uniform(1.0, 4.0))

    try:
        await client.send_message(target, invisib_text, parse_mode="html")
        return True

    except FloodWaitError as e:
        wait = int(getattr(e, "seconds", 60))
        logger.warning("[%s] FloodWait %ss — %s", session_name, wait, group_identifier)
        raise SendError(f"FloodWait {wait}s", retryable=True, wait_seconds=wait)

    except SlowModeWaitError as e:
        wait = int(getattr(e, "seconds", 30))
        logger.info("[%s] SlowMode %ss — %s", session_name, wait, group_identifier)
        raise SendError(f"SlowMode {wait}s", retryable=True, wait_seconds=wait)

    except (ChatWriteForbiddenError, ChannelPrivateError, ChatAdminRequiredError) as e:
        logger.warning("[%s] Yozish taqiqlangan: %s — %s", session_name, group_identifier, e)
        raise SendError("Yozish taqiqlangan", retryable=False)

    except UserBannedInChannelError as e:
        logger.warning("[%s] Kanalda ban: %s", session_name, group_identifier)
        raise SendError("Kanalda ban", retryable=False)

    except (AuthKeyUnregisteredError, UserDeactivatedBanError, UserDeactivatedError) as e:
        logger.error("[%s] Akkaunt muammosi: %s", session_name, e)
        raise SendError("Akkaunt muammosi", retryable=False)

    except RPCError as e:
        logger.warning("[%s] RPC xato %s: %s", session_name, group_identifier, e)
        raise SendError(f"RPC: {e}", retryable=True, wait_seconds=60)

    except Exception as e:
        logger.exception("[%s] Kutilmagan xato %s", session_name, group_identifier)
        raise SendError(f"Xato: {e}", retryable=True, wait_seconds=30)
