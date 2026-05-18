# 🏮 AURA Refúgio — HQ Sistema de Agentes IA

> *Objetos com intenção. Espaços com alma.*

Sistema completo de agentes IA para operar uma loja Shopify de decoração Japandi premium via dropshipping.

## ✨ Visão Geral

**8 agentes especializados** orquestrados por CrewAI + llama3.2 (local, gratuito):

| Agente | Função | Fase |
|--------|--------|------|
| 👩‍💼 **Ive** | CEO & Gerente Geral | Sempre |
| 🛍️ **Kal** | Curador de Produtos AliExpress | Lançamento |
| ⚙️ **Theo** | Operator Shopify | Lançamento |
| ✍️ **Vera** | Copywriter Afetiva | Lançamento |
| 🎨 **Luna** | Designer Visual (Canva Pro) | Lançamento |
| 🔍 **Echo** | Auditor do Sistema | Sempre |
| 📣 **Rex** | Gestor de Tráfego Pago | Escala |
| 🌙 **Nox** | Gestor de Conteúdo | Escala |

## 🖥️ Dashboard Terminal

Interface de terminal IDE com streaming real do llama3.2:

- **Clique em um agente** → abre terminal IDE com streaming token a token
- **📁 Documentos** → painel de análise com IA de todos os docs do vault
- **Terminal principal** → comandos em linguagem natural para toda a equipe
- **Feed ao vivo** → atividade dos agentes em tempo real via SSE

## 🏗️ Arquitetura

```
dashboard/aura-office.html   ← Frontend (HTML puro, sem deps)
bridge/obsidian_bridge.py    ← FastAPI Bridge (porta 8001)
src/meu_primeiro_time/       ← CrewAI agents
n8n-workflows/               ← Automações JSON para n8n
```

## 🚀 Iniciar

```bash
# 1. Instalar dependências
pip install crewai fastapi uvicorn httpx

# 2. Garantir Ollama + llama3.2
ollama pull llama3.2

# 3. Iniciar sistema completo
start-aura.bat

# Ou manualmente:
python -m uvicorn bridge.obsidian_bridge:app --port 8001 --reload
# Abrir dashboard/aura-office.html no navegador
```

## 🔧 Stack

- **LLM**: llama3.2 via Ollama (local, gratuito)
- **Backend**: FastAPI + SSE streaming
- **Agentes**: CrewAI
- **Automações**: n8n
- **Memória**: Obsidian Vault (escrita direta)
- **Loja**: Shopify + DSers + AliExpress

## 📋 Variáveis de Ambiente

Copie `.env.example` para `.env` e configure:

```env
OLLAMA_MODEL=llama3.2
SHOPIFY_STORE=sua-loja.myshopify.com
SHOPIFY_TOKEN=shpat_xxxxx
VAULT_PATH=C:\Users\seu-usuario\OneDrive\Documentos\Obsidian Vault
```

---
*Built with CrewAI + Ollama + FastAPI*
