from __future__ import annotations

import csv
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QProcess, QProcessEnvironment, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from arii.execution import (
    ClusterProfile, LocalRBackend, RJob, SlurmBackend, SlurmResources,
)
from arii.loading_values import backscaled_loading_values
from arii import plot_export as _plot_export  # Register Arii's exact-size exporter.
from arii.project_file import fingerprint_file, load_project, save_project
from arii.metadata import import_metadata
from arii.metrics import binary_roc, mean_external_scores, sensitivity_specificity_curve
from arii.omics_matrix import OmicsMatrixSummary, inspect_omics_matrix
from arii.styles import ClassStyle
from arii.ssh_access import provision_managed_key
from arii.system_resources import detect_system_resources, recommended_workers
from arii.resources import asset_path, worker_path
from arii.r_bridge import r_subprocess_environment
from arii.remote_runner import launcher_command, main as remote_runner_main


CLASS_COLORS = [
    "#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c",
    "#0891b2", "#be123c", "#4f46e5", "#65a30d", "#a16207",
]

SYMBOLS = {
    "Círculo": "o",
    "Cuadrado": "s",
    "Triángulo": "t",
    "Rombo": "d",
    "Cruz": "+",
    "Equis": "x",
    "Estrella": "star",
}

TABLE_COLUMNS = {
    "included": 0,
    "sample_name": 1,
    "class": 2,
    "biological_id": 3,
}


def _matlab_jet_colormap() -> pg.ColorMap:
    positions = np.linspace(0.0, 1.0, 256)
    red = np.clip(1.5 - np.abs(4 * positions - 3), 0, 1)
    green = np.clip(1.5 - np.abs(4 * positions - 2), 0, 1)
    blue = np.clip(1.5 - np.abs(4 * positions - 1), 0, 1)
    colors = np.column_stack((red, green, blue, np.ones_like(positions))) * 255
    return pg.ColorMap(positions, colors.astype(np.uint8), name="MATLAB jet")


MATLAB_JET = _matlab_jet_colormap()


class LoadingValueViewBox(pg.ViewBox):
    """ViewBox with axis-specific navigation for dense spectral curves."""

    def wheelEvent(self, event, axis=None) -> None:
        # Over the plot, the wheel changes only the vertical scale. AxisItem
        # supplies its own axis explicitly and remains free to control it.
        super().wheelEvent(event, axis=1 if axis is None else axis)

    def mouseDragEvent(self, event, axis=None) -> None:
        # Plot-area drags pan (left) or zoom (right) only along ppm. Dragging
        # directly over the Y axis arrives with axis=1 and therefore moves Y.
        super().mouseDragEvent(event, axis=0 if axis is None else axis)


class MetadataTableWidget(QTableWidget):
    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == TABLE_COLUMNS["included"]:
            selected_rows = sorted({item.row() for item in self.selectedIndexes()})
            if index.row() not in selected_rows:
                self.clearSelection()
                self.selectRow(index.row())
                selected_rows = [index.row()]
            item = self.item(index.row(), TABLE_COLUMNS["included"])
            new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            for row in selected_rows:
                self.item(row, TABLE_COLUMNS["included"]).setCheckState(new_state)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_tabular()
            return
        if event.key() == Qt.Key_Space:
            selected_rows = sorted({item.row() for item in self.selectedIndexes()})
            if selected_rows:
                first = self.item(selected_rows[0], TABLE_COLUMNS["included"])
                new_state = (
                    Qt.Unchecked if first.checkState() == Qt.Checked else Qt.Checked
                )
                for row in selected_rows:
                    self.item(row, TABLE_COLUMNS["included"]).setCheckState(new_state)
                return
        super().keyPressEvent(event)

    def _paste_tabular(self) -> None:
        selected = self.selectedIndexes()
        if not selected:
            return
        start_row = min(index.row() for index in selected)
        start_column = max(2, min(index.column() for index in selected))
        rows = [line.split("\t") for line in QApplication.clipboard().text().splitlines()]
        for row_offset, values in enumerate(rows):
            target_row = start_row + row_offset
            if target_row >= self.rowCount():
                break
            for column_offset, value in enumerate(values):
                target_column = start_column + column_offset
                if target_column >= self.columnCount():
                    break
                self.item(target_row, target_column).setText(value.strip())


class ClassStyleDialog(QDialog):
    def __init__(self, styles: dict[str, ClassStyle], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Estilos de clases")
        self.styles = {
            name: ClassStyle(style.color, style.symbol, style.size)
            for name, style in styles.items()
        }
        self._active_class: str | None = None
        self._color = "#2563eb"

        self.class_combo = QComboBox()
        self.class_combo.addItems(self.styles)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._choose_color)
        self.symbol_combo = QComboBox()
        self.symbol_combo.addItems(SYMBOLS)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(4, 30)

        form = QFormLayout()
        form.addRow("Clase", self.class_combo)
        form.addRow("Color", self.color_button)
        form.addRow("Forma", self.symbol_combo)
        form.addRow("Tamaño", self.size_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_styles)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.class_combo.currentTextChanged.connect(self._switch_class)
        if self.class_combo.count():
            self._switch_class(self.class_combo.currentText())

    def _save_active(self) -> None:
        if self._active_class is None:
            return
        self.styles[self._active_class] = ClassStyle(
            color=self._color,
            symbol=SYMBOLS[self.symbol_combo.currentText()],
            size=self.size_spin.value(),
        )

    def _switch_class(self, class_name: str) -> None:
        self._save_active()
        self._active_class = class_name
        style = self.styles[class_name]
        self._color = style.color
        self._update_color_button()
        symbol_name = next((name for name, value in SYMBOLS.items() if value == style.symbol), "Círculo")
        self.symbol_combo.setCurrentText(symbol_name)
        self.size_spin.setValue(style.size)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Color de la clase")
        if color.isValid():
            self._color = color.name()
            self._update_color_button()

    def _update_color_button(self) -> None:
        self.color_button.setText(self._color)
        self.color_button.setStyleSheet(
            f"background-color: {self._color}; color: white; padding: 5px;"
        )

    def _accept_styles(self) -> None:
        self._save_active()
        self.accept()


class ExecutionProfileDialog(QDialog):
    """Per-user, non-secret Slurm profile editor."""

    PROFILE_KEY = "execution/slurm_profile"
    RESOURCES_KEY = "execution/slurm_resources"
    LOCAL_KEY = "execution/local_resources"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar recursos y ejecución Slurm")
        self.resize(720, 720)
        self.settings = QSettings()
        self.system_resources = detect_system_resources()

        intro = QLabel(
            "Este perfil permite enviar cálculos al clúster mediante la conexión "
            "SSH integrada, OpenSSH o PuTTY. Arii nunca almacena contraseñas ni "
            "incluye secretos en los proyectos."
        )
        intro.setWordWrap(True)

        memory_text = (
            f"{self.system_resources.total_memory_mb / 1024:.1f} GB RAM"
            if self.system_resources.total_memory_mb is not None else "RAM no detectada"
        )
        gpu_text = ", ".join(self.system_resources.gpu_names) or "sin GPU NVIDIA compatible detectada"
        detected = QLabel(
            f"Equipo local: {self.system_resources.logical_cpus} CPU lógicas, "
            f"{memory_text}; {gpu_text}. mixOmics utiliza CPU."
        )
        detected.setWordWrap(True)
        self.reserved_local_cpus = QSpinBox()
        self.reserved_local_cpus.setRange(
            2, max(2, self.system_resources.logical_cpus - 1)
        )
        self.reserved_local_cpus.setValue(
            min(3, max(2, self.system_resources.logical_cpus - 1))
        )
        local_form = QFormLayout()
        local_form.addRow("CPU reservadas para Windows", self.reserved_local_cpus)

        self.profile_name = QLineEdit("Mi clúster")
        self.host = QLineEdit()
        self.host.setPlaceholderText("login.cluster.universidad.edu o alias SSH")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(22)
        self.username = QLineEdit()
        self.remote_workspace = QLineEdit()
        self.remote_workspace.setPlaceholderText("/scratch/mi_usuario/arii")
        self.authentication = QComboBox()
        self.authentication.addItem("Clave administrada por Arii", "arii_managed_key")
        self.authentication.addItem("OpenSSH / ssh-agent (avanzado)", "ssh_agent")
        self.authentication.addItem("Alias de configuración OpenSSH", "openssh_config")
        self.authentication.addItem("Pageant/PuTTY (Windows)", "pageant")
        self.ssh_alias = QLineEdit()
        self.ssh_alias.setPlaceholderText("Opcional; por ejemplo cluster-universidad")
        self.account = QLineEdit(); self.account.setPlaceholderText("Opcional")
        self.partition = QLineEdit(); self.partition.setPlaceholderText("Opcional")
        self.qos = QLineEdit(); self.qos.setPlaceholderText("Opcional")
        self.rscript_path = QLineEdit()
        self.rscript_path.setPlaceholderText(
            "Opcional; Arii usará su entorno administrado si queda vacío"
        )

        connection_form = QFormLayout()
        connection_form.addRow("Nombre del perfil", self.profile_name)
        connection_form.addRow("Servidor de acceso", self.host)
        connection_form.addRow("Puerto SSH", self.port)
        connection_form.addRow("Usuario individual", self.username)
        connection_form.addRow("Carpeta remota de Arii", self.remote_workspace)
        connection_form.addRow("Autenticación", self.authentication)
        connection_form.addRow("Alias SSH", self.ssh_alias)
        connection_form.addRow("Cuenta Slurm", self.account)
        connection_form.addRow("Partición", self.partition)
        connection_form.addRow("QOS", self.qos)
        connection_form.addRow("Rscript remoto", self.rscript_path)

        managed_access_note = QLabel(
            "Para la clave administrada, Arii solicita la contraseña una sola vez, "
            "instala una clave pública Ed25519 y guarda su secreto cifrado en el "
            "almacén de credenciales del sistema."
        )
        managed_access_note.setWordWrap(True)
        configure_managed_access_button = QPushButton(
            "Configurar acceso automático con contraseña…"
        )
        configure_managed_access_button.clicked.connect(self._configure_managed_access)

        self.cpus = QSpinBox(); self.cpus.setRange(1, 256); self.cpus.setValue(1)
        self.nodes = QSpinBox(); self.nodes.setRange(1, 64); self.nodes.setValue(1)
        self.memory_mb = QSpinBox()
        self.memory_mb.setRange(256, 1_048_576); self.memory_mb.setSingleStep(1024)
        self.memory_mb.setValue(8192); self.memory_mb.setSuffix(" MB")
        self.walltime = QSpinBox()
        self.walltime.setRange(1, 10_080); self.walltime.setValue(120)
        self.walltime.setSuffix(" min")
        resource_form = QFormLayout()
        resource_form.addRow("Nodos máximos (permutaciones)", self.nodes)
        resource_form.addRow("CPU por trabajo", self.cpus)
        resource_form.addRow("Memoria", self.memory_mb)
        resource_form.addRow("Tiempo máximo", self.walltime)

        environment_note = QLabel(
            "Requisito del clúster: Rscript y los paquetes mixOmics y jsonlite "
            "deben estar disponibles en los nodos de cálculo. Puede utilizar el "
            "runtime de servidor publicado con Arii o un entorno administrado por "
            "su institución, e indicar arriba la ruta de Rscript."
        )
        environment_note.setWordWrap(True)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Aquí aparecerá una vista segura del trabajo sbatch.")
        self.preview.setMaximumBlockCount(80)
        validate_button = QPushButton("Validar y previsualizar")
        validate_button.clicked.connect(self._preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(detected)
        layout.addLayout(local_form)
        layout.addLayout(connection_form)
        layout.addWidget(managed_access_note)
        layout.addWidget(configure_managed_access_button)
        layout.addLayout(resource_form)
        layout.addWidget(environment_note)
        layout.addWidget(validate_button)
        layout.addWidget(self.preview, 1)
        layout.addWidget(buttons)
        self._load()

    @staticmethod
    def _optional(field: QLineEdit) -> str | None:
        value = field.text().strip()
        return value or None

    def _values(self) -> tuple[ClusterProfile, SlurmResources]:
        profile = ClusterProfile(
            profile_id="default-slurm",
            display_name=self.profile_name.text().strip(),
            host=self.host.text().strip(), username=self.username.text().strip(),
            scheduler="slurm", remote_workspace=self.remote_workspace.text().strip(),
            port=self.port.value(), authentication=self.authentication.currentData(),
            ssh_config_host=self._optional(self.ssh_alias),
            account=self._optional(self.account), partition=self._optional(self.partition),
            qos=self._optional(self.qos), rscript_path=self._optional(self.rscript_path),
        )
        resources = SlurmResources(
            cpus=self.cpus.value(), memory_mb=self.memory_mb.value(),
            walltime_minutes=self.walltime.value(), nodes=self.nodes.value(),
        )
        return profile, resources

    def _preview(self) -> bool:
        try:
            profile, resources = self._values()
            submission = SlurmBackend(profile).build_submission(
                "preview-job", "permutation_worker.R", resources
            )
            self.preview.setPlainText(submission.script)
            return True
        except Exception as exc:
            self.preview.clear()
            QMessageBox.warning(self, "Perfil Slurm incompleto", str(exc))
            return False

    def _configure_managed_access(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        managed_index = self.authentication.findData("arii_managed_key")
        self.authentication.setCurrentIndex(managed_index)
        try:
            profile, _ = self._values()
        except Exception as exc:
            QMessageBox.warning(self, "Perfil incompleto", str(exc))
            return
        password, accepted = QInputDialog.getText(
            self,
            "Primer acceso al clúster",
            f"Contraseña SSH de {profile.username}@{profile.host}:\n"
            "Se usará solamente durante esta operación.",
            QLineEdit.Password,
        )
        if not accepted or not password:
            return

        def confirm_host_key(hostname: str, algorithm: str, fingerprint: str) -> bool:
            answer = QMessageBox.question(
                self,
                "Confirmar identidad del servidor",
                f"Servidor: {hostname}\n"
                f"Algoritmo: {algorithm}\n"
                f"Huella: {fingerprint}\n\n"
                "Compare esta huella con la publicada por el administrador del "
                "clúster. ¿Confía en este servidor?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return answer == QMessageBox.Yes

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            key_path = provision_managed_key(profile, password, confirm_host_key)
            self.preview.setPlainText(
                "ACCESO AUTOMÁTICO CONFIGURADO\n\n"
                f"Servidor: {profile.host}:{profile.port}\n"
                f"Usuario: {profile.username}\n"
                f"Clave cifrada: {key_path}\n\n"
                "La contraseña no fue guardada. Pulse Guardar para conservar el perfil."
            )
            QMessageBox.information(
                self,
                "Acceso configurado",
                "La clave Ed25519 fue instalada y Arii comprobó el ingreso "
                "automático correctamente.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo configurar el acceso", str(exc))
        finally:
            password = ""
            QApplication.restoreOverrideCursor()

    def _save(self) -> None:
        if not self._preview():
            return
        profile, resources = self._values()
        self.settings.setValue(
            self.PROFILE_KEY, json.dumps(profile.to_dict(), ensure_ascii=False)
        )
        self.settings.setValue(
            self.RESOURCES_KEY, json.dumps(
                {"cpus": resources.cpus, "memory_mb": resources.memory_mb,
                 "walltime_minutes": resources.walltime_minutes,
                 "nodes": resources.nodes}
            )
        )
        self.settings.setValue(
            self.LOCAL_KEY,
            json.dumps({"reserved_cpus": self.reserved_local_cpus.value()}),
        )
        self.accept()

    def _load(self) -> None:
        try:
            raw_profile = self.settings.value(self.PROFILE_KEY)
            raw_resources = self.settings.value(self.RESOURCES_KEY)
            raw_local = self.settings.value(self.LOCAL_KEY)
            if raw_profile:
                profile = ClusterProfile.from_dict(json.loads(raw_profile))
                self.profile_name.setText(profile.display_name)
                self.host.setText(profile.host); self.port.setValue(profile.port)
                self.username.setText(profile.username)
                self.remote_workspace.setText(profile.remote_workspace)
                auth_index = self.authentication.findData(profile.authentication)
                if auth_index >= 0: self.authentication.setCurrentIndex(auth_index)
                self.ssh_alias.setText(profile.ssh_config_host or "")
                self.account.setText(profile.account or "")
                self.partition.setText(profile.partition or "")
                self.qos.setText(profile.qos or "")
                self.rscript_path.setText(profile.rscript_path or "")
            if raw_resources:
                resources = SlurmResources(**json.loads(raw_resources))
                self.cpus.setValue(resources.cpus)
                self.nodes.setValue(resources.nodes)
                self.memory_mb.setValue(resources.memory_mb)
                self.walltime.setValue(resources.walltime_minutes)
            if raw_local:
                local = json.loads(raw_local)
                self.reserved_local_cpus.setValue(int(local.get("reserved_cpus", 3)))
        except Exception:
            self.preview.setPlainText(
                "El perfil guardado no es válido. Revise los campos y vuelva a guardarlo."
            )


class OmicsImportDialog(QDialog):
    """Confirm the interpretation of a delimited omics matrix."""

    def __init__(self, detected: OmicsMatrixSummary, parent: QWidget | None = None):
        super().__init__(parent)
        self.detected = detected
        self.setWindowTitle("Interpretar matriz ómica")
        self.setMinimumWidth(520)

        self.orientation = QComboBox()
        self.orientation.addItem("Variables × muestras", "variables_by_samples")
        self.orientation.addItem("Muestras × variables", "samples_by_variables")
        self.orientation.setCurrentIndex(
            max(0, self.orientation.findData(detected.proposed_orientation))
        )
        self.representation = QComboBox()
        self.representation.addItem("Perfil continuo", "continuous_profile")
        self.representation.addItem("Tabla de características", "feature_table")
        self.representation.setCurrentIndex(
            max(0, self.representation.findData(detected.representation))
        )
        self.modality = QComboBox()
        self.modality.setEditable(True)
        for name in (
            "1H-NMR", "LC-MS / HPLC-MS", "GC-MS", "HPLC / DAD",
            "Metabolómica genérica", "Proteómica", "Transcriptómica",
            "Genómica", "Matriz ómica genérica",
        ):
            self.modality.addItem(name)
        modality_index = self.modality.findText(detected.modality)
        if modality_index >= 0:
            self.modality.setCurrentIndex(modality_index)
        else:
            self.modality.setEditText(detected.modality)
        self.axis_label = QLineEdit(detected.axis_label)

        self.matrix_summary = QLabel()
        self.matrix_summary.setWordWrap(True)
        self.orientation.currentIndexChanged.connect(self._update_summary)
        self._update_summary()

        explanation = QLabel(
            "Arii propone una interpretación a partir de la forma y los "
            "identificadores, pero debe confirmarla: plataformas distintas pueden "
            "producir matrices numéricamente indistinguibles."
        )
        explanation.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Orientación", self.orientation)
        form.addRow("Representación", self.representation)
        form.addRow("Modalidad", self.modality)
        form.addRow("Etiqueta del eje/variables", self.axis_label)
        form.addRow("Resultado", self.matrix_summary)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        if detected.missing_values:
            missing = QLabel(
                f"El archivo contiene {detected.missing_values} valores ausentes o no "
                "finitos. La imputación aún no está implementada; corrija la matriz "
                "antes de modelar."
            )
            missing.setWordWrap(True)
            missing.setStyleSheet("color: #dc2626;")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        else:
            missing = None

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        if missing is not None:
            layout.addWidget(missing)
        layout.addWidget(self.buttons)

    def _update_summary(self, _index: int | None = None) -> None:
        if self.orientation.currentData() == "variables_by_samples":
            samples, features = self.detected.columns - 1, self.detected.rows
        else:
            samples, features = self.detected.rows, self.detected.columns - 1
        self.matrix_summary.setText(
            f"{samples} muestras × {features:,} variables · "
            f"confianza de detección {self.detected.orientation_confidence}"
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Arii — análisis quimiométrico")
        self.resize(1280, 780)
        self.dataset: OmicsMatrixSummary | None = None
        self.result: dict | None = None
        self.process: QProcess | None = None
        self._process_is_remote = False
        self.system_resources = detect_system_resources()
        self.result_path: Path | None = None
        self.permutation_result_path: Path | None = None
        self.class_styles: dict[str, ClassStyle] = {}
        self.project_path: Path | None = None
        self._dirty = False
        self._loading = False
        self._build_ui()

    def _build_ui(self) -> None:
        open_action = QAction("Abrir dataset…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_dataset)
        open_project_action = QAction("Abrir proyecto…", self)
        open_project_action.setShortcut("Ctrl+Shift+O")
        open_project_action.triggered.connect(self.open_project)
        save_action = QAction("Guardar proyecto", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_current_project)
        save_as_action = QAction("Guardar proyecto como…", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_project_as)
        self.export_action = QAction("Exportar datos de loadings…", self)
        self.export_action.setShortcut("Ctrl+E")
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.export_results)
        import_metadata_action = QAction("Importar clases e individuos…", self)
        import_metadata_action.triggered.connect(self.import_sample_metadata)
        file_menu = self.menuBar().addMenu("Archivo")
        file_menu.addAction(open_action)
        file_menu.addAction(open_project_action)
        file_menu.addAction(import_metadata_action)
        file_menu.addSeparator()
        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)

        configure_execution_action = QAction("Configurar recursos y Slurm…", self)
        configure_execution_action.triggered.connect(self.configure_execution)
        execution_menu = self.menuBar().addMenu("Ejecución")
        execution_menu.addAction(configure_execution_action)

        plot_menu = self.menuBar().addMenu("Gráficos")
        plot_theme_group = QActionGroup(self)
        plot_theme_group.setExclusive(True)
        saved_plot_theme = str(QSettings().value("display/plot_theme", "dark"))
        for label, value in (("Tema oscuro", "dark"), ("Tema claro", "light")):
            action = QAction(label, self, checkable=True)
            action.setData(value)
            action.setChecked(value == saved_plot_theme)
            action.triggered.connect(
                lambda _checked=False, theme=value: self._set_plot_theme(theme)
            )
            plot_theme_group.addAction(action)
            plot_menu.addAction(action)

        self.sample_table = MetadataTableWidget(0, 4)
        self.sample_table.setHorizontalHeaderLabels(
            ["Incluir", "Muestra", "Clase", "Individuo"]
        )
        self.sample_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sample_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sample_table.horizontalHeader().setStretchLastSection(True)
        self.sample_table.setColumnWidth(0, 56)
        self.sample_table.setColumnWidth(1, 245)
        self.sample_table.itemChanged.connect(self._mark_dirty)

        assign_button = QPushButton("Asignar clase a selección")
        assign_button.clicked.connect(self.assign_class)
        style_button = QPushButton("Estilos de clases…")
        style_button.clicked.connect(self.edit_class_styles)
        self.analysis_method = QComboBox()
        self.analysis_method.addItem("PCA", "pca")
        self.analysis_method.addItem("PLS-DA", "plsda")
        self.analysis_method.addItem("OPLS-DA", "orthogonalized_plsda")
        self.analysis_method.currentIndexChanged.connect(self._method_changed)
        self.ncomp = QSpinBox()
        self.ncomp.setRange(2, 20)
        self.ncomp.setValue(5)
        self.ncomp.valueChanged.connect(self._settings_changed)
        self.validation_method = QComboBox()
        self.validation_method.addItem("Random subsets", "random_subsets")
        self.validation_method.addItem("Monte Carlo", "monte_carlo")
        self.validation_method.addItem("Leave-one-out", "leave_one_out")
        self.validation_method.addItem("Venetian blinds", "venetian_blinds")
        self.validation_method.currentIndexChanged.connect(self._settings_changed)
        self.validation_method.currentIndexChanged.connect(self._update_validation_summary)
        self.supervised_repeats = QSpinBox()
        self.supervised_repeats.setRange(1, 200)
        self.supervised_repeats.setValue(20)
        self.supervised_splits = QSpinBox()
        self.supervised_splits.setRange(2, 20)
        self.supervised_splits.setValue(5)
        self.monte_carlo_iterations = QSpinBox()
        self.monte_carlo_iterations.setRange(1, 10000)
        self.monte_carlo_iterations.setValue(100)
        self.monte_carlo_train_percent = QSpinBox()
        self.monte_carlo_train_percent.setRange(50, 95)
        self.monte_carlo_train_percent.setSuffix(" %")
        self.monte_carlo_train_percent.setValue(80)
        self.validation_summary = QLabel()
        self.supervised_repeats.valueChanged.connect(self._settings_changed)
        self.supervised_splits.valueChanged.connect(self._settings_changed)
        self.supervised_repeats.valueChanged.connect(self._update_validation_summary)
        self.supervised_splits.valueChanged.connect(self._update_validation_summary)
        self.monte_carlo_iterations.valueChanged.connect(self._settings_changed)
        self.monte_carlo_iterations.valueChanged.connect(self._update_validation_summary)
        self.monte_carlo_train_percent.valueChanged.connect(self._settings_changed)
        self.monte_carlo_train_percent.valueChanged.connect(self._update_validation_summary)
        self.run_button = QPushButton("Ejecutar PCA")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_pca)

        controls = QFormLayout()
        controls.addRow("Modelo", self.analysis_method)
        self.execution_target = QComboBox()
        self.execution_target.addItem("Esta computadora", "local")
        self.execution_target.addItem("Clúster Slurm", "slurm")
        saved_target = QSettings().value("execution/target", "local")
        target_index = self.execution_target.findData(saved_target)
        self.execution_target.setCurrentIndex(max(0, target_index))
        self.execution_target.currentIndexChanged.connect(
            lambda: QSettings().setValue(
                "execution/target", self.execution_target.currentData()
            )
        )
        controls.addRow("Ejecutar en", self.execution_target)
        self.feature_scaling = QComboBox()
        self.feature_scaling.addItem("Pareto", "pareto")
        self.feature_scaling.addItem("Varianza unitaria", "unit_variance")
        self.feature_scaling.addItem("Sin escalado", "none")
        self.feature_scaling.currentIndexChanged.connect(self._settings_changed)
        controls.addRow("Escalado (tras centrado)", self.feature_scaling)
        self.ncomp_label = QLabel("Componentes PCA")
        self.validation_method_label = QLabel("Validación cruzada")
        self.iterations_label = QLabel("Iteraciones")
        self.splits_label = QLabel("Data splits")
        self.monte_carlo_iterations_label = QLabel("Iteraciones MC")
        self.monte_carlo_train_label = QLabel("Entrenamiento")
        self.validation_summary_label = QLabel("Resumen")
        controls.addRow(self.ncomp_label, self.ncomp)
        controls.addRow(self.validation_method_label, self.validation_method)
        controls.addRow(self.iterations_label, self.supervised_repeats)
        controls.addRow(self.splits_label, self.supervised_splits)
        controls.addRow(self.monte_carlo_iterations_label, self.monte_carlo_iterations)
        controls.addRow(self.monte_carlo_train_label, self.monte_carlo_train_percent)
        controls.addRow(self.validation_summary_label, self.validation_summary)
        self._update_validation_summary()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Muestras y clases"))
        left_layout.addWidget(self.sample_table, 1)
        left_layout.addWidget(assign_button)
        left_layout.addWidget(style_button)
        left_layout.addLayout(controls)
        left_layout.addWidget(self.run_button)

        self.summary = QLabel("Abra una matriz ómica CSV/TSV/TXT para comenzar.")
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setWordWrap(True)

        self.x_component = QComboBox()
        self.y_component = QComboBox()
        self.hotelling_level = QComboBox()
        self.hotelling_level.addItem("Sin elipse", None)
        self.hotelling_level.addItem("T² Hotelling 95 %", "0.95")
        self.hotelling_level.addItem("T² Hotelling 99 %", "0.99")
        self.hotelling_level.setCurrentIndex(1)
        self.show_legend = QCheckBox("Mostrar leyenda de clases")
        self.show_legend.setChecked(True)
        self.x_component.currentIndexChanged.connect(self.update_score_plot)
        self.y_component.currentIndexChanged.connect(self.update_score_plot)
        self.x_component.currentIndexChanged.connect(self._settings_changed)
        self.y_component.currentIndexChanged.connect(self._settings_changed)
        self.hotelling_level.currentIndexChanged.connect(self.update_score_plot)
        self.hotelling_level.currentIndexChanged.connect(self._settings_changed)
        self.show_legend.toggled.connect(self.update_score_plot)
        self.show_legend.toggled.connect(self._settings_changed)
        selectors = QHBoxLayout()
        selectors.addWidget(QLabel("Eje X"))
        selectors.addWidget(self.x_component)
        selectors.addWidget(QLabel("Eje Y"))
        selectors.addWidget(self.y_component)
        selectors.addWidget(QLabel("Confianza"))
        selectors.addWidget(self.hotelling_level)
        selectors.addWidget(self.show_legend)
        selectors.addStretch(1)

        self.score_plot = pg.PlotWidget(title="Scores")
        self.score_plot.showGrid(x=True, y=True, alpha=0.2)
        self.score_legend = self.score_plot.addLegend(offset=(12, 12))
        score_page = QWidget()
        score_layout = QVBoxLayout(score_page)
        score_layout.addLayout(selectors)
        score_layout.addWidget(self.score_plot, 1)

        self.variance_plot = pg.PlotWidget(title="Varianza explicada")
        self.variance_plot.showGrid(x=True, y=True, alpha=0.2)
        self.loading_plot = pg.PlotWidget(title="Loadings")
        self.loading_plot.showGrid(x=True, y=True, alpha=0.2)
        self.loading_plot.setLabel("bottom", "ppm")
        self.loading_plot.invertX(True)
        self.loading_component = QComboBox()
        self.loading_component.currentIndexChanged.connect(self.update_loading_plot)
        self.loading_component.currentIndexChanged.connect(self._settings_changed)
        loading_page = QWidget()
        loading_layout = QVBoxLayout(loading_page)
        loading_controls = QHBoxLayout()
        loading_controls.addWidget(QLabel("Componente"))
        loading_controls.addWidget(self.loading_component)
        loading_controls.addStretch(1)
        loading_layout.addLayout(loading_controls)
        loading_layout.addWidget(self.loading_plot, 1)

        self.fit_metric = QComboBox()
        self.fit_metric.addItem("RMSE de reconstrucción", "rmse")
        self.fit_metric.addItem("R²X acumulado", "r2x")
        self.fit_metric.currentIndexChanged.connect(self.update_fit_plot)
        self.fit_plot = pg.PlotWidget(title="Ajuste PCA")
        self.fit_plot.showGrid(x=True, y=True, alpha=0.2)
        fit_page = QWidget()
        fit_layout = QVBoxLayout(fit_page)
        fit_controls = QHBoxLayout()
        fit_controls.addWidget(QLabel("Métrica"))
        fit_controls.addWidget(self.fit_metric)
        fit_controls.addStretch(1)
        fit_layout.addLayout(fit_controls)
        fit_layout.addWidget(self.fit_plot, 1)

        self.model_selection_plot = pg.PlotWidget(title="Selección del modelo")
        self.model_selection_plot.showGrid(x=True, y=True, alpha=0.2)
        self.model_selection_legend = self.model_selection_plot.addLegend(offset=(12, 12))
        self.model_selection_summary = QLabel(
            "La selección por componentes estará disponible para modelos supervisados."
        )
        self.model_selection_summary.setWordWrap(True)
        self.model_selection_table = QTableWidget(0, 9)
        self.model_selection_table.setHorizontalHeaderLabels(
            [
                "Modelo", "Estado", "R²Y", "Q²Y", "BER ajuste",
                "BER CV", "DE CV", "AUC CV", "Correctas ajuste",
            ]
        )
        self.model_selection_table.setAlternatingRowColors(True)
        self.model_selection_table.cellDoubleClicked.connect(
            self._set_current_model_from_row
        )
        self.apply_model_button = QPushButton("Establecer como modelo actual")
        self.apply_model_button.clicked.connect(self._set_selected_model_as_current)
        self.current_model_label = QLabel("Modelo actual: —")
        selection_page = QWidget()
        selection_layout = QVBoxLayout(selection_page)
        selection_top = QWidget()
        selection_top_layout = QVBoxLayout(selection_top)
        selection_top_layout.setContentsMargins(0, 0, 0, 0)
        selection_top_layout.addWidget(self.model_selection_summary)
        selection_top_layout.addWidget(self.model_selection_plot, 1)
        selection_actions = QHBoxLayout()
        selection_actions.addWidget(self.current_model_label)
        selection_actions.addStretch(1)
        selection_actions.addWidget(self.apply_model_button)
        selection_bottom = QWidget()
        selection_bottom_layout = QVBoxLayout(selection_bottom)
        selection_bottom_layout.setContentsMargins(0, 0, 0, 0)
        selection_bottom_layout.addLayout(selection_actions)
        selection_bottom_layout.addWidget(self.model_selection_table, 1)
        selection_splitter = QSplitter(Qt.Vertical)
        selection_splitter.addWidget(selection_top)
        selection_splitter.addWidget(selection_bottom)
        selection_splitter.setSizes([430, 250])
        selection_layout.addWidget(selection_splitter, 1)

        self.confusion_component = QComboBox()
        self.confusion_component.currentIndexChanged.connect(self.update_confusion_table)
        self.confusion_table = QTableWidget(0, 0)
        confusion_page = QWidget()
        confusion_layout = QVBoxLayout(confusion_page)
        confusion_controls = QHBoxLayout()
        confusion_controls.addWidget(QLabel("Modelo"))
        confusion_controls.addWidget(self.confusion_component)
        confusion_controls.addStretch(1)
        confusion_layout.addLayout(confusion_controls)
        confusion_layout.addWidget(QLabel("Filas: clase real · Columnas: clase predicha"))
        confusion_layout.addWidget(self.confusion_table, 1)

        self.roc_component = QComboBox()
        self.roc_component.currentIndexChanged.connect(self.update_roc_plot)
        self.roc_component.currentIndexChanged.connect(self._settings_changed)
        self.roc_class = QComboBox()
        self.roc_class.currentIndexChanged.connect(self.update_roc_plot)
        self.roc_class.currentIndexChanged.connect(self._settings_changed)
        self.roc_plot = pg.PlotWidget(title="ROC multiclase")
        self.roc_plot.showGrid(x=True, y=True, alpha=0.2)
        self.roc_legend = self.roc_plot.addLegend(offset=(12, 12))
        self.threshold_plot = pg.PlotWidget(title="Sensibilidad y especificidad")
        self.threshold_plot.showGrid(x=True, y=True, alpha=0.2)
        self.threshold_legend = self.threshold_plot.addLegend(offset=(12, 12))
        self.roc_summary = QLabel("ROC disponible para PLS-DA y OPLS-DA")
        roc_page = QWidget()
        roc_layout = QVBoxLayout(roc_page)
        roc_controls = QHBoxLayout()
        roc_controls.addWidget(QLabel("Modelo"))
        roc_controls.addWidget(self.roc_component)
        roc_controls.addWidget(QLabel("Grupo"))
        roc_controls.addWidget(self.roc_class)
        self.roc_view = QComboBox()
        self.roc_view.addItem("Curva ROC", "roc")
        self.roc_view.addItem("Respuesta al umbral", "threshold")
        self.roc_view.currentIndexChanged.connect(self._settings_changed)
        roc_controls.addWidget(QLabel("Vista"))
        roc_controls.addWidget(self.roc_view)
        roc_controls.addStretch(1)
        roc_layout.addLayout(roc_controls)
        roc_layout.addWidget(self.roc_summary)
        self.roc_stack = QStackedWidget()
        self.roc_stack.addWidget(self.roc_plot)
        self.roc_stack.addWidget(self.threshold_plot)
        self.roc_view.currentIndexChanged.connect(self.roc_stack.setCurrentIndex)
        roc_layout.addWidget(self.roc_stack, 1)

        self.permutation_count = QSpinBox()
        self.permutation_count.setRange(1, 10000)
        self.permutation_count.setValue(100)
        self.permutation_count.valueChanged.connect(self._settings_changed)
        self.permutation_analysis_mode = QComboBox()
        self.permutation_analysis_mode.addItem("Ambos (recomendado)", "both")
        self.permutation_analysis_mode.addItem("Empírico", "empirical")
        self.permutation_analysis_mode.addItem("Comparación residual", "residual")
        self.permutation_analysis_mode.currentIndexChanged.connect(self._settings_changed)
        self.run_permutation_button = QPushButton("Ejecutar test de permutaciones")
        self.run_permutation_button.setEnabled(False)
        self.run_permutation_button.clicked.connect(self.run_permutation_test)
        self.permutation_metric = QComboBox()
        self.permutation_metric.addItem("Q²Y externo", "q2y")
        self.permutation_metric.addItem("R²Y", "r2y")
        self.permutation_metric.addItem("BER externo", "ber")
        self.permutation_metric.addItem("AUC macro externo", "auc_macro")
        self.permutation_metric.currentIndexChanged.connect(self.update_permutation_plot)
        self.permutation_view = QComboBox()
        self.permutation_view.addItem("Distribución nula", "histogram")
        self.permutation_view.addItem(
            "R²Y/Q²Y frente a correlación de Y", "correlation"
        )
        self.permutation_view.addItem(
            "SSQ residual frente a correlación de Y", "residual"
        )
        self.permutation_view.currentIndexChanged.connect(self.update_permutation_plot)
        self.permutation_response = QComboBox()
        self.permutation_response.addItem("Global", "global")
        self.permutation_response.currentIndexChanged.connect(self.update_permutation_plot)
        self.permutation_summary = QLabel(
            "Ejecute primero un modelo supervisado y después su test de permutaciones."
        )
        self.permutation_summary.setWordWrap(True)
        self.permutation_plot = pg.PlotWidget(title="Distribución nula por permutación")
        self.permutation_plot.showGrid(x=True, y=True, alpha=0.2)
        permutation_page = QWidget()
        permutation_layout = QVBoxLayout(permutation_page)
        permutation_controls = QHBoxLayout()
        permutation_controls.addWidget(QLabel("Permutaciones"))
        permutation_controls.addWidget(self.permutation_count)
        permutation_controls.addWidget(QLabel("Análisis"))
        permutation_controls.addWidget(self.permutation_analysis_mode)
        permutation_controls.addWidget(self.run_permutation_button)
        permutation_controls.addWidget(QLabel("Vista"))
        permutation_controls.addWidget(self.permutation_view)
        permutation_controls.addWidget(QLabel("Métrica mostrada"))
        permutation_controls.addWidget(self.permutation_metric)
        permutation_controls.addWidget(QLabel("Respuesta"))
        permutation_controls.addWidget(self.permutation_response)
        permutation_controls.addStretch(1)
        permutation_layout.addLayout(permutation_controls)
        permutation_layout.addWidget(self.permutation_summary)
        permutation_layout.addWidget(self.permutation_plot, 1)

        self.loading_value_plot = pg.PlotWidget(
            title="Gráfico de valores de carga",
            viewBox=LoadingValueViewBox(),
        )
        self.loading_value_plot.showGrid(x=True, y=True, alpha=0.2)
        self.loading_value_plot.setLabel("bottom", "Corrimiento químico", units="ppm")
        self.loading_value_plot.setLabel("left", "Valor de carga reescalado")
        self.loading_value_plot.invertX(True)
        self.loading_value_component = QComboBox()
        self.loading_value_component.currentIndexChanged.connect(
            self.update_loading_value_plot
        )
        self.loading_value_component.currentIndexChanged.connect(self._settings_changed)
        loading_value_page = QWidget()
        loading_value_layout = QVBoxLayout(loading_value_page)
        loading_value_controls = QHBoxLayout()
        loading_value_controls.addWidget(QLabel("Componente"))
        loading_value_controls.addWidget(self.loading_value_component)
        loading_value_controls.addStretch(1)
        loading_value_layout.addLayout(loading_value_controls)
        self.loading_value_explanation = QLabel(
            "Altura: √(desviación estándar) × loading con escalado Pareto; "
            "color: loading original."
        )
        self.loading_value_explanation.setWordWrap(True)
        loading_value_layout.addWidget(self.loading_value_explanation)
        loading_value_layout.addWidget(self.loading_value_plot, 1)
        self.loading_value_colorbar = pg.ColorBarItem(
            values=(-1.0, 1.0),
            colorMap=MATLAB_JET,
            label="Loading",
            interactive=False,
            colorMapMenu=False,
        )
        self.loading_value_colorbar.setImageItem(
            [], insert_in=self.loading_value_plot.getPlotItem()
        )

        tabs = QTabWidget()
        tabs.addTab(self.summary, "Resumen")
        tabs.addTab(score_page, "Scores")
        tabs.addTab(self.variance_plot, "Varianza")
        tabs.addTab(loading_page, "Loadings")
        tabs.addTab(selection_page, "Selección")
        tabs.addTab(fit_page, "Métricas")
        tabs.addTab(confusion_page, "Confusión")
        tabs.addTab(roc_page, "ROC")
        tabs.addTab(permutation_page, "Permutaciones")
        tabs.addTab(loading_value_page, "Loading plot")
        tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        tabs.setMinimumWidth(360)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(tabs)
        splitter.setSizes([380, 900])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Listo")
        self._configure_plots()
        self._set_plot_theme(saved_plot_theme, redraw=False)
        self._method_changed()

    def _plot_widgets(self) -> tuple[pg.PlotWidget, ...]:
        return (
            self.score_plot,
            self.variance_plot,
            self.loading_plot,
            self.fit_plot,
            self.model_selection_plot,
            self.roc_plot,
            self.threshold_plot,
            self.permutation_plot,
            self.loading_value_plot,
        )

    def _configure_plots(self) -> None:
        for plot in self._plot_widgets():
            plot.setMouseEnabled(x=False, y=False)
            plot.hideButtons()
        self.loading_value_plot.setMouseEnabled(x=True, y=True)

    def _set_plot_theme(self, theme: str, *, redraw: bool = True) -> None:
        theme = "light" if theme == "light" else "dark"
        background = "#ffffff" if theme == "light" else "#111827"
        foreground = "#111827" if theme == "light" else "#f8fafc"
        self._plot_theme = theme
        QSettings().setValue("display/plot_theme", theme)
        pg.setConfigOption("background", background)
        pg.setConfigOption("foreground", foreground)
        if redraw and self.result is not None:
            self._render_result()
        for plot in self._plot_widgets():
            plot.setBackground(background)
            title = plot.getPlotItem().titleLabel.text
            plot.getPlotItem().titleLabel.setText(title, color=foreground)
            for axis_name in ("left", "bottom", "right", "top"):
                axis = plot.getAxis(axis_name)
                axis.setPen(pg.mkPen(foreground))
                axis.setTextPen(pg.mkPen(foreground))
        for axis_name in ("left", "bottom", "right", "top"):
            axis = self.loading_value_colorbar.getAxis(axis_name)
            axis.setPen(pg.mkPen(foreground))
            axis.setTextPen(pg.mkPen(foreground))
        for legend in (
            self.score_legend,
            self.model_selection_legend,
            self.roc_legend,
            self.threshold_legend,
        ):
            legend.setLabelTextColor(foreground)

    def open_dataset(self) -> None:
        if not self._maybe_save_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir matriz ómica", "", "Datos (*.csv *.tsv *.txt);;Todos (*)"
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._loading = True
            detected = inspect_omics_matrix(path)
            QApplication.restoreOverrideCursor()
            dialog = OmicsImportDialog(detected, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.dataset = inspect_omics_matrix(
                path,
                detected.delimiter,
                orientation=dialog.orientation.currentData(),
                representation=dialog.representation.currentData(),
                modality=dialog.modality.currentText(),
                axis_label=dialog.axis_label.text(),
            )
            suggested_scaling = (
                "pareto"
                if self.dataset.modality == "1H-NMR"
                and self.dataset.representation == "continuous_profile"
                else "unit_variance"
            )
            scaling_index = self.feature_scaling.findData(suggested_scaling)
            self.feature_scaling.setCurrentIndex(max(0, scaling_index))
            self.project_path = None
            self.result = None
            self.export_action.setEnabled(False)
            self.class_styles.clear()
            self._populate_samples()
            self.summary.setText(
                f"<b>{Path(path).name}</b><br><br>"
                f"{self.dataset.samples} muestras × "
                f"{self.dataset.features:,} variables<br>"
                f"Modalidad: {self.dataset.modality}<br>"
                f"Representación: "
                f"{'perfil continuo' if self.dataset.representation == 'continuous_profile' else 'tabla de características'}<br>"
                f"Orientación confirmada: "
                f"{'variables × muestras' if self.dataset.orientation == 'variables_by_samples' else 'muestras × variables'}"
            )
            self.run_button.setEnabled(True)
            self._set_dirty(True)
            self.statusBar().showMessage("Dataset inspeccionado correctamente")
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo abrir", str(exc))
        finally:
            self._loading = False
            QApplication.restoreOverrideCursor()

    def configure_execution(self) -> None:
        dialog = ExecutionProfileDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.statusBar().showMessage(
                "Perfil Slurm guardado localmente; ya puede seleccionarlo en 'Ejecutar en'"
            )

    @staticmethod
    def _saved_slurm_configuration() -> tuple[ClusterProfile, SlurmResources]:
        settings = QSettings()
        raw_profile = settings.value(ExecutionProfileDialog.PROFILE_KEY)
        raw_resources = settings.value(ExecutionProfileDialog.RESOURCES_KEY)
        if not raw_profile or not raw_resources:
            raise ValueError(
                "Configure primero el perfil en Ejecución > "
                "Configurar recursos y Slurm…"
            )
        return (
            ClusterProfile.from_dict(json.loads(raw_profile)),
            SlurmResources(**json.loads(raw_resources)),
        )

    def _remote_progress(self) -> None:
        if self.process is None:
            return
        output = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        for line in output.splitlines():
            if line.startswith("ARII_STATUS:"):
                self.statusBar().showMessage(line.removeprefix("ARII_STATUS:"))

    def _start_r_job(
        self, *, worker: Path, job_path: Path, result_path: Path,
        dataset_path: Path, stamp: str, finished_callback, local_status: str,
        method: str,
    ) -> bool:
        target = self.execution_target.currentData()
        self.process = QProcess(self)
        self._process_is_remote = target == "slurm"
        if target == "local":
            command = LocalRBackend().command_for(RJob(worker, job_path, result_path))
            self.process.setProgram(command.program)
            self.process.setArguments(list(command.arguments))
            raw_local = QSettings().value(ExecutionProfileDialog.LOCAL_KEY)
            reserved = 3
            if raw_local:
                try:
                    reserved = int(json.loads(raw_local).get("reserved_cpus", 3))
                except (TypeError, ValueError, json.JSONDecodeError):
                    reserved = 3
            current_resources = detect_system_resources()
            workers = recommended_workers(
                current_resources, reserved_cpus=reserved,
                samples=self.dataset.samples if self.dataset else 0,
                variables=self.dataset.spectral_points if self.dataset else 0,
            )
            environment = QProcessEnvironment.systemEnvironment()
            r_environment = r_subprocess_environment(command.program)
            for name in (
                "LC_ALL", "LC_COLLATE", "LC_CTYPE", "LC_MONETARY",
                "LC_NUMERIC", "LC_TIME", "LANG",
            ):
                environment.remove(name)
            for name in ("R_HOME", "R_LIBS_SITE", "R_LIBS_USER"):
                if name in r_environment:
                    environment.insert(name, r_environment[name])
            environment.insert("ARII_PARALLEL_WORKERS", str(workers))
            environment.insert("OMP_NUM_THREADS", "1")
            environment.insert("OPENBLAS_NUM_THREADS", "1")
            environment.insert("MKL_NUM_THREADS", "1")
            self.process.setProcessEnvironment(environment)
            suffix = f" ({workers} procesos; {reserved} CPU reservadas)" if method != "pca" else ""
            self.statusBar().showMessage(local_status + suffix)
        else:
            try:
                profile, resources = self._saved_slurm_configuration()
                request_path = job_path.with_suffix(".remote.json")
                request_path.write_text(json.dumps({
                    "profile": profile.to_dict(),
                    "resources": {
                        "cpus": resources.cpus,
                        "memory_mb": resources.memory_mb,
                        "walltime_minutes": resources.walltime_minutes,
                        "nodes": resources.nodes,
                    },
                    "worker_path": str(worker),
                    "job_path": str(job_path),
                    "dataset_path": str(dataset_path),
                    "result_path": str(result_path),
                    "remote_job_id": f"{worker.stem}-{stamp}",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                self.process.deleteLater()
                self.process = None
                QMessageBox.warning(self, "Perfil Slurm", str(exc))
                return False
            program, arguments = launcher_command(request_path)
            self.process.setProgram(program)
            self.process.setArguments(arguments)
            self.process.readyReadStandardOutput.connect(self._remote_progress)
            self.statusBar().showMessage("Preparando la ejecución remota…")
        self.process.finished.connect(finished_callback)
        self.process.start()
        return True

    def _populate_samples(self) -> None:
        assert self.dataset is not None
        self.sample_table.setRowCount(len(self.dataset.sample_names))
        for row, name in enumerate(self.dataset.sample_names):
            include = QTableWidgetItem()
            include.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            include.setCheckState(Qt.Checked)
            include.setTextAlignment(Qt.AlignCenter)
            sample = QTableWidgetItem(name)
            sample.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            sample_class = QTableWidgetItem("Sin asignar")
            self.sample_table.setItem(row, 0, include)
            self.sample_table.setItem(row, 1, sample)
            self.sample_table.setItem(row, 2, sample_class)
            for column in range(3, self.sample_table.columnCount()):
                self.sample_table.setItem(row, column, QTableWidgetItem(""))

    def assign_class(self) -> None:
        cells = self.sample_table.selectedIndexes()
        rows = sorted({cell.row() for cell in cells})
        if not rows:
            QMessageBox.information(self, "Asignar clase", "Seleccione una o más filas.")
            return
        current = self.sample_table.item(rows[0], 2).text()
        from PySide6.QtWidgets import QInputDialog
        value, accepted = QInputDialog.getText(self, "Asignar clase", "Nombre:", text=current)
        if accepted and value.strip():
            for row in rows:
                self.sample_table.item(row, 2).setText(value.strip())

    def _method_changed(self, _index: int | None = None) -> None:
        method = self.analysis_method.currentData()
        is_supervised = method in {"plsda", "orthogonalized_plsda"}
        uses_pls_components = method in {"pca", "plsda", "orthogonalized_plsda"}
        self.validation_method.setEnabled(is_supervised)
        self.supervised_repeats.setEnabled(is_supervised)
        self.supervised_splits.setEnabled(is_supervised)
        self.validation_summary.setEnabled(is_supervised)
        self.ncomp.setVisible(uses_pls_components)
        self.ncomp_label.setVisible(uses_pls_components)
        self.ncomp_label.setText(
            "Componentes PCA" if method == "pca" else "Máximo de componentes"
        )
        for widget in (
            self.supervised_repeats,
            self.supervised_splits,
            self.validation_method,
            self.monte_carlo_iterations,
            self.monte_carlo_train_percent,
            self.validation_summary,
            self.validation_method_label,
            self.iterations_label,
            self.splits_label,
            self.monte_carlo_iterations_label,
            self.monte_carlo_train_label,
            self.validation_summary_label,
        ):
            widget.setVisible(is_supervised)
        self._update_validation_summary()
        method_label = {
            "pca": "PCA",
            "plsda": "PLS-DA",
            "orthogonalized_plsda": "OPLS-DA",
        }[method]
        self.run_button.setText(f"Ejecutar {method_label}")
        self.export_action.setEnabled(
            self.result is not None
            and self.result.get("method") == method
        )
        if not self._loading and self.dataset is not None:
            self._set_dirty(True)

    def _update_validation_summary(self, _value: int | None = None) -> None:
        strategy = self.validation_method.currentData()
        supervised = self.analysis_method.currentData() in {"plsda", "orthogonalized_plsda"}
        random_subsets = supervised and strategy == "random_subsets"
        monte_carlo = supervised and strategy == "monte_carlo"
        venetian = supervised and strategy == "venetian_blinds"
        self.supervised_repeats.setVisible(random_subsets)
        self.iterations_label.setVisible(random_subsets)
        self.supervised_splits.setVisible(random_subsets or venetian)
        self.splits_label.setVisible(random_subsets or venetian)
        self.monte_carlo_iterations.setVisible(monte_carlo)
        self.monte_carlo_iterations_label.setVisible(monte_carlo)
        self.monte_carlo_train_percent.setVisible(monte_carlo)
        self.monte_carlo_train_label.setVisible(monte_carlo)
        if random_subsets:
            splits = self.supervised_splits.value()
            iterations = self.supervised_repeats.value()
            validation = 100 / splits
            self.validation_summary.setText(
                f"{100 - validation:.1f}/{validation:.1f} % · "
                f"{splits * iterations} submodelos"
            )
        elif monte_carlo:
            training = self.monte_carlo_train_percent.value()
            self.validation_summary.setText(
                f"{training}/{100 - training} % · "
                f"{self.monte_carlo_iterations.value()} submodelos independientes"
            )
        elif strategy == "leave_one_out":
            self.validation_summary.setText("Una unidad biológica externa por submodelo")
        else:
            splits = self.supervised_splits.value()
            self.validation_summary.setText(
                f"{splits} bloques sistemáticos · orden actual de las muestras"
            )

    def _classes_in_table(self) -> list[str]:
        return list(dict.fromkeys(
            self.sample_table.item(row, 2).text().strip() or "Sin asignar"
            for row in range(self.sample_table.rowCount())
        ))

    def import_sample_metadata(self) -> None:
        if self.dataset is None:
            QMessageBox.information(self, "Metadatos", "Abra un dataset primero.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar metadatos",
            "",
            "Metadatos (*.csv *.tsv *.txt);;Todos (*)",
        )
        if not path:
            return
        try:
            result = import_metadata(path, list(self.dataset.sample_names))
            row_by_name = {
                self.sample_table.item(row, TABLE_COLUMNS["sample_name"]).text(): row
                for row in range(self.sample_table.rowCount())
            }
            self._loading = True
            try:
                for sample_name in result.matched_samples:
                    row = row_by_name[sample_name]
                    for field in ("class", "biological_id"):
                        if field not in result.imported_fields:
                            continue
                        self.sample_table.item(row, TABLE_COLUMNS[field]).setText(
                            result.values[sample_name].get(field, "")
                        )
            finally:
                self._loading = False
            self._set_dirty(True)
            details = [
                f"Coincidencias: {len(result.matched_samples)}",
                f"Sin metadatos: {len(result.missing_samples)}",
                f"Filas ajenas al dataset: {len(result.unknown_samples)}",
                "Campos usados: clase e individuo",
            ]
            QMessageBox.information(self, "Importación completada", "\n".join(details))
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo importar", str(exc))

    def _ensure_class_styles(self, classes: list[str]) -> None:
        for index, class_name in enumerate(dict.fromkeys(classes)):
            if class_name not in self.class_styles:
                self.class_styles[class_name] = ClassStyle(
                    color=CLASS_COLORS[len(self.class_styles) % len(CLASS_COLORS)]
                )

    def edit_class_styles(self) -> None:
        classes = self._classes_in_table()
        if not classes:
            QMessageBox.information(self, "Estilos", "Abra un dataset primero.")
            return
        self._ensure_class_styles(classes)
        active_styles = {name: self.class_styles[name] for name in classes}
        dialog = ClassStyleDialog(active_styles, self)
        if dialog.exec() == QDialog.Accepted:
            self.class_styles.update(dialog.styles)
            self._set_dirty(True)
            self.update_score_plot()

    def run_pca(self) -> None:
        if self.dataset is None or self.process is not None:
            return
        selected = [
            row for row in range(self.sample_table.rowCount())
            if self.sample_table.item(row, 0).checkState() == Qt.Checked
        ]
        if len(selected) < 3:
            QMessageBox.warning(self, "PCA", "Seleccione al menos tres muestras.")
            return
        classes = [
            self.sample_table.item(row, 2).text().strip() or "Sin asignar"
            for row in range(self.sample_table.rowCount())
        ]
        method = self.analysis_method.currentData()
        if method in {"plsda", "orthogonalized_plsda"}:
            selected_classes = [classes[row] for row in selected]
            if "Sin asignar" in selected_classes:
                QMessageBox.warning(
                    self, "PLS-DA", "Todas las muestras incluidas deben tener una clase asignada."
                )
                return
            class_counts = {name: selected_classes.count(name) for name in set(selected_classes)}
            if len(class_counts) < 2:
                QMessageBox.warning(self, "PLS-DA", "Seleccione al menos dos clases.")
                return
            if any(count < 2 for count in class_counts.values()):
                QMessageBox.warning(
                    self, "PLS-DA", "Cada clase debe contener al menos dos muestras."
                )
                return
            if method == "orthogonalized_plsda" and len(class_counts) != 2:
                QMessageBox.warning(
                    self, "OPLS-DA", "OPLS-DA requiere exactamente dos clases."
                )
                return
            validation_strategy = self.validation_method.currentData()
            data_splits = self.supervised_splits.value()
            biological_ids = [
                self.sample_table.item(row, TABLE_COLUMNS["biological_id"]).text().strip()
                for row in selected
            ]
            sample_names = [self.sample_table.item(row, 1).text() for row in selected]
            units_by_class: dict[str, set[str]] = {name: set() for name in class_counts}
            unit_classes: dict[str, str] = {}
            for class_name, biological_id, sample_name in zip(
                selected_classes, biological_ids, sample_names, strict=True
            ):
                unit = biological_id or f"__sample__{sample_name}"
                previous_class = unit_classes.setdefault(unit, class_name)
                if previous_class != class_name:
                    QMessageBox.warning(
                        self,
                        "Validación cruzada",
                        f"El individuo '{biological_id}' aparece en más de una clase.",
                    )
                    return
                units_by_class[class_name].add(unit)
            limiting_class, limiting_units = min(
                ((name, len(units)) for name, units in units_by_class.items()),
                key=lambda value: value[1],
            )
            if validation_strategy == "random_subsets" and limiting_units < data_splits:
                QMessageBox.warning(
                    self,
                    "Random subsets",
                    f"La clase '{limiting_class}' tiene {limiting_units} unidades biológicas "
                    f"independientes y no admite {data_splits} data splits. "
                    f"Use como máximo {limiting_units}.",
                )
                return
            if validation_strategy in {"monte_carlo", "leave_one_out"} and limiting_units < 2:
                QMessageBox.warning(
                    self,
                    "Validación cruzada",
                    f"La clase '{limiting_class}' necesita al menos dos unidades biológicas "
                    "independientes para mantener una en entrenamiento.",
                )
                return
            if validation_strategy == "venetian_blinds":
                total_units = len(unit_classes)
                if limiting_units < 2:
                    QMessageBox.warning(
                        self,
                        "Venetian blinds",
                        f"La clase '{limiting_class}' necesita al menos dos unidades biológicas "
                        "independientes.",
                    )
                    return
                if data_splits >= total_units:
                    QMessageBox.warning(
                        self,
                        "Venetian blinds",
                        f"Use menos de {total_units} bloques para conservar muestras de "
                        "entrenamiento en cada submodelo.",
                    )
                    return
        work = Path(tempfile.gettempdir()) / "arii-work"
        work.mkdir(exist_ok=True)
        stamp = str(time.time_ns())
        job_path = work / f"pca-{stamp}.job.json"
        self.result_path = work / f"pca-{stamp}.result.json"
        job = {
            "schema_version": "1.0",
            "dataset": {
                "path": self.dataset.path,
                "delimiter": self.dataset.delimiter,
                "orientation": self.dataset.orientation,
                "representation": self.dataset.representation,
                "modality": self.dataset.modality,
                "axis_label": self.dataset.axis_label,
            },
            "preprocessing": {
                "mean_center": True, "scaling": self.feature_scaling.currentData()
            },
            "selected_sample_indices": selected,
            "classes": classes,
            "n_components": self.ncomp.value(),
            "validation": {
                "strategy": self.validation_method.currentData(),
                "repeats": (
                    self.monte_carlo_iterations.value()
                    if self.validation_method.currentData() == "monte_carlo"
                    else self.supervised_repeats.value()
                ),
                "data_splits": self.supervised_splits.value(),
                "train_fraction": self.monte_carlo_train_percent.value() / 100,
                "seed": 1234,
            },
            "biological_ids": [
                self.sample_table.item(row, TABLE_COLUMNS["biological_id"]).text().strip()
                for row in range(self.sample_table.rowCount())
            ],
            "orthogonalize_plsda": method == "orthogonalized_plsda",
        }
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

        worker_name = {
            "pca": "pca_worker.R",
            "plsda": "plsda_worker.R",
            "orthogonalized_plsda": "plsda_worker.R",
        }[method]
        worker = worker_path(worker_name)
        method_display = {
            "pca": "PCA",
            "plsda": "PLS-DA",
            "orthogonalized_plsda": "OPLS-DA",
        }[method]
        started = self._start_r_job(
            worker=worker, job_path=job_path, result_path=self.result_path,
            dataset_path=Path(self.dataset.path), stamp=stamp,
            finished_callback=self._pca_finished,
            local_status=f"Ejecutando {method_display} con mixOmics…",
            method=method,
        )
        if started:
            self.run_button.setEnabled(False)

    def _pca_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        assert self.process is not None
        self._remote_progress()
        stderr = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self.process.deleteLater()
        self.process = None
        self.run_button.setEnabled(True)
        if exit_code != 0 or self.result_path is None or not self.result_path.exists():
            QMessageBox.critical(self, "Error en el modelo", stderr or "El motor R no produjo resultados.")
            self.statusBar().showMessage("El modelo falló")
            return
        try:
            self.result = json.loads(self.result_path.read_text(encoding="utf-8"))
            self._render_result()
            self._set_dirty(True)
            self.statusBar().showMessage(f"{self.result['method'].upper()} completado")
        except Exception as exc:
            QMessageBox.critical(self, "Resultado inválido", str(exc))

    def _render_result(self) -> None:
        assert self.result is not None
        names = self.result["component_names"]
        method = self.result.get("method", "pca")
        performance = self.result.get("performance", {})
        selection = performance.get("selection", {})
        current_component = int(selection.get("current_component", 1))
        self.x_component.blockSignals(True)
        self.y_component.blockSignals(True)
        self.x_component.clear()
        self.y_component.clear()
        self.x_component.addItems(names)
        self.y_component.addItems(names)
        self.x_component.setCurrentIndex(0)
        self.y_component.setCurrentIndex(min(1, len(names) - 1))
        self.x_component.blockSignals(False)
        self.y_component.blockSignals(False)
        self.update_score_plot()
        self.loading_component.blockSignals(True)
        self.loading_component.clear()
        self.loading_component.addItems(names)
        self.loading_component.setCurrentIndex(0)
        self.loading_component.blockSignals(False)
        self.loading_value_component.blockSignals(True)
        self.loading_value_component.clear()
        self.loading_value_component.addItems(names)
        self.loading_value_component.setCurrentIndex(0)
        self.loading_value_component.blockSignals(False)
        self.fit_metric.blockSignals(True)
        self.fit_metric.clear()
        if method in {"plsda", "orthogonalized_plsda"}:
            self.fit_metric.addItem("Error balanceado (BER)", "ber")
            self.fit_metric.addItem("Exactitud", "accuracy")
            if "r2y" in self.result.get("performance", {}):
                self.fit_metric.addItem("R²Y", "r2y")
            if "q2y" in self.result.get("performance", {}):
                self.fit_metric.addItem("Q²Y", "q2y")
        else:
            self.fit_metric.addItem("RMSE de reconstrucción", "rmse")
            self.fit_metric.addItem("R²X acumulado", "r2x")
        self.fit_metric.blockSignals(False)
        self.confusion_component.blockSignals(True)
        self.confusion_component.clear()
        if method in {"plsda", "orthogonalized_plsda"}:
            self.confusion_component.addItem(
                f"Modelo actual: {current_component} LV" + ("s" if current_component != 1 else "")
            )
        self.confusion_component.blockSignals(False)
        self.roc_component.blockSignals(True)
        self.roc_component.clear()
        if method in {"plsda", "orthogonalized_plsda"}:
            self.roc_component.addItem(
                f"Modelo actual: {current_component} LV" + ("s" if current_component != 1 else "")
            )
        self.roc_component.blockSignals(False)
        self.roc_class.blockSignals(True)
        self.roc_class.clear()
        if method in {"plsda", "orthogonalized_plsda"}:
            self.roc_class.addItems(self.result["class_levels"])
        self.roc_class.blockSignals(False)

        explained = np.asarray(self.result["explained_variance"], dtype=float) * 100
        x = np.arange(1, len(explained) + 1)
        self.variance_plot.clear()
        bars = pg.BarGraphItem(x=x, height=explained, width=0.65, brush="#2563eb")
        self.variance_plot.addItem(bars)
        self.variance_plot.setLabel("bottom", "Componente")
        self.variance_plot.setLabel("left", "Varianza explicada", units="%")

        self.update_loading_plot()
        self.update_loading_value_plot()
        self.update_model_selection()
        self.update_fit_plot()
        self.update_confusion_table()
        self.update_roc_plot()
        self.update_permutation_plot()
        self.run_permutation_button.setEnabled(method in {"plsda", "orthogonalized_plsda"})
        self.export_action.setEnabled(True)

        dimensions = self.result["dimensions"]
        engine = self.result["engine"]
        if method in {"plsda", "orthogonalized_plsda"}:
            performance = self.result["performance"]
            train_fraction = float(performance.get("train_fraction", 0.8))
            validation_strategy = performance.get(
                "validation_method", "random_subsets"
            )
            data_splits = int(
                performance.get(
                    "data_splits", round(1 / max(1e-9, 1 - train_fraction))
                )
            )
            submodels = int(
                performance.get("submodels", performance["repeats"] * data_splits)
            )
            selection = performance.get("selection", {})
            suggested_component = int(
                selection.get("suggested_component", len(np.atleast_1d(performance["mean_ber"])))
            )
            current_component = int(selection.get("current_component", suggested_component))
            metric_index = max(
                0,
                min(current_component - 1, len(np.atleast_1d(performance["mean_ber"])) - 1),
            )
            effective = performance.get("effective_validation_fraction", {})
            effective_text = ""
            if effective:
                effective_text = (
                    f" (efectivo {float(effective['minimum']) * 100:.1f}–"
                    f"{float(effective['maximum']) * 100:.1f} %, "
                    f"media {float(effective['average']) * 100:.1f} %)"
                )
            workers = int(performance.get("parallel_workers", 1))
            parallel_text = f" · {workers} proceso{'s' if workers != 1 else ''} en paralelo"
            validation_description = {
                "random_subsets": (
                    f"Random subsets externos: {data_splits} splits × "
                    f"{performance['repeats']} iteraciones"
                ),
                "monte_carlo": (
                    f"Monte Carlo externo: {performance['repeats']} particiones "
                    "independientes"
                ),
                "leave_one_out": (
                    f"Leave-one-out externo: {submodels} unidades retiradas"
                ),
                "venetian_blinds": (
                    f"Venetian blinds externo: {data_splits} bloques sistemáticos"
                ),
            }.get(validation_strategy, "Validación cruzada externa")
            coverage = performance.get("validation_coverage", {})
            uncovered = int(coverage.get("samples_never_validated", 0))
            coverage_text = (
                f" · advertencia: {uncovered} muestra(s) sin predicción CV"
                if uncovered else ""
            )
            metric_summary = (
                f"<br>{validation_description} = {submodels} submodelos"
                f"{parallel_text}, "
                f"{train_fraction * 100:.0f}/"
                f"{(1 - train_fraction) * 100:.0f}{effective_text}{coverage_text}<br>"
                + f"Modelo actual: {current_component} componente(s) · sugerido: {suggested_component}<br>"
                + f"BER actual: {self._format_metric(np.atleast_1d(performance['mean_ber'])[metric_index], '.4f')} ± "
                f"{self._format_metric(np.atleast_1d(performance['sd_ber'])[metric_index], '.3g')}<br>"
                f"Exactitud actual: {self._format_metric(np.atleast_1d(performance['mean_accuracy'])[metric_index], '.4f')} ± "
                f"{self._format_metric(np.atleast_1d(performance['sd_accuracy'])[metric_index], '.3g')}<br>"
                f"R²Y actual: {self._format_metric(np.atleast_1d(performance.get('r2y', [None]))[metric_index], '.4f')}<br>"
                f"Q²Y actual: {self._format_metric(np.atleast_1d(performance.get('q2y', [None]))[metric_index], '.4f')}"
                f" ({validation_description.lower()})"
            )
            title = {
                "orthogonalized_plsda": "OPLS-DA completado",
                "plsda": "PLS-DA completado",
            }[method]
        else:
            fit = self.result.get("fit_metrics")
            metric_summary = ""
            if fit:
                metric_summary = (
                    f"<br>RMSE de reconstrucción: {fit['rmse'][-1]:.5g}<br>"
                    f"R²X acumulado: {fit['r2x'][-1]:.4f}"
                )
            title = "PCA completado"
        self.summary.setText(
            f"<b>{title}</b><br><br>"
            f"Motor: {engine['name']} {engine['version']}<br>"
            f"Matriz modelada: {dimensions['samples']} muestras × "
            f"{dimensions['variables']:,} variables<br>"
            f"Variables constantes retiradas: {dimensions['removed_constant_variables']}<br>"
            f"Varianza X acumulada: {sum(explained):.2f}% en {len(explained)} componentes"
            f"{metric_summary}"
        )

    @staticmethod
    def _format_metric(value: object, format_spec: str) -> str:
        if value is None:
            return "NA"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "NA"
        if not np.isfinite(numeric):
            return "NA"
        return format(numeric, format_spec)

    def update_loading_plot(self) -> None:
        if self.result is None or self.loading_component.count() == 0:
            return
        component = self.loading_component.currentIndex()
        ppm = np.asarray(self.result["ppm"], dtype=float)
        loadings = np.asarray(self.result["loadings"], dtype=float)
        feature_axis = self.result.get("feature_axis", {})
        axis_label = feature_axis.get("label", "ppm")
        representation = feature_axis.get("representation", "continuous_profile")
        self.loading_plot.invertX(axis_label.lower() == "ppm")
        self.loading_plot.clear()
        self.loading_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen("#64748b", width=1.2)),
            ignoreBounds=True,
        )
        if representation == "feature_table":
            self.loading_plot.plot(
                ppm, loadings[:, component], pen=None, symbol="o", symbolSize=5,
                symbolPen=None, symbolBrush="#2563eb",
            )
        else:
            self.loading_plot.plot(
                ppm, loadings[:, component], pen=pg.mkPen("#2563eb", width=1)
            )
        self.loading_plot.setLabel("bottom", axis_label)
        self.loading_plot.setTitle(f"Loadings — {self.result['component_names'][component]}")

    def update_loading_value_plot(self) -> None:
        if self.result is None or self.loading_value_component.count() == 0:
            return
        component = self.loading_value_component.currentIndex()
        ppm = np.asarray(self.result["ppm"], dtype=float)
        feature_axis = self.result.get("feature_axis", {})
        axis_label = feature_axis.get("label", "Corrimiento químico")
        representation = feature_axis.get("representation", "continuous_profile")
        self.loading_value_plot.invertX(axis_label.lower() == "ppm")
        self.loading_value_plot.setLabel(
            "bottom", axis_label, units="ppm" if axis_label.lower() == "ppm" else None
        )
        scaling = self.result.get("preprocessing", {}).get("scaling", "pareto")
        scaling_explanation = {
            "pareto": "√(desviación estándar) × loading",
            "unit_variance": "desviación estándar × loading",
            "none": "loading sin reescalado",
        }.get(scaling, "loading reescalado")
        self.loading_value_explanation.setText(
            f"Altura: {scaling_explanation}; color: loading del modelo."
        )
        colour_values, plot_values = backscaled_loading_values(
            self.result["loadings"],
            self.result["standard_deviations"],
            component,
            scaling=scaling,
        )
        if ppm.ndim != 1 or ppm.shape[0] != plot_values.shape[0]:
            raise ValueError("El eje de variables no coincide con los valores de carga")

        self.loading_value_plot.clear()
        finite_ppm = ppm[np.isfinite(ppm)]
        if finite_ppm.size < 2:
            self.loading_value_plot.setTitle("Valores de carga — sin eje de variables válido")
            return
        ppm_min = float(np.min(finite_ppm))
        ppm_max = float(np.max(finite_ppm))
        ppm_span = ppm_max - ppm_min
        if not np.isfinite(ppm_span) or ppm_span <= 0:
            self.loading_value_plot.setTitle("Valores de carga — sin rango de variables válido")
            return
        self.loading_value_plot.setLimits(
            xMin=ppm_min,
            xMax=ppm_max,
            minXRange=max(ppm_span * 1e-9, np.finfo(float).eps),
            maxXRange=ppm_span,
        )
        self.loading_value_plot.setXRange(ppm_min, ppm_max, padding=0)
        self.loading_value_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen("#64748b", width=1.2)),
            ignoreBounds=True,
        )

        finite_values = colour_values[np.isfinite(colour_values)]
        if finite_values.size:
            colour_min = float(np.min(finite_values))
            colour_max = float(np.max(finite_values))
            if colour_min == colour_max:
                padding = max(abs(colour_min), 1.0) * 1e-9
                display_min, display_max = colour_min - padding, colour_max + padding
            else:
                display_min, display_max = colour_min, colour_max
            self.loading_value_colorbar.setLevels(
                (display_min, display_max), update_items=False
            )

            segment_finite = (
                np.isfinite(ppm[:-1])
                & np.isfinite(ppm[1:])
                & np.isfinite(plot_values[:-1])
                & np.isfinite(plot_values[1:])
                & np.isfinite(colour_values[:-1])
                & np.isfinite(colour_values[1:])
            )
            segment_indices = np.flatnonzero(segment_finite)
            if representation == "feature_table":
                point_finite = (
                    np.isfinite(ppm) & np.isfinite(plot_values)
                    & np.isfinite(colour_values)
                )
                point_indices = np.flatnonzero(point_finite)
                if colour_min == colour_max:
                    point_bins = np.full(point_indices.shape, 63, dtype=int)
                else:
                    point_bins = np.clip(np.floor(
                        (colour_values[point_indices] - colour_min)
                        / (colour_max - colour_min) * 127
                    ), 0, 127).astype(int)
                for colour_bin in np.unique(point_bins):
                    indices = point_indices[point_bins == colour_bin]
                    colour = MATLAB_JET.mapToQColor((colour_bin + 0.5) / 128)
                    self.loading_value_plot.plot(
                        ppm[indices], plot_values[indices], pen=None,
                        symbol="o", symbolSize=5, symbolPen=None,
                        symbolBrush=colour,
                    )
            elif segment_indices.size:
                segment_colours = (
                    colour_values[segment_indices]
                    + colour_values[segment_indices + 1]
                ) / 2
                if colour_min == colour_max:
                    bins = np.full(segment_indices.shape, 63, dtype=int)
                else:
                    normalized = (segment_colours - colour_min) / (
                        colour_max - colour_min
                    )
                    bins = np.clip(np.floor(normalized * 127), 0, 127).astype(int)
                for colour_bin in np.unique(bins):
                    indices = segment_indices[bins == colour_bin]
                    x_pairs = np.empty(indices.size * 2, dtype=float)
                    y_pairs = np.empty(indices.size * 2, dtype=float)
                    x_pairs[0::2], x_pairs[1::2] = ppm[indices], ppm[indices + 1]
                    y_pairs[0::2], y_pairs[1::2] = (
                        plot_values[indices], plot_values[indices + 1]
                    )
                    colour = MATLAB_JET.mapToQColor((colour_bin + 0.5) / 128)
                    self.loading_value_plot.plot(
                        x_pairs,
                        y_pairs,
                        connect="pairs",
                        pen=pg.mkPen(colour, width=1.2),
                        skipFiniteCheck=True,
                    )

        finite_plot_values = plot_values[np.isfinite(plot_values)]
        if finite_plot_values.size:
            y_min = float(np.min(finite_plot_values))
            y_max = float(np.max(finite_plot_values))
            if y_min == y_max:
                y_padding = max(abs(y_min), 1.0) * 0.05
                y_min -= y_padding
                y_max += y_padding
            self.loading_value_plot.setYRange(y_min, y_max, padding=0.05)

        component_name = self.result["component_names"][component]
        self.loading_value_plot.setTitle(f"Valores de carga — {component_name}")

    def update_model_selection(self) -> None:
        self.model_selection_plot.clear()
        self.model_selection_legend.clear()
        self.model_selection_table.setRowCount(0)
        supervised_methods = {"plsda", "orthogonalized_plsda"}
        if self.result is None or self.result.get("method") not in supervised_methods:
            self.model_selection_plot.setTitle("Selección disponible para modelos supervisados")
            self.model_selection_summary.setText(
                "La selección por componentes no se aplica al PCA descriptivo."
            )
            return

        performance = self.result["performance"]
        components = np.atleast_1d(performance.get("components", [1])).astype(int)
        mean_ber = np.atleast_1d(performance["mean_ber"]).astype(float)
        sd_ber = np.atleast_1d(performance.get("sd_ber", np.zeros_like(mean_ber))).astype(float)
        calibration_ber = np.atleast_1d(
            performance.get("calibration_ber", np.full(len(components), np.nan))
        ).astype(float)
        selection = performance.get("selection", {})
        minimum_component = int(selection.get("minimum_error_component", int(components[np.nanargmin(mean_ber)])))
        suggested_component = int(selection.get("suggested_component", minimum_component))
        current_component = int(selection.get("current_component", suggested_component))
        self.current_model_label.setText(f"Modelo actual: {current_component} componente(s)")
        self.apply_model_button.setEnabled(True)

        self.model_selection_plot.plot(
            components,
            mean_ber,
            pen=pg.mkPen("#2563eb", width=2.6),
            symbol="o",
            symbolBrush="#2563eb",
            symbolSize=8,
            name="BER validación cruzada",
        )
        finite_sd = np.where(np.isfinite(sd_ber), sd_ber, 0.0)
        self.model_selection_plot.addItem(
            pg.ErrorBarItem(
                x=components.astype(float), y=mean_ber, height=finite_sd,
                beam=0.15, pen=pg.mkPen(QColor(96, 165, 250, 180), width=1.2),
            )
        )
        if np.any(np.isfinite(calibration_ber)):
            self.model_selection_plot.plot(
                components,
                calibration_ber,
                pen=pg.mkPen("#f97316", width=2, style=Qt.DashLine),
                symbol="s",
                symbolBrush="#f97316",
                symbolSize=7,
                name="BER ajuste",
            )
        if len(components) > 1:
            self.model_selection_plot.addItem(
                pg.InfiniteLine(
                    pos=suggested_component,
                    angle=90,
                    pen=pg.mkPen("#22c55e", width=1.7, style=Qt.DashLine),
                    label="Sugerido",
                    labelOpts={"position": 0.92, "color": "#22c55e"},
                )
            )
            if minimum_component != suggested_component:
                self.model_selection_plot.addItem(
                    pg.InfiniteLine(
                        pos=minimum_component,
                        angle=90,
                        pen=pg.mkPen("#eab308", width=1.4, style=Qt.DotLine),
                        label="Mínimo",
                        labelOpts={"position": 0.78, "color": "#eab308"},
                    )
                )
            self.model_selection_plot.addItem(
                pg.InfiniteLine(
                    pos=current_component,
                    angle=90,
                    pen=pg.mkPen("#a855f7", width=2.0),
                    label="Actual",
                    labelOpts={"position": 0.64, "color": "#a855f7"},
                )
            )
        self.model_selection_plot.setLabel(
            "bottom",
            "Número de componentes",
        )
        self.model_selection_plot.setLabel("left", "Error balanceado (BER)")
        self.model_selection_plot.setTitle("Error de ajuste frente a validación cruzada")

        metric_keys = (
            "r2y", "q2y", "calibration_ber", "mean_ber",
            "sd_ber", "cv_auc_macro", "calibration_correct",
        )
        metric_arrays = {
            key: np.atleast_1d(performance.get(key, [np.nan] * len(components)))
            for key in metric_keys
        }
        self.model_selection_table.setRowCount(len(components))
        for row, component in enumerate(components):
            label = f"{component} componente" + ("s" if component != 1 else "")
            tags: list[str] = []
            if component == suggested_component:
                tags.append("sugerido")
            if component == minimum_component and component != suggested_component:
                tags.append("mínimo")
            state = "Actual" if component == current_component else ""
            if component == suggested_component and component != current_component:
                state = "Sugerido"
            if component == minimum_component and component != suggested_component:
                state += (" + " if state else "") + "Mínimo"
            values = [
                label,
                state,
                self._format_metric(metric_arrays["r2y"][row], ".4f"),
                self._format_metric(metric_arrays["q2y"][row], ".4f"),
                self._format_metric(metric_arrays["calibration_ber"][row], ".4f"),
                self._format_metric(metric_arrays["mean_ber"][row], ".4f"),
                self._format_metric(metric_arrays["sd_ber"][row], ".3g"),
                self._format_metric(metric_arrays["cv_auc_macro"][row], ".4f"),
                self._format_metric(metric_arrays["calibration_correct"][row], ".0f"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter if column else Qt.AlignLeft | Qt.AlignVCenter)
                if component == current_component:
                    item.setBackground(QColor(168, 85, 247, 75))
                elif component == suggested_component:
                    item.setBackground(QColor(22, 163, 74, 70))
                elif component == minimum_component:
                    item.setBackground(QColor(234, 179, 8, 55))
                self.model_selection_table.setItem(row, column, item)
        self.model_selection_table.resizeColumnsToContents()

        effective = performance.get("effective_validation_fraction", {})
        fraction_text = ""
        if effective:
            fraction_text = (
                f" Validación efectiva por fold: "
                f"{float(effective['minimum']) * 100:.1f}–"
                f"{float(effective['maximum']) * 100:.1f} % "
                f"(media {float(effective['average']) * 100:.1f} %)."
            )
        if selection.get("criterion") == "one_standard_error_on_mean_ber":
            criterion_text = (
                f"Sugerencia: {suggested_component} LV(s), el modelo más sencillo dentro "
                f"de un error estándar del BER mínimo ({minimum_component} LV(s)). "
                "Es una selección interna exploratoria, no una evaluación independiente."
            )
        else:
            criterion_text = (
                "La complejidad se conserva según la selección indicada por el motor."
            )
        warnings: list[str] = []
        minimum_training = int(performance.get("minimum_training_samples", 0) or 0)
        if minimum_training and int(np.max(components)) / minimum_training >= 0.5:
            warnings.append(
                f"se evaluaron {int(np.max(components))} LVs con un mínimo de "
                f"{minimum_training} muestras de entrenamiento"
            )
        selected_index = max(0, min(current_component - 1, len(mean_ber) - 1))
        if np.isfinite(calibration_ber[selected_index]) and mean_ber[selected_index] - calibration_ber[selected_index] > 0.10:
            warnings.append("hay una brecha marcada entre ajuste y validación")
        warning_text = ""
        if warnings:
            warning_text = " <b>Advertencia:</b> " + "; ".join(warnings) + "."
        current_text = f"Modelo actual: {current_component} componente(s)"
        self.model_selection_summary.setText(
            f"<b>{current_text}.</b> " + criterion_text + fraction_text + warning_text
        )

    def _set_selected_model_as_current(self) -> None:
        row = self.model_selection_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Seleccionar modelo", "Seleccione primero una fila de la tabla."
            )
            return
        self._set_current_model_from_row(row, 0)

    def _set_current_model_from_row(self, row: int, _column: int) -> None:
        if self.process is not None:
            QMessageBox.information(
                self, "Cálculo en curso", "Espere a que termine el cálculo actual."
            )
            return
        if self.result is None:
            return
        performance = self.result.get("performance", {})
        components = np.atleast_1d(performance.get("components", [])).astype(int)
        if row < 0 or row >= len(components):
            return
        self._apply_current_model(int(components[row]))

    def _apply_current_model(self, component_count: int) -> None:
        assert self.result is not None
        candidates = self.result.get("candidate_models", [])
        candidate = next(
            (
                value for value in candidates
                if int(value.get("component_count", 0)) == component_count
            ),
            None,
        )
        if candidate is None:
            QMessageBox.warning(
                self,
                "Modelo no disponible",
                "El resultado fue creado con una versión anterior y no contiene "
                "la reconstrucción de este modelo.",
            )
            return
        for key in (
            "component_names", "explained_variance", "cumulative_variance",
            "scores", "loadings",
        ):
            self.result[key] = candidate[key]
        self.result["performance"].setdefault("selection", {})[
            "current_component"
        ] = component_count
        self.result.pop("permutation_test", None)
        if self.result.get("orthogonalization"):
            self.result["orthogonalization"]["orthogonal_components"] = max(
                0, component_count - 1
            )
        self._render_result()
        self._set_dirty(True)
        self.statusBar().showMessage(
            f"Modelo actual establecido en {component_count} LV"
            + ("s" if component_count != 1 else "")
        )

    def update_fit_plot(self) -> None:
        self.fit_plot.clear()
        if self.result is None:
            self.fit_plot.setTitle("Métricas de ajuste no disponibles")
            return
        metric = self.fit_metric.currentData()
        if self.result.get("method") in {"plsda", "orthogonalized_plsda"}:
            performance = self.result["performance"]
            x = np.asarray(performance["components"], dtype=float)
            if metric in {"ber", "accuracy"}:
                values = np.asarray(performance[f"mean_{metric}"], dtype=float)
                deviation = np.asarray(performance[f"sd_{metric}"], dtype=float)
                upper = self.fit_plot.plot(
                    x, values + deviation, pen=pg.mkPen(QColor(96, 165, 250, 100), width=1)
                )
                lower = self.fit_plot.plot(
                    x, values - deviation, pen=pg.mkPen(QColor(96, 165, 250, 100), width=1)
                )
                self.fit_plot.addItem(
                    pg.FillBetweenItem(upper, lower, brush=QColor(37, 99, 235, 55))
                )
                label = "BER" if metric == "ber" else "Exactitud"
                title = f"{label}: media ± DE"
            else:
                values = np.asarray(performance[metric], dtype=float)
                label = "R²Y" if metric == "r2y" else "Q²Y"
                title = label
        else:
            fit = self.result.get("fit_metrics")
            if not fit:
                self.fit_plot.setTitle("Métricas de ajuste no disponibles")
                return
            x = np.asarray(fit["components"], dtype=float)
            values = np.asarray(fit[metric], dtype=float)
            label = "RMSE" if metric == "rmse" else "R²X acumulado"
            title = label
        self.fit_plot.plot(
            x,
            values,
            pen=pg.mkPen("#2563eb", width=2.5),
            symbol="o",
            symbolBrush="#2563eb",
            symbolSize=8,
        )
        self.fit_plot.setTitle(title)
        self.fit_plot.setLabel("bottom", "Componentes")
        self.fit_plot.setLabel("left", label)

    def update_confusion_table(self) -> None:
        self.confusion_table.clear()
        if (
            self.result is None
            or self.result.get("method") not in {"plsda", "orthogonalized_plsda"}
            or self.confusion_component.count() == 0
        ):
            self.confusion_table.setRowCount(0)
            self.confusion_table.setColumnCount(0)
            return
        component = self._current_performance_index()
        confusion = self.result["performance"]["confusion_matrices"][component]
        labels = confusion["labels"]
        values = confusion["matrix"]
        self.confusion_table.setRowCount(len(labels))
        self.confusion_table.setColumnCount(len(labels))
        self.confusion_table.setHorizontalHeaderLabels(labels)
        self.confusion_table.setVerticalHeaderLabels(labels)
        for row, row_values in enumerate(values):
            for column, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                if row == column:
                    item.setBackground(QColor(22, 163, 74, 90))
                self.confusion_table.setItem(row, column, item)
        self.confusion_table.resizeColumnsToContents()

    def update_roc_plot(self) -> None:
        self.roc_plot.clear()
        self.roc_legend.clear()
        self.threshold_plot.clear()
        self.threshold_legend.clear()
        self.roc_plot.plot([0, 1], [0, 1], pen=pg.mkPen(QColor(148, 163, 184, 150), style=Qt.DashLine))
        self.roc_plot.setLabel("bottom", "1 − especificidad")
        self.roc_plot.setLabel("left", "Sensibilidad")
        self.roc_plot.setXRange(0, 1, padding=0.02)
        self.roc_plot.setYRange(0, 1, padding=0.02)
        self.threshold_plot.setLabel("bottom", "Umbral sobre Y predicha")
        self.threshold_plot.setLabel("left", "Proporción")
        self.threshold_plot.setYRange(0, 1, padding=0.02)
        if (
            self.result is None
            or self.result.get("method") not in {"plsda", "orthogonalized_plsda"}
            or self.roc_component.count() == 0
            or self.roc_class.count() == 0
        ):
            self.roc_summary.setText("ROC disponible para PLS-DA y OPLS-DA")
            return
        component = self._current_performance_index()
        class_levels = self.result["class_levels"]
        class_name = self.roc_class.currentText()
        class_index = class_levels.index(class_name)
        performance = self.result["performance"]
        _, cv_truths, cv_scores = mean_external_scores(
            performance["repetitions"], component
        )
        calibration = performance.get("calibration")
        calibration_truths: list[str] = []
        calibration_scores: np.ndarray | None = None
        if calibration:
            calibration_truths = list(calibration["truth"])
            calibration_values = np.asarray(calibration["decision_values"], dtype=float)
            calibration_scores = calibration_values[:, :, component]
        self._ensure_class_styles(class_levels)
        color = self.class_styles[class_name].color
        calibration_curve = None
        if calibration_scores is not None:
            calibration_curve = binary_roc(
                np.asarray(calibration_truths) == class_name,
                calibration_scores[:, class_index],
            )
            self.roc_plot.plot(
                calibration_curve.false_positive_rate,
                calibration_curve.true_positive_rate,
                pen=pg.mkPen(color, width=1.7, style=Qt.DashLine),
                name=f"Ajuste (AUC {calibration_curve.auc:.3f})",
            )
        cv_curve = binary_roc(
            np.asarray(cv_truths) == class_name,
            cv_scores[:, class_index],
        )
        self.roc_plot.plot(
            cv_curve.false_positive_rate,
            cv_curve.true_positive_rate,
            pen=pg.mkPen(color, width=2.6),
            name=f"Validación cruzada (AUC {cv_curve.auc:.3f})",
        )
        component_label = self.roc_component.currentText()
        self.roc_plot.setTitle(f"ROC — {class_name} — {component_label}")
        summary = f"<b>{class_name}</b> · AUC CV: {cv_curve.auc:.3f}"
        if calibration_curve is not None:
            summary += f" · AUC ajuste: {calibration_curve.auc:.3f}"
        cv_threshold = sensitivity_specificity_curve(
            np.asarray(cv_truths) == class_name, cv_scores[:, class_index]
        )
        self.threshold_plot.plot(
            cv_threshold.thresholds,
            cv_threshold.sensitivity,
            pen=pg.mkPen("#ef4444", width=2.2, style=Qt.DashLine),
            name="Sensibilidad CV",
        )
        self.threshold_plot.plot(
            cv_threshold.thresholds,
            cv_threshold.specificity,
            pen=pg.mkPen("#2563eb", width=2.2, style=Qt.DashLine),
            name="Especificidad CV",
        )
        self.threshold_plot.addItem(
            pg.InfiniteLine(
                pos=cv_threshold.optimal_threshold,
                angle=90,
                pen=pg.mkPen("#dc2626", width=1.8, style=Qt.DashLine),
                label="Umbral CV",
                labelOpts={"position": 0.9, "color": "#dc2626"},
            )
        )
        summary += f" · Umbral CV exploratorio: {cv_threshold.optimal_threshold:.4g}"
        if calibration_scores is not None:
            calibration_threshold = sensitivity_specificity_curve(
                np.asarray(calibration_truths) == class_name,
                calibration_scores[:, class_index],
            )
            self.threshold_plot.plot(
                calibration_threshold.thresholds,
                calibration_threshold.sensitivity,
                pen=pg.mkPen("#ef4444", width=1.8),
                name="Sensibilidad ajuste",
            )
            self.threshold_plot.plot(
                calibration_threshold.thresholds,
                calibration_threshold.specificity,
                pen=pg.mkPen("#2563eb", width=1.8),
                name="Especificidad ajuste",
            )
        self.threshold_plot.setTitle(f"Respuesta frente al umbral — {class_name}")
        self.roc_summary.setText(summary)

    def _current_performance_index(self) -> int:
        if self.result is None:
            return 0
        selection = self.result.get("performance", {}).get("selection", {})
        return max(0, int(selection.get("current_component", 1)) - 1)

    def run_permutation_test(self) -> None:
        if self.result is None or self.dataset is None or self.process is not None:
            return
        method = self.result.get("method")
        if method not in {"plsda", "orthogonalized_plsda"}:
            QMessageBox.information(
                self, "Permutaciones", "El test requiere un modelo supervisado."
            )
            return
        selected_names = list(self.result["sample_names"])
        index_by_name = {
            name: index for index, name in enumerate(self.dataset.sample_names)
        }
        try:
            selected_indices = [index_by_name[name] for name in selected_names]
        except KeyError as exc:
            QMessageBox.critical(
                self, "Permutaciones", f"La muestra {exc!s} ya no existe en el dataset."
            )
            return
        classes = [
            self.sample_table.item(row, TABLE_COLUMNS["class"]).text().strip()
            or "Sin asignar"
            for row in range(self.sample_table.rowCount())
        ]
        table_row_by_name = {
            self.sample_table.item(row, TABLE_COLUMNS["sample_name"]).text(): row
            for row in range(self.sample_table.rowCount())
        }
        for sample_name, class_name in zip(
            selected_names, self.result["classes"], strict=True
        ):
            classes[table_row_by_name[sample_name]] = class_name
        performance = self.result["performance"]
        selection = performance.get("selection", {})
        current_components = int(
            selection.get("current_component", len(self.result["component_names"]))
        )
        opls = self.result.get("opls", {})
        job = {
            "schema_version": "1.0",
            "method": method,
            "dataset": {
                "path": self.dataset.path,
                "delimiter": self.dataset.delimiter,
                "orientation": self.dataset.orientation,
                "representation": self.dataset.representation,
                "modality": self.dataset.modality,
                "axis_label": self.dataset.axis_label,
            },
            "preprocessing": {
                "mean_center": True,
                "scaling": self.result.get("preprocessing", {}).get(
                    "scaling", self.feature_scaling.currentData()
                ),
            },
            "selected_sample_indices": selected_indices,
            "classes": classes,
            "biological_ids": [
                self.sample_table.item(row, TABLE_COLUMNS["biological_id"]).text().strip()
                for row in range(self.sample_table.rowCount())
            ],
            "current_components": current_components,
            "current_orthogonal_components": int(opls.get("orthogonal_components", 0)),
            "orthogonal_selection": selection.get("mode", "manual"),
            "validation": {
                "strategy": performance.get("validation_method", "random_subsets"),
                "repeats": int(performance["repeats"]),
                "data_splits": int(performance.get("data_splits", 5)),
                "train_fraction": float(
                    performance.get(
                        "configured_train_fraction", performance.get("train_fraction", 0.8)
                    ) or performance.get("train_fraction", 0.8)
                ),
                "seed": int(performance.get("seed", 1234)),
            },
            "permutations": {
                "count": self.permutation_count.value(), "seed": 4321,
                "analysis_mode": self.permutation_analysis_mode.currentData(),
            },
        }
        work = Path(tempfile.gettempdir()) / "arii-work"
        work.mkdir(exist_ok=True)
        stamp = str(time.time_ns())
        job_path = work / f"permutation-{stamp}.job.json"
        self.permutation_result_path = work / f"permutation-{stamp}.result.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        worker = worker_path("permutation_worker.R")
        started = self._start_r_job(
            worker=worker, job_path=job_path,
            result_path=self.permutation_result_path,
            dataset_path=Path(self.dataset.path), stamp=stamp,
            finished_callback=self._permutation_finished,
            local_status=(
                f"Ejecutando {self.permutation_count.value()} permutaciones; "
                "este cálculo puede tardar…"
            ),
            method=method,
        )
        if started:
            self.run_button.setEnabled(False)
            self.run_permutation_button.setEnabled(False)
            self.apply_model_button.setEnabled(False)

    def _permutation_finished(
        self, exit_code: int, _status: QProcess.ExitStatus
    ) -> None:
        assert self.process is not None
        self._remote_progress()
        stderr = bytes(self.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        self.process.deleteLater()
        self.process = None
        self.run_button.setEnabled(True)
        self.run_permutation_button.setEnabled(True)
        self.apply_model_button.setEnabled(self.result is not None)
        if (
            exit_code != 0
            or self.permutation_result_path is None
            or not self.permutation_result_path.exists()
        ):
            QMessageBox.critical(
                self,
                "Error en permutaciones",
                stderr or "El motor R no produjo el test de permutaciones.",
            )
            self.statusBar().showMessage("El test de permutaciones falló")
            return
        try:
            permutation = json.loads(
                self.permutation_result_path.read_text(encoding="utf-8")
            )
            assert self.result is not None
            self.result["permutation_test"] = permutation
            self.update_permutation_plot()
            self._set_dirty(True)
            self.statusBar().showMessage(
                f"Test completado: {permutation['permutations']} permutaciones"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Resultado de permutaciones inválido", str(exc))

    def update_permutation_plot(self) -> None:
        self.permutation_plot.clear()
        if self.result is None or not self.result.get("permutation_test"):
            self.permutation_plot.setTitle("Distribución nula por permutación")
            self.permutation_summary.setText(
                "Ejecute el test sobre el modelo actual. Al cambiar de modelo, el test anterior se invalida."
            )
            return
        permutation = self.result["permutation_test"]
        view = self.permutation_view.currentData()
        metric = self.permutation_metric.currentData()
        correlation_available = permutation.get("correlation_to_original") is not None
        residual_available = permutation.get("residual_comparison") is not None
        self._sync_permutation_responses(permutation)
        self.permutation_metric.setEnabled(view == "histogram" or not correlation_available)
        self.permutation_response.setEnabled(view == "residual" and residual_available)
        if view == "residual" and residual_available:
            self._plot_permutation_residual(permutation)
        elif view == "correlation" and correlation_available:
            self._plot_permutation_correlation(permutation)
        else:
            self._plot_permutation_histogram(permutation, metric)
        self._update_permutation_summary(permutation)

    def _sync_permutation_responses(self, permutation: dict) -> None:
        residual = permutation.get("residual_comparison") or {}
        wanted = ["global", *residual.get("class_levels", [])]
        existing = [self.permutation_response.itemData(index) for index in range(
            self.permutation_response.count()
        )]
        if existing == wanted:
            return
        current = self.permutation_response.currentData()
        self.permutation_response.blockSignals(True)
        self.permutation_response.clear()
        for value in wanted:
            self.permutation_response.addItem("Global" if value == "global" else value, value)
        selected = self.permutation_response.findData(current)
        self.permutation_response.setCurrentIndex(max(0, selected))
        self.permutation_response.blockSignals(False)

    def _plot_permutation_histogram(self, permutation: dict, metric: str) -> None:
        values = np.atleast_1d(permutation["null"][metric]).astype(float)
        values = values[np.isfinite(values)]
        observed = float(permutation["observed"][metric])
        if values.size:
            bin_count = min(30, max(5, int(np.ceil(np.sqrt(values.size)))))
            counts, edges = np.histogram(values, bins=bin_count)
            centers = (edges[:-1] + edges[1:]) / 2
            widths = np.diff(edges)
            self.permutation_plot.addItem(
                pg.BarGraphItem(
                    x=centers, height=counts, width=widths * 0.9,
                    brush=QColor(37, 99, 235, 150), pen=pg.mkPen("#60a5fa"),
                )
            )
        self.permutation_plot.addItem(
            pg.InfiniteLine(
                pos=observed, angle=90, pen=pg.mkPen("#f97316", width=2.4),
                label="Observado", labelOpts={"position": 0.9, "color": "#f97316"},
            )
        )
        labels = {
            "q2y": "Q²Y externo", "r2y": "R²Y", "ber": "BER externo",
            "auc_macro": "AUC macro externo",
        }
        self.permutation_plot.setLabel("bottom", labels[metric])
        self.permutation_plot.setLabel("left", "Frecuencia")
        self.permutation_plot.setTitle(
            f"Distribución nula — {labels[metric]} — {permutation['permutations']} permutaciones"
        )

    def _plot_permutation_correlation(self, permutation: dict) -> None:
        correlations = np.atleast_1d(
            permutation["correlation_to_original"]
        ).astype(float)
        palette = {"r2y": "#22c55e", "q2y": "#3b82f6"}
        labels = {"r2y": "R²Y", "q2y": "Q²Y externo"}
        for metric in ("r2y", "q2y"):
            values = np.atleast_1d(permutation["null"][metric]).astype(float)
            valid = np.isfinite(correlations) & np.isfinite(values)
            x_values, y_values = correlations[valid], values[valid]
            self.permutation_plot.plot(
                x_values, y_values, pen=None,
                symbol="o", symbolSize=7,
                symbolBrush=QColor(palette[metric]),
                symbolPen=pg.mkPen(palette[metric]), name=f"{labels[metric]} permutado",
            )
            observed = float(permutation["observed"][metric])
            self.permutation_plot.plot(
                [1.0], [observed], pen=None, symbol="o", symbolSize=10,
                symbolBrush=QColor("#f97316"),
                symbolPen=pg.mkPen("#fed7aa", width=1.5),
                name=f"{labels[metric]} observado",
            )
            if x_values.size >= 2 and np.unique(x_values).size >= 2:
                slope, intercept = np.polyfit(x_values, y_values, 1)
                line_x = np.array([float(np.min(x_values)), 1.0])
                self.permutation_plot.plot(
                    line_x, slope * line_x + intercept,
                    pen=pg.mkPen(palette[metric], width=1.5, style=Qt.DashLine),
                )
        self.permutation_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen("#94a3b8", width=1))
        )
        self.permutation_plot.setLabel(
            "bottom", "Correlación entre Y permutada e Y original"
        )
        self.permutation_plot.setLabel("left", "Bondad de ajuste / predicción")
        self.permutation_plot.setTitle(
            f"R²Y y Q²Y frente a correlación de Y — {permutation['permutations']} permutaciones"
        )

    def _plot_permutation_residual(self, permutation: dict) -> None:
        residual = permutation["residual_comparison"]
        response = self.permutation_response.currentData() or "global"
        correlations = np.atleast_1d(permutation["correlation_to_original"]).astype(float)
        palette = {"calibration": "#22c55e", "cross_validated": "#3b82f6"}
        labels = {"calibration": "Ajuste", "cross_validated": "Validación cruzada"}
        symbols = {"calibration": "t", "cross_validated": "s"}
        for mode in ("calibration", "cross_validated"):
            values = np.atleast_1d(
                residual["null_standardized_ssq"][mode][response]
            ).astype(float)
            valid = np.isfinite(correlations) & np.isfinite(values)
            x_values, y_values = correlations[valid], values[valid]
            self.permutation_plot.plot(
                x_values, y_values, pen=None, symbol=symbols[mode], symbolSize=8,
                symbolBrush=QColor(palette[mode]), symbolPen=pg.mkPen(palette[mode]),
                name=f"{labels[mode]} permutado",
            )
            observed = float(residual["observed_standardized_ssq"][mode][response])
            self.permutation_plot.plot(
                [1.0], [observed], pen=None, symbol="o", symbolSize=10,
                symbolBrush=QColor(palette[mode]),
                symbolPen=pg.mkPen("#475569", width=1.4),
                name=f"{labels[mode]} observado",
            )
            if x_values.size >= 2 and np.unique(x_values).size >= 2:
                slope, intercept = np.polyfit(x_values, y_values, 1)
                line_x = np.array([float(np.min(x_values)), 1.0])
                self.permutation_plot.plot(
                    line_x, slope * line_x + intercept,
                    pen=pg.mkPen(palette[mode], width=1.4, style=Qt.DashLine),
                )
        self.permutation_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen("#94a3b8", width=1))
        )
        response_label = "global" if response == "global" else f"clase {response}"
        self.permutation_plot.setLabel(
            "bottom", "Correlación entre Y permutada e Y original"
        )
        self.permutation_plot.setLabel("left", "SSQ residual estandarizada (menor es mejor)")
        self.permutation_plot.setTitle(
            f"Comparación residual — {response_label} — "
            f"{permutation['permutations']} permutaciones"
        )

    def _update_permutation_summary(self, permutation: dict) -> None:
        p_values = permutation["empirical_p"]
        policy = "complejidad actual fija"
        rejection_values = np.atleast_1d(
            permutation.get("null_rejected_fraction", [0])
        ).astype(float)
        rejection_text = ""
        if np.any(rejection_values > 0):
            rejection_text = (
                f" Rechazo medio de ajustes nulos: "
                f"{np.mean(rejection_values) * 100:.1f} %."
            )
        timing = permutation.get("timing", {})
        timing_text = ""
        if timing.get("total_seconds") is not None:
            workers = int(timing.get("parallel_workers", 1))
            timing_text = (
                f" Tiempo total: {float(timing['total_seconds']):.1f} s; "
                f"promedio por permutación: "
                f"{float(timing.get('mean_permutation_seconds', 0)):.1f} s; "
                f"{workers} proceso{'s' if workers != 1 else ''} en paralelo."
            )
        residual_text = ""
        residual = permutation.get("residual_comparison")
        if residual:
            response = self.permutation_response.currentData() or "global"
            tests = residual["tests"]
            calibration = tests["calibration"][response]
            cross_validated = tests["cross_validated"][response]
            residual_text = (
                "<br><b>Comparación residual "
                f"({'global' if response == 'global' else response})</b> · "
                "Ajuste: "
                f"Wilcoxon={self._format_metric(calibration.get('wilcoxon'), '.4f')}, "
                f"Signos={self._format_metric(calibration.get('sign_test'), '.4f')}, "
                f"t aleatorizado={self._format_metric(calibration.get('randomization_t'), '.4f')} · "
                "CV: "
                f"Wilcoxon={self._format_metric(cross_validated.get('wilcoxon'), '.4f')}, "
                f"Signos={self._format_metric(cross_validated.get('sign_test'), '.4f')}, "
                f"t aleatorizado={self._format_metric(cross_validated.get('randomization_t'), '.4f')}."
            )
        self.permutation_summary.setText(
            f"<b>Test sobre el modelo actual</b> · {policy} · "
            f"{permutation['permutations']} permutaciones por "
            f"{permutation.get('exchangeability_unit', 'sample')}.<br>"
            f"p(R²Y)={self._format_metric(p_values.get('r2y'), '.4f')} · "
            f"p(Q²Y)={self._format_metric(p_values.get('q2y'), '.4f')} · "
            f"p(BER)={self._format_metric(p_values.get('ber'), '.4f')} · "
            f"p(AUC)={self._format_metric(p_values.get('auc_macro'), '.4f')}."
            f"{rejection_text} Corrección empírica +1.{timing_text}{residual_text}"
        )

    def update_score_plot(self) -> None:
        if self.result is None or self.x_component.count() == 0:
            return
        xi, yi = self.x_component.currentIndex(), self.y_component.currentIndex()
        scores = np.asarray(self.result["scores"], dtype=float)
        classes = self.result["classes"]
        names = self.result["sample_names"]
        explained = np.asarray(self.result["explained_variance"], dtype=float) * 100
        self.score_plot.clear()
        self.score_legend.clear()
        self.score_legend.setVisible(self.show_legend.isChecked())
        origin_pen = pg.mkPen("#64748b", width=1.5)
        self.score_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=90, pen=origin_pen),
            ignoreBounds=True,
        )
        self.score_plot.addItem(
            pg.InfiniteLine(pos=0.0, angle=0, pen=origin_pen),
            ignoreBounds=True,
        )
        unique_classes = list(dict.fromkeys(classes))
        self._ensure_class_styles(unique_classes)
        for index, class_name in enumerate(unique_classes):
            rows = [i for i, value in enumerate(classes) if value == class_name]
            style = self.class_styles[class_name]
            scatter = pg.ScatterPlotItem(
                x=scores[rows, xi], y=scores[rows, yi],
                size=style.size, symbol=style.symbol, brush=QColor(style.color),
                pen=pg.mkPen("#ffffff", width=0.8), name=class_name,
                data=[
                    {"sample": names[i], "class": classes[i], "table_row": self._sample_table_row(names[i])}
                    for i in rows
                ],
                hoverable=True,
                hoverSize=14,
                tip=lambda x, y, data: (
                    f"Muestra: {data['sample']}\n"
                    f"Clase: {data['class']}\n"
                    f"X: {x:.4g}   Y: {y:.4g}"
                ),
            )
            scatter.sigClicked.connect(self._score_point_clicked)
            self.score_plot.addItem(scatter)
        self._add_hotelling_ellipse(scores[:, [xi, yi]])
        self.score_plot.setLabel("bottom", f"{self.result['component_names'][xi]} ({explained[xi]:.2f}%)")
        self.score_plot.setLabel("left", f"{self.result['component_names'][yi]} ({explained[yi]:.2f}%)")

    def _sample_table_row(self, sample_name: str) -> int:
        for row in range(self.sample_table.rowCount()):
            if self.sample_table.item(row, 1).text() == sample_name:
                return row
        return -1

    def _score_point_clicked(self, _item: object, points: list, _event: object) -> None:
        if not points:
            return
        row = points[0].data().get("table_row", -1)
        if row >= 0:
            self.sample_table.selectRow(row)
            self.sample_table.scrollToItem(self.sample_table.item(row, 1))
            self.statusBar().showMessage(
                f"Muestra seleccionada: {self.sample_table.item(row, 1).text()}"
            )

    def _mark_dirty(self, _item: QTableWidgetItem) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _settings_changed(self, _value: object) -> None:
        if not self._loading and self.dataset is not None:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        name = self.project_path.name if self.project_path else "Sin guardar"
        marker = " *" if dirty else ""
        self.setWindowTitle(f"Arii — {name}{marker}")

    def _project_payload(self) -> dict:
        if self.dataset is None:
            raise ValueError("No hay un dataset abierto")
        dataset_path = Path(self.dataset.path)
        dataset_hash = fingerprint_file(dataset_path) if dataset_path.is_file() else None
        return {
            "schema_version": "1.0",
            "application": {"name": "Arii", "version": "1.0.0"},
            "dataset": {
                "path": self.dataset.path,
                "sha256": dataset_hash,
                "summary": self.dataset.to_dict(),
            },
            "samples": [
                {
                    "name": self.sample_table.item(row, 1).text(),
                    "included": self.sample_table.item(row, 0).checkState() == Qt.Checked,
                    "class": self.sample_table.item(row, 2).text().strip() or "Sin asignar",
                    "biological_id": self.sample_table.item(row, 3).text().strip(),
                }
                for row in range(self.sample_table.rowCount())
            ],
            "analysis": {
                "method": self.analysis_method.currentData(),
                "n_components": self.ncomp.value(),
                "preprocessing": {
                    "mean_center": True, "scaling": self.feature_scaling.currentData()
                },
                "hotelling_level": self.hotelling_level.currentData(),
                "supervised_validation": {
                    "strategy": self.validation_method.currentData(),
                    "repeats": self.supervised_repeats.value(),
                    "data_splits": self.supervised_splits.value(),
                    "monte_carlo_iterations": self.monte_carlo_iterations.value(),
                    "train_fraction": self.monte_carlo_train_percent.value() / 100,
                    "seed": 1234,
                },
                "permutation_count": self.permutation_count.value(),
                "permutation_analysis_mode": self.permutation_analysis_mode.currentData(),
                "execution": {
                    "target": self.execution_target.currentData(),
                    "cluster_profile_id": "default-slurm",
                },
                "display": {
                    "show_legend": self.show_legend.isChecked(),
                    "score_x": self.x_component.currentIndex(),
                    "score_y": self.y_component.currentIndex(),
                    "loading_component": self.loading_component.currentIndex(),
                    "loading_value_component": self.loading_value_component.currentIndex(),
                    "roc_component": self.roc_component.currentIndex(),
                    "roc_class": self.roc_class.currentIndex(),
                    "roc_view": self.roc_view.currentData(),
                    "permutation_view": self.permutation_view.currentData(),
                    "permutation_metric": self.permutation_metric.currentData(),
                    "permutation_response": self.permutation_response.currentData(),
                },
            },
            "class_styles": {
                name: style.to_dict() for name, style in self.class_styles.items()
            },
        }

    def save_current_project(self) -> bool:
        if self.dataset is None:
            QMessageBox.information(self, "Guardar proyecto", "Abra primero un dataset.")
            return False
        if self.project_path is None:
            return self.save_project_as()
        try:
            self.project_path = save_project(
                self.project_path, self._project_payload(), self.result
            )
            self._set_dirty(False)
            self.statusBar().showMessage(f"Proyecto guardado: {self.project_path.name}")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo guardar", str(exc))
            return False

    def save_project_as(self) -> bool:
        if self.dataset is None:
            QMessageBox.information(self, "Guardar proyecto", "Abra primero un dataset.")
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar proyecto Arii", "", "Proyecto Arii (*.arii)"
        )
        if not path:
            return False
        self.project_path = Path(path)
        return self.save_current_project()

    def open_project(self) -> None:
        if not self._maybe_save_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir proyecto Arii", "", "Proyecto Arii (*.arii)"
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            manifest, result = load_project(path)
            self._restore_project(Path(path), manifest, result)
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo abrir el proyecto", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _restore_project(self, path: Path, manifest: dict, result: dict | None) -> None:
        self._loading = True
        try:
            summary_data = manifest["dataset"]["summary"]
            self.dataset = OmicsMatrixSummary.from_dict(summary_data)
            self.project_path = path
            self.result = result
            self.class_styles = {
                name: ClassStyle.from_dict(style)
                for name, style in manifest.get("class_styles", {}).items()
            }
            self._populate_samples()
            saved_samples = manifest["samples"]
            if len(saved_samples) != self.sample_table.rowCount():
                raise ValueError("La cantidad de muestras guardada no coincide con el dataset")
            for row, sample in enumerate(saved_samples):
                self.sample_table.item(row, 0).setCheckState(
                    Qt.Checked if sample["included"] else Qt.Unchecked
                )
                self.sample_table.item(row, 2).setText(sample["class"])
                self.sample_table.item(row, TABLE_COLUMNS["biological_id"]).setText(
                    sample.get("biological_id", "")
                )
            analysis = manifest["analysis"]
            saved_method = analysis.get("method", "pca")
            if saved_method == "oplsda":
                saved_method = "orthogonalized_plsda"
                self.result = None
                QMessageBox.information(
                    self,
                    "Modelo heredado retirado",
                    "El proyecto usaba OPLS-DA mediante ropls. La configuración se "
                    "convirtió al OPLS-DA actual; ejecute nuevamente el modelo.",
                )
            method_index = self.analysis_method.findData(saved_method)
            if method_index >= 0:
                self.analysis_method.setCurrentIndex(method_index)
            self.ncomp.setValue(int(analysis["n_components"]))
            scaling_index = self.feature_scaling.findData(
                analysis.get("preprocessing", {}).get("scaling", "pareto")
            )
            if scaling_index >= 0:
                self.feature_scaling.setCurrentIndex(scaling_index)
            supervised = analysis.get("supervised_validation", {})
            validation_index = self.validation_method.findData(
                supervised.get("strategy", "random_subsets")
            )
            if validation_index >= 0:
                self.validation_method.setCurrentIndex(validation_index)
            self.supervised_repeats.setValue(int(supervised.get("repeats", 20)))
            legacy_train_fraction = float(supervised.get("train_fraction", 0.8))
            legacy_splits = round(1 / max(1e-9, 1 - legacy_train_fraction))
            self.supervised_splits.setValue(
                int(supervised.get("data_splits", legacy_splits))
            )
            self.monte_carlo_iterations.setValue(
                int(supervised.get("monte_carlo_iterations", 100))
            )
            self.monte_carlo_train_percent.setValue(
                int(round(float(supervised.get("train_fraction", 0.8)) * 100))
            )
            self.permutation_count.setValue(int(analysis.get("permutation_count", 100)))
            permutation_mode = self.permutation_analysis_mode.findData(
                analysis.get("permutation_analysis_mode", "both")
            )
            if permutation_mode >= 0:
                self.permutation_analysis_mode.setCurrentIndex(permutation_mode)
            level_index = self.hotelling_level.findData(analysis.get("hotelling_level"))
            if level_index >= 0:
                self.hotelling_level.setCurrentIndex(level_index)
            display = analysis.get("display", {})
            self.show_legend.setChecked(bool(display.get("show_legend", True)))
            execution = analysis.get("execution", {})
            target_index = self.execution_target.findData(execution.get("target", "local"))
            if target_index >= 0:
                self.execution_target.setCurrentIndex(target_index)
            dataset_file = Path(self.dataset.path)
            self.run_button.setEnabled(dataset_file.is_file())
            if dataset_file.is_file() and manifest["dataset"].get("sha256"):
                actual_hash = fingerprint_file(dataset_file)
                if actual_hash != manifest["dataset"]["sha256"]:
                    QMessageBox.warning(
                        self, "Dataset modificado",
                        "El archivo existe, pero su huella SHA-256 no coincide con la guardada."
                    )
            if self.result is not None:
                self._render_result()
                self.x_component.setCurrentIndex(
                    min(int(display.get("score_x", 0)), self.x_component.count() - 1)
                )
                self.y_component.setCurrentIndex(
                    min(int(display.get("score_y", 1)), self.y_component.count() - 1)
                )
                self.loading_component.setCurrentIndex(
                    min(int(display.get("loading_component", 0)), self.loading_component.count() - 1)
                )
                self.loading_value_component.setCurrentIndex(
                    min(
                        int(display.get("loading_value_component", 0)),
                        self.loading_value_component.count() - 1,
                    )
                )
                self.roc_component.setCurrentIndex(
                    min(int(display.get("roc_component", 0)), self.roc_component.count() - 1)
                )
                self.roc_class.setCurrentIndex(
                    min(int(display.get("roc_class", 0)), self.roc_class.count() - 1)
                )
                roc_view = self.roc_view.findData(display.get("roc_view", "roc"))
                if roc_view >= 0:
                    self.roc_view.setCurrentIndex(roc_view)
                permutation_view = self.permutation_view.findData(
                    display.get("permutation_view", "histogram")
                )
                if permutation_view >= 0:
                    self.permutation_view.setCurrentIndex(permutation_view)
                permutation_metric = self.permutation_metric.findData(
                    display.get("permutation_metric", "q2y")
                )
                if permutation_metric >= 0:
                    self.permutation_metric.setCurrentIndex(permutation_metric)
                permutation_response = self.permutation_response.findData(
                    display.get("permutation_response", "global")
                )
                if permutation_response >= 0:
                    self.permutation_response.setCurrentIndex(permutation_response)
            self._set_dirty(False)
            self.statusBar().showMessage(f"Proyecto abierto: {path.name}")
        finally:
            self._loading = False

    def _maybe_save_changes(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Cambios sin guardar",
            "¿Desea guardar los cambios del proyecto?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_current_project()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.process is not None:
            QMessageBox.information(
                self, "Cálculo en curso",
                "Espere a que termine el cálculo antes de cerrar Arii. "
                "La cancelación segura de trabajos Slurm se incorporará en el "
                "siguiente incremento.",
            )
            event.ignore()
            return
        if self._maybe_save_changes():
            event.accept()
        else:
            event.ignore()

    def export_results(self) -> None:
        if self.result is None or self.dataset is None:
            QMessageBox.information(self, "Exportar", "Ejecute o abra primero un modelo.")
            return
        # El contrato de exportación de valores de carga usa siempre la primera
        # dirección del modelo actual: Predictiva en OPLS-DA y LV1/PC1 en los
        # otros modelos, independientemente de la vista abierta.
        component = 0
        component_name = self.result["component_names"][component]
        default_name = f"loadings_{component_name.replace(' ', '_').lower()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar datos del gráfico de loadings",
            default_name,
            "CSV (*.csv)",
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            destination = Path(path).with_suffix(".csv")
            loadings = np.asarray(self.result["loadings"], dtype=float)
            feature_axis = self.result.get("feature_axis", {})
            feature_ids = self.result.get("feature_ids")
            generic_features = bool(feature_ids) and (
                feature_axis.get("representation") == "feature_table"
                or feature_axis.get("modality") != "1H-NMR"
            )
            with destination.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                if generic_features:
                    writer.writerow([
                        "feature_id", "axis_value", "standard_deviation",
                        f"weight_{component_name}",
                    ])
                    writer.writerows(zip(
                        feature_ids, self.result["ppm"],
                        self.result["standard_deviations"], loadings[:, component],
                        strict=True,
                    ))
                else:
                    writer.writerow(
                        ["ppm", "standard_deviation", f"weight_{component_name}"]
                    )
                    writer.writerows(zip(
                        self.result["ppm"],
                        self.result["standard_deviations"],
                        loadings[:, component],
                        strict=True,
                    ))
            QMessageBox.information(
                self,
                "Exportación completada",
                f"Se exportaron identificadores, eje, desviación estándar y weights de "
                f"{component_name} en:\n{destination}",
            )
            self.statusBar().showMessage(f"Loadings exportados: {destination.name}")
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo exportar", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _add_hotelling_ellipse(self, pair_scores: np.ndarray) -> None:
        assert self.result is not None
        confidence = self.hotelling_level.currentData()
        hotelling = self.result.get("hotelling_t2")
        if confidence is None or not hotelling or pair_scores.shape[0] < 3:
            return
        limit = float(hotelling["limits"][confidence])
        covariance = np.cov(pair_scores, rowvar=False, ddof=1)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        eigenvalues = np.maximum(eigenvalues, 0.0)
        angles = np.linspace(0.0, 2.0 * np.pi, 361)
        unit_circle = np.vstack((np.cos(angles), np.sin(angles)))
        transform = eigenvectors @ np.diag(np.sqrt(eigenvalues * limit))
        ellipse = pair_scores.mean(axis=0)[:, None] + transform @ unit_circle
        self.score_plot.plot(
            ellipse[0], ellipse[1],
            pen=pg.mkPen(
                "#1d4ed8" if self._plot_theme == "light" else "#fbbf24",
                width=2,
                style=Qt.DashLine,
            ),
        )


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--arii-remote-runner":
        return remote_runner_main([sys.argv[2]])
    app = QApplication(sys.argv)
    app.setApplicationName("Arii")
    app.setOrganizationName("Arii")
    app.setApplicationVersion("1.0.0")
    app.setWindowIcon(QIcon(str(asset_path("icons/arii-256.png"))))
    pg.setConfigOptions(antialias=True, background="#111827", foreground="#e5e7eb")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
