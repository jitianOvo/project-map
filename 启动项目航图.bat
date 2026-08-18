@echo off
cd /d "%~dp0"
if exist "%~dp0dist\项目航图.exe" (
    start "" "%~dp0dist\项目航图.exe"
) else (
    python 项目航图.py
)
