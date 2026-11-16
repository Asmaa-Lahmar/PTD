@echo off
cd /d "%~dp0"
rem Ouvre le navigateur deux secondes après le démarrage du serveur.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8766"
python serveur\portail.py
pause
