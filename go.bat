@echo off
REM Check if the first argument is provided
if "%~1"=="" (
  echo Usage: %~nx0 STOCK_TICKER
  exit /b 1
)

REM Run the Python script using Poetry with the provided argument
poetry run python vd.py "%~1"
