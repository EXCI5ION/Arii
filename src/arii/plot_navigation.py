from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt


class SpectralNavigationViewBox(pg.ViewBox):
    """Axis-specific navigation for dense profiles with selectable plot areas."""

    def wheelEvent(self, event, axis=None) -> None:
        # AxisItem supplies its own axis explicitly and remains free to control
        # it. Over the plot: wheel zooms Y, Ctrl+wheel zooms X, Shift+wheel
        # pans X, and Alt+wheel pans Y.
        if axis is not None:
            super().wheelEvent(event, axis=axis)
            return
        modifiers = (
            event.modifiers()
            if hasattr(event, "modifiers")
            else Qt.KeyboardModifier.NoModifier
        )
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event, axis=0)
            return
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            delta = self._wheel_delta(event)
            if delta:
                x_min, x_max = self.viewRange()[0]
                shift = (delta / 120.0) * (x_max - x_min) * 0.1
                self.translateBy(x=shift, y=0.0)
            event.accept()
            return
        if modifiers & Qt.KeyboardModifier.AltModifier:
            delta = self._wheel_delta(event)
            if delta:
                y_min, y_max = self.viewRange()[1]
                shift = (delta / 120.0) * (y_max - y_min) * 0.1
                self.translateBy(x=0.0, y=shift)
            event.accept()
            return
        super().wheelEvent(event, axis=1)

    @staticmethod
    def _wheel_delta(event) -> float:
        if hasattr(event, "angleDelta"):
            angle_delta = event.angleDelta()
            if hasattr(angle_delta, "y") and angle_delta.y():
                return float(angle_delta.y())
            if hasattr(angle_delta, "x") and angle_delta.x():
                return float(angle_delta.x())
        if hasattr(event, "delta"):
            return float(event.delta())
        return 0.0

    def mouseDragEvent(self, event, axis=None) -> None:
        # Plot-area dragging stays disabled because clicks may be assigned to
        # spectral selection. Dragging directly over an axis remains enabled.
        if axis is not None:
            super().mouseDragEvent(event, axis=axis)
            return
        if hasattr(event, "accept"):
            event.accept()


# Preserve the public name already used by Arii and third-party tests.
LoadingValueViewBox = SpectralNavigationViewBox
