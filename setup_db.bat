@echo off
REM ======================================================================
REM  STEP 1 - Build the "olist" PostgreSQL database from the CSV files.
REM  The CSVs are expected in the folder ABOVE this project folder
REM  (e.g. ...\Downloads\Dataset). Change DATADIR if not.
REM ======================================================================
setlocal
cd /d "%~dp0"
set "PROJECT=%~dp0."
set "DATADIR=%~dp0.."
REM psql prefers forward slashes in paths
set "PROJECT=%PROJECT:\=/%"
set "DATADIR=%DATADIR:\=/%"

where psql >nul 2>nul
if errorlevel 1 (
  echo psql was not found. Add C:\Program Files\PostgreSQL\16\bin to PATH and open a new window.
  pause
  exit /b 1
)
if not exist "%~dp0..\olist_orders_dataset.csv" (
  echo Could not find the Olist CSV files in %DATADIR%
  echo Edit DATADIR in setup_db.bat so it points to the folder with the CSVs.
  pause
  exit /b 1
)

set /p "PGPASSWORD=Password of the PostgreSQL user 'postgres': "

echo.
echo Creating database "olist" (an "already exists" error here is fine) ...
psql -U postgres -h localhost -d postgres -c "CREATE DATABASE olist;"

echo.
echo Building schema, loading ~560k rows, views, triggers, procedures, security (about 1 minute) ...
psql -U postgres -h localhost -d olist -v ON_ERROR_STOP=1 -v "datadir=%DATADIR%" -v "dbdir=%PROJECT%/db" -f "%~dp0db\00_run_all.sql"
if errorlevel 1 (
  echo.
  echo *** The database build stopped with an error - see the message above. ***
  pause
  exit /b 1
)
echo.
echo Database ready.  Next:  train_model.bat
pause
