#!/usr/bin/env python3
"""Fine-tune Qwen2.5-14B with QLoRA for PP1 copilot.

Usage:
    pip install transformers peft trl datasets bitsandbytes accelerate
    python scripts/finetune_copilot.py [--model MODEL] [--epochs N] [--output DIR]

Workflow:
    1. Load training JSONL (data/training/dados_treino.jsonl)
    2. Apply QLoRA (4-bit quantization) to Qwen2.5-14B-Instruct
    3. Train with SFT (supervised fine-tuning) first
    4. Optionally apply GRPO with reward function from copilot.reward
    5. Save LoRA adapter → convert to GGUF → deploy via Ollama
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Paths
ROOT = Path(__file__).resolve().parent.parent
TRAIN_PATH = ROOT / "data" / "training" / "dados_treino.jsonl"
EVAL_PATH = ROOT / "data" / "training" / "dados_eval.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "data" / "training" / "system_prompt.txt"
DEFAULT_OUTPUT = ROOT / "models" / "pp1-copilot-qlora"

# QLoRA defaults
DEFAULT_MODEL = "Qwen/Qwen2.5-14B-Instruct"
LORA_R = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file into list of dicts."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def format_chat(record: dict, system_prompt: str) -> dict:
    """Convert training record to chat format for SFT.

    Expected input format:
        {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
    or:
        {"prompt": "...", "completion": "..."}
    """
    if "messages" in record:
        messages = [{"role": "system", "content": system_prompt}] + record["messages"]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": record.get("prompt", "")},
            {"role": "assistant", "content": record.get("completion", "")},
        ]
    return {"messages": messages}


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Qwen2.5 for PP1 copilot")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Base model ID")
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Per-device batch size")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument("--max-seq-length", type=int, default=4096, help="Max sequence length")
    parser.add_argument("--dry-run", action="store_true", help="Load data only, skip training")
    args = parser.parse_args()

    # ── 1. Validate data ──
    if not TRAIN_PATH.exists():
        logger.error("Training data not found: %s", TRAIN_PATH)
        sys.exit(1)

    train_records = load_jsonl(TRAIN_PATH)
    eval_records = load_jsonl(EVAL_PATH) if EVAL_PATH.exists() else []
    system_prompt = (
        SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if SYSTEM_PROMPT_PATH.exists()
        else ""
    )

    logger.info("Training examples: %d, Eval examples: %d", len(train_records), len(eval_records))
    logger.info("System prompt: %d chars", len(system_prompt))

    if args.dry_run:
        logger.info("Dry run — data loaded OK. Exiting.")
        for r in train_records[:3]:
            formatted = format_chat(r, system_prompt)
            logger.info(
                "Sample: %s", json.dumps(formatted["messages"][:2], ensure_ascii=False)[:200]
            )
        return

    # ── 2. Import training dependencies ──
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments,
        )
        from trl import SFTTrainer
    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        logger.error(
            "Install: pip install transformers peft trl datasets bitsandbytes accelerate torch"
        )
        sys.exit(1)

    # ── 3. Load model with QLoRA ──
    logger.info("Loading model: %s (4-bit QLoRA)", args.model)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=LORA_TARGET_MODULES,
        task_type=TaskType.CAUSAL_LM,
        bias="none",
    )

    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    logger.info("Trainable params: %d / %d (%.2f%%)", trainable, total, 100 * trainable / total)

    # ── 4. Prepare datasets ──
    train_data = [format_chat(r, system_prompt) for r in train_records]
    eval_data = [format_chat(r, system_prompt) for r in eval_records] if eval_records else None

    train_dataset = Dataset.from_list(train_data)
    eval_dataset = Dataset.from_list(eval_data) if eval_data else None

    # ── 5. Training ──
    args.output.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=4,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset else "no",
        bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        save_total_limit=2,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        args=training_args,
        max_seq_length=args.max_seq_length,
    )

    logger.info("Starting SFT training...")
    trainer.train()

    # ── 6. Save adapter ──
    adapter_path = args.output / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    logger.info("LoRA adapter saved to %s", adapter_path)

    # ── 7. Create Ollama Modelfile ──
    modelfile_path = args.output / "Modelfile"
    modelfile_path.write_text(
        f"""FROM {args.model}
ADAPTER {adapter_path}
SYSTEM \"\"\"{system_prompt}\"\"\"

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_ctx {args.max_seq_length}
""",
        encoding="utf-8",
    )
    logger.info("Ollama Modelfile written to %s", modelfile_path)
    logger.info("To deploy: ollama create pp1-copilot -f %s", modelfile_path)
    logger.info("Done!")


if __name__ == "__main__":
    main()
