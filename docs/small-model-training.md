# Training a Small Model for C++ Semantics Validation

This document describes how to train a specialized small model that can validate claims about C++ behavior against the axiom knowledge base. The model runs locally on consumer hardware (including M2 Macs) and provides smarter filtering than pure embedding similarity.

## Table of Contents

1. [Background: What Problem Are We Solving?](#background-what-problem-are-we-solving)
2. [What the Model Would Do](#what-the-model-would-do)
3. [Current System Overview](#current-system-overview)
4. [How the Model Fits In](#how-the-model-fits-in)
5. [Architecture Options](#architecture-options)
6. [Data Generation](#data-generation)
7. [Training Process](#training-process)
8. [Hardware Requirements](#hardware-requirements)
9. [Step-by-Step Implementation](#step-by-step-implementation)
10. [Evaluation](#evaluation)
11. [Integration](#integration)

---

## Background: What Problem Are We Solving?

### The Current Approach: Embeddings

The axiom database currently uses **embeddings** for search. An embedding is a list of numbers (typically 1536 numbers) that represents the "meaning" of a piece of text. Think of it like a fingerprint for meaning.

When you search for "is signed overflow undefined behavior?", the system:
1. Converts your query into a fingerprint (list of 1536 numbers)
2. Compares this fingerprint to every axiom's fingerprint
3. Returns axioms with the most similar fingerprints

**The problem**: Fingerprint matching finds "related" things, not necessarily "correct" things.

Example failure modes:
- Query: "signed overflow wraps around"
- Returns: axiom about signed overflow being undefined
- Issue: These are related topics, but the claim **contradicts** the axiom

The fingerprints are similar because both texts mention "signed overflow", but the system can't tell that one says "wraps" and the other says "undefined" - opposite meanings.

### The Solution: A Second Opinion

Add a small model that looks at the query and each candidate axiom, then makes a judgment:
- **VALID**: The claim matches/follows from the axiom
- **INVALID**: The claim contradicts the axiom
- **UNRELATED**: Different topics entirely

This model is slower than fingerprint matching, so we use it as a **filter** after the fast fingerprint search returns candidates.

---

## What the Model Would Do

### Primary Tasks

| Task | Input | Output | Example |
|------|-------|--------|---------|
| **Claim Validation** | claim + axiom | valid / invalid / unrelated | "overflow wraps" + [UB axiom] → invalid |
| **Entailment** | axiom A + axiom B | A implies B? | Does lifetime axiom imply destructor axiom? |
| **Relevance Scoring** | query + axiom | 0.0 - 1.0 score | How relevant is this axiom to the query? |

### Example Flow

```
User query: "Does signed integer overflow wrap around in C?"

Step 1: Embedding search (fast, ~1ms)
        → Returns 10 candidate axioms about overflow, integers, etc.

Step 2: Model filtering (slower, ~50ms per candidate)
        → Axiom 1: "signed overflow is undefined"
          Model says: CONTRADICTS (confidence: 0.94)
        → Axiom 2: "unsigned overflow wraps"
          Model says: RELATED but different type (confidence: 0.72)
        → Axiom 3: "integer promotion rules"
          Model says: UNRELATED (confidence: 0.89)

Step 3: Return to user
        → "Your claim is INVALID. Signed overflow is undefined behavior
           in C (C11 §6.5/5). You may be thinking of unsigned integers,
           which do wrap."
```

---

## Current System Overview

### What Exists Today

| Component | Count | Purpose |
|-----------|-------|---------|
| Axioms | 4,523 | Formal statements about C/C++ behavior |
| Vector Embeddings | 6,272 | Fingerprints for semantic search |
| Modules | 1,386 | Organizational groupings |
| Error Codes | 248 | Compiler error documentation |

### Axiom Structure

Each axiom contains:
```
{
  "id": "c11_expr_overflow_undefined_xyz",
  "content": "Signed integer overflow is undefined behavior",
  "formal_spec": "overflow(signed_int, op) => undefined_behavior",
  "module": "[expr]/5",
  "layer": "c11_core",
  "depends_on": ["c11_basic_types_signed", ...]
}
```

### Current Search Flow

```
Query → Embed → Vector similarity → Top K axioms → Return
         ↓
   1536-dim vector
```

The model would add:
```
Query → Embed → Vector similarity → Top K axioms → MODEL FILTER → Return
                                                        ↓
                                              valid/invalid/unrelated
```

---

## How the Model Fits In

### Before (Current)

```
┌─────────────────────────────────────────────────┐
│  User Query                                     │
│  "Is dividing by zero undefined in C?"          │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Embedding Model (already exists)               │
│  Convert query to 1536 numbers                  │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Vector Database                                │
│  Find similar axiom embeddings                  │
│  Returns: 10 candidates                         │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Return Results                                 │
│  May include unrelated or contradictory axioms  │
└─────────────────────────────────────────────────┘
```

### After (With Small Model)

```
┌─────────────────────────────────────────────────┐
│  User Query                                     │
│  "Is dividing by zero undefined in C?"          │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Embedding Model (already exists)               │
│  Convert query to 1536 numbers                  │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Vector Database                                │
│  Find similar axiom embeddings                  │
│  Returns: 10 candidates                         │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  ★ NEW: Small Validation Model ★                │
│  For each candidate:                            │
│    - Is claim valid given this axiom?           │
│    - Confidence score                           │
│  Filter out contradictions and unrelateds       │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Return Results                                 │
│  Only validated, relevant axioms                │
│  With validity judgments                        │
└─────────────────────────────────────────────────┘
```

---

## Architecture Options

### Option A: Cross-Encoder (Recommended for Starting)

A cross-encoder takes two pieces of text together and outputs a score or classification.

```
Input:  [CLS] claim text here [SEP] axiom text here [SEP]
         ↓
    Transformer layers (12 layers, 110M parameters)
         ↓
Output: [valid: 0.12, invalid: 0.85, unrelated: 0.03]
```

**What is a Transformer?**
A transformer is the architecture behind models like ChatGPT, but much smaller versions exist. It processes text by looking at how each word relates to every other word, building up an understanding of meaning.

**Why "Cross-Encoder"?**
Because it encodes both texts together (crosses them), allowing it to compare them directly. This is more accurate than comparing separate fingerprints.

**Base Model Options**:
| Model | Parameters | Size on Disk | Speed | Quality |
|-------|------------|--------------|-------|---------|
| DistilBERT | 66M | ~250MB | Fast | Good |
| BERT-base | 110M | ~420MB | Medium | Better |
| CodeBERT | 125M | ~480MB | Medium | Best for code |
| DeBERTa-v3-small | 44M | ~170MB | Fastest | Good |

**Recommendation**: Start with **DistilBERT** or **DeBERTa-v3-small** for fastest iteration, upgrade to CodeBERT if needed.

### Option B: Bi-Encoder with Reranker

Two-stage approach:
1. Bi-encoder: Separate fingerprints for query and axioms (fast)
2. Reranker: Cross-encoder on top K only (accurate)

More complex to implement, but scales better if you have 100k+ axioms.

### Option C: Graph Neural Network

Uses the axiom dependency graph (`depends_on` relationships) to learn how axioms relate.

```
Axiom A ──depends_on──→ Axiom B
   ↓                        ↓
 [node embedding]     [node embedding]
         ↓
    GNN message passing
         ↓
    Updated embeddings that capture dependencies
```

**Advantage**: Explicitly models that "if A is true and A implies B, then B is true"
**Disadvantage**: More complex, requires graph ML expertise

---

## Data Generation

The key insight: **you already have the training data**, it just needs to be reformatted.

### Source Material

Your 4,523 axioms contain:
- Natural language content
- Formal specifications
- Dependency relationships
- Standard section references

### Generating Training Examples

#### Positive Examples (claim matches axiom)

Take each axiom and create claims that it validates:

```python
axiom = {
    "content": "Signed integer overflow is undefined behavior",
    "formal": "overflow(signed_int, op) => undefined_behavior"
}

# Direct restatement
positive_1 = "Overflowing a signed int is undefined"

# Paraphrase
positive_2 = "Adding two large positive ints can cause UB"

# Question form
positive_3 = "Is signed overflow undefined behavior?"

# Implication
positive_4 = "The compiler can assume signed overflow doesn't happen"
```

#### Negative Examples (claim contradicts axiom)

Flip the meaning:

```python
# Contradiction
negative_1 = "Signed integer overflow wraps around to negative"

# Wrong guarantee
negative_2 = "Signed overflow is implementation-defined"

# Opposite
negative_3 = "Adding large signed integers is always safe"
```

#### Unrelated Examples (different topic)

Pair axioms with unrelated claims:

```python
# Completely different topic
unrelated_1 = ("Signed overflow is undefined",
               "std::vector growth is amortized O(1)")

# Same domain but different concept
unrelated_2 = ("Signed overflow is undefined",
               "Null pointer dereference is undefined")
```

### Automated Generation Script

```python
def generate_training_data(axioms: list) -> list:
    examples = []

    for axiom in axioms:
        # Positive: axiom content variations
        examples.append({
            "claim": axiom["content"],
            "axiom": axiom["content"],
            "label": "valid"
        })

        # Positive: paraphrase (use simple rules or LLM)
        paraphrase = generate_paraphrase(axiom["content"])
        examples.append({
            "claim": paraphrase,
            "axiom": axiom["content"],
            "label": "valid"
        })

        # Negative: negate the claim
        negation = generate_negation(axiom["content"])
        examples.append({
            "claim": negation,
            "axiom": axiom["content"],
            "label": "invalid"
        })

        # Unrelated: random other axiom
        other = random.choice(axioms)
        if other["id"] != axiom["id"]:
            examples.append({
                "claim": other["content"],
                "axiom": axiom["content"],
                "label": "unrelated"
            })

    return examples
```

### Target Dataset Size

| Axiom Count | Examples per Axiom | Total Examples |
|-------------|-------------------|----------------|
| 4,523 | 10-20 | 45,000 - 90,000 |

This is enough for a small model. More is better, but diminishing returns after ~100k.

### Data Quality Tips

1. **Balance classes**: Equal amounts of valid/invalid/unrelated
2. **Hard negatives**: Negations should be subtle, not obviously wrong
3. **Diverse paraphrases**: Don't just swap synonyms
4. **Use the formal spec**: Generate claims from formal notation too
5. **Include code**: "What does `int x = INT_MAX + 1;` do?"

---

## Training Process

### What Happens During Training

Training is an iterative process where the model:
1. Sees a batch of examples (e.g., 32 claim-axiom pairs)
2. Makes predictions (valid/invalid/unrelated)
3. Compares predictions to correct answers
4. Adjusts its internal numbers to make fewer mistakes
5. Repeats thousands of times

```
Epoch 1: Model sees all 50,000 examples once
         Accuracy: 45% (random guessing is 33%)

Epoch 2: Model sees all examples again
         Accuracy: 68%

Epoch 3: Model sees all examples again
         Accuracy: 82%

...

Epoch 10:
         Accuracy: 94%
         Training complete!
```

### Key Concepts

**Batch Size**: How many examples the model sees before adjusting. Larger = faster but needs more memory. Typical: 16-32.

**Learning Rate**: How big the adjustments are. Too high = overshoots, too low = too slow. Typical: 2e-5 (0.00002).

**Epochs**: How many times the model sees the full dataset. Typical: 3-10.

**Validation Set**: A held-out 10-20% of data to check if the model is actually learning or just memorizing. If training accuracy goes up but validation accuracy goes down, the model is memorizing.

### Training Script Overview

```python
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from transformers import Trainer, TrainingArguments
import torch

# 1. Load a pretrained model (already knows English/code)
model_name = "microsoft/codebert-base"  # or distilbert-base-uncased
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(
    model_name,
    num_labels=3  # valid, invalid, unrelated
)

# 2. Prepare your data
def tokenize(example):
    return tokenizer(
        example["claim"],
        example["axiom"],
        truncation=True,
        padding="max_length",
        max_length=256
    )

train_dataset = load_your_data("train.json").map(tokenize)
eval_dataset = load_your_data("eval.json").map(tokenize)

# 3. Configure training
training_args = TrainingArguments(
    output_dir="./axiom-validator",
    num_train_epochs=5,
    per_device_train_batch_size=16,  # reduce if out of memory
    per_device_eval_batch_size=32,
    learning_rate=2e-5,
    evaluation_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,

    # For M2 Mac
    use_mps_device=True,  # Use Apple GPU
)

# 4. Train!
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
)

trainer.train()

# 5. Save the result
model.save_pretrained("./axiom-validator-final")
tokenizer.save_pretrained("./axiom-validator-final")
```

---

## Hardware Requirements

### M2 Mac Specifics

Apple Silicon (M1/M2/M3) has unified memory - the CPU and GPU share the same RAM. PyTorch can use the GPU via "MPS" (Metal Performance Shaders).

| Your Mac | RAM | Training Time | Batch Size | Notes |
|----------|-----|---------------|------------|-------|
| M2 Air (8GB) | 8GB | 4-6 hours | 8 | Tight, close background apps |
| M2 Pro (16GB) | 16GB | 2-3 hours | 16-32 | Comfortable |
| M2 Max (32GB) | 32GB | 1-2 hours | 32-64 | Plenty of headroom |
| M2 Ultra (64GB+) | 64GB+ | <1 hour | 64+ | Overkill for this task |

### Software Setup for M2 Mac

```bash
# 1. Install Python (if not already)
brew install python@3.11

# 2. Create a virtual environment
python3.11 -m venv axiom-model-env
source axiom-model-env/bin/activate

# 3. Install PyTorch with MPS support
pip install torch torchvision torchaudio

# 4. Install Hugging Face libraries
pip install transformers datasets accelerate

# 5. Verify MPS is available
python -c "import torch; print(torch.backends.mps.is_available())"
# Should print: True
```

### Memory Management Tips for 8GB Macs

If you hit memory errors:

```python
# Reduce batch size
per_device_train_batch_size=4  # instead of 16

# Use gradient accumulation (simulates larger batch)
gradient_accumulation_steps=4  # 4 steps × 4 batch = effective batch of 16

# Use a smaller model
model_name = "distilbert-base-uncased"  # 66M instead of 125M

# Enable gradient checkpointing (trades speed for memory)
model.gradient_checkpointing_enable()
```

### What Your Mac Will Feel Like During Training

- **Fans**: Will likely spin up, especially on Air models
- **Temperature**: MacBook will get warm (normal)
- **Responsiveness**: Slightly sluggish if you're also using the computer
- **Battery**: Plug in! Training drains battery fast

**Recommendation**: Start training before bed, let it run overnight.

---

## Step-by-Step Implementation

### Phase 1: Data Preparation (Day 1)

#### Step 1.1: Export Axioms

Create a script to dump your axioms to a JSON file:

```python
# scripts/export_axioms.py
import json
from axiom.database import get_all_axioms  # your existing code

axioms = get_all_axioms()
with open("data/axioms.json", "w") as f:
    json.dump(axioms, f, indent=2)

print(f"Exported {len(axioms)} axioms")
```

#### Step 1.2: Generate Training Examples

```python
# scripts/generate_training_data.py
import json
import random
from collections import defaultdict

def load_axioms(path):
    with open(path) as f:
        return json.load(f)

def generate_negation(text):
    """Simple negation - replace key words with opposites."""
    replacements = {
        "undefined behavior": "well-defined behavior",
        "is undefined": "is defined",
        "must": "must not",
        "shall": "shall not",
        "valid": "invalid",
        "invalid": "valid",
        "true": "false",
        "false": "true",
    }
    result = text.lower()
    for old, new in replacements.items():
        if old in result:
            return text.replace(old, new, 1)
    # Fallback: add "not"
    return text.replace(" is ", " is not ", 1)

def generate_examples(axioms):
    examples = []
    axiom_list = list(axioms)

    for axiom in axiom_list:
        content = axiom.get("content", "")
        if not content:
            continue

        # Positive: exact match
        examples.append({
            "claim": content,
            "axiom_id": axiom["id"],
            "axiom_content": content,
            "label": "valid"
        })

        # Negative: negated claim
        negation = generate_negation(content)
        if negation != content:
            examples.append({
                "claim": negation,
                "axiom_id": axiom["id"],
                "axiom_content": content,
                "label": "invalid"
            })

        # Unrelated: random different axiom
        other = random.choice(axiom_list)
        if other["id"] != axiom["id"]:
            examples.append({
                "claim": other.get("content", ""),
                "axiom_id": axiom["id"],
                "axiom_content": content,
                "label": "unrelated"
            })

    return examples

def balance_dataset(examples):
    """Ensure equal numbers of each label."""
    by_label = defaultdict(list)
    for ex in examples:
        by_label[ex["label"]].append(ex)

    min_count = min(len(v) for v in by_label.values())
    balanced = []
    for label, items in by_label.items():
        balanced.extend(random.sample(items, min_count))

    random.shuffle(balanced)
    return balanced

def split_dataset(examples, train_ratio=0.8):
    """Split into training and validation sets."""
    split_idx = int(len(examples) * train_ratio)
    return examples[:split_idx], examples[split_idx:]

if __name__ == "__main__":
    axioms = load_axioms("data/axioms.json")
    print(f"Loaded {len(axioms)} axioms")

    examples = generate_examples(axioms)
    print(f"Generated {len(examples)} raw examples")

    balanced = balance_dataset(examples)
    print(f"Balanced to {len(balanced)} examples")

    train, val = split_dataset(balanced)
    print(f"Train: {len(train)}, Validation: {len(val)}")

    with open("data/train.json", "w") as f:
        json.dump(train, f)
    with open("data/val.json", "w") as f:
        json.dump(val, f)

    print("Done! Saved to data/train.json and data/val.json")
```

### Phase 2: Training (Day 1-2)

#### Step 2.1: Training Script

```python
# scripts/train_validator.py
import json
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
)

# Check for Apple Silicon
if torch.backends.mps.is_available():
    device = torch.device("mps")
    print("Using Apple Silicon GPU (MPS)")
elif torch.cuda.is_available():
    device = torch.device("cuda")
    print("Using NVIDIA GPU")
else:
    device = torch.device("cpu")
    print("Using CPU (this will be slow)")

# Configuration
MODEL_NAME = "distilbert-base-uncased"  # Small and fast
MAX_LENGTH = 256  # Max tokens per example
BATCH_SIZE = 16   # Reduce to 8 or 4 if out of memory
EPOCHS = 5
LEARNING_RATE = 2e-5

# Label mapping
LABEL2ID = {"valid": 0, "invalid": 1, "unrelated": 2}
ID2LABEL = {v: k for k, v in LABEL2ID.items()}

class AxiomDataset(Dataset):
    def __init__(self, examples, tokenizer, max_length):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]

        # Tokenize claim + axiom together
        encoding = self.tokenizer(
            ex["claim"],
            ex["axiom_content"],
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt"
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(),
            "attention_mask": encoding["attention_mask"].squeeze(),
            "labels": torch.tensor(LABEL2ID[ex["label"]])
        }

def main():
    # Load data
    with open("data/train.json") as f:
        train_examples = json.load(f)
    with open("data/val.json") as f:
        val_examples = json.load(f)

    print(f"Training examples: {len(train_examples)}")
    print(f"Validation examples: {len(val_examples)}")

    # Load tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    # Create datasets
    train_dataset = AxiomDataset(train_examples, tokenizer, MAX_LENGTH)
    val_dataset = AxiomDataset(val_examples, tokenizer, MAX_LENGTH)

    # Training configuration
    training_args = TrainingArguments(
        output_dir="./models/axiom-validator",
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE * 2,
        learning_rate=LEARNING_RATE,
        weight_decay=0.01,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        logging_steps=100,

        # Apple Silicon
        use_mps_device=(device.type == "mps"),
    )

    # Create trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
    )

    # Train!
    print("Starting training...")
    trainer.train()

    # Save final model
    model.save_pretrained("./models/axiom-validator-final")
    tokenizer.save_pretrained("./models/axiom-validator-final")
    print("Training complete! Model saved to ./models/axiom-validator-final")

if __name__ == "__main__":
    main()
```

#### Step 2.2: Run Training

```bash
# Activate environment
source axiom-model-env/bin/activate

# Run training
python scripts/train_validator.py

# Watch the output - you'll see something like:
# Epoch 1/5: loss=1.02, eval_loss=0.85, eval_accuracy=0.65
# Epoch 2/5: loss=0.71, eval_loss=0.52, eval_accuracy=0.78
# ...
```

### Phase 3: Inference (Day 2)

#### Step 3.1: Inference Script

```python
# axiom/validator.py
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

class AxiomValidator:
    def __init__(self, model_path="./models/axiom-validator-final"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)

        # Use Apple Silicon if available
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")

        self.model.to(self.device)
        self.model.eval()

        self.id2label = {0: "valid", 1: "invalid", 2: "unrelated"}

    def validate(self, claim: str, axiom_content: str) -> dict:
        """
        Check if a claim is valid given an axiom.

        Returns:
            {
                "label": "valid" | "invalid" | "unrelated",
                "confidence": 0.0 - 1.0,
                "scores": {"valid": 0.x, "invalid": 0.x, "unrelated": 0.x}
            }
        """
        # Tokenize
        inputs = self.tokenizer(
            claim,
            axiom_content,
            truncation=True,
            padding=True,
            max_length=256,
            return_tensors="pt"
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Predict
        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)[0]

        # Extract results
        predicted_id = probs.argmax().item()
        confidence = probs[predicted_id].item()

        scores = {
            self.id2label[i]: probs[i].item()
            for i in range(3)
        }

        return {
            "label": self.id2label[predicted_id],
            "confidence": confidence,
            "scores": scores
        }

    def validate_batch(self, claims: list, axiom_contents: list) -> list:
        """Validate multiple claim-axiom pairs efficiently."""
        results = []
        for claim, axiom in zip(claims, axiom_contents):
            results.append(self.validate(claim, axiom))
        return results


# Example usage
if __name__ == "__main__":
    validator = AxiomValidator()

    result = validator.validate(
        claim="Signed integer overflow wraps around",
        axiom_content="Signed integer overflow is undefined behavior"
    )

    print(f"Label: {result['label']}")
    print(f"Confidence: {result['confidence']:.2%}")
    print(f"Scores: {result['scores']}")
```

---

## Evaluation

### Metrics to Track

| Metric | What It Measures | Target |
|--------|------------------|--------|
| **Accuracy** | % of correct predictions | >85% |
| **Precision** | Of predicted "invalid", how many are actually invalid? | >80% |
| **Recall** | Of actual "invalid", how many did we catch? | >80% |
| **F1** | Balance of precision and recall | >80% |

### Evaluation Script

```python
# scripts/evaluate.py
from sklearn.metrics import classification_report, confusion_matrix
import json
from axiom.validator import AxiomValidator

def evaluate(model_path, test_data_path):
    validator = AxiomValidator(model_path)

    with open(test_data_path) as f:
        test_examples = json.load(f)

    y_true = []
    y_pred = []

    for ex in test_examples:
        result = validator.validate(ex["claim"], ex["axiom_content"])
        y_true.append(ex["label"])
        y_pred.append(result["label"])

    print("Classification Report:")
    print(classification_report(y_true, y_pred))

    print("\nConfusion Matrix:")
    print(confusion_matrix(y_true, y_pred))

if __name__ == "__main__":
    evaluate("./models/axiom-validator-final", "data/val.json")
```

### What Good Results Look Like

```
Classification Report:
              precision    recall  f1-score   support

     valid       0.87      0.89      0.88      1000
   invalid       0.84      0.82      0.83      1000
 unrelated       0.91      0.90      0.90      1000

  accuracy                           0.87      3000

Confusion Matrix:
[[890  70  40]
 [ 95 820  85]
 [ 35  65 900]]
```

---

## Integration

### Integrate with MCP

Update your `validate_claim` tool to use the model:

```python
# In your MCP server code

from axiom.validator import AxiomValidator
from axiom.database import search_axioms  # your existing search

validator = AxiomValidator("./models/axiom-validator-final")

async def validate_claim(claim: str) -> dict:
    # Step 1: Embedding search for candidates
    candidates = search_axioms(claim, limit=10)

    # Step 2: Model validation
    validated = []
    for axiom in candidates:
        result = validator.validate(claim, axiom["content"])

        if result["label"] == "valid" and result["confidence"] > 0.7:
            validated.append({
                "axiom": axiom,
                "validation": result
            })
        elif result["label"] == "invalid" and result["confidence"] > 0.8:
            # This is interesting - the claim contradicts an axiom!
            return {
                "valid": False,
                "contradiction": axiom,
                "confidence": result["confidence"]
            }

    # Step 3: Return best match
    if validated:
        best = max(validated, key=lambda x: x["validation"]["confidence"])
        return {
            "valid": True,
            "axiom": best["axiom"],
            "confidence": best["validation"]["confidence"]
        }
    else:
        return {
            "valid": None,  # Unknown
            "message": "No axioms found to validate this claim"
        }
```

---

## Summary

| Phase | Effort | Output |
|-------|--------|--------|
| Data generation | 2-4 hours | 50k+ training examples |
| Training | 2-6 hours (automated) | Trained model (~250MB) |
| Integration | 1-2 hours | Enhanced MCP validation |

**Total cost**: $0 (runs on your M2 Mac)

**Total time**: 1-2 days of work, mostly waiting for training

**Result**: Smarter claim validation that catches contradictions and filters irrelevant results.

---

## Next Steps

1. [ ] Export axioms to JSON
2. [ ] Generate training data
3. [ ] Set up Python environment on M2
4. [ ] Run training overnight
5. [ ] Evaluate results
6. [ ] Integrate with MCP
7. [ ] Iterate on data quality based on errors
