from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from arii.gui import MainWindow


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


if __name__ == "__main__":
    unittest.main()
