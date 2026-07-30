# 📨 Telegram Tools — دليل عربي

[![CI](https://github.com/DrAbdulmalek/telegram-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/DrAbdulmalek/telegram-tools/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**أدوات تيليجرام الموحّدة** — نسخ، توجيه، استخراج، ومعالجة نصوص عربية من قنوات تيليجرام.
مبنية على [Telethon](https://github.com/LonamiWebs/Telethon) مع حلقة asyncio ثابتة،
تحديد سرعة تكيّفي، وواجهة Gradio موحّدة.

> يدمج هذا المشروع ثلاثة مشاريع منفصلة سابقة (`telegram-channel-copier`،
> `telegram-forwarder`، `telegram-pipeline`) في قاعدة كود واحدة متناسقة.

---

## 🚀 الميزات

| الأداة | الوظيفة | متى تستخدمها |
|--------|---------|---------------|
| **⚡ نسخ سريع** | نسخ جماعي عبر إعادة إرسال الوسائط مباشرة | القنوات العامة أو حيث لديك صلاحية |
| **🛡️ توجيه متجاوز** | تجاوز "Restrict Saving Content" عبر تنزيل ثم رفع | القنوات المحمية (`noforwards`) |
| **📚 استخراج** | بناء corpus للـ NLP/OCR (نصوص + وسائط) | جمع بيانات تدريب |
| **🔧 معالجة** | تطبيع عربي، إزالة تكرار، فلترة جودة، تجزئة | تنظيف ما بعد الاستخراج |

### أبرز الميزات

- **حلقة asyncio ثابتة واحدة** — آمنة لـ Telethon عبر كل عمليات الواجهة
- **RateLimiter تكيّفي** — تراجع أُسّي عند FloodWait، استرخاء بعد سلسلة نجاحات
- **دعم StringSession** — صدّر مرة، أعد الاستخدام للأبد (متوافق مع HF Secrets)
- **دعم الاستئناف** — عمليات النسخ/الاستخراج تحفظ التقدم كل 10 رسائل
- **دعم الألبومات** — الوسائط المجمّعة تُوجَّه كألبوم واحد
- **كاش الكيانات** — يتعامل مع معرّفات القنوات الرقمية عبر `iter_dialogs`
- **واجهة ثنائية اللغة** — عربية مع fallback إنجليزي
- **جاهز لـ Docker** — `docker compose up` يكفي للنشر

---

## 📦 التثبيت

### من المصدر

```bash
git clone https://github.com/DrAbdulmalek/telegram-tools.git
cd telegram-tools
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .  # يثبّت CLI `tg-tools`
```

### Docker

```bash
docker compose up -d --build
# افتح http://localhost:7860
```

---

## 🔧 البدء السريع

### واجهة الويب (موصى بها)

```bash
python app.py
```

افتح http://localhost:7860 في المتصفح.

### CLI

```bash
# 1. مصادقة (مرة واحدة — يحفظ SESSION_STRING)
export TG_API_ID=12345678
export TG_API_HASH='your_api_hash'
tg-tools login --phone +963XXXXXXXXX

# 2. نسخ 100 رسالة من قناة عامة
tg-tools copy --source @public_channel --dest -1001234567890 --limit 100

# 3. توجيه من قناة محمية (أبطأ، يتجاوز القيود)
tg-tools forward --source @protected_channel --dest -1001234567890 --delay 3

# 4. استخراج corpus للـ NLP/OCR
tg-tools extract --channel @my_channel --output ./corpus --limit 500

# 5. معالجة corpus العربي
tg-tools process --input ./corpus --output ./processed
```

### متغيرات البيئة

| المتغير | الوصف | مطلوب |
|---------|-------|-------|
| `TG_API_ID` | معرّف Telegram API (من my.telegram.org) | ✅ |
| `TG_API_HASH` | تجزئة Telegram API | ✅ |
| `TG_PHONE` | رقم الهاتف مع رمز الدولة | لتسجيل الدخول عبر CLI |
| `TG_SESSION` | سلسلة الجلسة (بديل عن الهاتف) | اختياري |
| `PORT` | منفذ واجهة الويب (افتراضي: 7860) | اختياري |

---

## 🏗️ المعمارية

```
┌─────────────────────────────────────────────────────────────┐
│                  واجهة Gradio (app.py)                      │
│  ┌──────┐ ┌─────────┐ ┌──────┐ ┌──────────┐ ┌──────────┐   │
│  │دخول  │ │قنوات   │ │ نسخ  │ │ توجيه    │ │ استخراج  │   │
│  └──────┘ └─────────┘ └──────┘ └──────────┘ └──────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │ run_coroutine_threadsafe
                          ▼
              ┌────────────────────────┐
              │   حلقة asyncio ثابتة   │  ← thread خلفي واحد
              │  (واحدة لكل العملاء)   │
              └───────────┬────────────┘
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│   Copier    │  │  Forwarder   │  │  Extractor   │
│ (مباشر)     │  │ (تنزيل-رفع)  │  │ (بناء corpus)│
└──────┬──────┘  └──────┬───────┘  └──────┬───────┘
       └────────────────┼─────────────────┘
                        ▼
              ┌──────────────────┐
              │  TelegramClient  │  ← Telethon 1.36
              └────────┬─────────┘
                       ▼
                   Telegram API
```

راجع [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) للتفاصيل الكاملة.

---

## 🛡️ الأمان

- **لا تشارك أبداً** `API_ID` أو `API_HASH` أو `SESSION_STRING`
- ملفات الجلسة (`.session`) مستثناة من Git عبر `.gitignore`
- استخدم **متغيرات البيئة** أو **HF Secrets** — لا تكتب البيانات في الكود
- أمر `login` في CLI يطبع `SESSION_STRING` مرة واحدة — انسخها إلى Secrets وامسح الطرفية
- بعد الانتهاء، فكّر في إبطال تطبيق API من my.telegram.org
- راجع [SECURITY.md](SECURITY.md) للسياسة الكاملة

---

## ⚠️ إخلاء المسؤولية

هذا المشروع **للأغراض التعليمية فقط**. المؤلف غير مسؤول عن أي استخدام خاطئ
أو انتهاك لشروط خدمة تيليجرام. احترم دائماً حقوق منشئي المحتوى واستخدم
الأداة فقط على القنوات التي لديك إذن بنسخ/توجيه محتواها.

---

## 🤝 المساهمة

المساهمات مرحب بها! راجع [CONTRIBUTING.md](CONTRIBUTING.md) للإرشادات.

---

## 📄 الترخيص

[MIT License](LICENSE) — © 2026 Abdulmalek Husseini

---

## 📞 روابط

| المنصة | الرابط |
|--------|-------|
| **GitHub** | https://github.com/DrAbdulmalek/telegram-tools |
| **HuggingFace Spaces** | https://huggingface.co/spaces/DrAbdulmalek/telegram-tools |
| **المشكلات** | https://github.com/DrAbdulmalek/telegram-tools/issues |
| **النقاشات** | https://github.com/DrAbdulmalek/telegram-tools/discussions |
| **المؤلف** | [@DrAbdulmalekHusseini](https://t.me/DrAbdulmalekHusseini) |
