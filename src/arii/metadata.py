from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


METADATA_FIELDS = ("class", "treatment", "batch", "biological_id", "replicate")

HEADER_ALIASES = {
    "sample_name": {"sample_name", "sample", "muestra", "nombre_muestra", "id"},
    "class": {"class", "clase", "group", "grupo"},
    "treatment": {"treatment", "tratamiento"},
    "batch": {"batch", "lote"},
    "biological_id": {"biological_id", "individual", "individuo", "sujeto"},
    "replicate": {"replicate", "replica", "réplica"},
}


@dataclass(frozen=True)
class MetadataImportResult:
    values: dict[str, dict[str, str]]
    matched_samples: tuple[str, ...]
    missing_samples: tuple[str, ...]
    unknown_samples: tuple[str, ...]
    imported_fields: tuple[str, ...]


def _canonical_header(value: str) -> str | None:
    normalized = value.strip().lower().replace(" ", "_")
    for canonical, aliases in HEADER_ALIASES.items():
        if normalized in aliases:
            return canonical
    return None


def export_metadata_template(
    path: str | Path,
    sample_names: list[str] | tuple[str, ...],
    values: dict[str, dict[str, str]] | None = None,
) -> None:
    destination = Path(path)
    delimiter = "\t" if destination.suffix.lower() in {".tsv", ".txt"} else ","
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("sample_name", *METADATA_FIELDS), delimiter=delimiter)
        writer.writeheader()
        for sample_name in sample_names:
            writer.writerow({"sample_name": sample_name, **(values or {}).get(sample_name, {})})


def import_metadata(path: str | Path, dataset_samples: list[str] | tuple[str, ...]) -> MetadataImportResult:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        preview = stream.read(8192)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(preview, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(stream, dialect=dialect)
        if reader.fieldnames is None:
            raise ValueError("El archivo de metadatos no tiene encabezados")
        header_map = {
            original: _canonical_header(original) for original in reader.fieldnames
        }
        sample_columns = [name for name, canonical in header_map.items() if canonical == "sample_name"]
        if len(sample_columns) != 1:
            raise ValueError("Se requiere exactamente una columna sample_name (o muestra)")
        sample_column = sample_columns[0]
        imported_fields = tuple(
            canonical for canonical in METADATA_FIELDS if canonical in header_map.values()
        )
        if not imported_fields:
            raise ValueError("No se reconoció ninguna columna de metadatos")

        values: dict[str, dict[str, str]] = {}
        for line_number, row in enumerate(reader, start=2):
            sample_name = (row.get(sample_column) or "").strip()
            if not sample_name:
                raise ValueError(f"Fila {line_number}: nombre de muestra vacío")
            if sample_name in values:
                raise ValueError(f"Muestra duplicada en metadatos: {sample_name}")
            canonical_row: dict[str, str] = {}
            for original, canonical in header_map.items():
                if canonical in imported_fields:
                    canonical_row[canonical] = (row.get(original) or "").strip()
            values[sample_name] = canonical_row

    dataset_set = set(dataset_samples)
    metadata_set = set(values)
    return MetadataImportResult(
        values=values,
        matched_samples=tuple(name for name in dataset_samples if name in metadata_set),
        missing_samples=tuple(name for name in dataset_samples if name not in metadata_set),
        unknown_samples=tuple(name for name in values if name not in dataset_set),
        imported_fields=imported_fields,
    )
