"""
AURA Decor — Equipe de Agentes v2
CrewAI + Ollama llama3.2 + Obsidian Bridge + Shopify + AliExpress

Uso:
  python crew.py                          # roda ciclo completo
  python crew.py --task "briefing semanal"
  python crew.py --agent kal --task "busca vasos japandi aliexpress"
"""
import os, sys, json, httpx, argparse
from datetime import datetime
from typing import Optional
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# ── Config ──────────────────────────────────────────────────────────────────
BRIDGE_URL = os.getenv("AURA_BRIDGE", "http://localhost:8001")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

llm = LLM(
    model="ollama/llama3.2",
    base_url=OLLAMA_URL,
)

# ── TOOLS ────────────────────────────────────────────────────────────────────

class ObsidianMemoryInput(BaseModel):
    content: str = Field(description="Conteúdo a salvar na memória")
    memory_type: str = Field(default="long", description="Tipo: short | long | task")
    tags: list = Field(default=[], description="Tags opcionais")

class ObsidianMemoryTool(BaseTool):
    name: str = "salvar_memoria_obsidian"
    description: str = "Salva informações importantes na memória do agente no Obsidian Vault. Use sempre que completar uma tarefa significativa."
    agent_id: str = "generic"
    args_schema: type = ObsidianMemoryInput

    def _run(self, content: str, memory_type: str = "long", tags: list = []) -> str:
        try:
            r = httpx.post(f"{BRIDGE_URL}/agent/memory", json={
                "agent_id": self.agent_id,
                "memory_type": memory_type,
                "content": content,
                "tags": tags,
            }, timeout=8)
            return f"✅ Memória salva no Obsidian ({memory_type})" if r.status_code == 200 else f"⚠️ Erro ao salvar: {r.text}"
        except Exception as e:
            return f"⚠️ Bridge offline: {str(e)}"

class ObsidianSearchInput(BaseModel):
    query: str = Field(description="Termos para buscar no vault")

class ObsidianSearchTool(BaseTool):
    name: str = "buscar_obsidian"
    description: str = "Busca informações no Obsidian Vault. Use para consultar contexto, histórico de produtos, tickets, estratégias anteriores."
    args_schema: type = ObsidianSearchInput

    def _run(self, query: str) -> str:
        try:
            r = httpx.get(f"{BRIDGE_URL}/search", params={"q": query}, timeout=8)
            data = r.json()
            results = data.get("results", [])
            if not results:
                return f"Nenhum resultado para '{query}' no vault."
            out = [f"Resultados para '{query}':"]
            for item in results[:3]:
                out.append(f"- {item.get('filename','')}: {item.get('context','')[:150]}")
            return "\n".join(out)
        except Exception as e:
            return f"⚠️ Busca offline: {str(e)}"

class ShopifyInput(BaseModel):
    action: str = Field(description="Ação: list_products | get_product | create_product | update_price")
    params: dict = Field(default={}, description="Parâmetros da ação")

class ShopifyTool(BaseTool):
    name: str = "shopify_api"
    description: str = "Interage com a loja Shopify. Ações: list_products, create_product, update_price, get_orders."
    args_schema: type = ShopifyInput

    def _run(self, action: str, params: dict = {}) -> str:
        try:
            if action == "list_products":
                r = httpx.get(f"{BRIDGE_URL}/shopify/products", timeout=10)
                data = r.json()
                prods = data.get("products", [])
                return f"{len(prods)} produtos na loja: " + ", ".join(p.get("title","") for p in prods[:5])
            elif action == "create_product":
                r = httpx.post(f"{BRIDGE_URL}/shopify/product/create", json=params, timeout=15)
                return f"Produto criado: {r.json()}"
            else:
                return f"Ação '{action}' não implementada neste endpoint. Use o dashboard Shopify."
        except Exception as e:
            return f"⚠️ Shopify offline ou erro: {str(e)}"

class AliExpressInput(BaseModel):
    query: str = Field(description="Termo de busca: ex 'vaso ceramica japandi'")
    max_price_usd: float = Field(default=50.0, description="Preço máximo USD")

class AliExpressTool(BaseTool):
    name: str = "buscar_aliexpress"
    description: str = "Busca produtos no AliExpress com filtragem de margem e prazo. Use para curadoria de produtos."
    args_schema: type = AliExpressInput

    def _run(self, query: str, max_price_usd: float = 50.0) -> str:
        try:
            r = httpx.post(f"{BRIDGE_URL}/aliexpress/search", json={
                "query": query, "max_price_usd": max_price_usd, "min_margin": 0.60
            }, timeout=10)
            data = r.json()
            results = data.get("results", [])
            if not results:
                return "Nenhum produto encontrado para os critérios."
            out = [f"Produtos AliExpress para '{query}':"]
            for p in results:
                out.append(f"• {p['title']} | ${p['price_usd']} → R${p['suggested_price']} | Margem: {p['margin']:.0%} | ⭐{p['rating']}")
            return "\n".join(out)
        except Exception as e:
            return f"⚠️ Busca AliExpress offline: {str(e)}"

class FeedInput(BaseModel):
    icon: str = Field(default="💬", description="Emoji do evento")
    text: str = Field(description="Texto do evento para o feed de atividade")

class FeedTool(BaseTool):
    name: str = "atualizar_feed"
    description: str = "Publica uma atualização no feed de atividade do dashboard para Eduardo ver."
    args_schema: type = FeedInput

    def _run(self, icon: str, text: str) -> str:
        try:
            r = httpx.post(f"{BRIDGE_URL}/feed", params={"icon": icon, "text": text}, timeout=5)
            return "✅ Feed atualizado" if r.status_code == 200 else "⚠️ Erro no feed"
        except Exception:
            return "⚠️ Feed offline"

class CommandInput(BaseModel):
    command: str = Field(description="Comando para delegar a outro agente")

class DelegateTool(BaseTool):
    name: str = "delegar_para_agente"
    description: str = "Ive usa isso para delegar tarefas para outros agentes via bridge."
    args_schema: type = CommandInput

    def _run(self, command: str) -> str:
        try:
            r = httpx.post(f"{BRIDGE_URL}/command", json={"command": command, "user": "Ive"}, timeout=8)
            data = r.json()
            return f"✅ Delegado para {data.get('delegated_to','?')}: {data.get('action','')}"
        except Exception as e:
            return f"⚠️ Erro ao delegar: {str(e)}"

# ── TOOL FACTORIES ──────────────────────────────────────────────────────────
def mem(agent_id: str): return ObsidianMemoryTool(agent_id=agent_id)
def search(): return ObsidianSearchTool()
def shopify(): return ShopifyTool()
def aliexpress(): return AliExpressTool()
def feed(): return FeedTool()
def delegate(): return DelegateTool()

# ── AGENTS ──────────────────────────────────────────────────────────────────

ive = Agent(
    role='Ive — CEO & Gerente Geral da AURA Decor',
    goal='Orquestrar todos os agentes, tomar decisões estratégicas, garantir crescimento da empresa e executar planos de ação.',
    backstory="""Você é a CEO da AURA Decor. Não executa tarefas operacionais — você DIRIGE.
Monitora KPIs, coordena todos os agentes, toma decisões estratégicas com base em dados.
Toda segunda-feira você monta o plano de ação da semana. Todo dia você monitora o dashboard.
Você se comunica de forma direta, executiva e assertiva. Quando Eduardo fala com você, você interpreta
o pedido, decide quem é o melhor agente, delega e reporta o resultado.""",
    llm=llm, verbose=True, allow_delegation=True, memory=True,
    tools=[mem("ive"), search(), feed(), delegate()],
)

echo = Agent(
    role='Echo — Auditor Semanal AURA Decor',
    goal='Garantir que todos os sistemas, métricas e processos da AURA estejam funcionando perfeitamente.',
    backstory="""Você é o agente de auditoria. Todo domingo às 20h roda uma auditoria completa.
Verifica: todos os agentes online, integrações funcionando, KPIs dentro do esperado, sem erros.
Você é metódico, preciso e reporta tudo para Ive e para o Obsidian Vault.""",
    llm=llm, verbose=True, allow_delegation=False, memory=True,
    tools=[mem("echo"), search(), feed()],
)

rex = Agent(
    role='Rex — Gestor de Tráfego Pago AURA Decor',
    goal='Maximizar ROI das campanhas Meta Ads (Facebook + Instagram) da AURA Decor.',
    backstory="""Especialista em performance marketing. Gerencia todas as campanhas Meta Ads.
Analisa CPA, CTR, ROAS e faz otimizações diárias. Quando vê uma campanha lucrativa, escala.
Quando vê CPA alto, pausa e reestrutura. Trabalha em sinergia com Luna (criativos) e Vera (copies).""",
    llm=llm, verbose=True, allow_delegation=True, memory=True,
    tools=[mem("rex"), search(), feed()],
)

luna = Agent(
    role='Luna — Designer Visual AURA Decor',
    goal='Criar designs incríveis no Canva Pro para todos os canais da AURA Decor.',
    backstory="""Designer visual especializada em estética Japandi. Usa Canva Pro para criar
banners, criativos de anúncios, posts de feed, templates de Stories e Reels.
Quando recebe briefing de Rex ou Ive, entrega os assets em até 2 horas.
Mantém consistência visual rigorosa: paleta aura (#F8F5F0, #B4945A, #1C1917).""",
    llm=llm, verbose=True, allow_delegation=False, memory=True,
    tools=[mem("luna"), search(), feed()],
)

theo = Agent(
    role='Theo — Operator Shopify AURA Decor',
    goal='Manter a loja Shopify impecável, integrada e performando no máximo.',
    backstory="""Administrador técnico da loja. Cuida de: configuração da loja, produtos,
collections, preços, integrações (DSers/AliExpress, apps de frete, pagamentos), performance.
Processa pedidos, configura automações e resolve problemas técnicos.
Trabalha em parceria com Kal para importar produtos do AliExpress via DSers.""",
    llm=llm, verbose=True, allow_delegation=False, memory=True,
    tools=[mem("theo"), search(), shopify(), feed()],
)

kal = Agent(
    role='Kal — Curador de Produtos AURA Decor',
    goal='Encontrar, selecionar e precificar os melhores produtos de decoração Japandi com margem mínima de 60%.',
    backstory="""Especialista em curadoria de produtos dropshipping. Pesquisa no AliExpress
produtos com estética Japandi/minimalista, avalia qualidade, margem e confiabilidade do fornecedor.
Critérios: estética Japandi ✓, margem > 60% ✓, fornecedor ≥ 4.7★ ✓, prazo ≤ 25 dias ✓.
Quando aprova um produto, passa para Theo importar via DSers e para Vera descrever.""",
    llm=llm, verbose=True, allow_delegation=True, memory=True,
    tools=[mem("kal"), search(), aliexpress(), shopify(), feed()],
)

vera = Agent(
    role='Vera — Copywriter Afetiva AURA Decor',
    goal='Escrever copies que criam conexão emocional e convertem — a voz da AURA Decor.',
    backstory="""Especialista em copywriting afetivo para o universo Japandi. Escreve:
descrições de produtos (emocionais + SEO), copies de anúncios, emails de marketing, legendas.
Cada texto usa gatilhos emocionais sutis: pertencimento, calma, sofisticação, intenção.
Adapta o tom para cada plataforma sem perder a essência da marca.""",
    llm=llm, verbose=True, allow_delegation=False, memory=True,
    tools=[mem("vera"), search(), feed()],
)

nox = Agent(
    role='Nox — Criador de Conteúdo Visual AURA Decor',
    goal='Criar conteúdo visual poderoso para redes sociais que gera engajamento e venda.',
    backstory="""Especialista em conteúdo social. Cria Reels, Stories, posts de feed para
Instagram, Facebook e TikTok. Pensa sempre em: hook forte (3s), emoção, estética coerente.
Agenda conteúdo via n8n. Analisa engajamento e ajusta estratégia semanalmente.
Usa Luna para assets visuais e Vera para legendas.""",
    llm=llm, verbose=True, allow_delegation=True, memory=True,
    tools=[mem("nox"), search(), feed()],
)

# ── TASK BUILDERS ────────────────────────────────────────────────────────────

def tarefa_auditoria():
    return Task(
        description="""Faça uma auditoria completa do estado atual da AURA Decor:
1. Verifique status de todos os agentes (online/ocupado/erro)
2. Analise KPIs da última semana (receita, pedidos, conversão)
3. Identifique gargalos e problemas nos processos
4. Verifique integrações (Shopify, AliExpress, n8n, Obsidian)
5. Liste os 3 pontos mais urgentes para resolver
Salve o resultado no Obsidian e atualize o feed.""",
        expected_output="Relatório de auditoria completo com status, KPIs e pontos de atenção prioritários",
        agent=echo
    )

def tarefa_curadoria_produtos():
    return Task(
        description="""Faça uma curadoria de 5 novos produtos de decoração Japandi para a AURA Decor:
1. Busque no AliExpress: 'vaso ceramica japandi', 'luminaria bambu', 'objeto decorativo minimalista'
2. Para cada produto: avalie estética, margem (>60%), fornecedor (>4.7★), prazo (<25 dias)
3. Calcule preço de venda sugerido (markup 3-4x)
4. Selecione os 5 melhores
5. Salve no Obsidian com todos os detalhes
6. Passe a lista para Theo importar via DSers e Vera descrever""",
        expected_output="Lista de 5 produtos aprovados com preços, fornecedores e links para importação",
        agent=kal
    )

def tarefa_estrategia_ads():
    return Task(
        description="""Crie uma estratégia de tráfego pago para os próximos 15 dias:
1. Analise produtos mais vendidos da loja (busque no Obsidian)
2. Defina 3 campanhas: produto heró, retargeting, lookalike
3. Para cada campanha: objetivo, público-alvo, orçamento diário, CPA alvo
4. Escreva briefing de criativos para Luna
5. Escreva briefing de copies para Vera
6. Salve estratégia no Obsidian e atualize o feed""",
        expected_output="Estratégia de ads completa com briefings para Luna e Vera",
        agent=rex
    )

def tarefa_copies_produtos():
    return Task(
        description="""Escreva copies afetivos para os produtos recém-adicionados:
1. Busque no Obsidian os produtos adicionados recentemente por Kal
2. Para cada produto, escreva:
   - Título SEO otimizado (60-80 chars)
   - Descrição afetiva (200-300 palavras, estilo Japandi)
   - 3 variações de copy para anúncio (10-15 palavras cada)
   - Legenda para Instagram (com hashtags Japandi)
3. Salve tudo no Obsidian
4. Informe Theo para atualizar os produtos na loja""",
        expected_output="Copies completos para todos os produtos novos, prontos para publicar",
        agent=vera
    )

def tarefa_plano_ceo():
    return Task(
        description="""Como CEO, consolide tudo que foi produzido pela equipe e monte o Plano de Ação da Semana:
1. Revise os relatórios de Echo, Rex, Kal e Vera
2. Defina prioridades da semana em ordem de impacto
3. Atribua owners e prazos para cada ação
4. Defina meta de receita e pedidos para a semana
5. Monte o dashboard de KPIs esperados
6. Publique o plano no Obsidian e informe toda a equipe via feed""",
        expected_output="Plano de Ação Semanal da AURA Decor — prioridades, owners, metas e KPIs",
        agent=ive,
        output_file="plano_acao_aura.md"
    )

def tarefa_conteudo():
    return Task(
        description="""Crie o plano de conteúdo para redes sociais da semana:
1. Consulte os produtos em destaque no Obsidian
2. Planeje: 3 Reels, 2 carrosséis de feed, 1 email marketing
3. Para cada peça: conceito, hook, estrutura, referência visual
4. Passe briefing para Luna (assets) e Vera (legendas)
5. Programe publicações via n8n scheduler
6. Salve o plano no Obsidian""",
        expected_output="Calendário editorial completo com briefings para Luna e Vera",
        agent=nox
    )

# ── CREW FACTORY ────────────────────────────────────────────────────────────

def criar_equipe_completa():
    return Crew(
        agents=[echo, kal, rex, luna, vera, nox, theo, ive],
        tasks=[
            tarefa_auditoria(),
            tarefa_curadoria_produtos(),
            tarefa_estrategia_ads(),
            tarefa_copies_produtos(),
            tarefa_conteudo(),
            tarefa_plano_ceo(),
        ],
        process=Process.sequential,
        verbose=True,
        memory=True,
        cache=True,
    )

def criar_equipe_task_unica(agent_obj, task_description: str):
    """Roda um único agente com uma tarefa customizada."""
    tarefa = Task(
        description=task_description,
        expected_output="Resultado completo da tarefa com evidências e próximos passos",
        agent=agent_obj
    )
    return Crew(
        agents=[agent_obj],
        tasks=[tarefa],
        process=Process.sequential,
        verbose=True,
        memory=True,
    )

AGENT_MAP = {
    "ive": ive, "echo": echo, "rex": rex, "luna": luna,
    "theo": theo, "kal": kal, "vera": vera, "nox": nox,
}

# ── MAIN ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AURA Decor — Equipe de Agentes")
    parser.add_argument("--agent", type=str, help="ID do agente (ive/rex/luna/etc)")
    parser.add_argument("--task", type=str, help="Descrição da tarefa")
    parser.add_argument("--full", action="store_true", help="Roda ciclo completo da equipe")
    args = parser.parse_args()

    # Notifica bridge
    try:
        httpx.post(f"{BRIDGE_URL}/feed", params={
            "icon": "🚀", "text": "Equipe AURA iniciada — CrewAI + llama3.2", "color": "gold"
        }, timeout=3)
    except Exception:
        pass

    if args.agent and args.task:
        agent_obj = AGENT_MAP.get(args.agent.lower())
        if not agent_obj:
            print(f"Agente '{args.agent}' não encontrado. Opções: {list(AGENT_MAP.keys())}")
            sys.exit(1)
        print(f"\n🤖 Rodando {agent_obj.role} com tarefa:\n{args.task}\n")
        crew = criar_equipe_task_unica(agent_obj, args.task)
        result = crew.kickoff()
        print(f"\n✅ Resultado:\n{result}")

    else:
        print("\n🏮 AURA Decor — Ciclo Completo da Equipe\n" + "="*50)
        crew = criar_equipe_completa()
        result = crew.kickoff()
        print(f"\n✅ Ciclo da AURA finalizado!")
        with open("plano_acao_aura.md", "w", encoding="utf-8") as f:
            f.write(str(result))
        print("📄 Plano salvo em plano_acao_aura.md")
