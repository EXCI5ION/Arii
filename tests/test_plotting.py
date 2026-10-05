from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from arii.gui import LoadingValueViewBox
from arii.plot_export import ExactSizeImageExporter


class PlotInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_plot_area_routes_wheel_to_y_and_drag_to_x(self) -> None:
        view_box = LoadingValueViewBox()
        event = object()
        with patch.object(pg.ViewBox, "wheelEvent", autospec=True) as parent_wheel:
            view_box.wheelEvent(event)
            parent_wheel.assert_called_once_with(view_box, event, axis=1)
        with patch.object(pg.ViewBox, "mouseDragEvent", autospec=True) as parent_drag:
            view_box.mouseDragEvent(event)
            parent_drag.assert_called_once_with(view_box, event, axis=0)

    def test_explicit_axis_is_preserved(self) -> None:
        view_box = LoadingValueViewBox()
        event = object()
        with patch.object(pg.ViewBox, "mouseDragEvent", autospec=True) as parent_drag:
            view_box.mouseDragEvent(event, axis=1)
            parent_drag.assert_called_once_with(view_box, event, axis=1)

    def test_exact_size_exporter_keeps_dimensions_independent(self) -> None:
        plot = pg.PlotWidget()
        plot.resize(640, 480)
        self.app.processEvents()
        original_plot_size = plot.getPlotItem().size()
        exporter = ExactSizeImageExporter(plot.getPlotItem())
        exporter.params.param("width").setValue(1000)
        exporter.params.param("height").setValue(700)
        self.assertEqual(exporter.params["width"], 1000)
        self.assertEqual(exporter.params["height"], 700)
        image = exporter.export(toBytes=True)
        self.assertEqual((image.width(), image.height()), (1000, 700))
        self.assertEqual(plot.getPlotItem().size(), original_plot_size)
        plot.close()


if __name__ == "__main__":
    unittest.main()
