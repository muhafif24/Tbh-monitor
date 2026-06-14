@echo off
rem Change directory to the active directory where the batch file is located
cd /d "%~dp0"

rem Check if pythonw.exe exists in the virtual environment
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please set up the environment first as described in README.md.
    pause
    exit /b 1
)

rem Launch the GUI application in the background without a CMD window
start "" /d "%~dp0" ".venv\Scripts\pythonw.exe" main.py
exit
