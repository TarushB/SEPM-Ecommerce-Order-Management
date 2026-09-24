@echo off
REM ======================================================================
REM  STEP 2 - Train the late-delivery model and store its results in the DB.
REM  Reads features with SQL, trains/compares models, writes ml_model and
REM  ml_prediction. Takes about 1-3 minutes.
REM ======================================================================
setlocal
cd /d "%~dp0"
set /p "PGPASSWORD=Password of the PostgreSQL user 'postgres': "
set PGUSER=postgres
set PGHOST=localhost
set PGDATABASE=olist
python ml\train.py
if errorlevel 1 (
  echo.
  echo *** Training failed - see the message above. Did you run: pip install -r requirements.txt ? ***
  pause
  exit /b 1
)
echo.
echo Model trained.  Next:  run_app.bat
pause
