@echo off
SET PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
SET APP=%~dp0main.py

IF NOT EXIST "%PYTHON%" (
    echo Python nicht gefunden unter: %PYTHON%
    pause
    exit /b 1
)

echo Starte WoW Coach im REPLAY-Modus (5x Geschwindigkeit)...
start "" "%PYTHON%" "%APP%" --player "Lugoor" --talent spellslinger --replay --replay-speed 5
