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
        browser = await ss.ensure_browser()
        page = await browser.new_page()
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


@router.message(Command("debugteacher"))
async def debug_teacher(message: Message):
    """/debugteacher 5 - berilgan ID orqali o'qituvchi sahifasi
    qanday javob berayotganini xom holda ko'rsatadi (URL to'g'ri
    ekanini tekshirish uchun)."""
    from .. import teacher_scraper

    parts = message.text.split()
    teacher_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

    status_msg = await message.answer(f"⏳ ID={teacher_id} tekshirilmoqda...")
    try:
        result = await teacher_scraper.debug_one_teacher(teacher_id)
        name_display = result["name"] if result["name"] else "(bo'sh - topilmadi)"
        text = (
            f"🔍 O'qituvchi debug (ID={teacher_id})\n\n"
            f"URL: {result['url']}\n"
            f"SVG uzunligi: {result['svg_length']} belgi\n"
            f"Topilgan ism: {name_display}\n"
        )
        if result["svg_length"] == 0:
            text += "\n➡️ SVG umuman qaytmadi - sahifa yuklanmagan yoki bunday xona/URL yo'q."
        elif not result["name"]:
            text += (
                "\n➡️ Sahifa yuklandi, lekin ism topilmadi - ehtimol "
                "TEACHER_URL_PARAM noto'g'ri (masalan bu ID class/xona "
                "sifatida talqin qilinayotgan bo'lishi mumkin) yoki SVG "
                "formatida ism boshqacha joyda.\n\n"
                "SVG ichidagi topilgan matnli elementlar:\n"
            )
            if result.get("all_texts"):
                text += "\n".join(result["all_texts"])
            else:
                text += "(hech qanday <text> elementi topilmadi umuman)"
        await status_msg.edit_text(text)
    except Exception as e:
        await status_msg.edit_text(f"❌ Xatolik: {e}")
