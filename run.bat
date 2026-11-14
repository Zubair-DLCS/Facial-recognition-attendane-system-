@echo off
REM Run FaceRoll from source. First run creates a virtual environment and installs dependencies.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Setting up Python environment, please wait...
    py -3 -m venv .venv || python -m venv .venv || goto :nopython
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt || goto :fail
)
start "" .venv\Scripts\pythonw.exe app.py
exit /b 0
:nopython
echo Python 3.10 or newer is required: https://www.python.org/downloads/windows/
pause & exit /b 1
:fail
echo Installing dependencies failed. Check your internet connection and try again.
pause & exit /b 1
