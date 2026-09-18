@echo off
title Vigilante Google Drive - TB10 Plus
chcp 65001 > nul
echo Iniciando el servicio de monitoreo en segundo plano...
python "%~dp0gdrive_watcher.py"
pause
