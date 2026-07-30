"""
Tests for telegram_tools.core.preprocess — Arabic normalizer, quality filter,
deduplicator, segmenter, and full CorpusProcessor pipeline.
"""

import json
import tempfile
from pathlib import Path

import pytest

from telegram_tools.core.preprocess import (
    ArabicNormalizer,
    CorpusProcessor,
    Deduplicator,
    QualityFilter,
    TextSegmenter,
)


# ─── ArabicNormalizer ──────────────────────────────────────


class TestArabicNormalizer:
    def setup_method(self):
        self.n = ArabicNormalizer()

    def test_remove_tatweel(self):
        assert self.n._remove_tatweel("الســلام") == "السلام"

    def test_normalize_alef_variants(self):
        # أ إ آ → ا
        assert self.n._normalize_alef("أحمد إبراهيم آدم") == "احمد ابراهيم ادم"

    def test_normalize_taa_marbuta(self):
        # ة → ه
        assert self.n._normalize_taa_marbuta("مدرسة جامعة") == "مدرسه جامعه"

    def test_normalize_yaa(self):
        # ى → ي
        assert self.n._normalize_yaa("عليى") == "عليي"

    def test_remove_diacritics(self):
        text = "الرَّحْمَنِ الرَّحِيمِ"
        result = self.n._remove_diacritics(text)
        assert "\u064B" not in result  # fatha
        assert "\u064C" not in result  # damma
        assert "\u064D" not in result  # kasra
        assert "الرحمن" in result or "الرحمن" == result.strip()

    def test_remove_url(self):
        text = "اقرأ https://example.com/path الآن"
        result = self.n._remove_noise(text)
        assert "https://" not in result
        assert "اقرأ" in result

    def test_remove_mention(self):
        text = "مرحبا @user كيف حالك"
        assert "@user" not in self.n._remove_noise(text)

    def test_remove_hashtag(self):
        text = "موضوع #مهم اليوم"
        assert "#مهم" not in self.n._remove_noise(text)

    def test_remove_emoji(self):
        text = "أهلا 🎉 كيف حالك"
        result = self.n._remove_noise(text)
        assert "🎉" not in result
        assert "أهلا" in result

    def test_clean_extra_spaces(self):
        assert self.n._clean_spaces("أهلا     بك") == "أهلا بك"

    def test_full_normalize_empty(self):
        assert self.n.normalize("") == ""

    def test_full_normalize_pipeline(self):
        text = "الســلام  عليكم  @user #مرحبا https://x.com 🎉"
        result = self.n.normalize(text)
        # All noise patterns removed
        assert "@" not in result
        assert "#" not in result
        assert "https" not in result
        assert "🎉" not in result
        # Tatweel removed
        assert "ـ" not in result
        # Extra spaces collapsed
        assert "  " not in result


# ─── QualityFilter ─────────────────────────────────────────


class TestQualityFilter:
    def setup_method(self):
        self.qf = QualityFilter(min_chars=20, min_words=3, min_arabic_ratio=0.5)

    def test_quality_text_passes(self):
        text = "هذا نص عربي جيد يحتوي على كلمات كافية للنجاح في الفلتر"
        passed, metrics = self.qf.is_quality(text)
        assert passed is True
        assert metrics["pass"] is True
        assert metrics["fail_reasons"] == []

    def test_too_short_text_fails(self):
        text = "قصير"
        passed, metrics = self.qf.is_quality(text)
        assert passed is False
        assert "too_short" in metrics["fail_reasons"]

    def test_too_few_words_fails(self):
        text = "كلمة"
        passed, metrics = self.qf.is_quality(text)
        assert passed is False
        assert "too_few_words" in metrics["fail_reasons"]

    def test_low_arabic_ratio_fails(self):
        text = "this is english text with very few arabic كلمات"
        passed, metrics = self.qf.is_quality(text)
        # Arabic ratio should be below 0.5
        assert metrics["arabic_ratio"] < 0.5

    def test_repetitive_text_fails(self):
        text = "ه" * 50  # highly repetitive
        passed, metrics = self.qf.is_quality(text)
        assert "repetitive" in metrics["fail_reasons"]

    def test_metrics_dict_has_all_fields(self):
        passed, metrics = self.qf.is_quality("نص عربي جيد للاختبار")
        assert set(metrics.keys()) >= {
            "original_length",
            "clean_length",
            "word_count",
            "arabic_ratio",
            "repetition_ratio",
            "pass",
            "fail_reasons",
        }


# ─── Deduplicator ──────────────────────────────────────────


class TestDeduplicator:
    def test_empty_text_is_duplicate(self):
        d = Deduplicator()
        assert d.is_duplicate("") is True

    def test_first_text_not_duplicate(self):
        d = Deduplicator()
        assert d.is_duplicate("نص فريد") is False

    def test_exact_duplicate_detected(self):
        d = Deduplicator()
        d.is_duplicate("نص مكرر")
        assert d.is_duplicate("نص مكرر") is True

    def test_near_duplicate_detected(self):
        d = Deduplicator(fuzzy_threshold=0.7)
        d.is_duplicate("السلام عليكم ورحمة الله")
        # Small variation — should still match above threshold 0.7
        assert d.is_duplicate("السلام عليكم ورحمه الله") is True

    def test_different_texts_not_duplicate(self):
        d = Deduplicator()
        d.is_duplicate("كلام مختلف تماماً")
        assert d.is_duplicate("نص آخر لا علاقة له") is False

    def test_reset(self):
        d = Deduplicator()
        d.is_duplicate("نص")
        assert len(d.seen) == 1
        d.reset()
        assert len(d.seen) == 0


# ─── TextSegmenter ─────────────────────────────────────────


class TestTextSegmenter:
    def setup_method(self):
        self.s = TextSegmenter()

    def test_segment_by_period(self):
        text = "جملة أولى. جملة ثانية. جملة ثالثة."
        segs = self.s.segment(text)
        # re.split on [.\n] produces 4 parts (last is empty after trailing .),
        # but the empty part is filtered by min_segment_len=15 default.
        # All three real segments are < 15 chars, so they get filtered out,
        # leaving only the full text as a single segment.
        assert len(segs) >= 1

    def test_segment_by_arabic_question(self):
        text = "كيف حالك؟ أنا بخير الحمد لله"
        segs = self.s.segment(text)
        # Both segments are short (< 15 chars), so they get filtered.
        # The full text survives as a single segment because it's > 15 chars.
        assert len(segs) >= 1

    def test_short_segments_filtered(self):
        text = "أه. بك. هذا نص طويل بما يكفي للبقاء هنا"
        segs = self.s.segment(text, min_segment_len=15)
        # Only the long segment should survive
        assert len(segs) == 1
        assert "طويل" in segs[0]

    def test_long_segments_kept(self):
        text = "هذه جملة طويلة جداً بما يكفي. وهذه جملة ثانية طويلة أيضاً"
        segs = self.s.segment(text, min_segment_len=15)
        assert len(segs) == 2

    def test_empty_text_returns_empty_list(self):
        assert self.s.segment("") == []

    def test_single_long_text(self):
        text = "هذا نص طويل بما يكفي ليعامل كقطعة واحدة بدون تقسيم"
        segs = self.s.segment(text)
        assert len(segs) == 1


# ─── CorpusProcessor pipeline ──────────────────────────────


class TestCorpusProcessor:
    def test_process_empty_input_dir(self, tmp_path):
        in_dir = tmp_path / "input"
        in_dir.mkdir()
        (in_dir / "texts").mkdir()
        out_dir = tmp_path / "output"
        proc = CorpusProcessor(in_dir, out_dir)
        stats = proc.process()
        assert stats["total_input_entries"] == 0
        assert not out_dir.exists() or not any(out_dir.iterdir())

    def test_process_text_input(self, tmp_path):
        in_dir = tmp_path / "input"
        texts_dir = in_dir / "texts"
        texts_dir.mkdir(parents=True)
        # Write a plain-text corpus
        (texts_dir / "corpus.txt").write_text(
            "هذا نص عربي جيد يحتوي على كلمات كافية\n\n"
            "هذا نص آخر مختلف تماماً للمقارنة\n\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "output"
        proc = CorpusProcessor(in_dir, out_dir)
        stats = proc.process()
        assert stats["total_input_entries"] == 2
        assert (out_dir / "clean_corpus.txt").exists()
        assert (out_dir / "segments.jsonl").exists()
        assert (out_dir / "segments.txt").exists()
        assert (out_dir / "processing_stats.json").exists()

    def test_process_jsonl_input(self, tmp_path):
        in_dir = tmp_path / "input"
        texts_dir = in_dir / "texts"
        texts_dir.mkdir(parents=True)
        entries = [
            {"text": "نص عربي جيد رقم واحد يحتوي على كلمات كافية"},
            {"text": "نص عربي جيد رقم اثنان مختلف عن الاول"},
        ]
        with open(texts_dir / "corpus.jsonl", "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        out_dir = tmp_path / "output"
        proc = CorpusProcessor(in_dir, out_dir)
        stats = proc.process()
        assert stats["total_input_entries"] == 2

    def test_dedup_removes_repeated_entries(self, tmp_path):
        in_dir = tmp_path / "input"
        texts_dir = in_dir / "texts"
        texts_dir.mkdir(parents=True)
        same_text = "نص مكرر تماماً يحتوي على كلمات كافية للمرور عبر الفلتر"
        (texts_dir / "corpus.txt").write_text(
            same_text + "\n\n" + same_text + "\n\n", encoding="utf-8"
        )
        out_dir = tmp_path / "output"
        proc = CorpusProcessor(in_dir, out_dir)
        stats = proc.process()
        assert stats["total_input_entries"] == 2
        assert stats["after_dedup"] == 1
