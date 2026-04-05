@echo off
echo ===================================
echo   WoW Coach - Tests
echo ===================================
%LOCALAPPDATA%\Programs\Python\Python312\python.exe -m pytest tests\ -v --tb=short
pause
