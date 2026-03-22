@echo off
echo ==========================================
echo Iniciando SocIA Selling local...
echo ==========================================
cd /d %~dp0
python -m pip install -r requirements.txt
echo ==========================================
echo Servidor iniciando em http://localhost:8080
echo ==========================================
python backend/main.py
pause
