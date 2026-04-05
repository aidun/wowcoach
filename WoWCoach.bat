@echo off
SET PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
SET APP=%~dp0main.py

IF NOT EXIST "%PYTHON%" (
    echo Python nicht gefunden unter: %PYTHON%
    pause
    exit /b 1
)

echo Starte WoW Coach...
start "" "%PYTHON%" "%APP%" --player "Lugoor" --talent spellslinger
