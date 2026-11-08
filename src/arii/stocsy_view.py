from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arii.stocsy import StocsyResult


def _jet_colormap() -> pg.ColorMap:
    positions = np.linspace(0.0, 1.0, 256)
    red = np.clip(1.5 - np.abs(4 * positions - 3), 0, 1)
    green = np.clip(1.5 - np.abs(4 * positions - 2), 0, 1)
    blue = np.clip(1.5 - np.abs(4 * positions - 1), 0, 1)
    colors = np.column_stack((red, green, blue, np.ones_like(positions))) * 255
    return pg.ColorMap(positions, colors.astype(np.uint8), name="STOCSY jet")


STOCSY_JET = _jet_colormap()


class StocsyDialog(QDialog):
    """Transient two-panel view of a STOCSY calculation."""

    def __init__(
        self,
        result: StocsyResult,
        *,
        plot_theme: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.plot_theme = plot_theme
        self.setWindowTitle(f"S-TOCSY — pivote {result.pivot_value:.6g} ppm")
        self.resize(1100, 760)

        self.correlation_mode = QComboBox()
        self.correlation_mode.addItem("Correlación con signo", "signed")
        self.correlation_mode.addItem("Correlación absoluta", "absolute")
        self.correlation_mode.currentIndexChanged.connect(self._redraw)

        save_button = QPushButton("Guardar figura…")
        save_button.clicked.connect(self._save_figure)
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Color"))
        controls.addWidget(self.correlation_mode)
        controls.addStretch(1)
        controls.addWidget(save_button)
        controls.addWidget(close_button)

        self.summary = QLabel(
            f"Pivote: {result.pivot_value:.6g} ppm · dataset completo: "
            f"{result.sample_count} muestras · covarianza muestral (n−1)"
        )
        self.covariance_plot = pg.PlotWidget(
            title=f"S-TOCSY — pivote {result.pivot_value:.6g} ppm"
        )
        self.mean_plot = pg.PlotWidget(title="Perfil promedio")
        for plot, label in (
            (self.covariance_plot, "Covarianza"),
            (self.mean_plot, "Intensidad media"),
        ):
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("bottom", "Corrimiento químico", units="ppm")
            plot.setLabel("left", label)
            plot.invertX(True)
        self.mean_plot.setXLink(self.covariance_plot)

        background = "#ffffff" if plot_theme == "light" else "#111827"
        foreground = "#111827" if plot_theme == "light" else "#e5e7eb"
        for plot in (self.covariance_plot, self.mean_plot):
            plot.setBackground(background)
            for axis in ("left", "bottom"):
                plot.getAxis(axis).setTextPen(foreground)
                plot.getAxis(axis).setPen(foreground)

        self.colorbar = pg.ColorBarItem(
            values=(-1.0, 1.0),
            colorMap=STOCSY_JET,
            label="Correlación de Pearson",
            interactive=False,
            colorMapMenu=False,
        )
        self.colorbar.setImageItem(
            [], insert_in=self.covariance_plot.getPlotItem()
        )
        self.mean_colorbar = pg.ColorBarItem(
            values=(-1.0, 1.0),
            colorMap=STOCSY_JET,
            label="Correlación de Pearson",
            interactive=False,
            colorMapMenu=False,
        )
        self.mean_colorbar.setImageItem(
            [], insert_in=self.mean_plot.getPlotItem()
        )

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.summary)
        layout.addWidget(self.covariance_plot, 1)
        layout.addWidget(self.mean_plot, 1)
        self._redraw()

    def _redraw(self, _index: int | None = None) -> None:
        signed = self.correlation_mode.currentData() == "signed"
        colour_values = (
            self.result.correlation
            if signed else np.abs(self.result.correlation)
        )
        levels = (-1.0, 1.0) if signed else (0.0, 1.0)
        self.colorbar.setLevels(levels, update_items=False)
        self.mean_colorbar.setLevels(levels, update_items=False)

        for plot, values in (
            (self.covariance_plot, self.result.covariance),
            (self.mean_plot, self.result.mean_profile),
        ):
            plot.clear()
            self._add_coloured_curve(plot, self.result.axis, values, colour_values, levels)
            finite_axis = self.result.axis[np.isfinite(self.result.axis)]
            if finite_axis.size >= 2:
                x_min, x_max = float(finite_axis.min()), float(finite_axis.max())
                span = x_max - x_min
                plot.setLimits(
                    xMin=x_min,
                    xMax=x_max,
                    minXRange=max(span * 1e-9, np.finfo(float).eps),
                    maxXRange=span,
                )
                plot.setXRange(x_min, x_max, padding=0)

    @staticmethod
    def _add_coloured_curve(
        plot: pg.PlotWidget,
        axis: np.ndarray,
        values: np.ndarray,
        colours: np.ndarray,
        levels: tuple[float, float],
    ) -> None:
        finite = (
            np.isfinite(axis[:-1]) & np.isfinite(axis[1:])
            & np.isfinite(values[:-1]) & np.isfinite(values[1:])
            & np.isfinite(colours[:-1]) & np.isfinite(colours[1:])
        )
        indices = np.flatnonzero(finite)
        if not indices.size:
            return
        segment_colours = (colours[indices] + colours[indices + 1]) / 2
        low, high = levels
        bins = np.clip(
            np.floor((segment_colours - low) / (high - low) * 127),
            0,
            127,
        ).astype(int)
        for colour_bin in np.unique(bins):
            selected = indices[bins == colour_bin]
            x_pairs = np.empty(selected.size * 2, dtype=float)
            y_pairs = np.empty(selected.size * 2, dtype=float)
            x_pairs[0::2], x_pairs[1::2] = axis[selected], axis[selected + 1]
            y_pairs[0::2], y_pairs[1::2] = values[selected], values[selected + 1]
            colour = STOCSY_JET.mapToQColor((colour_bin + 0.5) / 128)
            plot.plot(
                x_pairs,
                y_pairs,
                connect="pairs",
                pen=pg.mkPen(colour, width=1.0),
                skipFiniteCheck=True,
            )

    def _save_figure(self) -> None:
        default_name = f"STOCSY_{self.result.pivot_value:.6g}_ppm.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar figura S-TOCSY",
            default_name,
            "Imagen PNG (*.png);;Imagen TIFF (*.tif *.tiff)",
        )
        if not path:
            return
        destination = Path(path)
        image = self.grab()
        if not image.save(str(destination)):
            QMessageBox.critical(
                self, "No se pudo guardar", f"No se pudo escribir {destination}."
            )
