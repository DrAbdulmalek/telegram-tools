#!/usr/bin/env python3
"""
Training script for medical translation models (EN ↔ AR).

Uses ``MedicalBilingualDataset`` to feed a HuggingFace Seq2Seq model
(NLLB / mBART / MarianMT) and reports SacreBLEU on the validation set.

Prerequisites
-------------
    pip install torch transformers evaluate sacrebleu accelerate

Usage
-----
    # Default: NLLB-200 distilled, 5 epochs, GPU if available
    python training/train_translation.py

    # Custom model / hyperparameters
    python training/train_translation.py \\
        --model facebook/mbart-large-50 \\
        --epochs 10 --batch-size 8 --lr 3e-5

    # Override data paths
    python training/train_translation.py \\
        --data-dir ~/omni_telegram_output/ml_splits \\
        --output-dir ~/models/my-medical-translator
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
        AutoModelForSeq2SeqLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Seq2SeqTrainingArguments,
        Seq2SeqTrainer,
    )
    import evaluate  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"Missing dependency: {exc.name}")
    print("Install with: pip install torch transformers evaluate sacrebleu accelerate")
    sys.exit(1)

from src.telegram_tools.pipeline.pytorch_dataset import MedicalBilingualDataset  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_translation")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train a medical translation model on bilingual TSV splits.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model", type=str, default="facebook/nllb-200-distilled-600M",
                   help="HuggingFace Seq2Seq model ID")
    p.add_argument("--data-dir", type=str,
                   default=str(Path.home() / "omni_telegram_output" / "ml_splits"),
                   help="Directory containing train.tsv / val.tsv")
    p.add_argument("--output-dir", type=str,
                   default=str(Path.home() / "omni_telegram_output" / "medical_translation_model"),
                   help="Where to save the trained model")
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--max-length", type=int, default=128)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--save-total-limit", type=int, default=3)
    p.add_argument("--push-to-hub", action="store_true",
                   help="Push final model to HuggingFace Hub (requires HF_TOKEN)")
    p.add_argument("--hub-repo-id", type=str,
                   help="Repo ID for push_to_hub (e.g. 'username/medical-translator-v1')")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    train_tsv = data_dir / "train.tsv"
    val_tsv = data_dir / "val.tsv"

    if not train_tsv.exists():
        logger.error("Training TSV not found: %s", train_tsv)
        sys.exit(1)
    if not val_tsv.exists():
        logger.error("Validation TSV not found: %s", val_tsv)
        sys.exit(1)

    logger.info("Loading tokenizer and model: %s", args.model)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model)

    logger.info("Building datasets...")
    train_dataset = MedicalBilingualDataset(
        tsv_path=train_tsv,
        tokenizer_name=args.model,
        max_length=args.max_length,
    )
    val_dataset = MedicalBilingualDataset(
        tsv_path=val_tsv,
        tokenizer_name=args.model,
        max_length=args.max_length,
    )
    logger.info("Train: %d samples | Val: %d samples",
                len(train_dataset), len(val_dataset))

    # SacreBLEU metric — better than vanilla BLEU for Arabic.
    bleu_metric = evaluate.load("sacrebleu")

    def compute_metrics(eval_pred):
        predictions, labels = eval_pred
        if isinstance(predictions, tuple):
            predictions = predictions[0]
        # Replace -100 in labels with pad_token_id for decoding.
        labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
        decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
        decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
        # SacreBLEU expects references as list of lists.
        result = bleu_metric.compute(
            predictions=decoded_preds,
            references=[[ref] for ref in decoded_labels],
        )
        return {"sacrebleu": result["score"]}

    # Training arguments.
    training_args = Seq2SeqTrainingArguments(
        output_dir=args.output_dir,
        evaluation_strategy="epoch",
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        weight_decay=args.weight_decay,
        save_total_limit=args.save_total_limit,
        num_train_epochs=args.epochs,
        predict_with_generate=True,
        fp16=torch.cuda.is_available(),
        push_to_hub=args.push_to_hub,
        hub_model_id=args.hub_repo_id if args.push_to_hub else None,
        logging_steps=50,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="sacrebleu",
        greater_is_better=True,
        report_to="none",
    )

    data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )

    logger.info("🚀 Starting training...")
    trainer.train()

    logger.info("✅ Training complete. Saving final model to %s", args.output_dir)
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    if args.push_to_hub and args.hub_repo_id:
        logger.info("Pushing model to HuggingFace Hub: %s", args.hub_repo_id)
        trainer.push_to_hub()

    logger.info("🎉 Done.")


if __name__ == "__main__":
    main()
