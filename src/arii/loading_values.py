from __future__ import annotations

import numpy as np


def backscaled_loading_values(
    loadings: object,
    standard_deviations: object,
    component: int,
    *,
    scaling: str = "pareto",
) -> tuple[np.ndarray, np.ndarray]:
    """Return the selected loading and its value on the original X scale.

    For Pareto-scaled data this reproduces the transformation used by the
    reference MATLAB script: ``sqrt(sd) * loading``.  The unscaled loading is
    retained separately because it controls the colour of the curve.
    """

    matrix = np.asarray(loadings, dtype=float)
    deviations = np.asarray(standard_deviations, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("Los loadings deben formar una matriz de variables × componentes")
    if deviations.ndim != 1 or deviations.shape[0] != matrix.shape[0]:
        raise ValueError("La desviación estándar no coincide con las variables del modelo")
    if not 0 <= component < matrix.shape[1]:
        raise ValueError("El componente solicitado no existe")
    if np.any(~np.isfinite(deviations)) or np.any(deviations < 0):
        raise ValueError("La desviación estándar contiene valores inválidos")

    multipliers = {
        "none": np.ones_like(deviations),
        "pareto": np.sqrt(deviations),
        "unit_variance": deviations,
    }
    try:
        multiplier = multipliers[scaling]
    except KeyError as exc:
        raise ValueError(f"Escalado no compatible con el loading plot: {scaling}") from exc

    selected = matrix[:, component].copy()
    return selected, selected * multiplier
