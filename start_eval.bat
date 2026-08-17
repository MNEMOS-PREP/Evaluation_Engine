@echo off
REM ============================================================
REM  M13 - Evaluation Engine, on its own.
REM
REM  This module's services only (PORTS.txt: API 8113).
REM  No sibling repos, so scoring runs against the committed
REM  fixture bank and /v1/deps names the modules it would have
REM  used - which is the fastest way to check that the
REM  clone-and-run promise still holds.
REM
REM  Usage:  start_eval.bat          launch M13
REM          start_eval.bat -Check   verify prerequisites only
REM ============================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Only m13 -Title "M13 - Evaluation Engine" %*
