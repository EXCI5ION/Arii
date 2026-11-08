from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from arii.omics_matrix import OmicsMatrixSummary


@dataclass(frozen=True)
class StocsyResult:
    axis: np.ndarray
    pivot_index: int
    pivot_value: float
    covariance: np.ndarray
    correlation: np.ndarray
    mean_profile: np.ndarray
    sample_count: int


def load_numeric_matrix(
    summary: OmicsMatrixSummary,
    *,
    sample_names: Sequence[str] | None = None,
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    """Load a validated delimited matrix as samples × variables.

    STOCSY needs the original profiles rather than model loadings.  This loader
    deliberately follows Arii's confirmed orientation and optionally restores
    the exact sample order used by the current model.
    """

    source = Path(summary.path)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=summary.delimiter)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("La matriz está vacía") from exc
        rows = [row for row in reader if row and any(cell.strip() for cell in row)]

    if not rows or len(header) < 3:
        raise ValueError("La matriz no contiene perfiles suficientes para S-TOCSY")
    expected_columns = len(header)
    if any(len(row) != expected_columns for row in rows):
        raise ValueError("La matriz contiene filas con diferente cantidad de columnas")

    if summary.orientation == "variables_by_samples":
        feature_ids = [row[0].strip() for row in rows]
        names = tuple(cell.strip() for cell in header[1:])
        numeric_rows = [row[1:] for row in rows]
        try:
            matrix = np.asarray(numeric_rows, dtype=float).T
        except ValueError as exc:
            raise ValueError("La matriz contiene intensidades no numéricas") from exc
    elif summary.orientation == "samples_by_variables":
        feature_ids = [cell.strip() for cell in header[1:]]
        names = tuple(row[0].strip() for row in rows)
        try:
            matrix = np.asarray([row[1:] for row in rows], dtype=float)
        except ValueError as exc:
            raise ValueError("La matriz contiene intensidades no numéricas") from exc
    else:
        raise ValueError(f"Orientación no compatible: {summary.orientation}")

    try:
        axis = np.asarray(feature_ids, dtype=float)
    except ValueError as exc:
        raise ValueError("S-TOCSY requiere un eje numérico de desplazamiento químico") from exc
    if not np.all(np.isfinite(axis)):
        raise ValueError("El vector de desplazamiento químico contiene valores no finitos")
    if matrix.ndim != 2 or matrix.shape[1] != axis.size:
        raise ValueError("Las dimensiones de la matriz no coinciden con el eje químico")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(
            "S-TOCSY requiere intensidades finitas; complete o elimine los valores faltantes"
        )

    if sample_names is not None:
        positions = {name: index for index, name in enumerate(names)}
        missing = [name for name in sample_names if name not in positions]
        if missing:
            raise ValueError(
                "No se encontraron en la matriz las muestras: " + ", ".join(missing[:5])
            )
        indices = [positions[name] for name in sample_names]
        matrix = matrix[indices, :]
        names = tuple(sample_names)

    return matrix, axis, names


def compute_stocsy(
    matrix: object,
    axis: object,
    pivot: float,
) -> StocsyResult:
    """Calculate sample covariance and signed Pearson correlation to a pivot."""

    values = np.asarray(matrix, dtype=float)
    chemical_axis = np.asarray(axis, dtype=float)
    if values.ndim != 2:
        raise ValueError("La matriz S-TOCSY debe tener dimensiones muestras × variables")
    if chemical_axis.ndim != 1 or chemical_axis.size != values.shape[1]:
        raise ValueError("El eje químico no coincide con las variables")
    if values.shape[0] < 3:
        raise ValueError("S-TOCSY requiere al menos tres muestras")
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(chemical_axis)):
        raise ValueError("S-TOCSY no admite valores ausentes o infinitos")

    pivot_index = int(np.argmin(np.abs(chemical_axis - float(pivot))))
    centered = values - values.mean(axis=0, keepdims=True)
    driver = centered[:, pivot_index]
    driver_ss = float(driver @ driver)
    if driver_ss <= np.finfo(float).eps:
        raise ValueError(
            "La variable seleccionada no presenta variación entre las muestras"
        )

    covariance = driver @ centered / (values.shape[0] - 1)
    variable_ss = np.einsum("ij,ij->j", centered, centered)
    denominator = np.sqrt(driver_ss * variable_ss)
    correlation = np.divide(
        driver @ centered,
        denominator,
        out=np.full(values.shape[1], np.nan, dtype=float),
        where=denominator > np.finfo(float).eps,
    )
    correlation = np.clip(correlation, -1.0, 1.0)
    correlation[pivot_index] = 1.0

    return StocsyResult(
        axis=chemical_axis.copy(),
        pivot_index=pivot_index,
        pivot_value=float(chemical_axis[pivot_index]),
        covariance=np.asarray(covariance, dtype=float),
        correlation=np.asarray(correlation, dtype=float),
        mean_profile=values.mean(axis=0),
        sample_count=values.shape[0],
    )
