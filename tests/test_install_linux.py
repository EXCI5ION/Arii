from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import install_linux as installer


class LinuxInstallerPythonTests(unittest.TestCase):
    def test_project_declares_the_same_supported_python_range(self) -> None:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        self.assertEqual(project["requires-python"], ">=3.12,<3.14")

    def test_uses_distribution_python_and_generic_venv_package(self) -> None:
        self.assertEqual(installer.PYTHON_COMMAND, Path("/usr/bin/python3"))
        self.assertIn("python3", installer.DEBIAN_PACKAGES)
        self.assertIn("python3-venv", installer.DEBIAN_PACKAGES)
        self.assertNotIn("python3.12", installer.DEBIAN_PACKAGES)
        self.assertNotIn("python3.12-venv", installer.DEBIAN_PACKAGES)

    def test_accepts_python_312_and_313(self) -> None:
        for version in ("3.12", "3.13"):
            with self.subTest(version=version), patch(
                "pathlib.Path.is_file", return_value=True
            ), patch.object(installer, "output", return_value=version):
                installer.verify_python()

    def test_rejects_other_python_versions(self) -> None:
        for version in ("3.11", "3.14"):
            with self.subTest(version=version), patch(
                "pathlib.Path.is_file", return_value=True
            ), patch.object(installer, "output", return_value=version):
                with self.assertRaisesRegex(
                    installer.InstallerError, "Python 3.12 o 3.13"
                ):
                    installer.verify_python()


class LinuxInstallerMetadataTests(unittest.TestCase):
    def test_parses_os_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "os-release"
            path.write_text(
                'ID="ubuntu"\nID_LIKE="debian"\nPRETTY_NAME="Xubuntu"\n',
                encoding="utf-8",
            )
            values = installer.parse_os_release(path)

        self.assertEqual(values["ID"], "ubuntu")
        self.assertEqual(values["ID_LIKE"], "debian")
        self.assertEqual(values["PRETTY_NAME"], "Xubuntu")

    def test_desktop_entry_uses_global_gui_command(self) -> None:
        entry = installer.desktop_entry()
        self.assertIn("Exec=/usr/local/bin/arii-gui", entry)
        self.assertIn("Icon=arii", entry)

    def test_updater_defaults_to_update_but_preserves_explicit_modes(self) -> None:
        source = Path("install_linux.py").read_text(encoding="utf-8")
        self.assertIn('if [ \\"$#\\" -eq 0 ]', source)
        self.assertIn('set -- --update', source)
        self.assertNotIn('--update \\"$@\\"', source)


if __name__ == "__main__":
    unittest.main()
