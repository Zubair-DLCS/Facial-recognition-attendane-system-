@echo off
REM Build a standalone Windows app in dist\FaceRoll (no Python needed on the target PC).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name FaceRoll ^
    --icon assets\icon.ico ^
    --add-data "models;models" ^
    --add-data "assets;assets" ^
    app.py || goto :fail
echo.
echo Done. Run dist\FaceRoll\FaceRoll.exe  (zip the dist\FaceRoll folder to share it)
pause & exit /b 0
:fail
echo Build failed.
pause & exit /b 1
