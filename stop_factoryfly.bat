@echo off
setlocal
set "PORT=8501"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    echo Stopping FactoryFly PID %%P...
    taskkill /PID %%P /F
)

echo FactoryFly stopped.
timeout /t 2 /nobreak >nul
endlocal
