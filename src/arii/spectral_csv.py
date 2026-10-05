from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpectralCsvSummary:
    path: str
    delimiter: str
    rows: int
    columns: int
    samples: int
    spectral_points: int
    axis_start: float
    axis_end: float
    axis_monotonic: bool
    proposed_orientation: str
    sample_names: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_spectral_csv(path: str | Path, delimiter: str = ",") -> SpectralCsvSummary:
    """Inspect a variables-by-samples spectral CSV using constant memory."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("El archivo está vacío") from exc

        if len(header) < 2:
            raise ValueError("Se esperaba un eje y al menos una muestra")

        sample_names = tuple(cell.strip() for cell in header[1:])
        if any(not name for name in sample_names):
            raise ValueError("Hay nombres de muestra vacíos")
        if len(set(sample_names)) != len(sample_names):
            raise ValueError("Hay nombres de muestra duplicados")

        row_count = 0
        first_axis: float | None = None
        last_axis: float | None = None
        direction = 0
        monotonic = True

        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"Fila {line_number}: {len(row)} columnas; se esperaban {len(header)}"
                )
            try:
                current = float(row[0])
            except ValueError as exc:
                raise ValueError(f"Fila {line_number}: eje no numérico: {row[0]!r}") from exc

            if first_axis is None:
                first_axis = current
            elif last_axis is not None:
                delta = current - last_axis
                current_direction = 1 if delta > 0 else -1 if delta < 0 else 0
                if current_direction == 0 or (direction and current_direction != direction):
                    monotonic = False
                if direction == 0 and current_direction:
                    direction = current_direction
            last_axis = current
            row_count += 1

    if row_count == 0 or first_axis is None or last_axis is None:
        raise ValueError("El archivo no contiene puntos espectrales")

    return SpectralCsvSummary(
        path=str(source.resolve()),
        delimiter=delimiter,
        rows=row_count,
        columns=len(header),
        samples=len(sample_names),
        spectral_points=row_count,
        axis_start=first_axis,
        axis_end=last_axis,
        axis_monotonic=monotonic,
        proposed_orientation="variables_by_samples",
        sample_names=sample_names,
    )
