@echo off
REM Bot automatico (SIMULADO por defecto). Dejar esta ventana abierta; para parar: Ctrl+C o crear state\STOP.
REM Para testnet: rellena BINANCE_TESTNET_KEY y BINANCE_TESTNET_SECRET en .env y cambia --mode sim por --mode testnet.
cd /d "%~dp0"
python -X utf8 -m scripts.run_bot --mode sim --risk balanceado --capital 1000
