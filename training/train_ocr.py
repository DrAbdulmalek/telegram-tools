#!/usr/bin/env python3
"""
Training script for medical OCR models (image → text).

Uses ``MedicalOCRDataset`` to fine-tune a Vision-Encoder-Decoder model
(Microsoft TrOCR family) on medical images paired with their captions.

Prerequisites
-------------
    pip install torch transformers evaluate Pillow accelerate

Usage
-----
    # Default: TrOCR base printed, 10 epochs
    python training/train_ocr.py

    # Handwritten prescriptions
    python training/train_ocr.py \\
        --model microsoft/trocr-base-handwritten \\
        --epochs 20

    # Custom paths
    python training/train_ocr.py \\
        --images-dir ~/omni_telegram_output/media/images \\
        --metadata ~/omni_telegram_output/metadata.jsonl \\
        --output-dir ~/models/my-medical-ocr
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

try:
    import torch  # noqa: E402
    from transformers import (  # noqa: E402
        AutoProcessor,
        Seq2SeqTrainingArguments,
        Seq2SeqTrainer,
        VisionEncoderDecoderModel,
    )
    import evaluate  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"Missing dependency: {exc.name}")
    print("Install with: pip install torch transformers evaluate Pillow accelerate")
    sys.exit(1)

from src.telegram_tools.pipeline.ocr_dataset import MedicalOCRDataset  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_ocr")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train a medical OCR model (image→text) with TrOCR.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model", type=str, default="microsoft/trocr-base-printed",
                   help="HuggingFace Vision-Encoder-Decoder model ID")
    p.add_argument("--images-dir", type=str,
                   default=str(Path.home() / "omni_telegram_output" / "media" / "images"),
                   help="Directory of training images")
    p.add_argument("--metadata", type=str,
                   default=str(Path.home() / "omni_telegram_output" / "metadata.jsonl"),
                   help="JSONL metadata file (from TelegramExtractor)")
    p.add_argument("--output-dir", type=str,
                   default=str(Path.home() / "omni_telegram_output" / "medical_ocr_model"),
                   help="Where to save the trained model")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--save-total-limit", type=int, default=3)
    p.add_argument("--val-split", type=float, default=0.15,
                   help="Fraction of samples to use as validation (0 to disable)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    images_dir = Path(args.images_dir)
    metadata_file = Path(args.metadata)
    if not images_dir.is_dir():
        logger.error("Images directory not found: %s", images_dir)
        sys.exit(1)
    if not metadata_file.is_file():
        logger.error("Metadata file not found: %s", metadata_file)
        sys.exit(1)

    logger.info("Loading processor and model: %s", args.model)
    processor = AutoProcessor.from_pretrained(args.model)
    model = VisionEncoderDecoderModel.from_pretrained(args.model)

    # TrOCR-specific config.
    model.config.decoder_start_token_id = processor.tokenizer.cls_token_id
    model.config.pad_token_id = processor.tokenizer.pad_token_id
    # Vocabulary parameters.
    model.config.vocab_size = model.config.encoder.vocab_size

    logger.info("Building dataset...")
    full_dataset = MedicalOCRDataset(
        images_dir=images_dir,
        metadata_file=metadata_file,
        processor_name=args.model,
        max_length=args.max_length,
    )
    if len(full_dataset) == 0:
        logger.error("Dataset is empty. Check images_dir and metadata file.")
        sys.exit(1)
    logger.info("Total samples: %d", len(full_dataset))

    # Optional train/val split.
    if args.val_split > 0:
        from torch.utils.data import random_split
        n_val = max(1, int(len(full_dataset) * args.val_split))
        n_train = len(full_dataset) - n_val
        train_dataset, val_dataset = random_split(
            full_dataset, [n_train, n_val],
            generator=torch.Generator().manual_seed(42),
        )
        logger.info("Train: %d | Val: %d", n_train, n_val)
    else:
        train_dataset = full_dataset
        val_dataset = full_dataset

    # CER (Character Error Rate) — the standard OCR metric.
    cer_metric = evaluate.load("cer")

    def compute_metrics(pred):
        labels_ids = pred.label_ids
        pred_ids = pred.predictions
        if isinstance(pred_ids, tuple):
            pred_ids = pred_ids[0]
        pred_str = processor.tokenizer.batch_decode(pred_ids, skip_special_tokens=True)
        labels_ids[labels_ids == -100] = processor.tokenizer.pad_token_id
        label_str = processor.tokenizer.batch_decode(labels_ids, skip_special_tokens=True)
        cer = cer_metric.compute(predictions=pred_str, references=label_str)
        return {"cer": float(cer)}

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        predict_with_generate=True,
        evaluation_strategy="epoch" if val_dataset is not None else "no",
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        save_total_limit=args.save_total_limit,
        remove_unused_columns=False,
        fp16=torch.cuda.is_available(),
        load_best_model_at_end=val_dataset is not None,
        metric_for_best_model="cer",
        greater_is_better=False,
        save_strategy="epoch",
        logging_steps=20,
        report_to="none",
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        compute_metrics=compute_metrics,
        train_dataset=train_dataset,
        eval_dataset=val_dataset if val_dataset is not None else None,
        tokenizer=processor.feature_extractor,
    )

    logger.info("🏋️ Starting OCR training...")
    trainer.train()

    logger.info("✅ Training complete. Saving model to %s", args.output_dir)
    trainer.save_model(args.output_dir)
    processor.save_pretrained(args.output_dir)

    logger.info("🎉 Done.")


if __name__ == "__main__":
    main()
