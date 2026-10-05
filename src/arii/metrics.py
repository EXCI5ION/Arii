from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RocCurve:
    false_positive_rate: np.ndarray
    true_positive_rate: np.ndarray
    auc: float


@dataclass(frozen=True)
class ThresholdCurve:
    thresholds: np.ndarray
    sensitivity: np.ndarray
    specificity: np.ndarray
    optimal_threshold: float
    optimal_index: int


def mean_external_scores(
    repetitions: list[dict], component: int
) -> tuple[list[str], list[str], np.ndarray]:
    """Average out-of-fold decision values for each sample across iterations."""
    accumulated: dict[str, tuple[str, list[np.ndarray]]] = {}
    for fold in repetitions:
        values = np.asarray(fold["decision_values"], dtype=float)
        for row, (sample_name, truth) in enumerate(
            zip(fold["validation_samples"], fold["truth"], strict=True)
        ):
            score = np.asarray(values[row, :, component], dtype=float)
            if sample_name not in accumulated:
                accumulated[sample_name] = (truth, [score])
            else:
                saved_truth, scores = accumulated[sample_name]
                if saved_truth != truth:
                    raise ValueError(
                        f"La clase de la muestra '{sample_name}' cambia entre particiones"
                    )
                scores.append(score)
    names = list(accumulated)
    truths = [accumulated[name][0] for name in names]
    averaged = np.asarray(
        [np.mean(accumulated[name][1], axis=0) for name in names], dtype=float
    )
    return names, truths, averaged


def binary_roc(truth: list[bool] | np.ndarray, scores: list[float] | np.ndarray) -> RocCurve:
    y = np.asarray(truth, dtype=bool)
    values = np.asarray(scores, dtype=float)
    valid = np.isfinite(values)
    y, values = y[valid], values[valid]
    positives = int(y.sum())
    negatives = int((~y).sum())
    if positives == 0 or negatives == 0:
        raise ValueError("ROC requiere observaciones positivas y negativas")
    order = np.argsort(-values, kind="mergesort")
    y = y[order]
    values = values[order]
    distinct = np.where(np.diff(values))[0]
    threshold_indices = np.r_[distinct, len(values) - 1]
    true_positives = np.cumsum(y)[threshold_indices]
    false_positives = 1 + threshold_indices - true_positives
    tpr = np.r_[0.0, true_positives / positives, 1.0]
    fpr = np.r_[0.0, false_positives / negatives, 1.0]
    auc = float(np.trapezoid(tpr, fpr))
    return RocCurve(fpr, tpr, auc)


def sensitivity_specificity_curve(
    truth: list[bool] | np.ndarray, scores: list[float] | np.ndarray
) -> ThresholdCurve:
    y = np.asarray(truth, dtype=bool)
    values = np.asarray(scores, dtype=float)
    valid = np.isfinite(values)
    y, values = y[valid], values[valid]
    if y.sum() == 0 or (~y).sum() == 0:
        raise ValueError("El umbral requiere observaciones positivas y negativas")
    unique = np.unique(values)
    margin = max(np.ptp(unique) * 1e-9, np.finfo(float).eps)
    thresholds = np.r_[unique[0] - margin, unique, unique[-1] + margin]
    sensitivity = np.asarray([np.mean(values[y] >= threshold) for threshold in thresholds])
    specificity = np.asarray([np.mean(values[~y] < threshold) for threshold in thresholds])
    youden = sensitivity + specificity - 1
    candidates = np.flatnonzero(np.isclose(youden, np.nanmax(youden)))
    balance = np.abs(sensitivity[candidates] - specificity[candidates])
    optimal_index = int(candidates[np.argmin(balance)])
    return ThresholdCurve(
        thresholds=thresholds,
        sensitivity=sensitivity,
        specificity=specificity,
        optimal_threshold=float(thresholds[optimal_index]),
        optimal_index=optimal_index,
    )
