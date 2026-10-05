from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


Orientation = Literal["variables_by_samples", "samples_by_variables"]


@dataclass(frozen=True)
class DatasetSpec:
    path: str
    delimiter: str = ","
    orientation: Orientation = "variables_by_samples"
    axis_column: int = 0
    representation: Literal["continuous_profile", "feature_table"] = "continuous_profile"
    modality: str = "1H-NMR"

    def validate(self) -> None:
        if not self.path.strip():
            raise ValueError("dataset.path no puede estar vacío")
        if len(self.delimiter) != 1:
            raise ValueError("dataset.delimiter debe tener un carácter")
        if self.axis_column < 0:
            raise ValueError("dataset.axis_column no puede ser negativo")
        if not self.modality.strip():
            raise ValueError("dataset.modality no puede estar vacía")


@dataclass(frozen=True)
class PreprocessingSpec:
    mean_center: bool = True
    scaling: Literal["none", "pareto", "unit_variance"] = "pareto"


@dataclass(frozen=True)
class ValidationSpec:
    strategy: Literal[
        "none", "random_subsets", "monte_carlo", "leave_one_out", "venetian_blinds"
    ] = "none"
    repeats: int = 20
    data_splits: int = 5
    train_fraction: float = 0.8
    seed: int = 1234

    def validate(self) -> None:
        if self.repeats < 1:
            raise ValueError("validation.repeats debe ser positivo")
        if self.data_splits < 2:
            raise ValueError("validation.data_splits debe ser al menos 2")
        if not 0 < self.train_fraction < 1:
            raise ValueError("validation.train_fraction debe estar entre 0 y 1")


@dataclass(frozen=True)
class AnalysisSpec:
    dataset: DatasetSpec
    method: Literal["pca", "plsda", "orthogonalized_plsda"] = "pca"
    preprocessing: PreprocessingSpec = field(default_factory=PreprocessingSpec)
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    selected_groups: tuple[str, ...] = ()
    n_components: int | None = None
    random_seed: int = 1234
    schema_version: str = "1.0"

    def validate(self) -> None:
        self.dataset.validate()
        self.validation.validate()
        if self.n_components is not None and self.n_components < 1:
            raise ValueError("n_components debe ser positivo")

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    @classmethod
    def for_spectral_csv(cls, path: str | Path) -> "AnalysisSpec":
        return cls(dataset=DatasetSpec(path=str(path)))
