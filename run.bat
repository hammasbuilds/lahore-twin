@echo off
rem Lahore Twin: serve the app on http://127.0.0.1:PORT (default 8860) and run simulations
rem with your values from the "Run with your values" forms. No browser is opened.
rem   run.bat            -> port 8860
rem   run.bat --port 8861
set PORT=8860
if "%~1"=="--port" set PORT=%~2
set PY=%USERPROFILE%\anaconda3\python.exe
if not exist "%PY%" set PY=py -3
set PYTHONUTF8=1
"%PY%" "%~dp0serve.py" --port %PORT%
