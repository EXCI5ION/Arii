from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


Orientation = Literal["variables_by_samples", "samples_by_variables"]
Representation = Literal["continuous_profile", "feature_table"]


@dataclass(frozen=True)
class OmicsMatrixSummary:
    """Validated description of a numeric omics matrix ready for modelling."""

    path: str
    delimiter: str
    rows: int
    columns: int
    samples: int
    features: int
    orientation: Orientation
    proposed_orientation: Orientation
    orientation_confidence: str
    representation: Representation
    modality: str
    identifier_label: str
    axis_label: str
    axis_start: float | None
    axis_end: float | None
    axis_monotonic: bool
    feature_axis_numeric: bool
    missing_values: int
    sample_names: tuple[str, ...]

    @property
    def spectral_points(self) -> int:
        """Compatibility alias for projects and views created for NMR data."""

        return self.features

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "OmicsMatrixSummary":
        """Load both the generic contract and legacy SpectralCsvSummary payloads."""

        if "features" in payload:
            values = dict(payload)
            values["sample_names"] = tuple(values["sample_names"])
            return cls(**values)
        axis_start = float(payload["axis_start"])
        axis_end = float(payload["axis_end"])
        return cls(
            path=payload["path"], delimiter=payload.get("delimiter", ","),
            rows=int(payload["rows"]), columns=int(payload["columns"]),
            samples=int(payload["samples"]),
            features=int(payload["spectral_points"]),
            orientation="variables_by_samples",
            proposed_orientation=payload.get(
                "proposed_orientation", "variables_by_samples"
            ),
            orientation_confidence="legacy",
            representation="continuous_profile", modality="1H-NMR",
            identifier_label="ppm", axis_label="ppm",
            axis_start=axis_start, axis_end=axis_end,
            axis_monotonic=bool(payload.get("axis_monotonic", False)),
            feature_axis_numeric=True, missing_values=0,
            sample_names=tuple(payload["sample_names"]),
        )


def detect_delimiter(path: str | Path) -> str:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(65536)
    if not sample.strip():
        raise ValueError("El archivo está vacío")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
    except csv.Error:
        return "\t" if source.suffix.lower() in {".tsv", ".txt"} else ","


def _numeric_axis(values: list[str]) -> tuple[bool, float | None, float | None, bool]:
    try:
        numeric = [float(value) for value in values]
    except ValueError:
        return False, None, None, False
    if not numeric or not all(math.isfinite(value) for value in numeric):
        return False, None, None, False
    differences = [right - left for left, right in zip(numeric, numeric[1:])]
    monotonic = bool(differences) and (
        all(value > 0 for value in differences) or all(value < 0 for value in differences)
    )
    return True, numeric[0], numeric[-1], monotonic


def _infer_modality(identifier_label: str, feature_ids: list[str]) -> str:
    text = " ".join([identifier_label, *feature_ids[:50]]).lower()
    if "ppm" in text or "chemical shift" in text:
        return "1H-NMR"
    if any(token in text for token in ("m/z", "mz", "retention time", "rt_")):
        return "MS"
    if any(token in text for token in ("gene", "ensembl", "transcript")):
        return "Transcriptómica/genómica"
    if any(token in text for token in ("protein", "uniprot", "peptide")):
        return "Proteómica"
    return "Matriz ómica genérica"


def inspect_omics_matrix(
    path: str | Path,
    delimiter: str | None = None,
    *,
    orientation: Orientation | None = None,
    representation: Representation | None = None,
    modality: str | None = None,
    axis_label: str | None = None,
) -> OmicsMatrixSummary:
    """Inspect a delimited numeric matrix without retaining its numeric body."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    separator = delimiter or detect_delimiter(source)
    if len(separator) != 1:
        raise ValueError("El delimitador debe tener exactamente un carácter")

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=separator)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("El archivo está vacío") from exc
        header = [cell.strip() for cell in header]
        if len(header) < 3:
            raise ValueError("Se requieren identificadores y al menos dos columnas numéricas")
        column_ids = header[1:]
        row_ids: list[str] = []
        missing_values = 0
        row_count = 0
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"Fila {line_number}: {len(row)} columnas; se esperaban {len(header)}"
                )
            identifier = row[0].strip()
            if not identifier:
                raise ValueError(f"Fila {line_number}: identificador vacío")
            row_ids.append(identifier)
            for column_number, cell in enumerate(row[1:], start=2):
                value = cell.strip()
                if not value:
                    missing_values += 1
                    continue
                try:
                    numeric = float(value)
                except ValueError as exc:
                    raise ValueError(
                        f"Fila {line_number}, columna {column_number}: "
                        f"valor no numérico {value!r}"
                    ) from exc
                if not math.isfinite(numeric):
                    missing_values += 1
            row_count += 1

    if row_count < 2:
        raise ValueError("Se requieren al menos dos filas de datos")
    if any(not value for value in column_ids):
        raise ValueError("Hay identificadores de columna vacíos")

    data_columns = len(column_ids)
    ratio = max(row_count, data_columns) / min(row_count, data_columns)
    proposed: Orientation = (
        "variables_by_samples" if row_count >= data_columns else "samples_by_variables"
    )
    confidence = "alta" if ratio >= 2 else "baja"
    chosen = orientation or proposed
    sample_names = column_ids if chosen == "variables_by_samples" else row_ids
    feature_ids = row_ids if chosen == "variables_by_samples" else column_ids
    if len(set(sample_names)) != len(sample_names):
        raise ValueError("Hay identificadores de muestra duplicados")
    if len(set(feature_ids)) != len(feature_ids):
        raise ValueError("Hay identificadores de variable duplicados")

    numeric_axis, axis_start, axis_end, monotonic = _numeric_axis(feature_ids)
    suggested_representation: Representation = (
        "continuous_profile" if numeric_axis and monotonic else "feature_table"
    )
    chosen_representation = representation or suggested_representation
    identifier_label = header[0] or (
        "variable" if chosen == "variables_by_samples" else "muestra"
    )
    chosen_axis_label = (
        axis_label
        or (identifier_label if chosen == "variables_by_samples" else "Característica")
    ).strip()
    if not chosen_axis_label:
        raise ValueError("La etiqueta del eje no puede quedar vacía")
    chosen_modality = (modality or _infer_modality(identifier_label, feature_ids)).strip()
    if not chosen_modality:
        raise ValueError("La modalidad no puede quedar vacía")

    return OmicsMatrixSummary(
        path=str(source.resolve()), delimiter=separator,
        rows=row_count, columns=len(header), samples=len(sample_names),
        features=len(feature_ids), orientation=chosen,
        proposed_orientation=proposed, orientation_confidence=confidence,
        representation=chosen_representation, modality=chosen_modality,
        identifier_label=identifier_label, axis_label=chosen_axis_label,
        axis_start=axis_start, axis_end=axis_end, axis_monotonic=monotonic,
        feature_axis_numeric=numeric_axis, missing_values=missing_values,
        sample_names=tuple(sample_names),
    )
