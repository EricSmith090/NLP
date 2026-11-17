# Run local Vintern-1B-v2 OCR on the Quoc ngu pages of one book.
#
# - only Quoc ngu pages (--only qn: vi/intro/toc/ref folders); Nom pages are
#   handled by run_ocr_nom.ps1 (Kim Han Nom API);
# - fully offline: the model is read from models\hf (downloaded once), no page
#   image leaves this computer;
# - finished pages are cached, so a restart resumes where it stopped;
# - after a crash (e.g. GPU out of memory) it waits and restarts, at most
#   $MaxRestarts times.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File tools\run_ocr_qn.ps1 -Book T1_CamPhong_Tap2
# Stop: close the window or press Ctrl+C. Log: data\logs\ocr_qn_<Book>.log

param(
    [string]$Book = "T1_CamPhong_Tap2",
    [int]$MaxRestarts = 5,
    [int]$RestartDelaySeconds = 60
)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:HF_HOME = Join-Path (Get-Location) "models\hf"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$py = ".\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force "data\logs" | Out-Null
$log = "data\logs\ocr_qn_$Book.log"
$host.UI.RawUI.WindowTitle = "OCR Quoc ngu - $Book (close this window to stop)"

for ($run = 0; $run -le $MaxRestarts; $run++) {
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') run #$run ===" | Tee-Object -FilePath $log -Append
    & $py -m hannom.cli ocr --book $Book --only qn 2>&1 |
        ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
    $code = $LASTEXITCODE
    if ($code -eq 0) {
        "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') DONE: all Quoc ngu pages of $Book are OCR'd ===" |
            Tee-Object -FilePath $log -Append
        break
    }
    "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') stopped with exit code $code; restarting in $RestartDelaySeconds s ===" |
        Tee-Object -FilePath $log -Append
    Start-Sleep -Seconds $RestartDelaySeconds
}
