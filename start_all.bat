@echo off
REM ============================================================
REM  Everything.
REM
REM  Every service in scripts\services.txt, plus any sibling
REM  module repo declared in module.json `depends_on` that is
REM  checked out next to this one and has scripts\launch.ps1.
REM  Sibling tabs join THIS window and this window's control tab
REM  closes them too.
REM
REM  Upstreams are optional, and for M13 that is a rule rather
REM  than a convenience: a student's score must never depend on
REM  whether a downstream service happened to be up
REM  (dependencies.txt, spec section 6.11).
REM
REM  Usage:  start_all.bat          launch everything
REM          start_all.bat -Check   verify prerequisites only
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -All -Title "AI Interviewer - all services" %*
