@echo off
rem Lahore Twin: serve the app on http://127.0.0.1:PORT (default 8860) and run simulations
rem with your values from the "Run with your values" forms. No browser is opened.
rem   run.bat            -> port 8860
rem   run.bat --port 8861
set PORT=8860
if "%~1"=="--port" set PORT=%~2
set PY=%USERPROFILE%\anaconda3\python.exe
set PYARGS=
rem without Anaconda: the Python launcher (-3 as its own argument; "py -3" quoted as one name fails),
rem and without that, whatever python is on PATH
if not exist "%PY%" (
  where py >nul 2>&1 && (set PY=py& set PYARGS=-3) || set PY=python
)
set PYTHONUTF8=1
"%PY%" %PYARGS% "%~dp0serve.py" --port %PORT%
