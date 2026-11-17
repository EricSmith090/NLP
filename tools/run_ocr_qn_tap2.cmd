@echo off
rem Double-click to (re)start the local Vintern OCR of the Quoc ngu pages of book 2.
rem Runs offline on this computer's GPU. Finished pages are cached, so it resumes
rem where it stopped. Close the window to stop.
cd /d "%~dp0.."
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0run_ocr_qn.ps1" -Book T1_CamPhong_Tap2
