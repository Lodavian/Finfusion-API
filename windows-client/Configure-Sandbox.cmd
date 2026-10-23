@echo off
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0..\deployment-tools\formal-deployment\Set-Sandbox-Credentials.ps1"
