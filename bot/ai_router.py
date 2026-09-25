"""
Foydalanuvchi botga yozgan (yoki OVOZLI xabar orqali aytgan) ERKIN
MATNNI OpenAI API yordamida botning MAVJUD uchta buyrug'idan biriga
aylantiradigan modul:

  1) "group_schedule"   - biror TALABALAR GURUHINING dars jadvalini so'rash
  2) "teacher_schedule"  - biror O'QITUVCHINING (domlaning) dars jadvalini so'rash
  3) "free_room"         - biror kun/bino/parada BO'SH XONA qidirish

MUHIM (xavfsizlik / foydalanuvchi tajribasi):
  - Agar matn bu uch niyatning birortasiga ham ANIQ mos kelmasa
    (masalan bu "texnik bo'lim"ga savol, shikoyat, salom yoki umuman
    boshqa mavzu bo'lsa), `classify_intent()` None qaytaradi - va
    chaqiruvchi tomon (bot/handlers/ai_intent.py) BU HOLATDA HECH
    QANDAY QO'SHIMCHA XABAR YOZMAYDI. Botning bu integratsiyasiz
    oldingi xatti-harakati (xabar shunchaki chat_messages jadvaliga
    "kiruvchi" sifatida yoziladi, admin panelning Texnik bo'limi
    orqali odam qo'lda javob beradi) TO'LIQ SAQLANADI.
  - OPENAI_API_KEY sozlanmagan, API chaqiruvi xato bergan, tarmoq
    ishlamagan yoki javobni JSON sifatida o'qib bo'lmagan HAR QANDAY
    holatda ham xuddi shunday None qaytariladi (fail-safe) - hech
    qachon foydalanuvchiga xato yoki tushunarsiz AI javobi ketmaydi.

Shuningdek, ovozli xabarlarni matnga aylantirish uchun
`transcribe_voice()` funksiyasi ham shu yerda - u ham xuddi shu
fail-safe qoidaga bo'ysunadi (xato/o'chirilgan holatda None).
"""

import json
import logging

import aiohttp

from . import config, data_loader, db
from .keyboards import DAYS, PERIOD_TIMES

logger = logging.getLogger(__name__)

_ERROR_CONTEXT = "openai_intent"


async def _log_ai_error(message: str):
    """AI chaqiruvida xatolik bo'lsa, buni ADMIN PANELdagi "Xatoliklar"
    bo'limida ham ko'rinadigan qilib yozadi - shunda integratsiya
    ishlayaptimi yoki yo'qmi, server loglariga qaramasdan ham,
    to'g'ridan-to'g'ri admin panelda bilib olish mumkin. Bu funksiya
    o'zi ham xato bersa (masalan baza hali tayyor bo'lmasa), fail-safe
    qoidani buzmaslik uchun sekingina e'tiborsiz qoldiriladi."""
    try:
        await db.log_error(_ERROR_CONTEXT, message[:500])
    except Exception:
        logger.exception("AI xatoligini bazaga yozib bo'lmadi")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
_REQUEST_TIMEOUT_SECONDS = 10
_TRANSCRIBE_TIMEOUT_SECONDS = 30

_VALID_DAY_CODES = {code for code, _ in DAYS}

_SYSTEM_PROMPT_TEMPLATE = """Siz Toshkent shahridagi bir universitet (TSUE) Telegram botining "niyat aniqlagich" (intent classifier) yordamchisisiz.

Foydalanuvchi botga ERKIN MATN yozadi (yoki ovozli xabar aytadi, keyin matnga aylantirilgan). Sizning vazifangiz - agar bu matn quyidagi UCH aniq buyruqdan biriga mos kelsa, shuni JSON formatida aniqlab berish. Agar mos kelmasa yoki shubhali bo'lsa, intent="none" deb javob bering - bu ODDIY holat va hech qanday xato emas (masalan salomlashish, savol-javob, shikoyat, yordam so'rash - bularning barchasi intent="none").

1) "group_schedule" - foydalanuvchi biror TALABALAR GURUHINING dars jadvalini so'rayapti.
   Misollar: "AT-75 guruh jadvalini topib ber", "MO-900 jadvali kerak edi", "BA-12 nima o'qiydi bugun".
   - "group_name" maydoniga foydalanuvchi yozgan guruh kodini XUddi O'ZI YOZGANDEK chiqaring (masalan "AT-75"). Hech narsani o'zingiz to'ldirmang yoki taxmin qilmang.

2) "teacher_schedule" - foydalanuvchi biror O'QITUVCHINING (domla/ustoz/domlaning) dars jadvalini so'rayapti.
   Misollar: "Fanonchiyev domlani jadvalini topib ber", "Abdullayeva Dilbar jadvali kerak edi", "Rahimov domla bugun nima o'qiydi", "Karimova opa qachon dars o'tadi".
   - "teacher_name" maydoniga foydalanuvchi aytgan ism/familiyani XUddi O'ZI AYTGANDEK chiqaring (masalan "Fanonchiyev"). "domla", "ustoz", "opa", "aka" kabi so'zlarni bu maydonga QO'SHMANG - faqat ism/familiyaning o'zini yozing. Imlo xatosini yoki qisqartmani O'ZINGIZ TUZATMANG/TO'LDIRMANG - qidiruv tizimi buni o'zi moslashtiradi.

3) "free_room" - foydalanuvchi BIRON KUN/VAQTDA BO'SH (band bo'lmagan) XONA qidiryapti (kun/bino/vaqt aytilmagan, umumiy "bo'sh xona kerak" so'rovi ham shu turga kiradi - bunday holda mos maydonlarni null qoldiring, baribir bu intent hisoblanadi).
   Misollar: "bo'sh xona topib ber", "dushanba kuniga bo'sh xona kerak", "ertaga soat 9 da 2-binoda bo'sh xona bormi", "juma kuni bo'sh auditoriya topib ber".
   - "day" maydoniga FAQAT quyidagi kodlardan birini yozing: Mn=dushanba, Tu=seshanba, Wed=chorshanba, Thu=payshanba, Fri=juma, Sat=shanba. Agar kun aytilmagan yoki yakshanba (bot yakshanbani qo'llab-quvvatlamaydi) bo'lsa - day=null (bu HALI HAM "free_room" intenti, "none" EMAS).
   - "building" maydoniga FAQAT quyidagi ro'yxatdagi bino nomlaridan birini yozing (aynan shu ro'yxatdagidek): {buildings}. Mos kelmasa yoki aytilmagan bo'lsa - null.
   - "period" maydoniga 1 dan 8 gacha butun son yozing, quyidagi jadval asosida (agar aniq vaqt yoki "N-para" aytilgan bo'lsa): {period_times}. Aytilmagan/aniq bo'lmasa - null.

Agar matn na guruh jadvali, na o'qituvchi jadvali, na bo'sh xona qidiruviga ALOHIDA aniq mos kelmasa - intent="none" qiling va qolgan barcha maydonlarni null qoldiring. Shubha bo'lsa ham "none" tanlang - xato taxmin qilishdan ko'ra "none" xavfsizroq.

FAQAT quyidagi formatdagi bitta JSON obyekt bilan javob bering, boshqa hech qanday matn/izoh yozmang:
{{"intent": "group_schedule" | "teacher_schedule" | "free_room" | "none", "group_name": string|null, "teacher_name": string|null, "day": string|null, "building": string|null, "period": integer|null}}
"""


def _clean_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _clean_day(value) -> str | None:
    value = _clean_str(value)
    if value in _VALID_DAY_CODES:
        return value
    return None


def _clean_building(value) -> str | None:
    value = _clean_str(value)
    if not value:
        return None
    if value in data_loader.store.buildings():
        return value
    return None


def _clean_period(value) -> int | None:
    try:
        period = int(value)
    except (TypeError, ValueError):
        return None
    return period if period in PERIOD_TIMES else None


async def classify_intent(text: str) -> dict | None:
    """Berilgan erkin matnni tahlil qilib, aniqlangan niyat va uning
    parametrlarini lug'at sifatida qaytaradi:

        {"intent": "group_schedule", "group_name": "AT-75"}
        {"intent": "teacher_schedule", "teacher_name": "Fanonchiyev"}
        {"intent": "free_room", "day": "Mn", "building": "2", "period": 3}
        {"intent": "free_room", "day": None, "building": None, "period": None}

    Hech narsa aniq bo'lmasa (yoki AI o'chirilgan/xato bergan bo'lsa) -
    None qaytaradi."""
    if not config.OPENAI_API_KEY:
        return None
    text = (text or "").strip()
    if not text:
        return None

    buildings = data_loader.store.buildings()
    buildings_str = ", ".join(buildings) if buildings else "(hozircha ma'lumot yo'q)"
    period_lines = "; ".join(f"{n}-para: {t}" for n, t in sorted(PERIOD_TIMES.items()))
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        buildings=buildings_str, period_times=period_lines
    )

    payload = {
        "model": config.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text[:500]},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "OpenAI API xato qaytardi (status=%s): %s", resp.status, body[:300]
                    )
                    await _log_ai_error(f"OpenAI API xato qaytardi (status={resp.status}): {body}")
                    return None
                data = await resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as e:
        logger.exception(
            "OpenAI orqali niyat aniqlashda xatolik - oddiy (AI'siz) "
            "xatti-harakatga qaytiladi."
        )
        await _log_ai_error(f"OpenAI chaqiruvida xatolik: {e}")
        return None

    if not isinstance(parsed, dict):
        return None

    intent = parsed.get("intent")
    if intent == "group_schedule":
        group_name = _clean_str(parsed.get("group_name"))
        if not group_name:
            return None
        return {"intent": "group_schedule", "group_name": group_name}

    if intent == "teacher_schedule":
        teacher_name = _clean_str(parsed.get("teacher_name"))
        if not teacher_name:
            return None
        return {"intent": "teacher_schedule", "teacher_name": teacher_name}

    if intent == "free_room":
        # MUHIM: "day" (yoki building/period) null bo'lishi mumkin -
        # masalan foydalanuvchi shunchaki "bo'sh xona topib ber" desa,
        # hech qanday aniq kun/bino/vaqt aytmagan. Bu HALI HAM tanilgan
        # "free_room" niyati hisoblanadi (avval bu yerda "kun bo'lmasa
        # None qaytaramiz" degan qoida bor edi - shu sabab aynan shunday
        # umumiy so'rovlarga bot hech javob bermas edi). Chaqiruvchi
        # tomon (ai_intent.py) endi day/building/period'ning istalgan
        # kombinatsiyasini (hattoki barchasi None bo'lsa ham) to'g'ri
        # boshqaradi - mavjud "Bo'sh xonalarni topish" oqimining tegishli
        # bosqichidan boshlab davom ettiradi.
        return {
            "intent": "free_room",
            "day": _clean_day(parsed.get("day")),
            "building": _clean_building(parsed.get("building")),
            "period": _clean_period(parsed.get("period")),
        }

    return None


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Telegramdan kelgan ovozli xabar baytlarini (odatda OGG/Opus
    formatida) OpenAI Whisper API orqali matnga aylantiradi.

    Xuddi classify_intent() kabi fail-safe: OPENAI_API_KEY sozlanmagan,
    fayl bo'sh, tarmoq/API xatosi bo'lsa - None qaytaradi, chaqiruvchi
    tomon bunda hech qanday qo'shimcha (AI) javob yubormaydi, lekin
    xabar baribir avvalgidek chat tarixiga yoziladi (ai_intent.py'ga
    qarang)."""
    if not config.OPENAI_API_KEY or not audio_bytes:
        return None

    form = aiohttp.FormData()
    form.add_field("model", "whisper-1")
    form.add_field(
        "file", audio_bytes, filename=filename, content_type="audio/ogg"
    )
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    try:
        timeout = aiohttp.ClientTimeout(total=_TRANSCRIBE_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_TRANSCRIBE_URL, data=form, headers=headers
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "OpenAI transkripsiya xato qaytardi (status=%s): %s",
                        resp.status, body[:300],
                    )
                    await _log_ai_error(
                        f"OpenAI transkripsiya xato (status={resp.status}): {body}"
                    )
                    return None
                data = await resp.json()
    except Exception as e:
        logger.exception("Ovozli xabarni matnga aylantirishda xatolik")
        await _log_ai_error(f"Transkripsiya chaqiruvida xatolik: {e}")
        return None

    text = _clean_str(data.get("text"))
    return text
