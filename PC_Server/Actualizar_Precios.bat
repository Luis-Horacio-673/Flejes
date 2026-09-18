@echo off
chcp 65001 > nul
echo ========================================================
echo   SISTEMA DE ACTUALIZACION DE PRECIOS EN VIVO - YPF
echo ========================================================
echo.
python "%~dp0update_ypf_prices.py"
echo.
echo Presione cualquier tecla para salir...
pause > nul
