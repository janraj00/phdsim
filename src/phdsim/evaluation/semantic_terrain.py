"""Offline semantic scoring. Missing predictions remain in whole-area denominators."""

from collections import Counter
from typing import Iterable

from phdsim.belief.semantic_terrain import Prediction


def semantic_metrics(classes: tuple[str, ...], reference: Iterable[str],
                     estimates: Iterable[Prediction | None],
                     mask: Iterable[bool] | None = None) -> dict:
    pairs = zip(reference, estimates, strict=True)
    if mask is not None:
        pairs = (pair for pair, selected in zip(pairs, mask, strict=True) if selected)
    counts = Counter((truth, p.label if p is not None else None) for truth, p in pairs)
    if any(t not in classes or (p is not None and p not in classes) for t, p in counts):
        raise ValueError("label outside the configured class set")

    total = counts.total()
    correct = sum(counts[c, c] for c in classes)
    resolved = total - sum(counts[c, None] for c in classes)
    per_class = {}
    for c in classes:
        support = sum(n for (t, _), n in counts.items() if t == c)
        predicted = sum(n for (_, p), n in counts.items() if p == c)
        hits = counts[c, c]
        union = support + predicted - hits
        per_class[c] = {
            "support": support, "correct": hits, "unresolved": counts[c, None],
            "recall": hits / support if support else None,
            "iou": hits / union if union else None,
        }
    return {
        "cells": total, "resolved": resolved, "correct": correct,
        "coverage": resolved / total if total else None,
        "accuracy_whole_area": correct / total if total else None,
        "accuracy_resolved": correct / resolved if resolved else None,
        "per_class": per_class,
    }
