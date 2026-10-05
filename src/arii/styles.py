from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ClassStyle:
    color: str
    symbol: str = "o"
    size: int = 10

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "ClassStyle":
        return cls(
            color=str(value["color"]),
            symbol=str(value.get("symbol", "o")),
            size=int(value.get("size", 10)),
        )
