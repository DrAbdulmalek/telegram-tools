#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Tools — Unified Gradio Web UI (5 tabs)

Tabs
----
  1. 🔐 Login        — API credentials + phone/code + SESSION_STRING export
  2. 📡 Channels     — List dialogs, inspect channel info
  3. ⚡ Copy         — Fast bulk copy (direct re-send)
  4. 🛡️ Forward      — Bypass 'Restrict Saving' via Download-Upload
  5. 📚 Extract      — Build NLP/OCR corpus from channel history

A single persistent asyncio loop runs in a background thread — every
Telethon call goes through run_coroutine_threadsafe to keep the client
bound to that loop (Telethon requirement).
"""

from __future__ import annotations

import asyncio
import os
import threading
import logging
from typing import Optional

import gradio as gr

from telegram_tools.core.copier import CopierConfig, TelegramCopier
from telegram_tools.core.forwarder import (
    ForwardConfig,
    TelegramForwarder,
    ForwardResult,
)
from telegram_tools.core.extractor import TelegramExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Persistent Event Loop ──────────────────────────────────

_loop = asyncio.new_event_loop()


def _loop_runner() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


_loop_thread = threading.Thread(target=_loop_runner, daemon=True)
_loop_thread.start()


def _run(coro, timeout: float = 120.0):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


# ─── Global State ───────────────────────────────────────────

# We keep one of each tool alive — they share the same client once
# authenticated (same api_id/api_hash/session_string).
_forwarder: Optional[TelegramForwarder] = None
_copier: Optional[TelegramCopier] = None
_extractor: Optional[TelegramExtractor] = None
_last_creds: tuple[int, str, Optional[str]] = (0, "", None)  # api_id, api_hash, session_string


def _get_or_create_tools(api_id, api_hash, session_string):
    """Lazily create tool instances sharing the same session config."""
    global _forwarder, _copier, _extractor, _last_creds

    api_id_int = int(str(api_id).strip())
    api_hash_str = str(api_hash).strip()
    session_str = (str(session_string).strip() or None) if session_string else None

    if (
        _forwarder is None
        or _last_creds != (api_id_int, api_hash_str, session_str)
    ):
        # Disconnect previous
        if _forwarder:
            try:
                _run(_forwarder.disconnect())
            except Exception:
                pass

        _forwarder = TelegramForwarder(
            api_id_int, api_hash_str, session_string=session_str
        )
        _copier = TelegramCopier(
            api_id_int, api_hash_str, session_string=session_str
        )
        _extractor = TelegramExtractor(
            api_id_int, api_hash_str, session_string=session_str
        )
        _last_creds = (api_id_int, api_hash_str, session_str)

    return _forwarder, _copier, _extractor


# ─── Status helper ─────────────────────────────────────────


def _status_html(text: str, kind: str = "info") -> str:
    return f'<div class="{kind}-box">{text}</div>'


# ─── CSS ────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap');
* { font-family: 'Tajawal', sans-serif !important; }
.gradio-container { direction: rtl; }
.header {
    text-align: center; padding: 24px;
    background: linear-gradient(135deg, #1a73e8 0%, #6c3fc5 100%);
    color: white; border-radius: 16px; margin-bottom: 20px;
}
.header h1 { margin: 0; font-size: 1.9em; font-weight: 700; }
.header p  { margin: 8px 0 0; opacity: .85; font-size: .95em; }
.warn-box    { background:#fff3cd; color:#856404; border:1px solid #ffc107;
               border-radius:10px; padding:12px 16px; margin:8px 0; }
.success-box { background:#d1e7dd; color:#0a3622; border:1px solid #badbcc;
               border-radius:10px; padding:12px 16px; margin:8px 0; }
.error-box   { background:#f8d7da; color:#58151c; border:1px solid #f1aeb5;
               border-radius:10px; padding:12px 16px; margin:8px 0; }
.info-box    { background:#cfe2ff; color:#052c65; border:1px solid #9ec5fe;
               border-radius:10px; padding:12px 16px; margin:8px 0; }
"""


# ═══════════════════════════════════════════════════════════
#  Tab 1: Login
# ═══════════════════════════════════════════════════════════


def do_send_code(api_id, api_hash, phone, session_str):
    """Send login code OR validate an existing session string."""
    try:
        fwd, _, _ = _get_or_create_tools(api_id, api_hash, session_str)
    except ValueError as e:
        return (
            gr.update(visible=False),
            _status_html(f"❌ {e}", "error"),
            gr.update(visible=False),
        )

    if _run(fwd.is_authorized()):
        return (
            gr.update(visible=False),
            _status_html("✅ متصل (جلسة محفوظة)!", "success"),
            gr.update(visible=True),
        )

    if not phone or not str(phone).startswith("+"):
        return (
            gr.update(visible=False),
            _status_html(
                "❌ أدخل رقم هاتف صالح يبدأ بـ + (مثال: +963XXXXXXXXX)",
                "error",
            ),
            gr.update(visible=False),
        )

    try:
        _run(fwd.send_code(str(phone).strip()))
        return (
            gr.update(visible=True),
            _status_html("📱 تم إرسال الكود — تحقق من تطبيق Telegram", "info"),
            gr.update(visible=False),
        )
    except Exception as e:
        return (
            gr.update(visible=False),
            _status_html(f"❌ {e}", "error"),
            gr.update(visible=False),
        )


def do_verify(code, password):
    if not _forwarder:
        return _status_html("❌ أعد إرسال الكود أولاً", "error"), gr.update(visible=False)
    try:
        _run(_forwarder.verify_code(str(code).strip(), password or None))
        return (
            _status_html("✅ تم تسجيل الدخول بنجاح!", "success"),
            gr.update(visible=True),
        )
    except Exception as e:
        msg = str(e)
        if "2FA_PASSWORD_REQUIRED" in msg:
            return (
                _status_html("🔐 أدخل كلمة مرور التحقق الثنائي", "warn"),
                gr.update(visible=False),
            )
        return _status_html(f"❌ {msg}", "error"), gr.update(visible=False)


def do_export_session():
    if not _forwarder:
        return _status_html("❌ غير متصل", "error"), ""
    try:
        s = _run(_forwarder.export_session_string())
        return (
            _status_html(
                "✅ انسخ الـ string واحفظه في HF Secrets باسم SESSION_STRING",
                "success",
            ),
            s,
        )
    except Exception as e:
        return _status_html(f"❌ {e}", "error"), ""


def do_disconnect():
    global _forwarder, _copier, _extractor
    if _forwarder:
        try:
            _run(_forwarder.disconnect())
        except Exception:
            pass
    _forwarder = None
    _copier = None
    _extractor = None
    return (
        gr.update(visible=False),
        _status_html("🔌 تم قطع الاتصال", "warn"),
        gr.update(visible=False),
    )


# ═══════════════════════════════════════════════════════════
#  Tab 2: Channels
# ═══════════════════════════════════════════════════════════


def do_refresh_channels():
    if not _forwarder or not _run(_forwarder.is_authorized()):
        return (
            gr.update(choices=[]),
            gr.update(choices=[]),
            _status_html("❌ غير متصل — سجل دخول أولاً", "error"),
        )
    try:
        dialogs = _run(_forwarder.get_dialogs())
        choices = []
        for d in dialogs:
            badge = "🔒 " if d.get("protected") else ""
            label = f"{badge}{d['title']} ({d['type']})"
            choices.append((label, str(d["id"])))
        return (
            gr.update(choices=choices, value=None),
            gr.update(choices=choices, value=None),
            _status_html(f"✅ تم تحميل {len(choices)} قناة/مجموعة", "success"),
        )
    except Exception as e:
        return (
            gr.update(choices=[]),
            gr.update(choices=[]),
            _status_html(f"❌ {e}", "error"),
        )


def do_channel_info(channel_id):
    if not channel_id or not _forwarder:
        return ""
    try:
        info = _run(_forwarder.get_channel_info(str(channel_id)))
        protected = "🔒 نعم" if info.get("protected") else "✅ لا"
        return (
            f"**{info['title']}** | "
            f"الأعضاء: {info.get('participants_count', 'غير معروف'):,} | "
            f"المحتوى محمي: {protected}"
        )
    except Exception as e:
        return f"⚠️ {e}"


# ═══════════════════════════════════════════════════════════
#  Tab 3: Copy (fast bulk)
# ═══════════════════════════════════════════════════════════


def do_copy(
    source, dest, source_manual, dest_manual,
    limit, delay, files_only, text_only, newest_first,
):
    """Generator that yields progress updates."""
    if not _copier or not _run(_copier.is_authorized()):
        yield _status_html("❌ غير متصل — سجل دخول أولاً", "error"), 0, "{}"
        return

    source = (source_manual or "").strip() or source
    dest = (dest_manual or "").strip() or dest
    if not source or not dest:
        yield _status_html("❌ اختر المصدر والوجهة", "error"), 0, "{}"
        return
    if source == dest:
        yield _status_html("❌ المصدر والوجهة لا يمكن أن يكونا نفسهما", "error"), 0, "{}"
        return

    config = CopierConfig(
        source_channel=source,
        dest_channel=dest,
        limit=int(limit),
        delay=float(delay),
        copy_text=not files_only,
        copy_media=not text_only,
        files_only=files_only,
        reverse_order=not newest_first,
    )

    yield _status_html("⏳ جارٍ النسخ…", "info"), 0, "{}"

    import queue as _q
    pq: "_q.Queue" = _q.Queue()

    def cb_sync(result, pct):
        pq.put((result, pct))

    async def cb(result, pct):
        cb_sync(result, pct)

    async def run():
        try:
            result = await _copier.copy(config, progress_callback=cb)
            pq.put(("DONE", result))
        except Exception as e:
            pq.put(("ERROR", str(e)))

    asyncio.run_coroutine_threadsafe(run(), _loop)

    while True:
        try:
            item = pq.get(timeout=0.5)
        except _q.Empty:
            continue

        if isinstance(item, tuple) and item[0] == "DONE":
            r = item[1]
            status = _status_html(
                f"✅ اكتمل — نجح: {r.copied} | فشل: {r.failed} | "
                f"تخطى: {r.skipped} | الوقت: {r.elapsed}",
                "success",
            )
            yield status, 100, str(r.to_dict())
            return
        elif isinstance(item, tuple) and item[0] == "ERROR":
            yield _status_html(f"❌ {item[1]}", "error"), 0, "{}"
            return
        elif isinstance(item, tuple) and len(item) == 2:
            r, pct = item
            status = _status_html(
                f"⏳ نسخ — نجح: {r.copied} | فشل: {r.failed} | تخطى: {r.skipped}",
                "info",
            )
            yield status, int(pct), str(r.to_dict())


def do_copy_cancel():
    if _copier:
        _copier.cancel()
    return _status_html("⛔ تم إرسال أمر الإلغاء…", "warn")


# ═══════════════════════════════════════════════════════════
#  Tab 4: Forward (Download-Upload)
# ═══════════════════════════════════════════════════════════


def do_forward(
    source, dest, source_manual, dest_manual,
    limit, delay, start_id, end_id,
    media_only, text_only, include_forwards,
    filter_text, send_caption, reverse,
):
    if not _forwarder or not _run(_forwarder.is_authorized()):
        yield _status_html("❌ غير متصل — سجل دخول أولاً", "error"), 0, "{}"
        return

    source = (source_manual or "").strip() or source
    dest = (dest_manual or "").strip() or dest
    if not source or not dest:
        yield _status_html("❌ اختر المصدر والوجهة", "error"), 0, "{}"
        return
    if source == dest:
        yield _status_html("❌ المصدر والوجهة لا يمكن أن يكونا نفسهما", "error"), 0, "{}"
        return
    if float(delay) < 1.0:
        yield _status_html(
            "⚠️ تأخير أقل من ثانية — خطر حظر! سيُستخدم 1.0 ثانية", "warn"
        ), 0, "{}"
        delay = 1.0

    config = ForwardConfig(
        source_channel=source,
        dest_channel=dest,
        limit=int(limit),
        delay=float(delay),
        media_only=bool(media_only),
        text_only=bool(text_only),
        skip_forwards=not bool(include_forwards),
        filter_text=str(filter_text).strip() or None,
        start_id=int(start_id) if int(start_id) > 0 else None,
        end_id=int(end_id) if int(end_id) > 0 else None,
        send_caption=bool(send_caption),
        reverse_order=bool(reverse),
    )

    yield _status_html("⏳ جارٍ النقل…", "info"), 0, "{}"

    import queue as _q
    pq: "_q.Queue" = _q.Queue()

    async def cb(result: ForwardResult, pct: int):
        pq.put((result, pct))

    async def run():
        try:
            result = await _forwarder.forward_content(config, progress_callback=cb)
            pq.put(("DONE", result))
        except Exception as e:
            pq.put(("ERROR", str(e)))

    asyncio.run_coroutine_threadsafe(run(), _loop)

    while True:
        try:
            item = pq.get(timeout=0.5)
        except _q.Empty:
            continue

        if isinstance(item, tuple) and item[0] == "DONE":
            r = item[1]
            status = _status_html(
                f"✅ اكتمل النقل — نجح: {r.success} | فشل: {r.failed} | "
                f"تخطى: {r.skipped} | الوقت: {r.elapsed}",
                "success",
            )
            yield status, 100, str(r.to_dict())
            return
        elif isinstance(item, tuple) and item[0] == "ERROR":
            yield _status_html(f"❌ {item[1]}", "error"), 0, "{}"
            return
        elif isinstance(item, tuple) and len(item) == 2:
            r, pct = item
            status = _status_html(
                f"⏳ نقل — نجح: {r.success} | فشل: {r.failed} | "
                f"تخطى: {r.skipped} | الإجمالي: {r.total}/{config.limit}",
                "info",
            )
            yield status, int(pct), str(r.to_dict())


def do_forward_cancel():
    if _forwarder:
        _forwarder.cancel()
    return _status_html("⛔ تم إرسال أمر الإلغاء…", "warn")


# ═══════════════════════════════════════════════════════════
#  Tab 5: Extract
# ═══════════════════════════════════════════════════════════


def do_extract(channel, channel_manual, output_dir, texts_only, no_media, limit, delay):
    if not _extractor or not _run(_extractor.is_authorized()):
        yield _status_html("❌ غير متصل — سجل دخول أولاً", "error"), "{}"
        return

    channel = (channel_manual or "").strip() or channel
    if not channel:
        yield _status_html("❌ اختر قناة أو أدخل معرّفها", "error"), "{}"
        return

    yield _status_html("⏳ جارٍ الاستخراج…", "info"), "{}"

    import queue as _q
    pq: "_q.Queue" = _q.Queue()

    async def run():
        try:
            metadata = await _extractor.extract(
                channel=channel,
                output_dir=output_dir or "./telegram_corpus",
                download_media=not no_media,
                texts_only=texts_only,
                limit=int(limit) if limit else 0,
                delay=float(delay),
            )
            pq.put(("DONE", metadata))
        except Exception as e:
            pq.put(("ERROR", str(e)))

    asyncio.run_coroutine_threadsafe(run(), _loop)

    while True:
        try:
            item = pq.get(timeout=0.5)
        except _q.Empty:
            continue
        if isinstance(item, tuple) and item[0] == "DONE":
            md = item[1]
            yield (
                _status_html(
                    f"✅ اكتمل — نصوص: {md.get('text_messages', 0)} | "
                    f"وسائط: {md.get('media_files', 0)} | الإجمالي: {md.get('total_messages', 0)}",
                    "success",
                ),
                str(md),
            )
            return
        elif isinstance(item, tuple) and item[0] == "ERROR":
            yield _status_html(f"❌ {item[1]}", "error"), "{}"
            return


# ═══════════════════════════════════════════════════════════
#  UI Build
# ═══════════════════════════════════════════════════════════


def build_app():
    with gr.Blocks(css=CSS, title="📨 Telegram Tools", theme=gr.themes.Soft()) as app:

        gr.HTML("""
        <div class="header">
            <h1>📨 Telegram Tools</h1>
            <p>أدوات تيليجرام الموحدة: نسخ سريع · نقل متجاوز للقيود · استخراج نصوص</p>
        </div>
        """)

        with gr.Tabs():

            # ─── TAB 1: Login ───────────────────────────────
            with gr.Tab("🔐 تسجيل الدخول"):
                gr.HTML("""<div class="info-box">
                    احصل على API ID و API Hash من
                    <a href="https://my.telegram.org" target="_blank">my.telegram.org</a>
                </div>""")

                with gr.Row():
                    api_id = gr.Number(label="API ID", value=0, precision=0, minimum=1)
                    api_hash = gr.Textbox(label="API Hash", type="password",
                                          placeholder="abc123def456...")

                phone = gr.Textbox(
                    label="رقم الهاتف (مع كود الدولة)",
                    placeholder="+963XXXXXXXXX",
                )

                with gr.Accordion("🔑 تسجيل دخول بـ Session String (موصى به لـ HF)", open=False):
                    gr.HTML("""<div class="info-box">
                        الصق Session String هنا لتجاوز إدخال الكود في كل مرة.
                        أو احفظها في HF Secrets باسم <code>SESSION_STRING</code>.
                    </div>""")
                    session_str = gr.Textbox(
                        label="Session String (اختياري)",
                        placeholder="1BVtsOK...",
                        type="password",
                        value=os.environ.get("SESSION_STRING", ""),
                    )

                with gr.Row():
                    send_code_btn = gr.Button("📱 إرسال كود التحقق", variant="primary")
                    disconnect_btn = gr.Button("🔌 قطع الاتصال", variant="secondary")

                with gr.Column(visible=False) as code_section:
                    gr.HTML('<div class="info-box">📲 تحقق من تطبيق Telegram</div>')
                    login_code = gr.Textbox(label="كود التحقق", placeholder="12345")
                    two_fa = gr.Textbox(label="كلمة مرور التحقق الثنائي (اختياري)",
                                        type="password")
                    verify_btn = gr.Button("✅ تأكيد وتسجيل الدخول", variant="primary")

                login_status = gr.HTML(_status_html("غير متصل 🔴", "warn"))

                with gr.Column(visible=False) as export_section:
                    gr.HTML('<div class="info-box">💾 احفظ الـ string في HF Secrets</div>')
                    export_btn = gr.Button("📤 تصدير الجلسة كـ String", variant="secondary")
                    export_status = gr.HTML()
                    session_out = gr.Textbox(label="Session String", interactive=False)

            # ─── TAB 2: Channels ────────────────────────────
            with gr.Tab("📡 القنوات"):
                refresh_btn = gr.Button("🔄 تحديث قائمة القنوات", variant="secondary")
                refresh_status = gr.HTML()

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### 📥 القناة المصدر")
                        source_list_c = gr.Dropdown(choices=[], label="اختر من القائمة",
                                                    interactive=True)
                        source_manual_c = gr.Textbox(
                            label="أو أدخل يدوياً (@username أو ID)",
                            placeholder="@channel_name"
                        )
                        source_info_c = gr.Markdown()

                    with gr.Column():
                        gr.Markdown("#### 📤 القناة الوجهة")
                        dest_list_c = gr.Dropdown(choices=[], label="اختر من القائمة",
                                                  interactive=True)
                        dest_manual_c = gr.Textbox(
                            label="أو أدخل يدوياً", placeholder="@my_channel"
                        )
                        dest_info_c = gr.Markdown()

                gr.HTML("""<div class="warn-box">
                    🔒 = محتوى محمي (Restrict Saving) — استخدم تبويب "النقل" لتجاوزه.
                </div>""")

            # ─── TAB 3: Copy ────────────────────────────────
            with gr.Tab("⚡ نسخ سريع"):
                gr.HTML("""<div class="info-box">
                    نسخ سريع عبر إعادة إرسال الوسائط مباشرة — لا يعمل على القنوات المحمية.
                    استخدم هذا للقنوات العامة أو حيث لديك صلاحية النشر.
                </div>""")

                with gr.Row():
                    with gr.Column():
                        limit_c = gr.Slider(0, 10000, value=0, step=1,
                                            label="عدد الرسائل (0 = الكل)")
                        delay_c = gr.Slider(1.0, 30.0, value=3.0, step=0.5,
                                            label="التأخير (ثانية)")

                    with gr.Column():
                        files_only_c = gr.Checkbox(label="🖼️ ملفات فقط", value=False)
                        text_only_c = gr.Checkbox(label="📝 نص فقط", value=False)
                        newest_first_c = gr.Checkbox(label="الأحدث أولاً", value=False)

                with gr.Row():
                    start_copy_btn = gr.Button("▶️ بدء النسخ", variant="primary", scale=3)
                    cancel_copy_btn = gr.Button("⛔ إيقاف", variant="stop", scale=1)

                copy_status = gr.HTML(_status_html("في الانتظار…", "info"))
                copy_progress = gr.Slider(0, 100, value=0, label="التقدم %", interactive=False)
                copy_stats = gr.Code(label="آخر نتيجة (JSON)", language="json", value="{}")

            # ─── TAB 4: Forward ─────────────────────────────
            with gr.Tab("🛡️ نقل متجاوز"):
                gr.HTML("""<div class="warn-box">
                    تجاوز قيود الحفظ عبر تنزيل الوسائط ثم إعادة رفعها.
                    أبطأ من النسخ السريع لكنه الوحيد الذي يعمل على القنوات المحمية.
                </div>""")

                with gr.Row():
                    with gr.Column():
                        limit_f = gr.Slider(1, 5000, value=100, step=1,
                                            label="عدد الرسائل")
                        delay_f = gr.Slider(1.0, 60.0, value=2.0, step=0.5,
                                            label="التأخير (ثانية)")

                    with gr.Column():
                        start_id_f = gr.Number(label="من رسالة رقم (0 = من البداية)",
                                               value=0, precision=0)
                        end_id_f = gr.Number(label="إلى رسالة رقم (0 = حتى النهاية)",
                                             value=0, precision=0)

                with gr.Row():
                    media_only_f = gr.Checkbox(label="🖼️ وسائط فقط", value=False)
                    text_only_f = gr.Checkbox(label="📝 نص فقط", value=False)
                    include_forwards_f = gr.Checkbox(label="⏭️ تضمين المعاد توجيهه", value=False)
                    send_caption_f = gr.Checkbox(label="💬 أرفق النص مع الوسائط", value=True)
                    reverse_f = gr.Checkbox(label="🔃 الأقدم أولاً", value=False)

                filter_text_f = gr.Textbox(
                    label="تصفية حسب النص (اختياري)",
                    placeholder="كلمة أو عبارة للبحث…",
                )

                with gr.Row():
                    start_fwd_btn = gr.Button("▶️ بدء النقل", variant="primary", scale=3)
                    cancel_fwd_btn = gr.Button("⛔ إيقاف", variant="stop", scale=1)

                fwd_status = gr.HTML(_status_html("في الانتظار…", "info"))
                fwd_progress = gr.Slider(0, 100, value=0, label="التقدم %", interactive=False)
                fwd_stats = gr.Code(label="آخر نتيجة (JSON)", language="json", value="{}")

            # ─── TAB 5: Extract ─────────────────────────────
            with gr.Tab("📚 استخراج نصوص"):
                gr.HTML("""<div class="info-box">
                    استخراج النصوص والوسائط من قناة لبناء مدونة لغوية (corpus)
                    صالحة لمعالجة NLP/OCR لاحقاً.
                </div>""")

                with gr.Row():
                    channel_list_e = gr.Dropdown(choices=[], label="اختر قناة من القائمة",
                                                 interactive=True)
                    channel_manual_e = gr.Textbox(
                        label="أو أدخل يدوياً", placeholder="@channel_name"
                    )

                output_dir_e = gr.Textbox(label="مجلد الإخراج",
                                          value="./telegram_corpus")

                with gr.Row():
                    limit_e = gr.Slider(0, 10000, value=0, step=1,
                                        label="عدد الرسائل (0 = الكل)")
                    delay_e = gr.Slider(1.0, 30.0, value=2.0, step=0.5,
                                        label="التأخير (ثانية)")

                with gr.Row():
                    texts_only_e = gr.Checkbox(label="📝 نصوص فقط (بدون وسائط)", value=False)
                    no_media_e = gr.Checkbox(label="🚫 تخطي الوسائط", value=False)

                start_ext_btn = gr.Button("▶️ بدء الاستخراج", variant="primary")
                ext_status = gr.HTML(_status_html("في الانتظار…", "info"))
                ext_stats = gr.Code(label="بيانات الاستخراج (JSON)", language="json", value="{}")

            # ─── TAB 6: Help ────────────────────────────────
            with gr.Tab("❓ المساعدة"):
                gr.Markdown("""
## كيفية الاستخدام

### الخطوة 1 — تسجيل الدخول
1. اذهب إلى [my.telegram.org](https://my.telegram.org)
2. سجل دخول → **API development tools** → أنشئ تطبيقاً
3. أدخل **API ID** و **API Hash** في التبويب الأول
4. أدخل رقم هاتفك واضغط **إرسال كود التحقق**
5. أدخل الكود المُرسَل إلى Telegram

### الخطوة 2 — حفظ الجلسة (مهم لـ HuggingFace)
بعد تسجيل الدخول، اضغط **تصدير الجلسة كـ String** واحفظها في:
`Settings → Secrets → SESSION_STRING`

### الخطوة 3 — اختر العملية
- **نسخ سريع** : للقنوات العامة (سريع لكن لا يتجاوز القيود)
- **نقل متجاوز** : للقنوات المحمية (تنزيل-إعادة-رفع)
- **استخراج نصوص** : لبناء corpus لـ NLP/OCR

---

### نصائح للاستخدام الآمن
- استخدم تأخيراً لا يقل عن **2 ثانية**
- لا تنقل أكثر من **500 رسالة** في الجلسة الواحدة
- **لا تُشارك Session String** مع أي أحد
- راجع [CONTRIBUTING.md](CONTRIBUTING.md) لمعلومات التطوير
                """)

        # ─── Event Wiring ────────────────────────────────

        # Login
        send_code_btn.click(
            do_send_code,
            inputs=[api_id, api_hash, phone, session_str],
            outputs=[code_section, login_status, export_section],
        )
        verify_btn.click(
            do_verify,
            inputs=[login_code, two_fa],
            outputs=[login_status, export_section],
        )
        disconnect_btn.click(
            do_disconnect,
            outputs=[code_section, login_status, export_section],
        )
        export_btn.click(
            do_export_session,
            outputs=[export_status, session_out],
        )

        # Channels
        refresh_btn.click(
            do_refresh_channels,
            outputs=[source_list_c, dest_list_c, refresh_status],
        )
        # Reuse the same channel list for both Copy/Forward/Extract tabs
        # by binding changes from the Channels tab into them
        source_list_c.change(
            do_channel_info, inputs=[source_list_c], outputs=[source_info_c]
        )
        dest_list_c.change(
            do_channel_info, inputs=[dest_list_c], outputs=[dest_info_c]
        )

        # Copy
        start_copy_btn.click(
            do_copy,
            inputs=[
                source_list_c, dest_list_c, source_manual_c, dest_manual_c,
                limit_c, delay_c, files_only_c, text_only_c, newest_first_c,
            ],
            outputs=[copy_status, copy_progress, copy_stats],
        )
        cancel_copy_btn.click(do_copy_cancel, outputs=[copy_status])

        # Forward
        start_fwd_btn.click(
            do_forward,
            inputs=[
                source_list_c, dest_list_c, source_manual_c, dest_manual_c,
                limit_f, delay_f, start_id_f, end_id_f,
                media_only_f, text_only_f, include_forwards_f,
                filter_text_f, send_caption_f, reverse_f,
            ],
            outputs=[fwd_status, fwd_progress, fwd_stats],
        )
        cancel_fwd_btn.click(do_forward_cancel, outputs=[fwd_status])

        # Extract
        start_ext_btn.click(
            do_extract,
            inputs=[
                channel_list_e, channel_manual_e, output_dir_e,
                texts_only_e, no_media_e, limit_e, delay_e,
            ],
            outputs=[ext_status, ext_stats],
        )

    return app


# ─── Launch ─────────────────────────────────────────────────

app = build_app()

if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        show_error=True,
    )
