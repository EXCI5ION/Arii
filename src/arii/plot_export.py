from __future__ import annotations

from pyqtgraph import PlotItem
from pyqtgraph.exporters import ImageExporter
from pyqtgraph.Qt import QtWidgets


class ExactSizeImageExporter(ImageExporter):
    """Raster exporter whose width and height can be edited independently."""

    Name = "Imagen Arii (ancho y alto exactos)"

    def widthChanged(self) -> None:
        # ImageExporter normally changes height to retain the on-screen ratio.
        return

    def heightChanged(self) -> None:
        # Keeping both fields independent produces a predictable output canvas.
        return

    def export(self, fileName=None, toBytes=False, copy=False):
        if fileName is None and not toBytes and not copy:
            return super().export(fileName=fileName, toBytes=toBytes, copy=copy)

        if not isinstance(self.item, PlotItem):
            return super().export(fileName=fileName, toBytes=toBytes, copy=copy)

        old_size = self.item.size()
        width = int(self.params["width"])
        height = int(self.params["height"])
        try:
            # Re-layout title, axes and ViewBox at the requested aspect ratio.
            # Merely changing QImage size would retain the screen aspect ratio
            # and center the old plot in a larger background canvas.
            self.item.resize(width, height)
            QtWidgets.QApplication.processEvents()
            return super().export(fileName=fileName, toBytes=toBytes, copy=copy)
        finally:
            self.item.resize(old_size)
            QtWidgets.QApplication.processEvents()


ExactSizeImageExporter.register()
