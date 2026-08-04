@echo off
setlocal
title FactoryFly Sentinel

set "ROOT=%~dp0"
set "APP=%ROOT%app.py"
set "PYTHON_EXE=%ROOT%.venv-vision\Scripts\python.exe"

if not exist "%APP%" (
    echo [ERROR] app.py was not found:
    echo %APP%
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Local environment was not found:
    echo %PYTHON_EXE%
    echo Run scripts\setup_local.ps1 first.
    pause
    exit /b 1
)

start "" http://localhost:8501
"%PYTHON_EXE%" -m streamlit run "%APP%" ^
  --server.port 8501 ^
  --server.headless true ^
  --browser.gatherUsageStats false

endlocal
