$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv-win\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "No se encontró el entorno .venv-win. Consulte README.md."
}

Start-Process -FilePath $pythonPath `
    -ArgumentList "-m", "arii.gui" `
    -WorkingDirectory $projectRoot
