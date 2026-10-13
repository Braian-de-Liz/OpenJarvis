@echo off
REM jarvis-show.bat - Ativação do Jarvis por duas palmas (chama PowerShell wrapper)
REM Use este arquivo para duplo-clique ou atalhos

set "JARVIS_DIR=%USERPROFILE%\desktop\jarvis"
set "UV_PATH=%USERPROFILE%\.local\bin\uv.exe"

powershell -ExecutionPolicy Bypass -File "%JARVIS_DIR%\jarvis-show.ps1" %*