@echo off
cd /d %~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0start_web_8765.ps1'"
echo Huage web dashboard is starting in background.
echo URL: http://127.0.0.1:8765/adminhuage
