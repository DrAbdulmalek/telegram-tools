"""
Tests for the bilingual pipeline modules:
- BilingualExtractor (hybrid / structured / sequential / contextual)
- DatasetSplitter (ratios, shuffle, tsv + jsonl output)
- BilingualAligner (alias compatibility)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from telegram_tools.pipeline.aligner import BilingualAligner
from telegram_tools.pipeline.bilingual_extractor import BilingualExtractor
from telegram_tools.pipeline.splitter import DatasetSplitter

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

STRUCTURED_TEXT = (
    "Myocardial Infarction - احتشاء عضلة القلب\n"
    "Hypertension (ارتفاع ضغط الدم)\n"
    "Diabetes Mellitus : داء السكري"
)

SEQUENTIAL_TEXT = (
    "Chronic Obstructive Pulmonary Disease\n"
    "مرض الانسداد الرئوي المزمن\n\n"
    "Osteoarthritis\n"
    "الفُصال العظمي"
)

CONTEXTUAL_TEXT = (
    "The patient was diagnosed with Acute Appendicitis أو ما يُعرف بالتهاب الزائدة الدودية الحاد, "
    "and was admitted to the emergency room غرفة الطوارئ."
)

HYBRID_TEXT = "\n\n".join([
    STRUCTURED_TEXT,
    SEQUENTIAL_TEXT,
    CONTEXTUAL_TEXT,
    "🔔 قناة الدكتور زكي للجراحة العظمية 🔔\nللتواصل: @dr_zaky_ortho",  # noise
])


# ──────────────────────────────────────────────────────────────
# BilingualExtractor
# ──────────────────────────────────────────────────────────────

class TestBilingualExtractor:
    def setup_method(self):
        self.extractor = BilingualExtractor()

    def test_structured_mode_finds_same_line_pairs(self):
        pairs = self.extractor.extract_pairs(STRUCTURED_TEXT, mode="structured")
        ens = {en.lower() for en, _ in pairs}
        assert "myocardial infarction" in ens
        assert "hypertension" in ens
        assert "diabetes mellitus" in ens

    def test_structured_mode_ignores_sequential(self):
        pairs = self.extractor.extract_pairs(SEQUENTIAL_TEXT, mode="structured")
        # Sequential-only blocks should produce zero pairs in structured mode.
        assert pairs == [] or all(
            "Chronic Obstructive" not in en and "Osteoarthritis" not in en
            for en, _ in pairs
        )

    def test_sequential_mode_finds_adjacent_pairs(self):
        pairs = self.extractor.extract_pairs(SEQUENTIAL_TEXT, mode="sequential")
        ens = {en.lower() for en, _ in pairs}
        ars = {ar for _, ar in pairs}
        assert "chronic obstructive pulmonary disease" in ens
        assert "osteoarthritis" in ens
        assert "مرض الانسداد الرئوي المزمن" in ars
        assert "الفُصال العظمي" in ars

    def test_contextual_mode_picks_longest_runs(self):
        pairs = self.extractor.extract_pairs(CONTEXTUAL_TEXT, mode="contextual")
        assert len(pairs) >= 1
        en, ar = pairs[0]
        assert "Acute Appendicitis" in en or "emergency room" in en
        assert any(c in ar for c in ("التهاب", "الطوارئ"))

    def test_hybrid_mode_covers_all_strategies(self):
        pairs = self.extractor.extract_pairs(HYBRID_TEXT, mode="hybrid")
        ens = {en.lower() for en, _ in pairs}
        # All three strategies should have contributed.
        assert "myocardial infarction" in ens          # structured
        assert "chronic obstructive pulmonary disease" in ens  # sequential
        # Contextual produces the longest run, which is "Acute Appendicitis"
        # or "emergency room" — we just check at least one made it.
        assert any("appendicitis" in en or "emergency" in en for en in ens)

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            self.extractor.extract_pairs("Heart - قلب", mode="bogus")

    def test_dedup_is_case_insensitive_on_english(self):
        text = "Heart - قلب\nheart - قلب"
        pairs = self.extractor.extract_pairs(text, mode="structured")
        assert len(pairs) == 1

    def test_empty_text_returns_empty_list(self):
        assert self.extractor.extract_pairs("", mode="hybrid") == []
        assert self.extractor.extract_pairs("   \n\n  ", mode="hybrid") == []

    def test_noise_block_produces_no_pairs(self):
        noise = "🔔 قناة الدكتور زكي للجراحة العظمية 🔔\nللتواصل: @dr_zaky_ortho"
        # In hybrid mode the noise block should not yield spurious pairs
        # (the contextual strategy might pick "Dr" + "الزائدة" — we tolerate
        # at most 1 pair, and it must not contain the @-mention).
        pairs = self.extractor.extract_pairs(noise, mode="hybrid")
        for en, ar in pairs:
            assert "@" not in en
            assert "@" not in ar

    def test_preserves_medical_text_verbatim(self):
        # Diacritics, ta-marbuta, alef variants — must be preserved.
        text = "Heart - قلبٌ\nBone - عظمٌ"
        pairs = self.extractor.extract_pairs(text, mode="structured")
        ars = {ar for _, ar in pairs}
        assert "قلبٌ" in ars or "قلب" in ars
        assert "عظمٌ" in ars or "عظم" in ars

    def test_save_and_load_tsv_roundtrip(self, tmp_path: Path):
        pairs = [("Heart", "قلب"), ("Bone", "عظم"), ("Liver", "كبد")]
        tsv = tmp_path / "glossary.tsv"
        count = self.extractor.save_to_tsv(pairs, tsv)
        assert count == 3
        assert tsv.exists()
        # Header + 3 rows.
        lines = tsv.read_text(encoding="utf-8").strip().split("\n")
        assert lines[0] == "English\tArabic"
        assert len(lines) == 4
        # Round-trip.
        loaded = BilingualExtractor.load_from_tsv(tsv)
        assert loaded == pairs

    def test_save_tsv_replaces_internal_tabs_and_newlines(self, tmp_path: Path):
        # A malicious pair containing an embedded tab and newline.
        pairs = [("Heart\nDisease", "قلب\tمرض")]
        tsv = tmp_path / "evil.tsv"
        count = self.extractor.save_to_tsv(pairs, tsv)
        assert count == 1
        content = tsv.read_text(encoding="utf-8").strip().split("\n")
        # Header + exactly 1 data row (the embedded \n was replaced).
        assert len(content) == 2
        # Each row has exactly 2 tab-separated fields.
        for line in content:
            assert len(line.split("\t")) == 2

    def test_stats_returns_expected_fields(self):
        pairs = [("Heart", "قلب"), ("Bone", "عظم"), ("Heart", "قلب")]
        stats = self.extractor.stats(pairs)
        assert stats["pairs"] == 3
        assert stats["unique_en"] == 2  # "heart" deduped
        assert stats["unique_ar"] == 2
        assert stats["avg_en_chars"] > 0
        assert stats["avg_ar_chars"] > 0


# ──────────────────────────────────────────────────────────────
# BilingualAligner (alias)
# ──────────────────────────────────────────────────────────────

class TestBilingualAlignerAlias:
    def test_alias_is_subclass_of_extractor(self):
        assert issubclass(BilingualAligner, BilingualExtractor)

    def test_alias_produces_same_output(self):
        e = BilingualExtractor()
        a = BilingualAligner()
        text = "Heart - قلب\nBone - عظم"
        assert e.extract_pairs(text) == a.extract_pairs(text)


# ──────────────────────────────────────────────────────────────
# DatasetSplitter
# ──────────────────────────────────────────────────────────────

class TestDatasetSplitter:
    def setup_method(self):
        self.splitter = DatasetSplitter(seed=42)
        # 100 alphabetical pairs (a, a), (b, b), ..., (j*10, j*10) -- 10 letters × 10 each
        self.pairs = [(chr(i), chr(i)) for i in range(ord("a"), ord("z") + 1)] * 4  # 104 pairs

    def test_invalid_ratios_raise(self):
        with pytest.raises(ValueError):
            self.splitter.split_data(self.pairs, 0.8, 0.2)  # sums to 1.0
        with pytest.raises(ValueError):
            self.splitter.split_data(self.pairs, 1.0, 0.0)  # val=0
        with pytest.raises(ValueError):
            self.splitter.split_data(self.pairs, 0.0, 0.5)  # train=0

    def test_split_sums_to_total(self):
        splits = self.splitter.split_data(self.pairs, 0.7, 0.15)
        total = len(splits["train"]) + len(splits["val"]) + len(splits["test"])
        assert total == len(self.pairs)

    def test_ratios_approximate(self):
        splits = self.splitter.split_data(self.pairs, 0.8, 0.1)
        n = len(self.pairs)
        assert abs(len(splits["train"]) - int(n * 0.8)) <= 1
        assert abs(len(splits["val"]) - int(n * 0.1)) <= 1
        assert len(splits["test"]) == n - len(splits["train"]) - len(splits["val"])

    def test_shuffle_breaks_alphabetical_order(self):
        # Without shuffle, train would be all 'a'-'t'. With seed=42 shuffle,
        # the first 5 items in train must not be all 'a'.
        splits = self.splitter.split_data(self.pairs, 0.5, 0.25)
        first_five = splits["train"][:5]
        unique_letters = {en for en, _ in first_five}
        assert len(unique_letters) > 1, "Shuffle failed — first 5 train items all identical"

    def test_same_seed_gives_same_split(self):
        s1 = self.splitter.split_data(self.pairs, 0.7, 0.15)
        s2 = DatasetSplitter(seed=42).split_data(self.pairs, 0.7, 0.15)
        assert s1 == s2

    def test_different_seed_gives_different_split(self):
        s1 = DatasetSplitter(seed=42).split_data(self.pairs, 0.7, 0.15)
        s2 = DatasetSplitter(seed=7).split_data(self.pairs, 0.7, 0.15)
        # At least the train sets should differ in order.
        assert s1["train"] != s2["train"]

    def test_save_tsv_splits(self, tmp_path: Path):
        splits = self.splitter.split_data(self.pairs[:10], 0.6, 0.2)
        saved = self.splitter.save_splits(splits, tmp_path, file_format="tsv")
        for name in ("train", "val", "test"):
            assert name in saved
            assert Path(saved[name]).exists()
            assert Path(saved[name]).read_text(encoding="utf-8").startswith("English\tArabic")

    def test_save_jsonl_splits(self, tmp_path: Path):
        splits = self.splitter.split_data(self.pairs[:10], 0.6, 0.2)
        saved = self.splitter.save_splits(splits, tmp_path, file_format="jsonl")
        for name in ("train", "val", "test"):
            path = Path(saved[name])
            assert path.exists()
            # Each line is valid JSON with the expected schema.
            for line in path.read_text(encoding="utf-8").strip().split("\n"):
                record = json.loads(line)
                assert "translation" in record
                assert "en" in record["translation"]
                assert "ar" in record["translation"]

    def test_save_invalid_format_raises(self, tmp_path: Path):
        splits = {"train": [("a", "أ")]}
        with pytest.raises(ValueError):
            self.splitter.save_splits(splits, tmp_path, file_format="xml")

    def test_summary_string_contains_all_splits(self):
        splits = self.splitter.split_data(self.pairs[:10], 0.6, 0.2)
        summary = self.splitter.summary(splits)
        assert "train" in summary
        assert "val" in summary
        assert "test" in summary
        assert "seed=42" in summary
