param(
    [string]$Version = "1.0.0",
    [Parameter(Mandatory = $true)]
    [string]$ExplicitLock,
    [string]$OutputDirectory = "build\cluster-release-kit"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$lockPath = (Resolve-Path -LiteralPath $ExplicitLock).Path
$stageRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
if (-not $stageRoot.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "El kit sólo puede prepararse dentro de la carpeta build del proyecto."
}
if (Test-Path -LiteralPath $stageRoot) {
    throw "El destino ya existe: $stageRoot"
}

$kitName = "Arii-$Version-cluster-build-kit"
$kitRoot = Join-Path $stageRoot $kitName
$payload = Join-Path $kitRoot "payload"
$smoke = Join-Path $kitRoot "smoke"
New-Item -ItemType Directory -Path $payload, $smoke -Force | Out-Null

$copies = @{
    "cluster\runtime\build-runtime.sbatch" = "build-runtime.sbatch"
    "cluster\runtime\validate-runtime.sbatch" = "validate-runtime.sbatch"
    "cluster\runtime\smoke-runtime.sbatch" = "smoke-runtime.sbatch"
    "cluster\runtime\audit-runtime.sbatch" = "audit-runtime.sbatch"
    "cluster\runtime\README-SERVER.md" = "payload\README-SERVER.md"
    "cluster\runtime\install-runtime.sh" = "payload\install-runtime.sh"
    "cluster\runtime\health.sbatch" = "payload\health.sbatch"
    "r\health.R" = "payload\health.R"
    "scripts\runtime_manifest.R" = "payload\runtime_manifest.R"
    "LICENSE" = "payload\LICENSE"
    "THIRD_PARTY_NOTICES.md" = "payload\THIRD_PARTY_NOTICES.md"
    "r\pca_worker.R" = "smoke\pca_worker.R"
}
foreach ($entry in $copies.GetEnumerator()) {
    $destination = Join-Path $kitRoot $entry.Value
    Copy-Item -LiteralPath (Join-Path $projectRoot $entry.Key) `
        -Destination $destination

    # The kit is assembled on Windows but its shell and Slurm scripts run on
    # Linux.  Normalize them explicitly because Git's working-tree settings
    # may still expose CRLF files even when .gitattributes records LF.
    if ([IO.Path]::GetExtension($destination) -in @(".sh", ".sbatch")) {
        $content = [IO.File]::ReadAllText($destination)
        $content = $content.Replace("`r`n", "`n").Replace("`r", "`n")
        [IO.File]::WriteAllText(
            $destination,
            $content,
            [Text.UTF8Encoding]::new($false)
        )
    }
}
Copy-Item -LiteralPath $lockPath -Destination (Join-Path $payload "explicit-lock.txt")

@'
sample,feature_1,feature_2,feature_3,feature_4
sample_1,1.0,2.0,3.0,2.5
sample_2,1.2,2.1,2.8,2.7
sample_3,0.9,1.8,3.2,2.4
sample_4,2.1,1.1,1.4,3.3
sample_5,2.3,1.0,1.6,3.5
sample_6,1.9,1.3,1.5,3.2
sample_7,2.0,1.2,1.7,3.4
'@ | Set-Content -LiteralPath (Join-Path $smoke "dataset.csv") -Encoding utf8NoBOM

$job = @{
    schema_version = "1.0"
    dataset = @{
        path = "dataset.csv"
        delimiter = ","
        orientation = "samples_by_variables"
        representation = "feature_table"
        modality = "generic"
        axis_label = "Variable"
    }
    preprocessing = @{ mean_center = $true; scaling = "pareto" }
    selected_sample_indices = @(0, 1, 2, 3, 4, 5, 6)
    classes = @("A", "A", "A", "B", "B", "B", "B")
    n_components = 2
    validation = @{ enabled = $false; repeats = 20; train_fraction = 0.8; seed = 1234 }
}
$job | ConvertTo-Json -Depth 6 | Set-Content `
    -LiteralPath (Join-Path $smoke "job.json") -Encoding utf8NoBOM

$instructions = @"
# Construcción del runtime Arii $Version

Este kit es un insumo temporal de construcción; no es el runtime distribuible.

Desde la carpeta descomprimida en el clúster:

``````bash
export ARII_VERSION="$Version"

BUILD_JOB=`$(sbatch --parsable build-runtime.sbatch)
echo "Build: `$BUILD_JOB"
``````

Cuando termine correctamente:

``````bash
VALIDATE_JOB=`$(sbatch --parsable validate-runtime.sbatch)
SMOKE_JOB=`$(sbatch --parsable smoke-runtime.sbatch)
AUDIT_JOB=`$(sbatch --parsable audit-runtime.sbatch)
echo "Validación: `$VALIDATE_JOB | PCA: `$SMOKE_JOB | Auditoría: `$AUDIT_JOB"
``````

El artefacto final y su checksum quedarán en ```$HOME/arii/releases``.
"@
$instructions | Set-Content -LiteralPath (Join-Path $kitRoot "BUILD-INSTRUCTIONS.md") `
    -Encoding utf8NoBOM

$archive = Join-Path $stageRoot "$kitName.tar.gz"
Push-Location $stageRoot
try {
    & tar -czf $archive $kitName
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo comprimir el kit de construcción."
    }
} finally {
    Pop-Location
}
Write-Output "ARII_CLUSTER_BUILD_KIT=$archive"
