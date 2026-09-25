"""
Berilgan edupage jadval sahifasidan (guruh/o'qituvchi/xona) faqat
jadval qismining (SVG) skrinshotini olib, PNG faylga saqlaydi.

Butun brauzer sessiyasi bot ishga tushganda BIR MARTA ochiladi
(main.py -> on_startup) va yopilganda yopiladi (on_shutdown), har bir
so'rov uchun esa faqat yangi "page" ochiladi - bu tezlik uchun muhim,
chunki brauzerni har safar qayta ishga tushirish sekin bo'ladi.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from playwright.async_api import Browser, async_playwright

from . import config

logger = logging.getLogger(__name__)

_playwright = None
_browser: Browser | None = None

# Butun ilova bo'ylab bitta vaqtda faqat BITTA brauzer sahifasi
# ochilishini ta'minlaydi (foydalanuvchi so'rovi ham, fon
# skanerlashi ham shu qulfdan foydalanadi). Bu Railway kabi cheklangan
# resurs (RAM/CPU) muhitida bir nechta sahifa bir vaqtda ochilib,
# hammasi sekinlashib/timeout berishining oldini oladi.
_page_lock = asyncio.Lock()

# Foydalanuvchi so'rovlari FON SKANERLASHIDAN USTUN turishi kerak -
# shuning uchun nechta foydalanuvchi so'rovi navbatda turganini
# hisoblab boramiz; skaner esa shu son 0 bo'lgunicha kutib turadi.
_pending_user_requests = 0


async def start_browser():
    global _playwright, _browser
    if _browser is not None:
        if _browser.is_connected():
            return
        # MUHIM: brauzer obyekti hali ham mavjud, lekin ULANISH uzilgan -
        # masalan Chromium subprocess operatsion tizim tomonidan
        # kutilmaganda o'chirilgan (masalan xotira yetishmay "OOM kill"
        # bo'lgan) bo'lishi mumkin, lekin Python jarayonining o'zi omon
        # qolgan. Bunday holatda ESKI tekshiruv ("agar _browser bor bo'lsa,
        # hech narsa qilmaymiz") brauzerni HECH QACHON qayta ishga
        # tushirmasdi - shu sabab "Target page, context or browser has
        # been closed" xatosi butun jarayon qayta ishga tushmaguncha
        # (Railway konteyneri qulab tushmaguncha) davom etardi. Endi
        # bunday holatda eski (o'lik) obyektlarni tozalab, qaytadan
        # ishga tushiramiz.
        logger.warning(
            "Brauzer ulanishi uzilgan ekan (kutilmagan yopilish) - qaytadan "
            "ishga tushirilmoqda."
        )
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None

    _playwright = await async_playwright().start()
    # MUHIM: Docker konteynerida (odatda root foydalanuvchi ostida)
    # Chromium standart "sandbox" bilan ishga tushmasligi yoki
    # navigatsiya paytida to'xtab (hang) qolishi mumkin. Shu sabab
    # konteyner muhitlar uchun standart bo'lgan flaglar qo'shiladi.
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            # Ba'zi server muhitlarida (masalan Railway) IPv6 orqali
            # chiqish ishlamaydi yoki juda sekin bo'lib, ulanish
            # "osilib qolishiga" sabab bo'ladi (garchi IPv4 to'liq
            # ishlasa ham). Shuni oldini olish uchun Chromium'da
            # IPv6'ni butunlay o'chirib qo'yamiz - faqat IPv4 orqali
            # ulanadi.
            "--disable-ipv6",
        ],
    )


async def stop_browser():
    global _playwright, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


async def ensure_browser() -> Browser:
    """Brauzer mavjud VA hali ham ulanган (ishlayotgan) ekanini
    ta'minlaydi - agar u yo'q bo'lsa yoki kutilmaganda uzilib qolgan
    bo'lsa, avtomatik qaytadan ishga tushiradi.

    Barcha skraperlar (room_scraper, teacher_scraper, group_url_scraper)
    va skrinshot funksiyasi endi `_browser`ni to'g'ridan-to'g'ri emas,
    shu funksiya orqali olishi kerak - aks holda brauzer o'lib qolganda
    (masalan Railway konteynerida xotira yetishmay Chromium subprocess
    o'chirilganda) "Target page, context or browser has been closed"
    xatosi butun jarayon qayta ishga tushmaguncha cheksiz takrorlanaveradi."""
    if _browser is None or not _browser.is_connected():
        await start_browser()
    return _browser


async def take_timetable_screenshot(url: str, max_retries: int = 3) -> Path:
    """Berilgan URL manzilidagi jadval qismini skrinshot qilib,
    vaqtinchalik PNG faylga saqlaydi va shu fayl yo'lini qaytaradi.
    Fayl chaqiruvchi tomonidan (Telegramga yuborilgach) o'chirilishi
    kerak.

    Tarmoq vaqtinchalik sekin bo'lib qolishi (masalan TSUE serveri
    biroz kech javob berishi) odatiy hol, shuning uchun bir martalik
    xatoda darhol taslim bo'lmasdan, bir necha marta qayta urinib
    ko'radi (har safar orasida biroz kutib)."""
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return await _take_screenshot_once(url)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)  # 2s, 4s, 6s... kutib qayta urinadi
    raise last_error


async def _take_screenshot_once(url: str) -> Path:
    global _pending_user_requests

    browser = await ensure_browser()

    _pending_user_requests += 1
    try:
        async with _page_lock:
            return await _do_screenshot(url, browser)
    finally:
        _pending_user_requests -= 1


async def _do_screenshot(url: str, browser: Browser) -> Path:
    page = await browser.new_page(
        viewport={"width": 1600, "height": 1000},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        ignore_https_errors=True,
    )
    try:
        # 1-BOSQICH: avval eng tezkor signalni kutamiz - "commit" holati
        # serverdan birinchi bayt(lar) kelishi bilanoq bajariladi. Agar
        # shu ham belgilangan vaqtda bajarilmasa, bu HTML sekin
        # yuklanayotgani emas, balki ULANISHNING O'ZI muammoli ekanini
        # bildiradi (server bloklagan, tarmoq muammosi va h.k.).
        try:
            await page.goto(url, wait_until="commit", timeout=25000)
        except Exception as e:
            raise RuntimeError(
                "Serverga ulanib bo'lmadi (tarmoq/bloklash muammosi bo'lishi "
                f"mumkin). Texnik xato: {e}"
            )

        # 2-BOSQICH: ulanish muvaffaqiyatli bo'lsa, endi HTML to'liq
        # yuklanishini kutamiz.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass  # asosiy HTML allaqachon "commit" bosqichida kelgan bo'lishi mumkin

        try:
            await page.wait_for_selector("svg", timeout=20000)
        except Exception:
            # svg umuman chiqmasa ham, sahifani skrinshot qilishga
            # urinib ko'ramiz (masalan xato xabari chiqqan bo'lishi mumkin)
            pass

        await page.wait_for_timeout(800)

        element = await page.query_selector("div.print-sheet svg")
        if element is None:
            element = await page.query_selector("svg")

        out_path = config.SCREENSHOT_DIR / f"{uuid.uuid4().hex}.png"

        if element is not None:
            await element.screenshot(path=str(out_path))
        else:
            # Zaxira variant: butun sahifani skrinshot qilish
            await page.screenshot(path=str(out_path), full_page=True)

        return out_path
    finally:
        await page.close()
