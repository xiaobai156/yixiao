@echo off
chcp 65001 >nul
pushd "%~dp0" || (
  echo ERROR: cannot enter project directory "%~dp0"
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
set "PYTHONPATH=%CD%\src"
python -X utf8 -c "import zodiac_v2.cli" >nul 2>nul || (
  echo ERROR: cannot import zodiac_v2.cli
  echo CWD=%CD%
  echo PYTHONPATH=%PYTHONPATH%
  pause
  exit /b 1
)
set "PERIOD="
set /p PERIOD=Input period: 
if not defined PERIOD (
  echo ERROR: period is required.
  pause
  exit /b 1
)
python -X utf8 -m zodiac_v2.cli single --period "%PERIOD%" --workers 8 --formal
pause
