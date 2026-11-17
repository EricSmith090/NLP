@echo off
rem Double-click to (re)start the Kim Han Nom OCR of the Nom pages of book 2.
rem Finished pages are cached, so it resumes where it stopped. Close the window to stop.
cd /d "%~dp0.."
powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0run_ocr_nom.ps1" -Book T1_CamPhong_Tap2
