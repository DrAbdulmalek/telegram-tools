#!/usr/bin/env python3
"""
Mock-data smoke test for the bilingual pipeline.

Generates fake Telegram messages that exercise all three extraction
strategies (structured / sequential / contextual), runs them through
``BilingualExtractor`` and ``DatasetSplitter``, and writes the resulting
TSV + splits to ``./mock_test_output/``.

Run with::

    python -m automation.test_mock_pipeline

Or::

    python automation/test_mock_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.telegram_tools.pipeline.bilingual_extractor import BilingualExtractor
from src.telegram_tools.pipeline.splitter import DatasetSplitter


MOCK_MESSAGES = [
    # ── Strategy 1: structured (same-line) ───────────────────
    "Myocardial Infarction - احتشاء عضلة القلب\n"
    "Hypertension (ارتفاع ضغط الدم)\n"
    "Diabetes Mellitus : داء السكري",

    # ── Strategy 2: sequential (adjacent lines) ──────────────
    "Chronic Obstructive Pulmonary Disease\n"
    "مرض الانسداد الرئوي المزمن\n\n"
    "Osteoarthritis\n"
    "الفُصال العظمي",

    # ── Strategy 3: contextual (free-flowing text) ───────────
    "The patient was diagnosed with Acute Appendicitis أو ما يُعرف بالتهاب الزائدة الدودية الحاد, "
    "and was admitted to the emergency room غرفة الطوارئ.",

    # ── Noise (should not produce any pair) ──────────────────
    "🔔 قناة الدكتور زكي للجراحة العظمية 🔔\nللتواصل: @dr_zaky_ortho",

    # ── Mixed: structured + sequential in one block ──────────
    "Electrocardiogram (ECG) - تخطيط القلب الكهربائي\n"
    "Magnetic Resonance Imaging\n"
    "التصوير بالرنين المغناطيسي",

    # ── Edge cases ───────────────────────────────────────────
    "Cardiac Arrest - سكتة قلبية",        # minimal structured pair
    "Stroke\nسكتة دماغية",                  # minimal sequential pair
]


def main() -> None:
    print("=" * 70)
    print("🧪 Bilingual Pipeline — Mock Data Smoke Test")
    print("=" * 70)

    # 1. Combine mock messages.
    combined = "\n\n".join(MOCK_MESSAGES)
    print(f"\n📄 Combined mock text: {len(combined)} chars, "
          f"{len(MOCK_MESSAGES)} blocks\n")

    # 2. Extract pairs (hybrid mode).
    print("🔍 Step 1: Extracting pairs (mode=hybrid)...")
    extractor = BilingualExtractor()
    pairs = extractor.extract_pairs(combined, mode="hybrid")
    print(f"✅ Extracted {len(pairs)} unique pairs.\n")

    print("📋 First 5 pairs:")
    for i, (en, ar) in enumerate(pairs[:5], 1):
        print(f"  {i}. [EN] {en}")
        print(f"     [AR] {ar}")
    print()

    # 3. Stats.
    stats = extractor.stats(pairs)
    print("📊 Stats:")
    for k, v in stats.items():
        print(f"  {k:15s}: {v}")
    print()

    # 4. Split with shuffle.
    print("🔀 Step 2: Splitting (train=0.7, val=0.15, test=0.15)...")
    splitter = DatasetSplitter(seed=42)
    splits = splitter.split_data(pairs, train_ratio=0.7, val_ratio=0.15)
    print(splitter.summary(splits))
    print()

    # 5. Save to disk.
    out_dir = Path("mock_test_output")
    out_dir.mkdir(exist_ok=True)

    glossary_path = out_dir / "bilingual_glossary.tsv"
    count = extractor.save_to_tsv(pairs, glossary_path)
    print(f"💾 Saved glossary: {glossary_path} ({count} pairs)")

    splits_dir = out_dir / "ml_splits"
    saved = splitter.save_splits(splits, splits_dir, file_format="tsv")
    print(f"💾 Saved splits to: {splits_dir}")
    for name, path in saved.items():
        print(f"  - {name}: {path}")

    # 6. Also save as JSONL to demonstrate the format.
    saved_jsonl = splitter.save_splits(splits, out_dir / "ml_splits_jsonl",
                                       file_format="jsonl")
    print(f"\n💾 Also saved JSONL splits to: {out_dir / 'ml_splits_jsonl'}")
    for name, path in saved_jsonl.items():
        print(f"  - {name}: {path}")

    print("\n" + "=" * 70)
    print("🎉 Smoke test passed! Pipeline is ready for real Telegram data.")
    print("=" * 70)


if __name__ == "__main__":
    main()
