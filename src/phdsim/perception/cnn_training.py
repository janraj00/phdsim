"""Train independent modality models; select checkpoints with validation only."""

from dataclasses import asdict
from hashlib import sha256
import json
from math import log
from pathlib import Path

import torch
from torch import nn
from torchvision.models import ResNet18_Weights
import torchvision

from phdsim.datasets import ObservationPool, digest, write_json
from phdsim.core.identity import stable_id
from .baseline import load_observation
from .cnn_config import CnnConfig
from .cnn_input import image_tensor
from .cnn_perception import CnnPerception
from .resnet18_model import ResNet18Model
from .training_result import TrainingResult


def sample_fingerprint(rows, labels):
    return sha256(json.dumps([(r.observation_id, r.payload_sha256, labels[r.target]) for r in rows],
                             separators=(",", ":")).encode()).hexdigest()


def select_rows(pool, modality, split, labels, sequences=None):
    rows = tuple(r for r in pool.records if r.modality == modality and r.split == split
                 and (sequences is None or r.sequence_id in sequences))
    if not rows or len({r.target for r in rows}) != len(rows):
        raise ValueError("CNN requires one observation per target and modality")
    if any(type(labels.get(r.target)) is not int or labels[r.target] not in (0, 1) for r in rows):
        raise ValueError("CNN fitting requires binary labels on train/validation")
    if {labels[r.target] for r in rows} != {0, 1}:
        raise ValueError(f"Both classes required in {split}")
    return rows


def encode_training_images(pool, rows, model, config):
    """The frozen stem/layers 1–3 need only one pass per train/validation image."""
    features = []
    model.eval()
    for start in range(0, len(rows), config.batch_size):
        batch = rows[start:start + config.batch_size]
        images = torch.stack([image_tensor(load_observation(pool, r).payload, r.modality,
                                           config.image_height, config.image_width) for r in batch])
        with torch.no_grad():
            features.append(model.encode(images).detach())
        if start % (config.batch_size * 8) == 0:
            print(f"{model.modality}: encoded {min(start + len(batch), len(rows))}/{len(rows)} images", flush=True)
    return torch.cat(features)


def evaluate_encoded(model, features, labels, batch_size):
    model.eval()
    with torch.no_grad():
        logits = torch.cat([model.classify(features[i:i + batch_size]) for i in range(0, len(features), batch_size)])
        probabilities = logits.sigmoid()
        predicted = probabilities >= 0.5
        positive = labels == 1
        tp, tn = int((predicted & positive).sum()), int((~predicted & ~positive).sum())
        fp, fn = int((predicted & ~positive).sum()), int((~predicted & positive).sum())
        return {"n": len(labels), "positive": int(positive.sum()), "negative": int((~positive).sum()),
                "accuracy": (tp + tn) / len(labels), "brier": float(((probabilities - labels) ** 2).mean()),
                "log_loss": float(nn.functional.binary_cross_entropy_with_logits(logits, labels)),
                "tp": tp, "tn": tn, "fp": fp, "fn": fn,
                "balanced_accuracy": (tp / (tp + fn) + tn / (tn + fp)) / 2}


def train_cnn(pool: ObservationPool, output, config: CnnConfig, *, training_sequences=None):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Model directory is not empty: {output}")
    labels = pool.read_labels()
    modalities = tuple(sorted({r.modality for r in pool.records}))
    if modalities != ("rgb", "thermal"):
        raise ValueError("This CNN experiment requires RGB and thermal")
    if training_sequences is not None:
        training_sequences = tuple(sorted(set(training_sequences)))
        available = {r.sequence_id for r in pool.records if r.split == "train"}
        if not training_sequences or not set(training_sequences) <= available:
            raise ValueError("CNN training scope must contain existing train sequences only")
    rows = {m: {split: select_rows(pool, m, split, labels,
                                training_sequences if split == "train" else None)
                for split in ("train", "validation")}
            for m in modalities}
    for split in ("train", "validation"):
        if {r.target for r in rows["rgb"][split]} != {r.target for r in rows["thermal"][split]}:
            raise ValueError("Training/validation modalities must be paired")
    torch.set_num_threads(config.cpu_threads)
    torch.use_deterministic_algorithms(True)
    torch.hub.set_dir(str(Path(config.torch_cache) / "hub"))
    weights = ResNet18_Weights.IMAGENET1K_V1
    # Official state dict; the documented SHA256 prefix is checked on download.
    pretrained = weights.get_state_dict(progress=True, check_hash=True)
    pretrained_path = Path(torch.hub.get_dir()) / "checkpoints" / weights.url.rsplit("/", 1)[-1]
    if not digest(pretrained_path).startswith("f37072fd"):
        raise ValueError("ResNet18 initialization checksum mismatch")
    prior = (sum(labels[r.target] for r in rows["rgb"]["train"]) + 1) / (len(rows["rgb"]["train"]) + 2)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "phdsim-cnn-models-v1", "pool_fingerprint": pool.fingerprint,
        "description": "Two independent ResNet-18 models, pretrained on ImageNet; layer4 and classifier fine-tuned separately for RGB/thermal",
        "fit": asdict(config), "class_prior": prior,
        "training_sequences": training_sequences,
        "initialization": {"weights": config.weights, "url": weights.url, "sha256": digest(pretrained_path)},
        "preprocessing": "whole-frame aspect-preserving resize/pad, no center crop; ImageNet normalization; thermal L repeated into 3 channels",
        "selection": "minimum validation Brier, including epoch 0; no test image/label used for fitting or selection",
        "frozen": "stem, layers1-3 and all BatchNorm running statistics; no augmentation in this first run",
        "runtime": {"torch": torch.__version__, "torchvision": torchvision.__version__, "device": "cpu"},
        "models": [],
    }
    histories = {}
    for index, modality in enumerate(modalities):
        torch.manual_seed(config.seed + index)
        model = ResNet18Model(modality, pretrained, config.trainable)
        with torch.no_grad():
            model.network.fc.weight.normal_(0, 0.01)
            model.network.fc.bias.fill_(log(prior / (1 - prior)))
        train_rows, validation_rows = rows[modality]["train"], rows[modality]["validation"]
        train_x = encode_training_images(pool, train_rows, model, config)
        validation_x = encode_training_images(pool, validation_rows, model, config)
        train_y = torch.tensor([labels[r.target] for r in train_rows], dtype=torch.float32)
        validation_y = torch.tensor([labels[r.target] for r in validation_rows], dtype=torch.float32)
        params = [{"params": model.network.fc.parameters(), "lr": config.head_learning_rate}]
        if config.trainable == "layer4_and_head":
            params.append({"params": model.network.layer4.parameters(), "lr": config.learning_rate})
        optimizer = torch.optim.AdamW(params, weight_decay=config.weight_decay)
        generator = torch.Generator().manual_seed(config.seed + index)
        history = [{"epoch": 0, "train": evaluate_encoded(model, train_x, train_y, config.batch_size),
                    "validation": evaluate_encoded(model, validation_x, validation_y, config.batch_size)}]
        checkpoint = output / f"{modality}.pt"
        torch.save(model.state_dict(), checkpoint)
        best_brier, best_epoch = history[0]["validation"]["brier"], 0
        for epoch in range(1, config.epochs + 1):
            model.train()
            permutation = torch.randperm(len(train_y), generator=generator)
            for batch_index, start in enumerate(range(0, len(train_y), config.batch_size)):
                ids = permutation[start:start + config.batch_size]
                optimizer.zero_grad(set_to_none=True)
                loss = nn.functional.binary_cross_entropy_with_logits(model.classify(train_x[ids]), train_y[ids])
                loss.backward()
                optimizer.step()
                if batch_index % 8 == 0:
                    print(f"{modality}: epoch {epoch}/{config.epochs}, batch {batch_index + 1}/{(len(train_y) + config.batch_size - 1) // config.batch_size}", flush=True)
            entry = {"epoch": epoch, "train": evaluate_encoded(model, train_x, train_y, config.batch_size),
                     "validation": evaluate_encoded(model, validation_x, validation_y, config.batch_size)}
            history.append(entry)
            value = entry["validation"]["brier"]
            if value < best_brier:
                best_brier, best_epoch = value, epoch
                torch.save(model.state_dict(), checkpoint)
            print(f"{modality}: epoch {epoch}, train accuracy={entry['train']['accuracy']:.3f}, validation accuracy={entry['validation']['accuracy']:.3f}, Brier={value:.4f}; best epoch={best_epoch}", flush=True)
        model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True), strict=True)
        history_metadata = {"history": history, "selected_epoch": best_epoch,
                            "selected_train": evaluate_encoded(model, train_x, train_y, config.batch_size),
                            "selected_validation": evaluate_encoded(model, validation_x, validation_y, config.batch_size)}
        histories[modality] = history_metadata
        checkpoint_sha = digest(checkpoint)
        manifest["models"].append({"modality": modality, "checkpoint": checkpoint.name, "sha256": checkpoint_sha,
                                    "version": stable_id("resnet18-presence", modality, checkpoint_sha),
                                    "train_count": len(train_rows), "validation_count": len(validation_rows),
                                    "training_sha256": sample_fingerprint(train_rows, labels),
                                    "validation_sha256": sample_fingerprint(validation_rows, labels),
                                    "selected_epoch": best_epoch})
        write_json(output / "training.json", histories)
        del model, train_x, validation_x
    write_json(output / "models.json", manifest)
    return load_cnn(pool, output)


def load_cnn(pool: ObservationPool, root):
    root = Path(root).resolve()
    manifest = json.loads((root / "models.json").read_text(encoding="utf-8"))
    if manifest["schema"] != "phdsim-cnn-models-v1" or manifest["pool_fingerprint"] != pool.fingerprint:
        raise ValueError("CNN model bundle belongs to another observation pool")
    config = CnnConfig(**manifest["fit"])
    torch.set_num_threads(config.cpu_threads)
    models, versions = {}, {}
    labels = pool.read_labels()
    for entry in manifest["models"]:
        path = (root / entry["checkpoint"]).resolve()
        if not path.is_relative_to(root) or digest(path) != entry["sha256"]:
            raise ValueError("CNN checkpoint path/fingerprint mismatch")
        modality = entry["modality"]
        if modality in models:
            raise ValueError("Duplicate modality model")
        for split, field in (("train", "training_sha256"), ("validation", "validation_sha256")):
            sequences = manifest.get("training_sequences") if split == "train" else None
            if sample_fingerprint(select_rows(pool, modality, split, labels, sequences), labels) != entry[field]:
                raise ValueError("CNN fitting/selection labels or observations have changed")
        model = ResNet18Model(modality, trainable=config.trainable)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
        models[modality], versions[modality] = model, entry["version"]
    if set(models) != {"rgb", "thermal"}:
        raise ValueError("Both independent modality checkpoints are required")
    snapshot = {**manifest, "artifact_root": str(root)}
    return TrainingResult(CnnPerception(models, versions, config), manifest["class_prior"], snapshot)
