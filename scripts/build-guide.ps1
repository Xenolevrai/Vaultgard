# Régénère SecureHorizons-Prep\GUIDE-VAULTGUARD.pdf depuis docs\guide.html (PowerShell Windows).
$root = Split-Path -Parent $PSScriptRoot
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$src = "file:///" + ((Join-Path $root "docs\guide.html") -replace "\\", "/")
$out = Join-Path (Split-Path -Parent $root) "GUIDE-VAULTGUARD.pdf"
Start-Process -FilePath $chrome -Wait -NoNewWindow -ArgumentList @(
  "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
  "--user-data-dir=$env:TEMP\chrome-pdf", "--print-to-pdf=$out", $src)
Write-Host "PDF : $out"
