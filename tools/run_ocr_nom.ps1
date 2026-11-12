# Run Kim Han Nom OCR on the Nom pages of one book until every page is done.
#
# - only Nom pages (--only nom), no structure-classification (--no-classify),
#   pages enlarged before upload (--upscale), waits when a quota window is
#   full (--wait-quota);
# - finished pages are cached, so a restart resumes where it stopped;
# - after a crash (network error, server error) it waits and restarts, at
#   most $MaxRestarts times; an expired token (HTTP 401) shows up in the log.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File tools\run_ocr_nom.ps1 -Book T1_CamPhong_Tap2
# Stop: close the window or press Ctrl+C. Log: data\logs\ocr_nom_<Book>.log

param(
    [string]$Book = "T1_CamPhong_Tap2",
    [int]$Upscale = 2,
    [int]$MaxRestarts = 30,
    [int]$RestartDelaySeconds = 600
)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$py = ".\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force "data\logs" | Out-Null
$log = "data\logs\ocr_nom_$Book.log"
$host.UI.RawUI.WindowTitle = "OCR Nom - $Book (close this window to stop)"

for ($run = 0; $run -le $MaxRestarts; $run++) {
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') run #$run ===" | Tee-Object -FilePath $log -Append
    & $py -m hannom.cli ocr --book $Book --only nom --no-classify --upscale $Upscale --wait-quota 2>&1 |
        ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') DONE: all Nom pages of $Book are OCR'd ===" |
            Tee-Object -FilePath $log -Append
        break
    }
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') stopped with exit code $code; restarting in $RestartDelaySeconds s ===" |
        Tee-Object -FilePath $log -Append
    Start-Sleep -Seconds $RestartDelaySeconds
}
