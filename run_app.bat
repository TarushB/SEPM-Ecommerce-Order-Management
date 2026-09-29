@echo off
REM ======================================================================
REM  STEP 3 - Start the web app on http://localhost:5000
REM  The app connects as the low-privilege role olist_app (see db\08_security.sql).
REM  Keep this window open while you use the app; close it to stop.
REM ======================================================================
setlocal
cd /d "%~dp0"

REM --- check that PostgreSQL is installed and running before starting ----
where pg_isready >nul 2>nul
if errorlevel 1 (
  echo PostgreSQL tools were not found on PATH.
  echo  1. Install PostgreSQL 16 from https://www.postgresql.org/download/windows/
  echo  2. Add C:\Program Files\PostgreSQL\16\bin to PATH and open a new window
  echo  3. Run setup_db.bat, then train_model.bat, then this file again.
  pause
  exit /b 1
)
pg_isready -h localhost -p 5432 >nul 2>nul
if errorlevel 1 (
  echo PostgreSQL is not running on localhost:5432.
  echo Start the "postgresql-x64-16" service ^(Win+R, services.msc^) and try again.
  pause
  exit /b 1
)

start "" http://localhost:5000
python backend\app.py
pause
