from __future__ import annotations

from math import comb, erfc, sqrt

import numpy as np


def _average_ranks(values: np.ndarray) -> tuple[np.ndarray, list[int]]:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    ties: list[int] = []
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        ties.append(end - start)
        start = end
    return ranks, ties


def paired_residual_tests(
    observed_errors,
    permuted_errors,
    *,
    seed: int,
    randomization_iterations: int = 9_999,
) -> dict:
    """One-sided paired tests for lower observed squared prediction error.

    ``permuted_errors`` is the per-sample mean across response permutations. This
    keeps the experimental unit as the sample instead of treating repeated CV
    predictions or permutations as independent observations.
    """

    observed = np.asarray(observed_errors, dtype=float).reshape(-1)
    permuted = np.asarray(permuted_errors, dtype=float).reshape(-1)
    finite = np.isfinite(observed) & np.isfinite(permuted)
    observed, permuted = observed[finite], permuted[finite]
    differences = permuted - observed
    nonzero = differences[np.abs(differences) > np.sqrt(np.finfo(float).eps)]
    if nonzero.size == 0:
        wilcoxon_p = sign_p = randomization_p = 1.0
    else:
        ranks, ties = _average_ranks(np.abs(nonzero))
        positive_rank_sum = float(np.sum(ranks[nonzero > 0]))
        count = int(nonzero.size)
        expected = count * (count + 1) / 4
        variance = (
            count * (count + 1) * (2 * count + 1)
            - sum(size**3 - size for size in ties)
        ) / 24
        if variance > 0:
            z_value = (positive_rank_sum - expected - 0.5) / sqrt(variance)
            wilcoxon_p = 0.5 * erfc(z_value / sqrt(2))
        else:
            wilcoxon_p = 1.0

        positives = int(np.sum(nonzero > 0))
        sign_p = sum(comb(count, value) for value in range(positives, count + 1)) / 2**count

        observed_sd = float(np.std(nonzero, ddof=1)) if count > 1 else 0.0
        observed_t = (
            float(np.mean(nonzero)) / (observed_sd / sqrt(count))
            if observed_sd > 0
            else (float("inf") if float(np.mean(nonzero)) > 0 else float("-inf"))
        )
        state = int(seed) % 2_147_483_647
        if state <= 0:
            state = 1
        extreme = 0
        completed = 0
        while completed < randomization_iterations:
            chunk = min(1_000, randomization_iterations - completed)
            generated = np.empty(chunk * count, dtype=float)
            for index in range(generated.size):
                state = (48_271 * state) % 2_147_483_647
                generated[index] = -1.0 if state % 2 == 0 else 1.0
            signs = generated.reshape((chunk, count), order="C")
            randomized = signs * nonzero
            means = np.mean(randomized, axis=1)
            deviations = np.std(randomized, axis=1, ddof=1) if count > 1 else np.zeros(chunk)
            statistics = np.divide(
                means,
                deviations / sqrt(count),
                out=np.where(means > 0, np.inf, -np.inf),
                where=deviations > 0,
            )
            extreme += int(np.sum(statistics >= observed_t))
            completed += chunk
        randomization_p = (1 + extreme) / (randomization_iterations + 1)

    return {
        "wilcoxon": float(wilcoxon_p),
        "sign_test": float(sign_p),
        "randomization_t": float(randomization_p),
        "samples": int(differences.size),
        "observed_mean_squared_error": float(np.mean(observed)),
        "permuted_mean_squared_error": float(np.mean(permuted)),
        "mean_error_improvement": float(np.mean(differences)),
        "alternative": "observed_error_lower_than_permuted",
    }


def build_residual_tests(
    observed_errors: dict,
    null_error_sum: dict,
    permutations: int,
    class_levels: list[str],
    *,
    seed: int,
) -> dict:
    output: dict[str, dict] = {}
    for mode_index, mode in enumerate(("calibration", "cross_validated"), start=1):
        observed = np.asarray(observed_errors[mode], dtype=float)
        null_mean = np.asarray(null_error_sum[mode], dtype=float) / permutations
        scopes = ["global", *class_levels]
        output[mode] = {}
        for scope_index, scope in enumerate(scopes, start=1):
            if scope == "global":
                observed_values = np.sum(observed, axis=1)
                null_values = np.sum(null_mean, axis=1)
            else:
                class_index = class_levels.index(scope)
                observed_values = observed[:, class_index]
                null_values = null_mean[:, class_index]
            output[mode][scope] = paired_residual_tests(
                observed_values,
                null_values,
                seed=seed + mode_index * 1009 + scope_index * 9176,
            )
    return output
