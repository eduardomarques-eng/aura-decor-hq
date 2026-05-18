@echo off
title AURA Decor — Sistema Completo
color 0A
cls

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║         🏮  AURA DECOR — SISTEMA COMPLETO           ║
echo  ║     Obsidian + n8n + CrewAI + Ollama + Dashboard    ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ── Verifica .env ────────────────────────────────────────────────────────
if exist ".env" (
    echo [✓] Carregando configurações .env
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
) else (
    echo [!] .env não encontrado — usando valores padrão
)

:: ── Verifica Ollama ─────────────────────────────────────────────────────
echo.
echo [1/5] Verificando Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo [✓] Ollama já está rodando
) else (
    echo [~] Iniciando Ollama...
    start /min "Ollama" ollama serve
    timeout /t 3 /nobreak >nul
    echo [✓] Ollama iniciado
)

:: Garante que llama3.2 está disponível
echo [~] Verificando modelo llama3.2...
ollama list 2>&1 | find "llama3.2" >nul
if %errorlevel%==0 (
    echo [✓] llama3.2 disponível
) else (
    echo [~] Baixando llama3.2 (2GB — pode demorar ~10min)...
    ollama pull llama3.2
    echo [✓] llama3.2 instalado
)

:: ── Verifica Python env ─────────────────────────────────────────────────
echo.
echo [2/5] Verificando ambiente Python...
if exist ".venv\Scripts\activate.bat" (
    echo [✓] Virtualenv encontrado
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [✓] Venv ativado
)

:: ── Instala dependências se necessário ──────────────────────────────────
python -c "import crewai" 2>nul
if %errorlevel% neq 0 (
    echo [~] Instalando dependências Python...
    pip install crewai crewai-tools fastapi uvicorn httpx pydantic -q
    echo [✓] Dependências instaladas
) else (
    echo [✓] CrewAI disponível
)

:: ── FastAPI Bridge ───────────────────────────────────────────────────────
echo.
echo [3/5] Iniciando Bridge API (porta 8001)...
curl -s http://localhost:8001/health >nul 2>&1
if %errorlevel%==0 (
    echo [✓] Bridge já está rodando em localhost:8001
) else (
    start /min "AURA Bridge" cmd /c "cd bridge && python -m uvicorn obsidian_bridge:app --host 0.0.0.0 --port 8001 --reload 2>&1 | tee bridge.log"
    timeout /t 4 /nobreak >nul
    echo [✓] Bridge iniciado em http://localhost:8001
)

:: ── Setup Vault Obsidian ─────────────────────────────────────────────────
echo.
echo [4/5] Configurando Obsidian Vault...
curl -s -X POST http://localhost:8001/vault/setup >nul 2>&1
if %errorlevel%==0 (
    echo [✓] Vault configurado com estrutura de agentes
) else (
    echo [!] Bridge offline — vault setup pendente (rode manualmente depois)
)

:: ── Abre Dashboard ────────────────────────────────────────────────────────
echo.
echo [5/5] Abrindo Dashboard...
start "" "dashboard\aura-office.html"
echo [✓] Dashboard aberto no navegador

:: ── Summary ───────────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                  ✅ SISTEMA ONLINE                   ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║  Bridge API:   http://localhost:8001/docs            ║
echo  ║  n8n:          http://localhost:5678                 ║
echo  ║  Ollama:       http://localhost:11434                ║
echo  ║  Dashboard:    dashboard\aura-office.html            ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  Comandos rápidos:
echo    python src\meu_primeiro_time\crew.py --full
echo    python src\meu_primeiro_time\crew.py --agent kal --task "busca vasos japandi"
echo    python src\meu_primeiro_time\crew.py --agent ive --task "relatório semanal"
echo.

:menu
echo  ╔══════════════════════════════════════════════════════╗
echo  ║  O que deseja fazer?                                 ║
echo  ║  [1] Rodar ciclo completo da equipe                  ║
echo  ║  [2] Falar com um agente específico                  ║
echo  ║  [3] Verificar status do sistema                     ║
echo  ║  [4] Abrir n8n                                       ║
echo  ║  [5] Abrir docs da API                               ║
echo  ║  [Q] Sair                                            ║
echo  ╚══════════════════════════════════════════════════════╝
set /p choice="  Escolha: "

if /i "%choice%"=="1" (
    echo.
    echo Iniciando ciclo completo da equipe AURA...
    python src\meu_primeiro_time\crew.py --full
    goto menu
)
if /i "%choice%"=="2" (
    set /p agent_id="  Agente (ive/rex/luna/theo/kal/vera/nox/echo): "
    set /p task_desc="  Tarefa: "
    python src\meu_primeiro_time\crew.py --agent !agent_id! --task "!task_desc!"
    goto menu
)
if /i "%choice%"=="3" (
    echo.
    curl -s http://localhost:8001/status
    echo.
    goto menu
)
if /i "%choice%"=="4" (
    start "" http://localhost:5678
    goto menu
)
if /i "%choice%"=="5" (
    start "" http://localhost:8001/docs
    goto menu
)
if /i "%choice%"=="Q" goto :eof
if /i "%choice%"=="q" goto :eof
goto menu
