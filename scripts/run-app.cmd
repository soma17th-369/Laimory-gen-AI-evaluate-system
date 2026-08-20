@echo off
rem Laimory evaluation tool launcher (double-click me).
rem Korean text lives in run-app.ps1; this wrapper stays ASCII on purpose.
title Laimory
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-app.ps1"
if errorlevel 1 pause
