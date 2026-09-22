@echo off
REM Informe diario: ejecutar cada día a las 00:05 UTC (02:05 en Madrid en verano CEST, 01:05 en invierno CET).
REM Guarda el informe en reports\ultimo_informe.txt y actualiza el registro en papel (--record).
REM Cambia --risk (conservador | balanceado | agresivo) y --capital a tu gusto.
cd /d "%~dp0"
if not exist reports mkdir reports
python -X utf8 -m scripts.daily_report --risk balanceado --capital 1000 --record > reports\ultimo_informe.txt 2>&1
type reports\ultimo_informe.txt
