@echo off
rem Serve the Lahore Twin viewer on http://127.0.0.1:PORT (default 8860). No browser is opened.
rem   run.bat            -> port 8860
rem   run.bat --port 8861
set PORT=8860
if "%~1"=="--port" set PORT=%~2
set PY=%USERPROFILE%\anaconda3\python.exe
if not exist "%PY%" set PY=py -3
"%PY%" -m http.server %PORT% --bind 127.0.0.1 --directory "%~dp0viewer"