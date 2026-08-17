@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  Dispatcher. The launchers are start_all.bat and
REM  start_eval.bat; this file exists because every README on
REM  this platform tells you to type `start.bat`.
REM
REM    start.bat            everything     -> start_all.bat
REM    start.bat eval       this module    -> start_eval.bat
REM    start.bat m13        same thing
REM    start.bat check      prerequisites, launch nothing
REM
REM  What actually runs the services: scripts\launch.ps1
REM  What you add a service to:       scripts\services.txt
REM  What closes them again:          scripts\control.ps1
REM ============================================================

if /i "%~1"=="check" goto CHECK
if /i "%~1"=="eval"  goto EVAL
if /i "%~1"=="m13"   goto EVAL
if /i "%~1"=="all"   goto ALL
if "%~1"==""         goto ALL
goto USAGE

:ALL
call "%~dp0start_all.bat"
goto :EOF

:EVAL
call "%~dp0start_eval.bat"
goto :EOF

:CHECK
call "%~dp0start_all.bat" -Check
goto :EOF

:USAGE
echo Usage: start.bat [all^|eval^|m13^|check]
exit /b 1
