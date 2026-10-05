from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def normalized_square(source: Path, padding_fraction: float = 0.08) -> Image.Image:
    image = Image.open(source).convert("RGBA")
    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise ValueError(f"El icono no contiene píxeles visibles: {source}")
    cropped = image.crop(alpha_bbox)
    padding = round(max(cropped.size) * padding_fraction)
    side = max(cropped.size) + 2 * padding
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    position = ((side - cropped.width) // 2, (side - cropped.height) // 2)
    canvas.alpha_composite(cropped, position)
    return canvas


def build(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    icon = normalized_square(source)
    rendered: dict[int, Image.Image] = {}
    for size in PNG_SIZES:
        rendered[size] = icon.resize((size, size), Image.Resampling.LANCZOS)
        rendered[size].save(output / f"arii-{size}.png", optimize=True)
    rendered[256].save(output / "arii.ico", format="ICO", sizes=ICO_SIZES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera los iconos de distribución de Arii")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("assets/branding/arii-icon-master.png"),
    )
    parser.add_argument("--output", type=Path, default=Path("assets/icons"))
    arguments = parser.parse_args()
    build(arguments.source, arguments.output)


if __name__ == "__main__":
    main()
