"""
/netcheck - serverdan tsue.edupage.org saytiga ulanish bor-yo'qligini
bosqichma-bosqich tekshiradi (DNS -> IPv4 TCP -> IPv6 TCP -> brauzer
orqali HTTP). Skrinshot doim "timeout" xatosi berayotgan bo'lsa, shu
buyruq orqali muammo aniq qaysi bosqichda (va IPv4/IPv6 muammosi
ekanini) bilib olish mumkin.
"""

import asyncio
import socket
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import screenshot as ss

router = Router(name="debug")

HOST = "tsue.edupage.org"


async def _check_tcp(host: str, port: int, family, timeout: float = 8) -> tuple:
    """Berilgan IP oilasi (IPv4/IPv6) orqali TCP ulanishni sinaydi.
    (muvaffaqiyatli_bo'ldimi, xabar) qaytaradi."""
    t0 = time.monotonic()
    try:
        infos = await asyncio.get_event_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        return False, "bu IP oilasida manzil topilmadi"

    if not infos:
        return False, "bu IP oilasida manzil topilmadi"

    ip = infos[0][4][0]
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True, f"{ip} ({time.monotonic() - t0:.2f}s)"
    except Exception as e:
        return False, f"{ip} - {e}"


@router.message(Command("netcheck"))
async def netcheck(message: Message):
    lines = [f"🔍 Tarmoq tekshiruvi: {HOST}\n"]
    status_msg = await message.answer("⏳ Tekshirilmoqda...")

    # 1) DNS (umumiy)
    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(loop.getaddrinfo(HOST, 443), timeout=10)
        ip = infos[0][4][0]
        lines.append(f"✅ DNS aniqlandi: {ip} ({time.monotonic() - t0:.2f}s)")
    except Exception as e:
        lines.append(f"❌ DNS xatosi: {e}")
        await status_msg.edit_text("\n".join(lines))
        return

    # 2) IPv4 orqali TCP
    ipv4_ok, ipv4_msg = await _check_tcp(HOST, 443, socket.AF_INET)
    lines.append(f"{'✅' if ipv4_ok else '❌'} IPv4 orqali TCP: {ipv4_msg}")

    # 3) IPv6 orqali TCP
    ipv6_ok, ipv6_msg = await _check_tcp(HOST, 443, socket.AF_INET6)
    lines.append(f"{'✅' if ipv6_ok else '❌'} IPv6 orqali TCP: {ipv6_msg}")

    if not ipv4_ok and not ipv6_ok:
        lines.append(
            "\n➡️ Na IPv4, na IPv6 orqali ulanib bo'lmadi - server bu saytga "
            "umuman chiqa olmayapti (tarmoq/bloklash muammosi)."
        )
        await status_msg.edit_text("\n".join(lines))
        return

    if not ipv4_ok and ipv6_ok:
        lines.append(
            "\n➡️ IPv6 ishlayapti, lekin IPv4 ishlamayapti - odatiy holda "
            "muammo emas (IPv6 orqali ishlaydi)."
        )
    elif ipv4_ok and not ipv6_ok:
        lines.append(
            "\n⚠️ IPv4 ishlayapti, lekin IPv6 ISHLAMAYAPTI. Agar brauzer "
            "(keyingi bosqich) baribir vaqti-vaqti bilan timeout bersa, "
            "aynan shu sabab bo'lishi mumkin (Chromium ba'zan IPv6'ni "
            "birinchi urinib, javob kutib turib qoladi)."
        )

    # 4) Brauzer orqali (Playwright) ulanish
    t0 = time.monotonic()
    try:
        if ss._browser is None:
            await ss.start_browser()
        page = await ss._browser.new_page()
        try:
            await page.goto(
                f"https://{HOST}/timetable/", wait_until="commit", timeout=15000
            )
            lines.append(
                f"✅ Brauzer orqali ulanish: OK ({time.monotonic() - t0:.2f}s)"
            )
        finally:
            await page.close()
    except Exception as e:
        lines.append(f"❌ Brauzer orqali ulanish xatosi: {e}")
        if ipv4_ok and not ipv6_ok:
            lines.append(
                "\n➡️ Bu aynan IPv6 muammosi bo'lishi ehtimoli katta - "
                "Chromium'da IPv6'ni o'chirib qo'yish tavsiya etiladi."
            )
        await status_msg.edit_text("\n".join(lines))
        return

    lines.append("\n🎉 Hammasi joyida - ulanish muammosi yo'q.")
    await status_msg.edit_text("\n".join(lines))
