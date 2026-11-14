from __future__ import annotations

import unittest
from pathlib import Path


class WindowsPackagingTests(unittest.TestCase):
    def test_x64_installer_is_admitted_on_windows_11_arm(self) -> None:
        script = Path("packaging/windows/arii.iss").read_text(encoding="utf-8")
        self.assertIn("ArchitecturesAllowed=x64compatible", script)
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", script)
        self.assertNotIn("ArchitecturesAllowed=x64\n", script)

    def test_installer_always_offers_the_destination_page(self) -> None:
        script = Path("packaging/windows/arii.iss").read_text(encoding="utf-8")
        self.assertIn("DisableDirPage=no", script)

    def test_build_prefers_current_inno_setup(self) -> None:
        script = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")
        self.assertLess(
            script.index("Inno Setup 7\\ISCC.exe"),
            script.index("Inno Setup 6\\ISCC.exe"),
        )

    def test_windows_bundle_contains_versioned_pdf_documentation(self) -> None:
        specification = Path("packaging/arii.spec").read_text(encoding="utf-8")
        self.assertIn('project_root / "docs" / "pdf"', specification)
        pdf_names = {path.name for path in Path("docs/pdf").glob("*.pdf")}
        self.assertIn("Arii-manual-de-usuario-versión1.1.0.pdf", pdf_names)
        self.assertIn(
            "Arii-documentacion-cientifica-versión1.1.0.pdf",
            pdf_names,
        )


if __name__ == "__main__":
    unittest.main()
