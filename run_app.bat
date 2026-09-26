@echo off
REM ======================================================================
REM  STEP 3 - Start the web app on http://localhost:5000
REM  The app connects as the low-privilege role olist_app (see db\08_security.sql).
REM  Keep this window open while you use the app; close it to stop.
REM ======================================================================
setlocal
cd /d "%~dp0"
start "" http://localhost:5000
python backend\app.py
pause
