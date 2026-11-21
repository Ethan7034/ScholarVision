@echo off
:: ASCII-only file (cmd byte-offset parsing breaks on multibyte comments).
:: =====================================================================
:: Scholar Vision v2.1 - (re)start just the analysis worker.
:: Use when Redis came up after start_server.bat, or to recover the worker.
:: Worker must run from the project folder (shares uploads/ and images/).
:: =====================================================================

cd /d "%~dp0"
python worker.py
pause
