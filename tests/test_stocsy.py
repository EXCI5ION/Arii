from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

import numpy as np
import pyqtgraph as pg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from arii.omics_matrix import inspect_omics_matrix
from arii.stocsy import compute_stocsy, load_numeric_matrix
from arii.stocsy_view import StocsyDialog


class StocsyCalculationTests(unittest.TestCase):
    def test_covariance_uses_samples_and_correlation_preserves_sign(self) -> None:
        matrix = np.asarray([
            [1.0, 4.0, 3.0],
            [2.0, 3.0, 3.0],
            [3.0, 2.0, 3.0],
            [4.0, 1.0, 3.0],
        ])
        result = compute_stocsy(matrix, [1.0, 2.0, 3.0], pivot=1.1)

        self.assertEqual(result.pivot_index, 0)
        self.assertEqual(result.pivot_value, 1.0)
        self.assertAlmostEqual(result.covariance[0], np.var(matrix[:, 0], ddof=1))
        self.assertAlmostEqual(result.correlation[0], 1.0)
        self.assertAlmostEqual(result.correlation[1], -1.0)
        self.assertTrue(np.isnan(result.correlation[2]))

    def test_constant_pivot_is_rejected(self) -> None:
        matrix = np.asarray([
            [1.0, 2.0],
            [1.0, 3.0],
            [1.0, 4.0],
        ])
        with self.assertRaisesRegex(ValueError, "no presenta variación"):
            compute_stocsy(matrix, [1.0, 2.0], pivot=1.0)


class StocsyMatrixLoadingTests(unittest.TestCase):
    def test_loads_variables_by_samples_and_restores_model_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectra.csv"
            path.write_text(
                "ppm,m1,m2,m3\n"
                "1.0,1,2,3\n"
                "2.0,4,5,6\n",
                encoding="utf-8",
            )
            summary = inspect_omics_matrix(
                path,
                orientation="variables_by_samples",
                representation="continuous_profile",
                modality="1H-NMR",
                axis_label="ppm",
            )
            matrix, axis, names = load_numeric_matrix(
                summary, sample_names=("m3", "m1")
            )

        np.testing.assert_allclose(axis, [1.0, 2.0])
        np.testing.assert_allclose(matrix, [[3.0, 6.0], [1.0, 4.0]])
        self.assertEqual(names, ("m3", "m1"))

    def test_loads_samples_by_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spectra.csv"
            path.write_text(
                "sample,1.0,2.0\n"
                "m1,1,4\n"
                "m2,2,5\n"
                "m3,3,6\n",
                encoding="utf-8",
            )
            summary = inspect_omics_matrix(
                path,
                orientation="samples_by_variables",
                representation="continuous_profile",
                modality="1H-NMR",
                axis_label="ppm",
            )
            matrix, axis, names = load_numeric_matrix(summary)

        np.testing.assert_allclose(axis, [1.0, 2.0])
        np.testing.assert_allclose(matrix, [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
        self.assertEqual(names, ("m1", "m2", "m3"))


class StocsyDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_renders_signed_and_absolute_views(self) -> None:
        result = compute_stocsy(
            np.asarray([
                [1.0, 4.0, 2.0],
                [2.0, 3.0, 4.0],
                [3.0, 2.0, 5.0],
                [4.0, 1.0, 8.0],
            ]),
            [1.0, 2.0, 3.0],
            pivot=1.0,
        )
        dialog = StocsyDialog(result, plot_theme="light")
        dialog.show()
        self.app.processEvents()
        self.assertGreater(len(dialog.covariance_plot.items()), 0)
        self.assertGreater(len(dialog.mean_plot.items()), 0)
        self.assertFalse(any(
            isinstance(item, pg.InfiniteLine)
            for item in dialog.covariance_plot.items()
        ))
        self.assertIn("pivote 1", dialog.covariance_plot.getPlotItem().titleLabel.text)
        self.assertIn("dataset completo", dialog.summary.text())
        self.assertIsInstance(dialog.colorbar, pg.ColorBarItem)
        self.assertIsInstance(dialog.mean_colorbar, pg.ColorBarItem)
        covariance_width = (
            dialog.covariance_plot.getPlotItem().vb.sceneBoundingRect().width()
        )
        mean_width = dialog.mean_plot.getPlotItem().vb.sceneBoundingRect().width()
        self.assertAlmostEqual(covariance_width, mean_width, places=1)

        dialog.correlation_mode.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(dialog.correlation_mode.currentData(), "absolute")
        self.assertEqual(tuple(dialog.colorbar.levels()), (0.0, 1.0))
        self.assertEqual(tuple(dialog.mean_colorbar.levels()), (0.0, 1.0))
        self.assertGreater(len(dialog.covariance_plot.items()), 0)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
