@echo off
title AURA Bridge — porta 8001
cd /d "%~dp0.."
echo [AURA Bridge] Iniciando em http://localhost:8001 ...
python -m uvicorn bridge.obsidian_bridge:app --host 0.0.0.0 --port 8001 --reload --log-level info
pause
