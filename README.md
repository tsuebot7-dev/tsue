# TSUE Dars Jadvali Telegram Bot

TSUE (tsue.edupage.org) dars jadvalini Telegram orqali ko'rsatuvchi bot.
Talabalar, o'qituvchilar va xonalar bo'yicha jadval skrinshotini
yuboradi, shuningdek berilgan bino/kun/para bo'yicha **bo'sh xonalarni**
topib beradi.

## Tarkibi

```
tsue_bot/
├── bot/                    # Telegram bot (aiogram 3)
│   ├── config.py           # sozlamalar (.env dan o'qiladi)
│   ├── data_loader.py      # JSON fayllarni ierarxik daraxtga aylantiradi
│   ├── screenshot.py       # Playwright orqali jadval skrinshotini oladi
│   ├── keyboards.py        # inline tugmalar
│   ├── states.py           # FSM holatlari
│   ├── main.py             # botning kirish nuqtasi
│   └── handlers/
│       ├── start.py        # /start, bosh menyu
│       ├── browser.py      # Talabalar/O'qituvchilar/Xonalar navigatsiyasi
│       └── free_rooms.py   # Bo'sh xonalarni topish oqimi
├── admin/                  # Web-admin panel (FastAPI)
│   ├── app.py
│   └── templates/
├── data/                   # JSON ma'lumot fayllari (shu yerda saqlanadi)
│   ├── guruhlar.json
│   ├── ustozlar.json
│   ├── xonalar.json
│   ├── boshxonalar.json
│   └── hierarchy_config.json   # avtomatik yaratiladi
├── run.py                  # bot + admin panelni birga ishga tushiradi
├── Dockerfile
├── requirements.txt
└── railway.json
```

## Ma'lumot fayllari haqida

### guruhlar.json / ustozlar.json / xonalar.json

Bu fayllar **"tekis" (flat) dict** ko'rinishida bo'lishi kerak, lekin
ichida ketma-ket joylashgan sarlavha kalitlari bor:

```json
{
  "MENEJMENTFAKULTETI": "https://tsue.edupage.org/timetable/view.php?num=94&class=*1800",
  "1KURS": "https://tsue.edupage.org/timetable/view.php?num=94&class=*1389",
  "MO-900/26": "https://tsue.edupage.org/timetable/view.php?num=94&class=*3",
  "MO-901/26": "https://tsue.edupage.org/timetable/view.php?num=94&class=*4",
  "2KURS": "...",
  "...": "..."
}
```

Bot bu faylni avtomatik ravishda **{fakultet: {kurs: {guruh: url}}}**
ko'rinishidagi daraxtga aylantiradi. Qaysi kalitlar "sarlavha"
(fakultet/kurs/bino) ekanini aniqlash uchun **regex naqshlari**
ishlatiladi - ular `data/hierarchy_config.json` faylida (yoki admin
panelning "Ierarxiya sozlamalari" bo'limida) saqlanadi:

```json
{
  "guruhlar": {
    "levels": [
      {"pattern": "^[A-Z]+$", "label": "fakultet"},
      {"pattern": "^\\dKURS$", "label": "kurs"}
    ]
  },
  "ustozlar": {
    "levels": [
      {"pattern": "^[A-Z]+$", "label": "fakultet"}
    ]
  },
  "xonalar": {
    "levels": [
      {"pattern": "^[A-Z0-9]+$", "label": "bino"}
    ]
  }
}
```

**MUHIM:** `ustozlar.json` va `xonalar.json` ning aniq formatini hali
ko'rmaganim uchun, ularning "sarlavha" pattern'lari `guruhlar.json`
asosida **taxminiy** qilib qo'yilgan. Fayllarni yuklab bo'lgach:

1. Admin panelda **Ierarxiya sozlamalari** bo'limiga kiring.
2. Botda **O'qituvchilar** yoki **Xonalar** tugmasini bosib ko'ring.
3. Agar sarlavha (masalan bino nomi) guruh/o'qituvchi sifatida chiqib
   qolsa yoki aksincha - pattern'ni shunga qarab to'g'irlang va
   saqlang (kod o'zgartirishga hojat yo'q, avtomatik qayta yuklanadi).

### boshxonalar.json ("bo'sh xonalar")

Bu fayl **oldindan tayyorlangan** (scraper orqali yig'ilgan) va quyidagi
formatda bo'lishi kerak:

```json
{
  "10": {
    "room_id": 10,
    "room_name": "1/126",
    "url": "https://tsue.edupage.org/timetable/view.php?num=94&classroom=*10",
    "busy_slots": [{"day": "Mn", "period": 3, "time": "11:00-12:20", "info": "..."}],
    "free_slots": [{"day": "Mn", "period": 1, "time": "8:00-9:20"}]
  },
  "11": { "...": "..." }
}
```

Bino nomi `room_name` dagi `/` belgisidan oldingi qismdan olinadi
(masalan `"1/126"` -> bino **"1"**). Botda foydalanuvchi bino, kun va
parani tanlaganda, bot shu binoga tegishli barcha xonalar orasidan
`free_slots` ichida mos (kun, para) yozuvi bor xonalarni ro'yxat
qilib chiqaradi.

Bu faylni yangilash uchun avval yozgan `room_schedule_scraper_svg.py`
skriptini qayta ishga tushirib, natijani (`rooms_schedule.json`) admin
panel orqali `boshxonalar.json` sifatida yuklashingiz mumkin.

## Lokal ishga tushirish (test uchun)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# .env faylini oching va BOT_TOKEN, ADMIN_PASSWORD qiymatlarini kiriting

# data/ papkasiga guruhlar.json, ustozlar.json, xonalar.json,
# boshxonalar.json fayllaringizni joylashtiring

python run.py
```

Bot ishga tushadi (polling), admin panel esa http://localhost:8000
manzilida ochiladi (login: .env dagi ADMIN_USERNAME/ADMIN_PASSWORD).

## Railway'ga deploy qilish

1. Loyihani GitHub'ga yuklang (yangi repository yarating, shu papkani
   push qiling).
2. [railway.app](https://railway.app) da **New Project -> Deploy from
   GitHub repo** ni tanlang, shu repo'ni tanlang.
3. Railway `Dockerfile`ni avtomatik topib, shu asosida build qiladi.
4. **Variables** bo'limiga quyidagilarni qo'shing:
   - `BOT_TOKEN` - @BotFather dan olingan token
   - `ADMIN_USERNAME` - admin panel login
   - `ADMIN_PASSWORD` - admin panel paroli (kuchli parol tanlang!)
5. **Settings -> Networking** bo'limida **Generate Domain** tugmasini
   bosing - shu orqali admin panelga ochiladigan havola olasiz
   (masalan `https://sizning-loyiha.up.railway.app`).
6. Deploy tugagach, botga Telegram'da `/start` yuboring - ishlashi
   kerak.
7. `data/` papkasidagi JSON fayllarni admin panel orqali (havola oxiriga
   `/file/guruhlar` va h.k. qo'shib, yoki bosh sahifadan) yuklang.

**Eslatma - fayllar saqlanishi haqida:** Railway'ning standart
(ephemeral) fayl tizimida konteyner qayta ishga tushganda (masalan
yangi deploy qilinganda) `data/` papkasidagi o'zgarishlar **yo'qolishi
mumkin**, chunki ular image ichida emas, balki runtime paytida yozilgan
bo'ladi. Bunday holatni oldini olish uchun ikki yo'l bor:
  - **Railway Volume** qo'shing (Settings -> Volumes) va uni `/app/data`
    ga ulang - shunda fayllar doimiy saqlanadi.
  - Yoki har safar deploy qilishdan oldin yangi JSON fayllarni to'g'ridan-to'g'ri
    repo ichidagi `data/` papkasiga qo'yib, GitHub'ga push qiling.

Birinchi variant (Volume) tavsiya etiladi, chunki shunda fayllarni
admin panel orqali qayta deploy qilmasdan yangilash mumkin bo'ladi.

### Guruhlar - havolalarni sinxronlash (struktura saqlanadi)
- Siz `guruhlar.json` faylini **qo'lda** tuzasiz/tahrirlaysiz (fakultet
  → kurs → guruh tartibi to'liq sizning nazoratingizda).
- Bot esa fon rejimida (`bot/group_url_scraper.py`) har hafta barcha
  guruh ID'larini (`class=*1` dan `class=*2500` gacha, `.env` orqali
  sozlanadi) tekshirib, agar biror guruhning ID'si TSUE saytida
  o'zgargan bo'lsa (masalan "MO-900/26" endi boshqa `class=*ID` da
  bo'lsa), faylingizdagi **faqat o'sha bitta yozuvning URL qiymatini**
  yangilaydi - guruh nomlari, ularning tartibi va fakultet/kurs
  tuzilishi **hech qachon o'zgartirilmaydi**.
- Saytda topilgan, lekin sizning faylingizda yo'q guruhlar **avtomatik
  qo'shilmaydi** (strukturangizni buzmaslik uchun) - ular "Xatolar
  jurnali"ga ma'lumot sifatida yoziladi, xohlasangiz qo'lda qo'shasiz.
- Admin panelda **"🎓 Guruhlar - havolalarni sinxronlash"** kartasi
  orqali holatni ko'rish va qo'lda ishga tushirish mumkin.

### Bo'sh xonalar - avtomatik skanerlash
- Bot endi **o'zi**, har `ROOM_SCAN_INTERVAL_DAYS` kunda (standart: 7)
  barcha xonalarni (tsue.edupage.org) qayta skanerlab,
  `data/boshxonalar.json` faylini avtomatik yangilaydi — qo'lda
  skript ishga tushirib, admin panelga yuklashning hojati yo'q.
- Xona ID oralig'i `.env` orqali sozlanadi: `ROOM_SCAN_START=1`,
  `ROOM_SCAN_END=640` (standart qiymatlar).
- Admin paneldagi **"Ma'lumotlarni yangilash"** sahifasida skanerlash
  holati (jarayonda / tayyor / oxirgi marta qachon) ko'rinadi, va
  **"🔍 Xonalarni hozir skanerlash"** tugmasi orqali kutmasdan
  qo'lda ham ishga tushirish mumkin.

## Ma'lumotlar bazasi: PostgreSQL (Railway) yoki SQLite (lokal)

Bot foydalanuvchilar, guruh obunalari, chat yozishmalari va sozlamalarni
saqlash uchun ikki xil bazani qo'llab-quvvatlaydi - **kodni
o'zgartirishning hojati yo'q**, faqat `DATABASE_URL` muhit
o'zgaruvchisi bor-yo'qligiga qarab avtomatik tanlanadi:

- **DATABASE_URL berilgan bo'lsa** -> PostgreSQL ishlatiladi (asyncpg
  orqali, connection pool bilan). Bu Railway'ning ephemeral fayl
  tizimi muammosini butunlay hal qiladi.
- **DATABASE_URL berilmagan bo'lsa** (masalan lokal kompyuterda test
  qilishda) -> oddiy SQLite fayliga (`data/bot_data.db`) yoziladi.

### Railway'da PostgreSQL qanday ulanadi

1. Railway loyihangiz sahifasida **"+ New"** -> **"Database"** ->
   **"Add PostgreSQL"** ni tanlang.
2. Railway avtomatik ravishda yangi "Postgres" xizmatini yaratadi va
   sizning asosiy (bot) xizmatingizga **`DATABASE_URL`** muhit
   o'zgaruvchisini **avtomatik** qo'shib qo'yadi (agar ikkalasi bir
   loyiha ichida bo'lsa - Railway ularni avtomatik bog'laydi;
   bog'lanmasa, Postgres xizmatidan "Connect" -> "Connection URL" ni
   nusxalab, bot xizmatingizning Variables bo'limiga o'zingiz
   `DATABASE_URL` nomi bilan qo'shing).
3. Botni qayta deploy qiling (yoki Railway avtomatik qayta ishga
   tushiradi). Keyingi ishga tushirishda bot avtomatik ravishda
   kerakli jadvallarni PostgreSQL'da yaratadi (`bot/db.py` ->
   `init_db()`), hech qanday qo'shimcha amal shart emas.
4. Tasdiqlash uchun: botga bir necha marta `/start` yuboring, so'ng
   admin paneldagi **"Foydalanuvchilar"** bo'limida ular ko'rinishi
   kerak. Endi Railway qayta deploy qilinsa ham (yoki hatto Volume
   ulanmagan bo'lsa ham) bu ma'lumotlar **yo'qolmaydi**.

### Lokal kompyuterda

Hech narsa qilishning hojati yo'q - `.env` faylida `DATABASE_URL`
qatori bo'lmasa (yoki bo'sh bo'lsa), bot avtomatik SQLite'ga
o'tadi va oddiy `data/bot_data.db` fayliga yozadi.

## Yangi qo'shilgan funksiyalar (v2)

### Foydalanuvchi tomoni
- Har bir jadval skrinshoti ostida **"💾 Saqlab qo'yish"** tugmasi bor —
  bosilsa, o'sha jadval foydalanuvchining shaxsiy ro'yxatiga saqlanadi
  (`/saqlanganlar` buyrug'i orqali ko'rish mumkin).
- **"👥 Guruhga sozlash"** tugmasi — botni Telegram guruhga qo'shib,
  o'sha guruhda avtomatik jadval yuborishni qanday sozlash haqida
  yo'riqnoma beradi.
- Botni biror Telegram guruhga qo'shib, guruhda `/start` yuborilsa,
  bot fakultet → kurs → guruh tanlashni so'raydi, so'ng **qaysi hafta
  kunlari** va **qaysi soatda** jadval avtomatik yuborilishini so'raydi.
  Shundan keyin bot belgilangan kun/vaqtda avtomatik ravishda shu
  guruhga jadval skrinshotini yuborib turadi (`bot/scheduler.py`, har
  30 soniyada bir tekshiradi, Toshkent vaqti UTC+5 bo'yicha).

### Admin panel tomoni
- **Foydalanuvchilar** bo'limida endi har bir foydalanuvchi qatorida
  **"💬 Yozish"** tugmasi bor — bosilsa, Telegramga o'xshash chat
  oynasi ochiladi: foydalanuvchi botga yozgan xabarlar va admin
  javoblari shu yerda ko'rinadi, pastdan yangi xabar yozib yuborish
  mumkin (to'g'ridan-to'g'ri botning o'zi orqali).
- Yangi **"👨‍👩‍👧‍👦 Guruhlar"** bo'limi — botni qaysi Telegram
  guruhlar avtomatik jadval uchun ulaganini, qanday kun/vaqtda
  yuborilishini ko'rish, to'xtatish/faollashtirish, o'chirish, va
  barcha faol guruhlarga bittada xabar yuborish imkonini beradi.

Buning uchun `bot_data.db` (SQLite) bazasiga yangi jadvallar qo'shildi:
`saved_schedules`, `group_subscriptions`, `chat_messages`. Qo'shimcha
kutubxona kerak emas (SQLite Python bilan birga keladi).

## Struktura-saqlovchi sinxronlash (guruhlar, o'qituvchilar, xonalar)

`guruhlar.json`, `ustozlar.json`, `xonalar.json` fayllarining
**strukturasini (qanday nomlar bor, qaysi tartibda) siz qo'lda
boshqarasiz**. Bot esa fon rejimida (haftada bir marta, yoki admin
paneldan qo'lda) har bir mavjud nomning TSUE saytidagi joriy to'g'ri
havolasini tekshirib, agar ID almashgan bo'lsa, **faqat o'sha bitta
qiymatni** yangilaydi:

- Guruhlar: `bot/group_url_scraper.py` (`class=*1..2500`)
- O'qituvchilar: `bot/teacher_scraper.py` (`teacher=*1..3100`)
- Xonalar: `bot/room_scraper.py` ichida (`classroom=*1..640` - bu
  skanerlash bir vaqtning o'zida ham "bo'sh xonalar" ma'lumotini, ham
  `xonalar.json`ni yangilaydi, qo'shimcha so'rov yubormasdan)

**Saytda topilgan, lekin faylingizda yo'q nomlar avtomatik
qo'shilmaydi** - ular admin panelning **"🆕 Yangi topilganlar"**
sahifasida havolasi bilan ko'rinadi, xohlasangiz qo'lda faylga
qo'shasiz.

**Muhim - haddan tashqari ehtiyotkorlik**: barcha skanerlash
funksiyalari TSUE saytini "zo'riqtirmaslik" uchun ataylab sekin
ishlaydi (har so'rov orasida 5 soniya kutadi), va agar ketma-ket 8
marta xato chiqsa (sayt bloklagan bo'lishi mumkin degan belgi), 45
daqiqaga butunlay to'xtab, keyin avtomatik davom etadi. Bularning
barchasini admin panelning **"⚙️ Avtomatik skanerlash"** kartasidan
butunlay o'chirib qo'yish ham mumkin.

## Almashtirishlar (guruh jadvali o'zgarishi)

`bot/group_watcher.py` kuniga bir marta, **"Mening guruhim" qilib
belgilangan** VA **Telegram guruhida avtomatik jadval sozlangan**
barcha guruhlarni tekshirib, agar jadval o'zgargan bo'lsa (xona,
o'qituvchi, dars qo'shilgan/o'chirilgan), tegishli **shaxsiy
foydalanuvchilarga VA Telegram guruh chatlariga** avtomatik xabar
yuboradi (bitta skrinshot olib, hammaga qayta ishlatiladi - ortiqcha
so'rov yubormaslik uchun).

## Botning ishlash mantig'i (qisqacha)

- **Talabalar / O'qituvchilar / Xonalar**: foydalanuvchi daraxt
  bo'ylab (fakultet -> kurs -> guruh, yoki bino -> xona) yuradi,
  oxirida tanlangan element uchun edupage sahifasiga Playwright orqali
  kirilib, jadval qismining (SVG) skrinshoti olinadi va foydalanuvchiga
  rasm sifatida yuboriladi.
- **Bo'sh xonalarni topish**: bino -> kun -> para tanlanadi, so'ng
  `boshxonalar.json` dagi tayyor `free_slots` ma'lumotidan foydalanib,
  mos keluvchi xonalar ro'yxati matn ko'rinishida chiqariladi (bunda
  skrinshotga hojat yo'q, chunki ma'lumot allaqachon tayyor).

## Muammolarni bartaraf etish

- **Bot javob bermayapti**: Railway loglarini tekshiring
  (`BOT_TOKEN` to'g'ri kiritilganiga ishonch hosil qiling).
- **Skrinshot o'rniga xatolik chiqyapti**: edupage sayti vaqtincha
  ishlamay qolgan yoki URL noto'g'ri bo'lishi mumkin - loglarda aniq
  xabar ko'rinadi.
- **Fakultet/bino noto'g'ri aniqlanmoqda**: admin paneldagi
  "Ierarxiya sozlamalari" bo'limidan regex pattern'larni to'g'irlang.
- **Admin panelga kira olmayapman**: `.env` (yoki Railway Variables)
  dagi `ADMIN_USERNAME`/`ADMIN_PASSWORD` to'g'ri ekanini tekshiring.
