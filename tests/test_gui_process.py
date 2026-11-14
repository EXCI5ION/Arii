from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
)
import pyqtgraph as pg

from arii.gui import (
    AboutDialog,
    ExecutionProfileDialog,
    MANUAL_FILENAME,
    MainWindow,
    TABLE_COLUMNS,
    settings_application_name,
)


class InterfaceOrganizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setOrganizationName("AriiTests")
        cls.app.setApplicationName("AriiTests")

    def test_graphics_menu_groups_themes_and_styles(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(window.theme_menu.title(), "Tema")
            self.assertEqual(
                [action.text() for action in window.theme_menu.actions()],
                ["Claro", "Oscuro", "Clásico"],
            )
            self.assertEqual(window.style_menu.title(), "Estilo")
            self.assertEqual(
                [action.text() for action in window.style_menu.actions()],
                ["Clases…", "Individuos…"],
            )
            self.assertEqual(
                window.sample_table.horizontalHeaderItem(
                    TABLE_COLUMNS["biological_id"]
                ).text(),
                "Individuo",
            )
            button_texts = {
                button.text() for button in window.findChildren(QPushButton)
            }
            self.assertIn("Asignar individuo a selección", button_texts)
            self.assertNotIn("Estilos de clases…", button_texts)
            self.assertNotIn("Colores de individuos…", button_texts)
            self.assertEqual(self.help_menu_title(window), "Ayuda")
            self.assertEqual(
                [
                    action.text()
                    for action in window.help_menu.actions()
                    if not action.isSeparator()
                ],
                [
                    "Manual",
                    "Documentación",
                    "Documentación GitHub",
                    "Acerca de Arii",
                ],
            )
        finally:
            window._dirty = False
            window.close()

    @staticmethod
    def help_menu_title(window: MainWindow) -> str:
        return window.help_menu.title().replace("&", "")

    def test_help_document_prefers_the_bundled_pdf(self) -> None:
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manual = root / "docs" / "pdf" / MANUAL_FILENAME
                manual.parent.mkdir(parents=True)
                manual.touch()
                with patch("arii.gui.bundle_root", return_value=root), patch(
                    "arii.gui.QDesktopServices.openUrl", return_value=True
                ) as open_url:
                    window.open_manual()
                opened_url = open_url.call_args.args[0]
                self.assertTrue(opened_url.isLocalFile())
                self.assertTrue(
                    os.path.samefile(opened_url.toLocalFile(), manual)
                )
        finally:
            window._dirty = False
            window.close()

    def test_about_dialog_reads_version_and_release_metadata(self) -> None:
        dialog = AboutDialog()
        try:
            text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("Versión:</b> 1.1.0", text)
            self.assertIn("Publicada:</b> 2026-11-13", text)
            self.assertIn("Gabriel Anderson", text)
            self.assertIn("Página del proyecto", text)
        finally:
            dialog.close()

    def test_source_and_installed_preferences_use_different_namespaces(self) -> None:
        self.assertEqual(settings_application_name(frozen=False), "Arii Development")
        self.assertEqual(settings_application_name(frozen=True), "Arii")

    def test_cluster_profile_can_be_cleared_without_touching_credentials(self) -> None:
        class MemorySettings:
            def __init__(self) -> None:
                self.values = {
                    ExecutionProfileDialog.PROFILE_KEY: '{"saved": true}',
                    ExecutionProfileDialog.RESOURCES_KEY: '{"cpus": 8}',
                    "execution/target": "slurm",
                }

            def value(self, key: str, default=None):
                return self.values.get(key, default)

            def setValue(self, key: str, value) -> None:
                self.values[key] = value

            def remove(self, key: str) -> None:
                self.values.pop(key, None)

            def sync(self) -> None:
                pass

        settings = MemorySettings()
        with patch("arii.gui.QSettings", return_value=settings):
            dialog = ExecutionProfileDialog()
        try:
            dialog.host.setText("cluster.example.edu")
            dialog.username.setText("researcher")
            dialog.remote_workspace.setText("/scratch/researcher/arii")
            with patch(
                "arii.gui.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ):
                dialog._reset_saved_profile()

            self.assertIsNone(settings.value(ExecutionProfileDialog.PROFILE_KEY))
            self.assertIsNone(settings.value(ExecutionProfileDialog.RESOURCES_KEY))
            self.assertEqual(settings.value("execution/target"), "local")
            self.assertEqual(dialog.profile_name.text(), "Mi clúster")
            self.assertEqual(dialog.host.text(), "")
            self.assertEqual(dialog.port.value(), 22)
            self.assertEqual(dialog.username.text(), "")
            self.assertEqual(dialog.remote_workspace.text(), "")
            self.assertEqual(dialog.partition.text(), "")
        finally:
            dialog.close()

    def test_classic_theme_forces_windows_style_and_light_palette(self) -> None:
        window = MainWindow()
        previous_theme = window._display_theme
        try:
            window._set_plot_theme("classic", redraw=False)

            self.assertEqual(window._display_theme, "classic")
            self.assertEqual(window._plot_theme, "light")
            self.assertTrue(window.theme_actions["classic"].isChecked())
            self.assertEqual(self.app.style().objectName().lower(), "windows")
            window_colour = self.app.palette().color(QPalette.ColorRole.Window)
            self.assertGreater(window_colour.lightness(), 128)
        finally:
            restored = str(previous_theme)
            if restored not in {"light", "dark", "classic"}:
                restored = "dark"
            window._set_plot_theme(restored, redraw=False)
            window._dirty = False
            window.close()


class ProcessLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        if self.window.process is not None:
            self.window.process.blockSignals(True)
            self.window.process.kill()
            self.window.process.deleteLater()
            self.window.process = None
        self.window.close()

    def test_local_preparation_failure_does_not_leave_phantom_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "arii.gui.LocalRBackend.command_for",
            side_effect=FileNotFoundError("No se encontró Rscript"),
        ), patch("arii.gui.QMessageBox.critical") as critical:
            root = Path(directory)
            started = self.window._start_r_job(
                worker=root / "pca_worker.R",
                job_path=root / "job.json",
                result_path=root / "result.json",
                dataset_path=root / "dataset.csv",
                stamp="test",
                finished_callback=lambda *_args: None,
                local_status="Ejecutando PCA…",
                method="pca",
            )

        self.assertFalse(started)
        self.assertIsNone(self.window.process)
        self.assertFalse(self.window._process_is_remote)
        critical.assert_called_once()
        self.assertIn("Rscript", critical.call_args.args[2])

    def test_failed_to_start_signal_restores_process_state(self) -> None:
        process = QProcess(self.window)
        process.setProgram("Rscript-que-no-existe.exe")
        self.window.process = process
        self.window._process_is_remote = False
        self.window._active_process_name = "modelo"

        with patch("arii.gui.QMessageBox.critical") as critical:
            self.window._process_error(QProcess.ProcessError.FailedToStart)

        self.assertIsNone(self.window.process)
        self.assertFalse(self.window._process_is_remote)
        self.assertEqual(self.window._active_process_name, "")
        critical.assert_called_once()
        message = critical.call_args.args[2]
        self.assertIn("modelo local", message)
        self.assertIn("Rscript-que-no-existe.exe", message)


class IndividualScoreBorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        rows = (
            ("m1", "Control", "Sana"),
            ("m2", "Control", "Infectada"),
            ("m3", "Tratada", "Sana"),
            ("m4", "Tratada", "Infectada"),
        )
        self.window.sample_table.setRowCount(len(rows))
        for row, (sample, primary, individual) in enumerate(rows):
            for column, value in (
                (TABLE_COLUMNS["included"], ""),
                (TABLE_COLUMNS["sample_name"], sample),
                (TABLE_COLUMNS["class"], primary),
                (TABLE_COLUMNS["biological_id"], individual),
            ):
                self.window.sample_table.setItem(row, column, QTableWidgetItem(value))
        self.window.result = {
            "scores": [[-2, -1], [-1, 1], [1, -1], [2, 1]],
            "classes": ["Control", "Control", "Tratada", "Tratada"],
            "sample_names": ["m1", "m2", "m3", "m4"],
            "explained_variance": [0.6, 0.25],
            "component_names": ["PC1", "PC2"],
        }
        self.window.x_component.addItems(["PC1", "PC2"])
        self.window.y_component.addItems(["PC1", "PC2"])
        self.window.y_component.setCurrentIndex(1)
        self.window.hotelling_level.setCurrentIndex(0)

    def tearDown(self) -> None:
        self.window._dirty = False
        self.window.close()

    def _score_scatters(self) -> list[pg.ScatterPlotItem]:
        return [
            item for item in self.window.score_plot.items()
            if isinstance(item, pg.ScatterPlotItem)
        ]

    def test_individual_splits_points_and_adds_two_legend_dimensions(self) -> None:
        self.window.update_score_plot()

        self.assertEqual(len(self._score_scatters()), 4)
        self.assertEqual(len(self.window.score_legend.items), 4)
        self.assertEqual(set(self.window.individual_colors), {"Sana", "Infectada"})
        for scatter in self._score_scatters():
            self.assertAlmostEqual(scatter.opts["pen"].widthF(), 1.5)
        legend_labels = [
            label.text for _sample, label in self.window.score_legend.items
        ]
        self.assertEqual(
            legend_labels,
            ["Control", "Tratada", "Sana", "Infectada"],
        )
        self.assertFalse(any("Relleno" in label for label in legend_labels))
        self.assertFalse(any("Borde" in label for label in legend_labels))

    def test_individual_border_can_be_hidden_without_changing_primary_classes(self) -> None:
        self.window.show_individual_border.setChecked(False)

        self.assertEqual(len(self._score_scatters()), 2)
        self.assertEqual(len(self.window.score_legend.items), 2)


class DatasetOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dataset_opens_directly_with_automatic_interpretation(self) -> None:
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "spectra.csv"
                path.write_text(
                    "ppm,m1,m2,m3\n"
                    "1.0,1,2,3\n"
                    "2.0,2,3,4\n"
                    "3.0,3,4,5\n"
                    "4.0,4,5,6\n",
                    encoding="utf-8",
                )
                with patch(
                    "arii.gui.QFileDialog.getOpenFileName",
                    return_value=(str(path), "Datos (*.csv)"),
                ):
                    window.open_dataset()

            self.assertIsNotNone(window.dataset)
            self.assertEqual(window.dataset.orientation, "variables_by_samples")
            self.assertEqual(window.dataset.representation, "continuous_profile")
            self.assertEqual(window.dataset.modality, "1H-NMR")
            self.assertTrue(window.run_button.isEnabled())
            self.assertEqual(window.sample_table.rowCount(), 3)
        finally:
            window._dirty = False
            window.close()

    def test_stocsy_uses_the_complete_loaded_dataset(self) -> None:
        window = MainWindow()
        window.dataset = object()
        window.result = {"sample_names": ["model-sample-only"]}
        matrix = [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]]
        axis = [1.0, 2.0]
        stocsy_result = object()
        try:
            with patch(
                "arii.gui.load_numeric_matrix",
                return_value=(matrix, axis, ("all-1", "all-2", "all-3")),
            ) as load_matrix, patch(
                "arii.gui.compute_stocsy", return_value=stocsy_result
            ) as compute, patch("arii.gui.StocsyDialog") as dialog:
                window._open_stocsy_dialog(1.2)

            load_matrix.assert_called_once_with(window.dataset)
            compute.assert_called_once_with(matrix, axis, 1.2)
            dialog.assert_called_once_with(
                stocsy_result,
                plot_theme=window._plot_theme,
                parent=window,
            )
            dialog.return_value.exec.assert_called_once()
        finally:
            window._dirty = False
            window.close()

    def test_stocsy_crosshair_uses_the_configured_style(self) -> None:
        window = MainWindow()
        try:
            window._install_stocsy_crosshair()

            for line in (
                window._stocsy_crosshair_x,
                window._stocsy_crosshair_y,
            ):
                self.assertIsNotNone(line)
                pen = line.pen
                self.assertEqual(pen.color().name().upper(), "#AA0000")
                self.assertAlmostEqual(pen.color().alphaF(), 0.65, places=2)
                self.assertAlmostEqual(pen.widthF(), 1.5)
        finally:
            window._dirty = False
            window.close()


if __name__ == "__main__":
    unittest.main()
