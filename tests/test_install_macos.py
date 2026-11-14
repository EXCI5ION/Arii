from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_macos as installer


class MacOSInstallerPlatformTests(unittest.TestCase):
    def detect(self, machine: str) -> tuple[str, str]:
        with patch.object(installer.sys, "platform", "darwin"), patch.object(
            installer, "running_under_rosetta", return_value=False
        ), patch.object(installer.platform, "machine", return_value=machine), patch.object(
            installer.platform, "mac_ver", return_value=("15.4", ("", "", ""), "")
        ):
            return installer.detect_macos_platform()

    def test_detects_native_apple_silicon_and_intel(self) -> None:
        self.assertEqual(self.detect("arm64"), ("arm64", "osx-arm64"))
        self.assertEqual(self.detect("x86_64"), ("x86_64", "osx-64"))

    def test_rejects_rosetta_to_prevent_mixed_architectures(self) -> None:
        with patch.object(installer.sys, "platform", "darwin"), patch.object(
            installer, "running_under_rosetta", return_value=True
        ):
            with self.assertRaisesRegex(installer.InstallerError, "Rosetta"):
                installer.detect_macos_platform()

    def test_requires_macos_13_or_later(self) -> None:
        with patch.object(installer.sys, "platform", "darwin"), patch.object(
            installer, "running_under_rosetta", return_value=False
        ), patch.object(installer.platform, "mac_ver", return_value=("12.7", (), "")):
            with self.assertRaisesRegex(installer.InstallerError, "macOS 13.0"):
                installer.detect_macos_platform()


class MacOSInstallerIntegrityTests(unittest.TestCase):
    def test_micromamba_downloads_are_versioned_and_hashed(self) -> None:
        for conda_platform, (url, checksum) in installer.MICROMAMBA_DOWNLOADS.items():
            with self.subTest(conda_platform=conda_platform):
                self.assertIn(installer.MICROMAMBA_VERSION, url)
                self.assertNotIn("/latest", url)
                self.assertRegex(checksum, r"^[0-9a-f]{64}$")

    def test_runtime_versions_are_pinned(self) -> None:
        self.assertIn("python=3.12", installer.RUNTIME_PACKAGES)
        self.assertIn("r-base=4.5.3", installer.RUNTIME_PACKAGES)
        self.assertIn("bioconductor-mixomics=6.34.0", installer.RUNTIME_PACKAGES)
        self.assertIn("r-jsonlite=2.0.0", installer.RUNTIME_PACKAGES)

    def test_app_bundle_declares_the_supported_macos_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plist = Path(directory) / "Info.plist"
            with patch.object(installer, "INFO_PLIST", plist):
                installer.write_info_plist("1.0.1")
            with plist.open("rb") as stream:
                metadata = plistlib.load(stream)

        self.assertEqual(metadata["CFBundleShortVersionString"], "1.0.1")
        self.assertEqual(metadata["LSMinimumSystemVersion"], "13.0")

    def test_updater_defaults_to_update_but_preserves_explicit_modes(self) -> None:
        source = Path("install_macos.py").read_text(encoding="utf-8")
        self.assertIn('if [ \\"$#\\" -eq 0 ]', source)
        self.assertIn("set -- --update", source)
        self.assertNotIn('--update \\"$@\\"', source)


if __name__ == "__main__":
    unittest.main()
