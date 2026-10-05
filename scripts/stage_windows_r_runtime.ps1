param(
    [string]$Rscript = "C:\Program Files\R\R-4.5.2\bin\Rscript.exe",
    [string]$Destination = "dist\Arii\runtime\R"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$destinationPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Destination))
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist\Arii\runtime"))
if (-not $destinationPath.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "El runtime sólo puede prepararse dentro de dist\Arii\runtime."
}
if (-not (Test-Path -LiteralPath $Rscript -PathType Leaf)) {
    throw "No se encontró Rscript en $Rscript"
}
if (Test-Path -LiteralPath $destinationPath) {
    throw "El destino ya existe; reconstruya dist\Arii antes de preparar el runtime."
}

$manifestPath = Join-Path ([IO.Path]::GetTempPath()) "arii-r-runtime-manifest-$PID.json"
if (Test-Path -LiteralPath $manifestPath) {
    Remove-Item -LiteralPath $manifestPath -Force
}
$localeVariables = @("LANG", "LC_ALL", "LC_COLLATE", "LC_CTYPE", "LC_MONETARY", "LC_TIME")
$savedLocale = @{}
try {
    foreach ($variable in $localeVariables) {
        $savedLocale[$variable] = [Environment]::GetEnvironmentVariable($variable, "Process")
        [Environment]::SetEnvironmentVariable($variable, $null, "Process")
    }
    & $Rscript (Join-Path $projectRoot "scripts\runtime_manifest.R") $manifestPath
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo construir el manifiesto de dependencias R."
    }
} finally {
    foreach ($variable in $localeVariables) {
        [Environment]::SetEnvironmentVariable($variable, $savedLocale[$variable], "Process")
    }
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if (-not $manifest.r_home) {
    throw "El manifiesto de R no contiene r_home."
}
$rHome = [IO.Path]::GetFullPath(($manifest.r_home -replace '/', '\'))

New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
Copy-Item -Path (Join-Path $rHome "*") -Destination $destinationPath -Recurse -Force

$bundledLibrary = Join-Path $destinationPath "library"
foreach ($package in $manifest.packages) {
    if ($package.priority -in @("base", "recommended")) {
        continue
    }
    if (-not $package.path) {
        throw "El manifiesto de R no contiene la ruta del paquete $($package.name)."
    }
    $source = [IO.Path]::GetFullPath(($package.path -replace '/', '\'))
    $target = Join-Path $bundledLibrary $package.name
    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
}

Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $destinationPath "ARII_RUNTIME_MANIFEST.json") -Force
Remove-Item -LiteralPath $manifestPath -Force
Write-Output "Runtime R preparado en $destinationPath"
