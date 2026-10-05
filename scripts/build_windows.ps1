param(
    [switch]$BundleR,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv-win\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No se encontró el entorno .venv-win."
}

Push-Location $projectRoot
try {
    & $python "scripts\build_icons.py"
    $originalPath = $env:PATH
    $originalPythonPath = $env:PYTHONPATH
    try {
        $pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
        $env:PATH = @(
            (Split-Path -Parent $python),
            $pythonBase,
            (Join-Path $pythonBase "Scripts"),
            (Join-Path $env:SystemRoot "System32"),
            $env:SystemRoot
        ) -join ";"
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        & $python -m PyInstaller --noconfirm --clean "packaging\arii.spec"
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller no pudo construir Arii."
        }
    } finally {
        $env:PATH = $originalPath
        if ($null -eq $originalPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $originalPythonPath
        }
    }

    $foreignIcu = Get-ChildItem "dist\Arii\_internal" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "icuuc.dll" -or $_.Name -match '^icudt\d+\.dll$' }
    if ($foreignIcu) {
        throw "El paquete contiene una biblioteca ICU ajena a Qt: $($foreignIcu.Name -join ', ')."
    }

    $probeEnvironment = $env:QT_QPA_PLATFORM
    $probe = $null
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $probe = Start-Process -FilePath "dist\Arii\Arii.exe" -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 5
        if ($probe.HasExited) {
            throw "Arii terminó durante la prueba de arranque (código $($probe.ExitCode))."
        }
        $loadedModules = @($probe.Modules | ForEach-Object { $_.ModuleName.ToLowerInvariant() })
        if ($loadedModules -notcontains "qtcore.pyd" -or $loadedModules -notcontains "qtwidgets.pyd") {
            throw "La prueba de arranque no pudo cargar QtCore/QtWidgets."
        }
    } finally {
        if ($probe -and -not $probe.HasExited) {
            Stop-Process -Id $probe.Id -Force
        }
        if ($null -eq $probeEnvironment) {
            Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        } else {
            $env:QT_QPA_PLATFORM = $probeEnvironment
        }
    }

    # A frozen sys.executable is Arii.exe, not Python. Verify that the internal
    # remote-runner dispatch exits as a worker instead of opening a second GUI.
    $missingRemoteRequest = Join-Path $projectRoot "build\missing-remote-request.json"
    $remoteProbe = Start-Process -FilePath "dist\Arii\Arii.exe" `
        -ArgumentList @("--arii-remote-runner", $missingRemoteRequest) `
        -PassThru -WindowStyle Hidden
    try {
        if (-not $remoteProbe.WaitForExit(10000)) {
            throw "El runner remoto congelado abrió una GUI o quedó bloqueado."
        }
        if ($remoteProbe.ExitCode -ne 1) {
            throw "El runner remoto congelado devolvió un código inesperado: $($remoteProbe.ExitCode)."
        }
    } finally {
        if (-not $remoteProbe.HasExited) {
            Stop-Process -Id $remoteProbe.Id -Force
        }
    }
    if ($BundleR) {
        & (Join-Path $projectRoot "scripts\stage_windows_r_runtime.ps1")
        $bundledRHome = Join-Path $projectRoot "dist\Arii\runtime\R"
        $bundledRscript = Join-Path $bundledRHome "bin\x64\Rscript.exe"
        if (-not (Test-Path -LiteralPath $bundledRscript -PathType Leaf)) {
            throw "El runtime privado no contiene bin\x64\Rscript.exe."
        }
        $savedREnvironment = @{}
        $rEnvironmentNames = @(
            "R_HOME", "R_LIBS_SITE", "R_LIBS_USER",
            "LANG", "LC_ALL", "LC_COLLATE", "LC_CTYPE",
            "LC_MONETARY", "LC_NUMERIC", "LC_TIME"
        )
        try {
            foreach ($name in $rEnvironmentNames) {
                $savedREnvironment[$name] =
                    [Environment]::GetEnvironmentVariable($name, "Process")
                [Environment]::SetEnvironmentVariable($name, $null, "Process")
            }
            $env:R_HOME = $bundledRHome
            $env:R_LIBS_SITE = Join-Path $bundledRHome "library"
            $env:R_LIBS_USER = Join-Path $bundledRHome "library"
            & $bundledRscript --vanilla -e `
                'stopifnot(requireNamespace("mixOmics", quietly=TRUE), requireNamespace("jsonlite", quietly=TRUE))'
            if ($LASTEXITCODE -ne 0) {
                throw "El runtime R privado no superó su prueba de carga."
            }
        } finally {
            foreach ($name in $rEnvironmentNames) {
                [Environment]::SetEnvironmentVariable(
                    $name, $savedREnvironment[$name], "Process"
                )
            }
        }
    }
    if ($Installer) {
        $compiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
            throw "No se encontró Inno Setup 6."
        }
        & $compiler "packaging\windows\arii.iss"
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup no pudo construir el instalador."
        }
    }
} finally {
    Pop-Location
}
