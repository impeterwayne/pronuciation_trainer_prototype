# Puts a portable espeak-ng under vendor\ and verifies it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#
# Uses `msiexec /a` (administrative install), which *extracts* the MSI payload
# instead of installing it -- no UAC prompt, no registry entry, no admin rights.
# The backend looks in vendor\eSpeak NG first, then the usual Program Files paths,
# so a system-wide install works too if you already have one.

$ErrorActionPreference = 'Stop'

$root   = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root 'vendor'
$target = Join-Path $vendor 'eSpeak NG'

function Test-Espeak($dir) {
  return (Test-Path (Join-Path $dir 'libespeak-ng.dll')) -and
         (Test-Path (Join-Path $dir 'espeak-ng.exe')) -and
         (Test-Path (Join-Path $dir 'espeak-ng-data'))
}

$existing = @(
  $target,
  "$env:ProgramFiles\eSpeak NG",
  "${env:ProgramFiles(x86)}\eSpeak NG"
) | Where-Object { Test-Espeak $_ } | Select-Object -First 1

if (-not $existing) {
  Write-Host 'Fetching espeak-ng...' -ForegroundColor Yellow
  $rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/espeak-ng/espeak-ng/releases/latest' `
                           -Headers @{ 'User-Agent' = 'pronunciation-trainer' }
  $asset = $rel.assets | Where-Object { $_.name -like '*.msi' } | Select-Object -First 1
  if (-not $asset) { throw 'No .msi asset in the latest espeak-ng release.' }

  $msi = Join-Path $env:TEMP $asset.name
  Write-Host "  $($rel.tag_name) / $($asset.name)"
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $msi

  New-Item -ItemType Directory -Force $vendor | Out-Null
  $p = Start-Process msiexec.exe -Wait -PassThru `
        -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$vendor`""
  if ($p.ExitCode -ne 0) { throw "msiexec /a exited with $($p.ExitCode)" }
  Remove-Item (Join-Path $vendor $asset.name) -Force -ErrorAction SilentlyContinue

  if (-not (Test-Espeak $target)) { throw "extraction did not produce $target" }
  $existing = $target
}

$exe  = Join-Path $existing 'espeak-ng.exe'
$dll  = Join-Path $existing 'libespeak-ng.dll'

Write-Host ''
Write-Host 'espeak-ng ready:' -ForegroundColor Green
Write-Host "  binary  : $exe"
Write-Host "  library : $dll"
Write-Host "  data    : $(Join-Path $existing 'espeak-ng-data')"

Write-Host ''
Write-Host 'Smoke test (should print IPA):' -ForegroundColor Cyan
& $exe "--path=$existing" -v en-us -q --ipa -- 'she sells seashells'

Write-Host ''
Write-Host 'The backend auto-detects the paths above -- no environment variables needed.'
Write-Host 'Next:  pip install -r backend\requirements.txt' -ForegroundColor Green
