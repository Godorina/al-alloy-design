@echo off
rem Double-click this file on Windows: sets up WSL2 + Ubuntu, then installs al-alloy-design inside it.
rem Options are passed through, e.g.  install.cmd -User alloy -MemoryGB 20
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-wsl.ps1" %*
echo.
pause
