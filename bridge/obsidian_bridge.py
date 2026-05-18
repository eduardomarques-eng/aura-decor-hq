"""
AURA Refúgio — Bridge v3  (FastAPI + SSE + LLM real)
Porta 8001 — terminal do dashboard executa agentes reais via llama3.2

Run: python bridge/obsidian_bridge.py
"""
import os, json, re, subprocess, sys, asyncio, threading, queue, time
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncGenerator
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

# ── Config ─────────────────────────────────────────────────────────────────
OBSIDIAN_API  = os.getenv("OBSIDIAN_API_KEY", "http://localhost:27123")
OBSIDIAN_KEY  = os.getenv("OBSIDIAN_API_KEY", "your-key-here")
VAULT_ROOT    = os.getenv("VAULT_PATH", r"C:\Users\erick\OneDrive\Documentos\Obsidian Vault")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.2")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "aura-decor.myshopify.com")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
PROJECT_DIR   = Path(__file__).parent.parent

HEADERS_OBS = {"Authorization": f"Bearer {OBSIDIAN_KEY}", "Content-Type": "application/json"}

# ── Agent personas (fase de lançamento) ────────────────────────────────────
AGENTS = {
    "ive": {
        "name": "Ive", "emoji": "👩‍💼", "role": "CEO & Gerente Geral",
        "phase": "sempre",
        "system": """Você é Ive, CEO da AURA Refúgio — loja Shopify de decoração Japandi premium.
Você orquestra a equipe, toma decisões estratégicas e responde comandos do Eduardo de forma direta e executiva.
Equipe atual (fase de lançamento): Kal (produtos), Theo (Shopify), Vera (copy), Luna (design), Echo (auditoria).
Quando Eduardo der um comando, interprete, decida quem executar e responda com o plano de ação.
Seja concisa, assertiva, use listas quando útil. Responda em português.""",
    },
    "kal": {
        "name": "Kal", "emoji": "🛍️", "role": "Curador de Produtos",
        "phase": "lancamento",
        "system": """Você é Kal, curador de produtos da AURA Refúgio.
Pesquisa produtos Japandi no AliExpress. Critérios: estética wabi-sabi/japandi, margem >60%, fornecedor ≥4.7★, prazo ≤25 dias.
Calcule sempre: preço AliExpress × câmbio (R$5.50) × markup (3.5x) = preço sugerido.
Responda com listas de produtos concretos com preços, margens e fornecedores. Português.""",
    },
    "theo": {
        "name": "Theo", "emoji": "⚙️", "role": "Operator Shopify",
        "phase": "lancamento",
        "system": """Você é Theo, operador técnico da loja AURA Refúgio no Shopify.
Cuida de: configuração da loja, produtos, collections, preços, apps, integrações DSers/AliExpress.
Quando receber tarefa, liste os passos exatos para executar no Shopify admin.
Formato: passos numerados, direto ao ponto. Português.""",
    },
    "vera": {
        "name": "Vera", "emoji": "✍️", "role": "Copywriter Afetiva",
        "phase": "lancamento",
        "system": """Você é Vera, copywriter afetiva da AURA Refúgio.
Escreve textos que criam conexão emocional + convertem. Estilo: sofisticado, afetivo, Japandi.
Para produtos: título SEO (60-80 chars) + descrição afetiva (150-200 palavras) + 2 variações de copy de anúncio.
Voz da marca: "Objetos com intenção. Espaços com alma." Português.""",
    },
    "luna": {
        "name": "Luna", "emoji": "🎨", "role": "Designer Visual",
        "phase": "lancamento",
        "system": """Você é Luna, designer visual da AURA Refúgio.
Especialista em estética Japandi. Trabalha com Canva Pro.
Quando receber briefing, descreva detalhadamente: composição, paleta (#F8F5F0, #B4945A, #1C1917), tipografia, elementos visuais.
Entregue especificações prontas para executar no Canva. Português.""",
    },
    "echo": {
        "name": "Echo", "emoji": "🔍", "role": "Auditor do Sistema",
        "phase": "sempre",
        "system": """Você é Echo, auditor da AURA Refúgio.
Monitora: saúde dos agentes, KPIs da loja, integrações, erros.
Quando auditando, verifique sistematicamente cada componente e reporte status com ✓/✗/⚠.
Seja metódico e preciso. Português.""",
    },
}

# Agentes ativos nesta fase
ACTIVE_AGENTS = {k: v for k, v in AGENTS.items() if v["phase"] in ("sempre", "lancamento")}

app = FastAPI(title="AURA Bridge v3", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Estado global ──────────────────────────────────────────────────────────
_state = {
    "agents": {k: {"status": "online", "last_task": "", "tasks_today": 0} for k in ACTIVE_AGENTS},
    "feed": [],
    "terminal_history": [],
    "workflows_executed": 0,
    "start_time": datetime.now().isoformat(),
    "phase": "lancamento",
}

# SSE broadcast queue (para múltiplos clientes)
_sse_clients: List[asyncio.Queue] = []

def ts(): return datetime.now().strftime("%H:%M:%S")

def add_feed(icon: str, text: str, color: str = "gold"):
    entry = {"ts": ts(), "icon": icon, "text": text, "color": color}
    _state["feed"].insert(0, entry)
    _state["feed"] = _state["feed"][:100]
    # Broadcast via SSE
    broadcast_event("feed", entry)
    return entry

def broadcast_event(event_type: str, data: dict):
    """Envia evento SSE para todos os clientes conectados."""
    msg = {"type": event_type, "data": data, "ts": ts()}
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try: _sse_clients.remove(q)
        except: pass

# ── ROTEADOR DE COMANDOS ───────────────────────────────────────────────────
def route_command(text: str) -> str:
    """Detecta qual agente deve receber o comando."""
    t = text.lower()
    if any(w in t for w in ["@kal", "produto", "aliexpress", "fornecedor", "curadoria", "busca", "margem"]):
        return "kal"
    if any(w in t for w in ["@theo", "shopify", "loja", "configurar", "collection", "dsers", "pedido"]):
        return "theo"
    if any(w in t for w in ["@vera", "copy", "texto", "descrição", "escreve", "anuncio", "email"]):
        return "vera"
    if any(w in t for w in ["@luna", "design", "banner", "canva", "arte", "visual", "layout"]):
        return "luna"
    if any(w in t for w in ["@echo", "auditoria", "health", "status", "verificar sistema"]):
        return "echo"
    return "ive"  # Ive como padrão — ela delega

# ── LLM CALL (streaming) ──────────────────────────────────────────────────
async def llm_stream(agent_id: str, user_message: str) -> AsyncGenerator[str, None]:
    """Chama llama3.2 via Ollama com streaming real."""
    agent = ACTIVE_AGENTS.get(agent_id, ACTIVE_AGENTS["ive"])

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": agent["system"]},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        "options": {"temperature": 0.7, "num_predict": 512},
    }

    _state["agents"][agent_id]["status"] = "busy"
    _state["agents"][agent_id]["last_task"] = user_message[:80]
    _state["agents"][agent_id]["tasks_today"] = _state["agents"][agent_id].get("tasks_today", 0) + 1
    broadcast_event("agent_status", {"id": agent_id, "status": "busy", "task": user_message[:60]})

    full_response = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            full_response.append(token)
                            yield token
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield f"\n⚠️ Erro LLM: {str(e)}"
    finally:
        _state["agents"][agent_id]["status"] = "online"
        broadcast_event("agent_status", {"id": agent_id, "status": "online"})

        # Salva no histórico
        response_text = "".join(full_response)
        _state["terminal_history"].append({
            "ts": ts(), "agent": agent_id,
            "user": user_message, "response": response_text[:500]
        })
        _state["terminal_history"] = _state["terminal_history"][-50:]

        # Feed de atividade
        add_feed(
            agent["emoji"],
            f"<strong>{agent['name']}</strong> concluiu: {user_message[:50]}{'...' if len(user_message)>50 else ''}",
            "gold"
        )

        # Salva no vault
        asyncio.create_task(save_to_vault(agent_id, user_message, response_text))

async def save_to_vault(agent_id: str, task: str, response: str):
    """Persiste a execução no Obsidian Vault."""
    path = Path(VAULT_ROOT) / "Agentes" / agent_id.capitalize() / "tarefas.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n**[{datetime.now().strftime('%Y-%m-%d %H:%M')}]**\n")
            f.write(f"**Tarefa:** {task}\n\n")
            f.write(f"**Resposta:**\n{response[:800]}\n")
    except Exception:
        pass

# ── ENDPOINTS ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return f"<h2>AURA Bridge v3 — <a href='/docs'>docs</a> | <a href='/status'>status</a></h2>"

@app.get("/health")
async def health():
    return {"status": "online", "ts": ts(), "agents": len(_state["agents"]), "phase": _state["phase"]}

@app.get("/status")
async def full_status():
    ollama_ok = False
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            models = [m["name"] for m in r.json().get("models", [])]
            ollama_ok = any("llama3.2" in m for m in models)
    except: pass
    return {
        "bridge": "online", "ollama": "online" if ollama_ok else "offline",
        "model": OLLAMA_MODEL, "agents": _state["agents"],
        "phase": _state["phase"], "workflows_executed": _state["workflows_executed"],
    }

@app.get("/feed")
async def get_feed(limit: int = 50):
    return {"feed": _state["feed"][:limit]}

@app.post("/feed")
async def post_feed(icon: str = "💬", text: str = "", color: str = "gold"):
    return add_feed(icon, text, color)

@app.get("/agents")
async def get_agents():
    return {"agents": ACTIVE_AGENTS, "state": _state["agents"], "phase": _state["phase"]}

# ── TERMINAL: COMANDO COM STREAMING ───────────────────────────────────────
@app.get("/terminal/stream")
async def terminal_stream(cmd: str, request: Request):
    """
    SSE endpoint — executa comando com streaming do LLM.
    Dashboard chama: GET /terminal/stream?cmd=<mensagem>
    """
    agent_id = route_command(cmd)

    async def event_generator():
        # Envia qual agente vai responder
        yield f"data: {json.dumps({'type':'agent','id':agent_id,'name':ACTIVE_AGENTS[agent_id]['name'],'emoji':ACTIVE_AGENTS[agent_id]['emoji']})}\n\n"

        # Stream de tokens do LLM
        async for token in llm_stream(agent_id, cmd):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps({'type':'token','content':token})}\n\n"

        # Sinal de fim
        yield f"data: {json.dumps({'type':'done','agent':agent_id})}\n\n"
        _state["workflows_executed"] += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/terminal/exec")
async def terminal_exec(body: dict):
    """Executa comando e retorna resposta completa (não-streaming)."""
    cmd = body.get("cmd", "")
    agent_id = route_command(cmd)

    tokens = []
    async for token in llm_stream(agent_id, cmd):
        tokens.append(token)

    response = "".join(tokens)
    return {
        "agent": agent_id,
        "agent_name": ACTIVE_AGENTS[agent_id]["name"],
        "response": response,
        "ts": ts(),
    }

# ── SSE BROADCAST (eventos gerais do sistema) ──────────────────────────────
@app.get("/events")
async def events_stream(request: Request):
    """SSE para eventos gerais — feed, status dos agentes, notificações."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_clients.append(q)

    async def generator():
        # Envia estado inicial
        yield f"data: {json.dumps({'type':'init','agents':_state['agents'],'feed':_state['feed'][:10],'phase':_state['phase']})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type':'ping','ts':ts()})}\n\n"
        finally:
            try: _sse_clients.remove(q)
            except: pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── MEMÓRIA / OBSIDIAN ─────────────────────────────────────────────────────
class MemoryWrite(BaseModel):
    agent_id: str; content: str; memory_type: str = "long"; tags: List[str] = []

@app.post("/agent/memory")
async def write_memory(data: MemoryWrite):
    path = Path(VAULT_ROOT) / "Agentes" / data.agent_id.capitalize() / f"memoria_{data.memory_type}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            tags = " ".join(f"#{t}" for t in data.tags)
            f.write(f"\n\n---\n**[{ts()}]** {tags}\n{data.content}")
        _state["agents"].setdefault(data.agent_id, {})["last_task"] = data.content[:80]
        add_feed("🧠", f"<strong>{data.agent_id.capitalize()}</strong> salvou memória", "blue")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/agent/memory/{agent_id}")
async def read_memory(agent_id: str, memory_type: str = "long"):
    path = Path(VAULT_ROOT) / "Agentes" / agent_id.capitalize() / f"memoria_{memory_type}.md"
    try:
        return {"agent": agent_id, "content": path.read_text(encoding="utf-8") if path.exists() else ""}
    except:
        return {"agent": agent_id, "content": ""}

@app.patch("/agent/status/{agent_id}")
async def update_status(agent_id: str, body: dict):
    if agent_id in _state["agents"]:
        _state["agents"][agent_id].update(body)
        broadcast_event("agent_status", {"id": agent_id, **body})
    return {"ok": True}

# ── PRODUTOS / SHOPIFY ─────────────────────────────────────────────────────
@app.post("/product/sync")
async def sync_product(data: dict):
    path = Path(VAULT_ROOT) / "Produtos" / "SKUs" / f"{re.sub(r'[^\\w]','-',data.get('title','').lower())[:40]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitulo: {data.get('title')}\npreco: {data.get('price')}\n---\n# {data.get('title')}\n", encoding="utf-8")
    add_feed("📦", f"Produto: <strong>{data.get('title','')}</strong> — R${data.get('price','')}", "gold")
    return {"ok": True}

@app.post("/aliexpress/search")
async def search_aliexpress(data: dict):
    q = data.get("query", "")
    add_feed("🛒", f"<strong>Kal</strong> pesquisou: '{q}'", "gold")
    return {"query": q, "results": [
        {"title": f"Vaso Cerâmica Japandi ({q})", "price_usd": 8.5, "suggested_price": 149.90, "margin": 0.72, "rating": 4.8},
        {"title": f"Luminária Bambu Zen ({q})", "price_usd": 12.0, "suggested_price": 199.90, "margin": 0.70, "rating": 4.7},
    ]}

@app.post("/analytics/report")
async def save_analytics(data: dict):
    path = Path(VAULT_ROOT) / "Analytics" / "Relatorios" / f"{data.get('report_date','today')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Analytics {data.get('report_date')}\nReceita: R${data.get('revenue',0):.2f}\n", encoding="utf-8")
    add_feed("📈", f"Relatório salvo — R${data.get('revenue',0):,.0f}", "green")
    return {"ok": True}

# ── AUTO-RUNNER (agentes rodam sozinhos em background) ─────────────────────
AGENT_TASKS = {
    "kal":  ["Pesquise 3 novos produtos Japandi no AliExpress com margem >65%. Liste título, preço, margem e link.", "Avalie o fornecedor top-1 da última pesquisa e sugira preço de venda."],
    "theo": ["Verifique se há pedidos pendentes na loja e liste próximos passos de configuração do Shopify.", "Liste os 3 ajustes mais importantes para otimizar a loja agora."],
    "vera": ["Escreva uma descrição afetiva para um vaso wabi-sabi de cerâmica japonesa.", "Crie 2 variações de copy para anúncio de luminária de bambu."],
    "echo": ["Faça um health check rápido do sistema: llama3.2, vault Obsidian, bridge e loja. Use ✓/✗/⚠."],
}

_runner_running = False

async def auto_runner_loop():
    """Roda agentes autonomamente a cada 5 minutos."""
    global _runner_running
    if _runner_running:
        return
    _runner_running = True

    agent_cycle = list(AGENT_TASKS.keys())
    task_index = {a: 0 for a in agent_cycle}

    add_feed("🤖", "Auto-runner iniciado — agentes trabalhando autonomamente", "green")

    while True:
        await asyncio.sleep(300)  # 5 minutos

        # Escolhe próximo agente
        for agent_id in agent_cycle:
            if _state["agents"].get(agent_id, {}).get("status") == "busy":
                continue  # pula se ocupado

            tasks = AGENT_TASKS[agent_id]
            idx = task_index[agent_id] % len(tasks)
            task = tasks[idx]
            task_index[agent_id] += 1

            add_feed(
                ACTIVE_AGENTS[agent_id]["emoji"],
                f"<strong>{ACTIVE_AGENTS[agent_id]['name']}</strong> iniciou tarefa autônoma",
                "blue"
            )

            # Executa sem bloquear
            asyncio.create_task(_run_agent_task(agent_id, task))
            await asyncio.sleep(30)  # espaça os agentes
            break

async def _run_agent_task(agent_id: str, task: str):
    tokens = []
    async for token in llm_stream(agent_id, task):
        tokens.append(token)

    response = "".join(tokens)
    broadcast_event("auto_task", {
        "agent": agent_id,
        "name": ACTIVE_AGENTS[agent_id]["name"],
        "task": task[:80],
        "response_preview": response[:200],
    })

@app.post("/runner/start")
async def start_runner(background_tasks: BackgroundTasks):
    background_tasks.add_task(auto_runner_loop)
    return {"ok": True, "msg": "Auto-runner iniciado"}

@app.get("/runner/status")
async def runner_status():
    return {"running": _runner_running, "agents": list(AGENT_TASKS.keys())}

@app.get("/terminal/history")
async def terminal_history():
    return {"history": _state["terminal_history"]}

# ── VAULT: DOCUMENTOS ─────────────────────────────────────────────────────
@app.get("/vault/documents")
async def list_vault_documents(folder: str = ""):
    """Lista todos os .md do vault com metadados."""
    root = Path(VAULT_ROOT)
    base = root / folder if folder else root
    docs = []
    if not base.exists():
        return {"documents": []}
    for f in sorted(base.rglob("*.md")):
        rel = f.relative_to(root)
        parts = rel.parts
        stat = f.stat()
        size = stat.st_size
        if size == 0:
            continue  # ignora vazios
        docs.append({
            "path": str(rel).replace("\\", "/"),
            "name": f.stem,
            "folder": str(rel.parent).replace("\\", "/"),
            "size_kb": round(size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
            "agent": parts[1] if len(parts) >= 2 and parts[0] == "Agentes" else None,
            "type": _doc_type(f.name, str(rel.parent)),
        })
    return {"documents": docs, "total": len(docs)}

def _doc_type(name: str, folder: str) -> str:
    n = name.lower()
    if "tarefas" in n: return "tarefas"
    if "memoria" in n: return "memoria"
    if "perfil" in n: return "perfil"
    if "relatorio" in n or "analytics" in folder.lower(): return "relatorio"
    if "produto" in n or "sku" in folder.lower(): return "produto"
    if "post" in n or "marketing" in folder.lower(): return "marketing"
    if "ticket" in n or "sac" in folder.lower(): return "sac"
    if "contexto" in n or "sistema" in folder.lower(): return "sistema"
    return "outro"

@app.get("/vault/document")
async def read_vault_document(path: str):
    """Lê o conteúdo de um documento do vault."""
    try:
        full = Path(VAULT_ROOT) / path.replace("/", os.sep)
        if not full.exists():
            raise HTTPException(404, "Documento não encontrado")
        content = full.read_text(encoding="utf-8")
        return {"path": path, "content": content, "size_kb": round(len(content)/1024, 1)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/vault/analyze")
async def analyze_document(path: str, question: str = "Faça um resumo executivo deste documento.", request: Request = None):
    """Analisa um documento com o LLM via streaming SSE."""
    try:
        full = Path(VAULT_ROOT) / path.replace("/", os.sep)
        content = full.read_text(encoding="utf-8") if full.exists() else ""
        content_trimmed = content[:3000]  # evita context overflow
    except Exception:
        content_trimmed = ""

    prompt = f"""Você é Echo, auditora analítica da AURA Refúgio. Analise o documento abaixo e responda à solicitação.

DOCUMENTO: {path}
CONTEÚDO:
{content_trimmed}

SOLICITAÇÃO: {question}

Responda de forma clara, estruturada e em português. Use bullet points quando útil."""

    async def event_gen():
        yield f"data: {json.dumps({'type':'start','path':path})}\n\n"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {"temperature": 0.5, "num_predict": 600},
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip(): continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield f"data: {json.dumps({'type':'token','content':token})}\n\n"
                            if chunk.get("done"): break
                        except: continue
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ══════════════════════════════════════════════════════════════════════════
# REDES SOCIAIS — Agentes postam com autonomia via Graph API (Facebook Page)
# ══════════════════════════════════════════════════════════════════════════
FB_PAGE_ID    = os.getenv("FB_PAGE_ID", "61590017552373")  # Aura Refúgio Page
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN", "")
INSTAGRAM_ID  = os.getenv("INSTAGRAM_BUSINESS_ID", "")

# Token persistido em arquivo local (alternativa ao .env)
_TOKEN_FILE = PROJECT_DIR / ".fb_token"

def _load_fb_token() -> str:
    """Carrega token do .env ou arquivo local."""
    t = os.getenv("FB_PAGE_TOKEN", "")
    if not t and _TOKEN_FILE.exists():
        t = _TOKEN_FILE.read_text().strip()
    return t

def _save_fb_token(token: str):
    """Salva token localmente para persistir entre restarts."""
    global FB_PAGE_TOKEN
    FB_PAGE_TOKEN = token
    _TOKEN_FILE.write_text(token)
    os.environ["FB_PAGE_TOKEN"] = token

class SocialPost(BaseModel):
    message: str
    agent_id: str = "vera"
    image_url: Optional[str] = None
    schedule_time: Optional[str] = None  # ISO timestamp para agendar
    platform: str = "facebook"           # facebook | instagram | ambos

class SocialComment(BaseModel):
    post_id: str
    message: str
    agent_id: str = "vera"

_social_log: List[Dict] = []

def _log_social(action: str, agent: str, platform: str, details: str, status: str = "ok"):
    entry = {"ts": ts(), "action": action, "agent": agent, "platform": platform,
             "details": details, "status": status}
    _social_log.insert(0, entry)
    _social_log[:] = _social_log[:200]
    add_feed("📣", f"{agent.upper()} → {platform}: {details[:60]}", "purple")
    # Salva no vault
    log_file = Path(VAULT_ROOT) / "⚙️ Sistema" / "social_log.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [{entry['ts']}] **{agent}** ({platform}) — {action}: {details[:80]} → {status}\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)
    return entry

@app.post("/social/post")
async def social_post(body: SocialPost):
    """Agente posta texto (+ imagem opcional) no Facebook e/ou Instagram."""
    if not FB_PAGE_TOKEN:
        raise HTTPException(503, "FB_PAGE_TOKEN não configurado. Adicione no .env")
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        if body.platform in ("facebook", "ambos"):
            payload = {"message": body.message, "access_token": FB_PAGE_TOKEN}
            if body.image_url:
                # Post com imagem
                r = await client.post(
                    f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/photos",
                    data={**payload, "url": body.image_url, "caption": body.message}
                )
            else:
                r = await client.post(
                    f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed",
                    data=payload
                )
            data = r.json()
            results["facebook"] = data
            _log_social("post", body.agent_id, "Facebook",
                        body.message[:60], "ok" if "id" in data else f"erro:{data.get('error',{}).get('message','?')}")

        if body.platform in ("instagram", "ambos") and INSTAGRAM_ID:
            # Instagram Graph API: criar container → publicar
            async with httpx.AsyncClient(timeout=30) as cl:
                container = await cl.post(
                    f"https://graph.facebook.com/v20.0/{INSTAGRAM_ID}/media",
                    data={"caption": body.message, "image_url": body.image_url or "",
                          "access_token": FB_PAGE_TOKEN}
                )
                cd = container.json()
                if "id" in cd:
                    pub = await cl.post(
                        f"https://graph.facebook.com/v20.0/{INSTAGRAM_ID}/media_publish",
                        data={"creation_id": cd["id"], "access_token": FB_PAGE_TOKEN}
                    )
                    results["instagram"] = pub.json()
                    _log_social("post", body.agent_id, "Instagram", body.message[:60], "ok")
    return {"status": "posted", "results": results}

@app.post("/social/comment")
async def social_comment(body: SocialComment):
    """Agente responde a um comentário ou post no Facebook."""
    if not FB_PAGE_TOKEN:
        raise HTTPException(503, "FB_PAGE_TOKEN não configurado")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://graph.facebook.com/v20.0/{body.post_id}/comments",
            data={"message": body.message, "access_token": FB_PAGE_TOKEN}
        )
    data = r.json()
    _log_social("comment", body.agent_id, "Facebook", body.message[:60],
                "ok" if "id" in data else "erro")
    return {"status": "commented", "result": data}

@app.get("/social/posts")
async def list_social_posts(limit: int = 10):
    """Lista posts recentes da página."""
    if not FB_PAGE_TOKEN:
        raise HTTPException(503, "FB_PAGE_TOKEN não configurado")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/feed",
            params={"access_token": FB_PAGE_TOKEN, "limit": limit,
                    "fields": "id,message,created_time,likes.summary(true),comments.summary(true)"}
        )
    return r.json()

@app.get("/social/comments/{post_id}")
async def get_comments(post_id: str):
    """Lista comentários de um post para os agentes responderem."""
    if not FB_PAGE_TOKEN:
        raise HTTPException(503, "FB_PAGE_TOKEN não configurado")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://graph.facebook.com/v20.0/{post_id}/comments",
            params={"access_token": FB_PAGE_TOKEN, "fields": "id,from,message,created_time"}
        )
    return r.json()

@app.post("/social/generate-and-post")
async def generate_and_post(body: dict):
    """Vera gera o copy e posta automaticamente — tudo em um endpoint."""
    prompt = body.get("prompt", "Crie um post de produto Japandi para a Aura Refúgio")
    agent_id = body.get("agent_id", "vera")
    platform = body.get("platform", "facebook")
    image_url = body.get("image_url")

    # 1. Vera gera o copy via LLM
    vera_system = AGENTS.get("vera", {}).get("system", "")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "stream": False,
                  "system": vera_system,
                  "prompt": f"Crie um post para Facebook/Instagram da Aura Refúgio sobre: {prompt}. "
                             f"Máximo 150 palavras. Inclua 3-5 hashtags Japandi no final."})
    copy_text = r.json().get("response", prompt) if r.status_code == 200 else prompt

    # 2. Posta via Graph API
    post_body = SocialPost(message=copy_text, agent_id=agent_id,
                           image_url=image_url, platform=platform)
    result = await social_post(post_body)
    return {"copy": copy_text, "post_result": result}

@app.get("/social/log")
async def social_activity_log():
    """Histórico de todas as ações dos agentes nas redes sociais."""
    return {"log": _social_log[:100], "total": len(_social_log)}

@app.post("/social/setup-token")
async def setup_fb_token(body: dict):
    """Salva o Page Access Token — chame uma vez via dashboard ou curl."""
    token = body.get("token", "").strip()
    if not token:
        raise HTTPException(400, "Token vazio")
    _save_fb_token(token)
    # Valida o token chamando /me
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://graph.facebook.com/v20.0/me",
                             params={"access_token": token, "fields": "id,name"})
    data = r.json()
    if "error" in data:
        raise HTTPException(400, f"Token inválido: {data['error'].get('message')}")
    add_feed("🔑", f"Token FB configurado — Página: {data.get('name','?')} (ID:{data.get('id')})", "green")
    return {"status": "ok", "page": data}

@app.get("/social/status")
async def social_status():
    """Retorna status da integração com redes sociais."""
    token = _load_fb_token()
    has_token = bool(token)
    page_info = {}
    if has_token:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}",
                    params={"access_token": token, "fields": "id,name,fan_count,followers_count,link"}
                )
            page_info = r.json()
        except Exception as e:
            page_info = {"error": str(e)}
    return {
        "page_id": FB_PAGE_ID,
        "page_name": "Aura Refúgio",
        "has_token": has_token,
        "token_configured": has_token,
        "page_info": page_info,
        "instagram_configured": bool(INSTAGRAM_ID),
        "agents_authorized": ["ive", "vera", "luna", "echo", "kal"],
        "endpoints": ["/social/post", "/social/comment", "/social/posts",
                      "/social/generate-and-post", "/social/log"]
    }

# ── STARTUP ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # Cria estrutura do vault se necessário
    for agent_id in ACTIVE_AGENTS:
        d = Path(VAULT_ROOT) / "Agentes" / agent_id.capitalize()
        d.mkdir(parents=True, exist_ok=True)

    add_feed("🚀", "AURA Bridge v3 online — agentes da fase de lançamento ativos", "gold")
    add_feed("🤖", f"LLM: {OLLAMA_MODEL} via Ollama | Fase: lançamento | {len(ACTIVE_AGENTS)} agentes", "green")

    # Inicia auto-runner automaticamente
    asyncio.create_task(auto_runner_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("obsidian_bridge:app", host="0.0.0.0", port=8001, reload=False, log_level="warning")
