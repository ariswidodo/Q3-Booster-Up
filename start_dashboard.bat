@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0server.py"
) else (
    start "" /B python "%~dp0server.py"
)
exit /b 0
