
<#
.SYNOPSIS
    Publish a translation release to GitHub and update manifest.json automatically.

.PARAMETER GameId
    The game ID in manifest.json (e.g. "Grounded2")

.PARAMETER Version
    The translation version to publish (e.g. "0.2")

.PARAMETER Notes
    Arabic release notes (optional)

.EXAMPLE
    .\publish_translation.ps1 -GameId Grounded2 -Version 0.2 -Notes "إضافة ترجمة Release 0.5"
#>

param(
    [Parameter(Mandatory)][string]$GameId,
    [Parameter(Mandatory)][string]$Version,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$Repo = "nssr12/GameArabicTranslator"
$Tag  = "translation-$GameId-v$Version"

# ── 1. Locate ready/ folder ───────────────────────────────────────────────────
$ReadyDir = Join-Path $PSScriptRoot "mods\$GameId\ready"
if (-not (Test-Path $ReadyDir)) {
    Write-Error "Ready folder not found: $ReadyDir`nRun 'مزامنة التعديل' first."
}

$PakFiles = Get-ChildItem $ReadyDir -File | Where-Object { $_.Extension -in ".pak",".ucas",".utoc" }
if ($PakFiles.Count -eq 0) {
    Write-Error "No .pak/.ucas/.utoc files found in $ReadyDir"
}

Write-Host "`n=== Publish Translation: $GameId v$Version ===" -ForegroundColor Cyan
Write-Host "Files to upload:"
$PakFiles | ForEach-Object { Write-Host "  $($_.Name)  ($([math]::Round($_.Length/1MB,1)) MB)" }

# ── 2. Check if release tag already exists ────────────────────────────────────
$existing = gh release view $Tag --repo $Repo 2>$null
if ($existing) {
    Write-Host "`nRelease $Tag already exists — deleting and recreating..." -ForegroundColor Yellow
    gh release delete $Tag --repo $Repo --yes --cleanup-tag 2>$null
    Start-Sleep -Seconds 2
}

# ── 3. Create GitHub Release and upload files ────────────────────────────────
Write-Host "`nCreating GitHub Release $Tag ..." -ForegroundColor Green

$NotesText = if ($Notes) { $Notes } else { "ترجمة عربية لـ $GameId — الإصدار $Version" }
$FileArgs  = $PakFiles | ForEach-Object { $_.FullName }

gh release create $Tag `
    --repo $Repo `
    --title "$GameId Arabic Translation v$Version" `
    --notes $NotesText `
    @FileArgs

Write-Host "Upload complete." -ForegroundColor Green

# ── 4. Read file sizes ────────────────────────────────────────────────────────
$SizeMap = @{}
$PakFiles | ForEach-Object { $SizeMap[$_.Name] = $_.Length }
$TotalMB  = [math]::Round(($PakFiles | Measure-Object Length -Sum).Sum / 1MB)

# ── 5. Update manifest.json ───────────────────────────────────────────────────
$ManifestPath = Join-Path $PSScriptRoot "manifest.json"
$m = Get-Content $ManifestPath -Raw | ConvertFrom-Json

if (-not $m.translations.$GameId) {
    Write-Error "Game '$GameId' not found in manifest.json — add it manually first."
}

# Update version + size_mb
$m.translations.$GameId.version = $Version
$m.translations.$GameId.size_mb = $TotalMB

# Update each file entry: url + size
foreach ($f in $m.translations.$GameId.files) {
    $BaseUrl = "https://github.com/$Repo/releases/download/$Tag/$($f.name)"
    $f.url  = $BaseUrl
    if ($SizeMap.ContainsKey($f.name)) {
        $f.size = $SizeMap[$f.name]
    }
}

$m | ConvertTo-Json -Depth 10 | Set-Content $ManifestPath -Encoding UTF8

Write-Host "manifest.json updated (v$Version, $TotalMB MB)." -ForegroundColor Green

# ── 6. Git commit and push ────────────────────────────────────────────────────
git -C $PSScriptRoot add manifest.json
git -C $PSScriptRoot commit -m "Update manifest: $GameId v$Version ($TotalMB MB)"
git -C $PSScriptRoot push origin main

Write-Host "`n=== Done! ===" -ForegroundColor Cyan
Write-Host "Release URL: https://github.com/$Repo/releases/tag/$Tag"
Write-Host "Users will see the download button automatically on next app launch."
