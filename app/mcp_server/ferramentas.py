"""As ferramentas do servidor MCP. Cada uma chama uma função de app/agente/operacoes.py, a mesma da CLI.

Três tipos, que viram anotações MCP (o cliente pode liberar leituras de vez e pedir confirmação para escrita):
- LEITURA: readOnlyHint;
- ESCRITA: grava, mas dá para desfazer (recategorizar, importar análise…);
- SENSIVEL: destructiveHint; os roteiros dizem para usar só com pedido explícito do usuário.

Todas passam por `Sessao.rodar`, que troca para a base da demonstração quando é o caso, resolve o titular,
registra o uso (para a tela Configurações › IA), faz backup antes da primeira escrita da sessão, grava o nome do
cliente como autor e devolve JSON compacto. Sem `from __future__ import annotations`: o SDK lê as anotações dos
parâmetros para montar o esquema.
"""
import json
import time
from contextlib import nullcontext
from typing import Annotated, Any, Callable, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from app import __version__, agente, db, demo
from app.agente import ROTEIROS, esquemas
from app.agente import operacoes as op
from app.mcp_server import instalar, tarefas
from app.services import household, spending

LEITURA, ESCRITA, SENSIVEL, LONGA = "leitura", "escrita", "sensivel", "longa"
ANOTACOES = {
    LEITURA: ToolAnnotations(read_only_hint=True, open_world_hint=False),
    ESCRITA: ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False),
    SENSIVEL: ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False),
    LONGA: ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True),
}
TIPOS: dict[str, str] = {}  # nome da ferramenta → tipo, preenchido por registrar()
ESPERA_TAREFA = 25  # segundos que atualizar/fundamentos esperam antes de devolver o tarefa_id

# Ferramenta → comando equivalente da CLI (documentação, pasta da IA de transição e teste de paridade)
EQUIVALENTE_CLI: dict[str, str] = {
    "status": "", "roteiro": "", "tarefa_status": "",
    "titulares": "titulares", "carteira_contexto": "carteira contexto", "carteira_posicoes": "carteira posicoes",
    "fundamentos_contexto": "fundamentos contexto TICKER", "fundamentos_atualizar": "fundamentos atualizar",
    "metas_mostrar": "metas mostrar", "metas_definir": "metas definir", "metas_regiao": "metas regiao TICKER REGIAO",
    "gastos_resumo": "gastos resumo", "gastos_listar": "gastos listar", "gastos_categorias": "gastos categorias",
    "gastos_regras": "gastos regras", "gastos_recategorizar": "gastos recategorizar",
    "gastos_criar_regra": "gastos regra", "gastos_remover_regra": "gastos remover-regra ID",
    "gastos_criar_categoria": "gastos criar-categoria", "gastos_excluir_categoria": "gastos excluir-categoria",
    "gastos_restaurar_categoria": "gastos restaurar-categoria",
    "orcamento_mostrar": "orcamento mostrar", "orcamento_contexto": "orcamento contexto",
    "orcamento_definir": "orcamento definir", "orcamento_remover": "orcamento remover",
    "orcamento_importar_recomendacoes": "orcamento importar-recomendacoes ARQUIVO",
    "analise_importar": "analise importar ARQUIVO", "analise_listar": "analise listar", "analise_mostrar": "analise mostrar ID",
    "recomendacoes_importar": "recomendacoes importar ARQUIVO", "recomendacoes_listar": "recomendacoes listar",
    "recomendacoes_mostrar": "recomendacoes mostrar", "alertas_listar": "alertas listar", "alertas_resolver": "alertas resolver ID",
    "backup": "backup", "atualizar_dados": "atualizar",
}

Titular = Annotated[str | None, Field(description="Nome do titular (gestão a dois). Sem ele, vale a casa toda.")]
Aporte = Annotated[float | None, Field(description="Valor do próximo aporte em reais. Sem ele, usa a média de sobra mensal.", ge=0)]


def _json(data: Any) -> CallToolResult:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return CallToolResult(content=[TextContent(type="text", text=text)])


class Sessao:
    """Estado de uma conexão (um processo do servidor por cliente)."""

    def __init__(self, na_demo: bool = False) -> None:
        self.demo = na_demo
        self.backup_feito = False
        self._registrado_em = 0.0

    def _cliente(self, ctx: Context | None) -> tuple[str | None, str | None]:
        try:
            params = ctx.session.client_params if ctx else None
            info = params.client_info if params else None
            return (info.name, info.version) if info else (None, None)
        except Exception:  # noqa: BLE001 - informação opcional
            return None, None

    def autor(self, ctx: Context | None) -> str:
        return self._cliente(ctx)[0] or "agente"

    def _registrar(self, ctx: Context | None) -> None:
        if time.monotonic() - self._registrado_em < 60:
            return
        self._registrado_em = time.monotonic()
        nome, versao = self._cliente(ctx)
        instalar.registrar_uso(nome or "agente", versao, self.demo)

    def contexto(self):
        return demo.active() if self.demo else nullcontext()

    def rodar(self, ctx: Context | None, tipo: str, trabalho: Callable[..., Any], titular: str | None = None,
              usa_titular: bool = False) -> CallToolResult:
        self._registrar(ctx)
        try:
            with self.contexto():
                extra: dict[str, Any] = {}
                if tipo in (ESCRITA, SENSIVEL) and not self.demo and not self.backup_feito:
                    extra["backup_automatico"] = str(db.create_backup())
                    self.backup_feito = True
                if usa_titular:
                    result = trabalho(household.resolve(titular) if titular else None)
                else:
                    result = trabalho()
        except spending.CategoryInUse as exc:
            raise ToolError(json.dumps(op.categoria_em_uso(exc, "repita com destino 'Outros' (ou outra categoria, "
                                                                "ou 'automatica')"), ensure_ascii=False)) from exc
        except op.ERROS as exc:
            raise ToolError(str(exc)) from exc
        if isinstance(result, dict) and result.get("erro") and len(result) == 1:
            raise ToolError(result["erro"])
        if extra and isinstance(result, dict):
            result = {**result, **extra}
        return _json(result)

    async def longa(self, ctx: Context, tipo: str, trabalho: Callable[[Callable[[str], None]], dict[str, Any]]) -> CallToolResult:
        """Inicia a tarefa, informa o progresso enquanto espera e devolve o resultado ou o tarefa_id."""
        self._registrar(ctx)
        with self.contexto():
            tarefa = tarefas.iniciar(tipo, trabalho)
        etapa = None
        for passo in range(ESPERA_TAREFA * 4):
            tarefa = tarefas.obter(tarefa["tarefa_id"])
            if tarefa["situacao"] != "rodando":
                break
            if tarefa["etapa"] != etapa:
                etapa = tarefa["etapa"]
                try:
                    await ctx.report_progress(passo, None, f"Etapa: {etapa}")
                except Exception:  # noqa: BLE001 - progresso é cortesia; nem todo cliente pede
                    pass
            await anyio.sleep(0.25)
        if tarefa["situacao"] == "rodando":
            tarefa["dica"] = "Ainda rodando. Chame tarefa_status com este tarefa_id em alguns segundos."
        return _json(tarefa)


def registrar(server: MCPServer, sessao: Sessao) -> None:  # noqa: C901 - uma lista de ferramentas, de propósito
    def tool(tipo: str, titulo: str):
        def decorator(fn):
            server.add_tool(fn, name=fn.__name__, title=titulo, description=fn.__doc__, annotations=ANOTACOES[tipo])
            TIPOS[fn.__name__] = tipo
            return fn
        return decorator

    # ---------------------------------------------------------------- visão geral

    @tool(LEITURA, "Situação do Tabimoney")
    def status(ctx: Context) -> CallToolResult:
        """Versão do app, se é a demonstração, titulares e quando cada fonte (Open Finance, cotações, CVM) foi
        atualizada. Bom primeiro passo; para saber o que fazer, chame `roteiro`."""
        def trabalho():
            return {"app": "Tabimoney", "versao": __version__, "demonstracao": sessao.demo,
                    "titulares": [m["name"] for m in household.members()],
                    "ultimas_atualizacoes": op.ultimas_atualizacoes(),
                    "roteiros": list(ROTEIROS), "unidades": "reais; percentuais como fração (0.15 = 15%)"}
        return sessao.rodar(ctx, LEITURA, trabalho)

    @tool(LEITURA, "Roteiro de uma tarefa")
    def roteiro(nome: Annotated[Literal[ROTEIROS], Field(description="Qual roteiro.")], ctx: Context) -> CallToolResult:
        """Passo a passo de uma tarefa: visao-geral (qual roteiro usar), ciclo (atualizar tudo), gastos, orcamento,
        metas, analise-trimestral ou recomendacoes. Chame antes de uma tarefa com mais de um passo e siga o texto."""
        return sessao.rodar(ctx, LEITURA, lambda: agente.roteiro(nome))

    @tool(LEITURA, "Titulares e contas")
    def titulares(ctx: Context) -> CallToolResult:
        """Titulares da casa (gestão a dois), as conexões Pluggy (sem segredos) e as contas de cada um."""
        return sessao.rodar(ctx, LEITURA, op.titulares)

    @tool(LEITURA, "Andamento de uma tarefa")
    def tarefa_status(tarefa_id: Annotated[str, Field(description="O tarefa_id devolvido por atualizar_dados ou "
                                                                  "fundamentos_atualizar.")], ctx: Context) -> CallToolResult:
        """Situação de uma tarefa longa: rodando, concluida ou falhou, a etapa atual e o resultado."""
        return sessao.rodar(ctx, LEITURA, lambda: tarefas.obter(tarefa_id))

    # ---------------------------------------------------------------- carteira, metas e fundamentos

    @tool(LEITURA, "Carteira completa")
    def carteira_contexto(ctx: Context, aporte: Aporte = None, titular: Titular = None) -> CallToolResult:
        """Ponto de partida de qualquer tarefa de investimentos: metas e balanço, plano de aporte, posições com
        fundamentos, avisos e a última análise de cada ativo, renda fixa, previdência, caixa e a recomendação anterior."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.carteira_contexto(aporte, member=m), titular, True)

    @tool(LEITURA, "Posições da carteira")
    def carteira_posicoes(ctx: Context, titular: Titular = None) -> CallToolResult:
        """Versão curta da carteira: só as posições, renda fixa e previdência."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.carteira_posicoes(member=m), titular, True)

    @tool(LEITURA, "Contexto de uma empresa")
    def fundamentos_contexto(ticker: Annotated[str, Field(description="Ticker, ex.: EGIE3.")], ctx: Context) -> CallToolResult:
        """Tudo para analisar uma empresa: perfil, indicadores, série trimestral (quarters), links do ITR/DFP na CVM
        (filings), avisos e relatórios anteriores."""
        return sessao.rodar(ctx, LEITURA, lambda: op.fundamentos_contexto(ticker))

    @tool(LEITURA, "Metas de alocação e aporte")
    def metas_mostrar(ctx: Context, aporte: Aporte = None, titular: Titular = None) -> CallToolResult:
        """Metas de alocação, balanço atual, desvios, avisos e para onde vai o aporte (o plano nunca vende)."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.metas_mostrar(aporte, member=m), titular, True)

    @tool(SENSIVEL, "Definir metas de alocação")
    def metas_definir(
        ctx: Context,
        reserva: Annotated[float | None, Field(description="Reserva de emergência em reais.", ge=0)] = None,
        renda_fixa: Annotated[float | None, Field(description="% do investível em renda fixa (0 a 100).", ge=0, le=100)] = None,
        renda_variavel: Annotated[float | None, Field(description="% em renda variável (0 a 100); com renda_fixa soma 100.",
                                                      ge=0, le=100)] = None,
        internacional: Annotated[float | None, Field(description="% da renda variável no exterior (0 a 100).", ge=0, le=100)] = None,
        previdencia: Annotated[bool | None, Field(description="Conta a previdência como renda fixa?")] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Grava as metas de alocação. SÓ com pedido explícito do usuário. O que não for informado fica como está."""
        return sessao.rodar(ctx, SENSIVEL, lambda m: op.metas_definir(reserva, renda_fixa, renda_variavel, internacional,
                                                                       previdencia, member=m), titular, True)

    @tool(ESCRITA, "Corrigir região de um ativo")
    def metas_regiao(ticker: str, regiao: Literal["nacional", "internacional", "automatica"], ctx: Context) -> CallToolResult:
        """Define se um ativo conta como exposição nacional ou internacional ('automatica' desfaz a correção)."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.metas_regiao(ticker, regiao))

    @tool(LONGA, "Atualizar balanços da CVM")
    async def fundamentos_atualizar(
        ctx: Context,
        tickers: Annotated[list[str] | None, Field(description="Só estes tickers; sem eles, a carteira toda.")] = None,
    ) -> CallToolResult:
        """Baixa ITR/DFP da CVM (cache semanal), atualiza preços da brapi e recalcula os avisos. Pode levar minutos:
        se não terminar em ~25 s, devolve tarefa_id para acompanhar com tarefa_status."""
        return await sessao.longa(ctx, "fundamentos", lambda progresso: op.fundamentos_atualizar(tickers))

    # ---------------------------------------------------------------- gastos

    @tool(LEITURA, "Resumo dos gastos")
    def gastos_resumo(ctx: Context, meses: Annotated[int, Field(ge=1, le=36)] = 6, titular: Titular = None) -> CallToolResult:
        """Gasto por categoria mês a mês, o último mês fechado contra a média dos 3 anteriores e os lançamentos que
        puxaram cada mudança."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.gastos_resumo(meses, member=m), titular, True)

    @tool(LEITURA, "Listar lançamentos")
    def gastos_listar(
        ctx: Context,
        mes: Annotated[str | None, Field(description="AAAA-MM.", pattern=r"^\d{4}-\d{2}$")] = None,
        de: Annotated[str | None, Field(description="Data inicial AAAA-MM-DD.")] = None,
        ate: Annotated[str | None, Field(description="Data final AAAA-MM-DD.")] = None,
        categoria: str | None = None,
        busca: Annotated[str | None, Field(description="Texto na descrição (sem caixa nem acento).")] = None,
        conta: Annotated[str | None, Field(description="Parte do nome da conta, ex.: Nubank.")] = None,
        origem: Annotated[Literal["auto", "regra", "manual"] | None, Field(description="De onde veio a categoria.")] = None,
        so_gastos: Annotated[bool, Field(description="Só o que entra em despesas.")] = False,
        limite: Annotated[int, Field(ge=1, le=200)] = 50,
        deslocamento: Annotated[int, Field(ge=0, description="Pula os N primeiros; use o proximo_deslocamento da resposta.")] = 0,
        campos: Annotated[list[str] | None, Field(description="Só estes campos de cada lançamento (o id vem sempre), ex.: "
                                                              "['data','descricao','valor','categoria'].")] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Lançamentos com id, categoria efetiva e automática, do mais recente ao mais antigo. Paginado: se vier
        proximo_deslocamento, há mais."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.gastos_listar(mes, de, ate, categoria, busca, conta, origem,
                                                                      so_gastos, limite, deslocamento, campos, member=m),
                            titular, True)

    @tool(LEITURA, "Categorias")
    def gastos_categorias(ctx: Context) -> CallToolResult:
        """Categorias existentes, o uso de cada uma, as excluídas e as internas (fora de receita e despesa)."""
        return sessao.rodar(ctx, LEITURA, op.gastos_categorias)

    @tool(LEITURA, "Regras de categoria")
    def gastos_regras(ctx: Context) -> CallToolResult:
        """Regras permanentes 'descrição contém X → categoria'."""
        return sessao.rodar(ctx, LEITURA, op.gastos_regras)

    @tool(ESCRITA, "Recategorizar lançamentos")
    def gastos_recategorizar(
        ids: Annotated[list[int], Field(min_length=1, description="ids de gastos_listar.")],
        ctx: Context,
        categoria: str | None = None,
        automatica: Annotated[bool, Field(description="Volta à categoria automática (desfaz a correção).")] = False,
    ) -> CallToolResult:
        """Corrige a categoria de lançamentos específicos. Mais de 20 lançamentos: confirme a lista com o usuário antes."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_recategorizar(ids, categoria, automatica))

    @tool(ESCRITA, "Criar regra de categoria")
    def gastos_criar_regra(
        contem: Annotated[str, Field(description="Texto que a descrição contém, ex.: 'PAGTO SALARIO'.")],
        categoria: str,
        ctx: Context,
        conta: Annotated[str | None, Field(description="Só nesta conta.")] = None,
        nota: Annotated[str | None, Field(description="Motivo da regra.")] = None,
    ) -> CallToolResult:
        """Cria ou atualiza uma regra permanente, que vale para lançamentos antigos e futuros."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_regra(contem, categoria, conta, nota, sessao.autor(ctx)))

    @tool(SENSIVEL, "Remover regra de categoria")
    def gastos_remover_regra(regra_id: Annotated[int, Field(description="id de gastos_regras.")], ctx: Context) -> CallToolResult:
        """Remove uma regra de categoria. SÓ com pedido explícito do usuário."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.gastos_remover_regra(regra_id))

    @tool(ESCRITA, "Criar categoria")
    def gastos_criar_categoria(nome: str, ctx: Context) -> CallToolResult:
        """Cria uma categoria. Idempotente: se já existe em qualquer grafia, devolve a existente com criada: false."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_criar_categoria(nome, sessao.autor(ctx)))

    @tool(SENSIVEL, "Excluir categoria")
    def gastos_excluir_categoria(
        nome: str,
        ctx: Context,
        destino: Annotated[str | None, Field(description="Categoria que recebe lançamentos, regras e metas, ou "
                                                         "'automatica'. Obrigatório se a categoria estiver em uso.")] = None,
    ) -> CallToolResult:
        """Exclui uma categoria própria (as padrão não podem). SÓ com pedido explícito do usuário;
        gastos_restaurar_categoria desfaz."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.gastos_excluir_categoria(nome, destino, sessao.autor(ctx)))

    @tool(ESCRITA, "Restaurar categoria")
    def gastos_restaurar_categoria(nome: str, ctx: Context) -> CallToolResult:
        """Desfaz a exclusão de uma categoria: o que ainda está no destino volta para ela."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_restaurar_categoria(nome))

    # ---------------------------------------------------------------- orçamento

    @tool(LEITURA, "Orçamento do mês")
    def orcamento_mostrar(ctx: Context) -> CallToolResult:
        """Mês corrente contra cada meta de gasto: gasto, projeção, situação, quanto cabe por dia e histórico."""
        return sessao.rodar(ctx, LEITURA, op.orcamento_mostrar)

    @tool(LEITURA, "Contexto do orçamento")
    def orcamento_contexto(ctx: Context, meses: Annotated[int, Field(ge=1, le=24)] = 6) -> CallToolResult:
        """Ponto de partida da análise orçamentária: orçamento, receitas e despesas por mês, gasto por categoria, o que
        mudou, metas sugeridas pela média e a recomendação anterior. Metas de gastos são sempre da casa."""
        return sessao.rodar(ctx, LEITURA, lambda: op.orcamento_contexto(meses))

    @tool(SENSIVEL, "Criar ou ajustar meta de gasto")
    def orcamento_definir(
        nome: str,
        limite: Annotated[float, Field(gt=0, description="Limite mensal em reais.")],
        ctx: Context,
        categorias: Annotated[list[str] | None, Field(description="Categorias da meta (nomes de gastos_categorias).")] = None,
        total: Annotated[bool, Field(description="Meta de todos os gastos do mês.")] = False,
        aviso: Annotated[float | None, Field(description="% do limite que dispara o aviso (padrão 80).", gt=0, le=100)] = None,
        nota: str | None = None,
    ) -> CallToolResult:
        """Cria ou atualiza uma meta de gasto. SÓ com pedido explícito do usuário; para sugerir, use
        orcamento_importar_recomendacoes (o usuário aplica com um clique)."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.orcamento_definir(nome, limite, categorias, total, aviso, nota,
                                                                         sessao.autor(ctx)))

    @tool(SENSIVEL, "Remover meta de gasto")
    def orcamento_remover(nome: str, ctx: Context) -> CallToolResult:
        """Remove uma meta de gasto. SÓ com pedido explícito do usuário."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.orcamento_remover(nome))

    @tool(ESCRITA, "Gravar recomendações de orçamento")
    def orcamento_importar_recomendacoes(conjunto: esquemas.ConjuntoOrcamento, ctx: Context) -> CallToolResult:
        """Grava as recomendações orçamentárias do mês (aparecem com botão Aplicar). Reenviar o mesmo mês substitui.
        Um item inválido recusa o lote inteiro. Exemplo: resource tabimoney://exemplos/orcamento."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.orcamento_importar(conjunto.dados(), sessao.autor(ctx)))

    # ---------------------------------------------------------------- análises, recomendações e avisos

    @tool(ESCRITA, "Gravar análises")
    def analise_importar(
        relatorios: Annotated[list[esquemas.ItemAnalise], Field(min_length=1, description="Um relatório por ativo e trimestre.")],
        ctx: Context,
    ) -> CallToolResult:
        """Grava relatórios de análise, métricas e avisos. Regravar o mesmo assunto, período e autor substitui; os
        trimestres anteriores ficam no histórico. Um item inválido recusa o lote inteiro. Exemplo: resource
        tabimoney://exemplos/analise-trimestral; modelo: tabimoney://docs/modelo-relatorio-trimestral."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.analise_importar([r.dados() for r in relatorios], sessao.autor(ctx)))

    @tool(LEITURA, "Listar análises")
    def analise_listar(
        ctx: Context,
        ticker: str | None = None,
        tipo: Literal["ativo", "renda_fixa", "previdencia", "carteira"] | None = None,
        limite: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> CallToolResult:
        """Relatórios guardados, sem o corpo (para o texto completo, analise_mostrar)."""
        return sessao.rodar(ctx, LEITURA, lambda: op.analise_listar(ticker, tipo, limite))

    @tool(LEITURA, "Mostrar análise")
    def analise_mostrar(relatorio_id: int, ctx: Context) -> CallToolResult:
        """Relatório completo, para comparar com o trimestre anterior."""
        return sessao.rodar(ctx, LEITURA, lambda: op.analise_mostrar(relatorio_id))

    @tool(ESCRITA, "Gravar recomendações do trimestre")
    def recomendacoes_importar(conjunto: esquemas.ConjuntoRecomendacoes, ctx: Context) -> CallToolResult:
        """Grava as recomendações trimestrais (mudanças na carteira e carteiras-modelo). Reenviar o mesmo período
        substitui; os anteriores ficam no histórico. Exemplo: resource tabimoney://exemplos/recomendacoes."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.recomendacoes_importar(conjunto.dados(), sessao.autor(ctx)))

    @tool(LEITURA, "Histórico de recomendações")
    def recomendacoes_listar(ctx: Context) -> CallToolResult:
        """Conjuntos de recomendações gravados, do mais recente ao mais antigo."""
        return sessao.rodar(ctx, LEITURA, op.recomendacoes_listar)

    @tool(LEITURA, "Mostrar recomendação")
    def recomendacoes_mostrar(ctx: Context, recomendacao_id: Annotated[int | None, Field(description="Sem ele, a mais recente.")] = None) -> CallToolResult:
        """Um conjunto de recomendações completo."""
        return sessao.rodar(ctx, LEITURA, lambda: op.recomendacoes_mostrar(recomendacao_id))

    @tool(LEITURA, "Avisos")
    def alertas_listar(ctx: Context, todos: Annotated[bool, Field(description="Inclui os já vistos.")] = False) -> CallToolResult:
        """Avisos de fundamentos (regras automáticas e os gravados pelo agente)."""
        return sessao.rodar(ctx, LEITURA, lambda: op.alertas_listar(todos))

    @tool(ESCRITA, "Marcar avisos como vistos")
    def alertas_resolver(ids: Annotated[list[int], Field(min_length=1)], ctx: Context) -> CallToolResult:
        """Marca avisos como vistos (ids de alertas_listar). Eles saem da lista padrão, mas continuam no histórico."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.alertas_resolver(ids))

    # ---------------------------------------------------------------- backup e atualização

    @tool(ESCRITA, "Backup")
    def backup(ctx: Context) -> CallToolResult:
        """Cópia da base. O servidor já faz uma antes da primeira mudança da sessão; use antes de mudanças em massa."""
        def trabalho():
            if sessao.demo:
                raise ValueError("Na demonstração, o backup fica desligado: não há dados de verdade.")
            sessao.backup_feito = True
            return op.backup()
        return sessao.rodar(ctx, LEITURA, trabalho)  # LEITURA: não dispara o backup automático antes do próprio backup

    @tool(LONGA, "Atualizar todos os dados")
    async def atualizar_dados(ctx: Context) -> CallToolResult:
        """Backup + Open Finance + cotações e CDI + balanços da CVM, em ordem; uma etapa com falha não impede as
        outras. Pode levar minutos: se não terminar em ~25 s, devolve tarefa_id para acompanhar com tarefa_status."""
        if sessao.demo:
            raise ToolError("Na demonstração, atualizar fica desligado: não há dados de verdade.")
        return await sessao.longa(ctx, "atualizar", lambda progresso: op.atualizar(progresso))
