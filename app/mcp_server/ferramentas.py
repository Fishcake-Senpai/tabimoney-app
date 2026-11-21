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
    "perfil_investidor": "perfil mostrar", "perfil_definir": "perfil definir HORIZONTE OBJETIVO",
    "gastos_resumo": "gastos resumo", "gastos_listar": "gastos listar", "gastos_categorias": "gastos categorias",
    "gastos_regras": "gastos regras", "gastos_recategorizar": "gastos recategorizar",
    "gastos_criar_regra": "gastos regra", "gastos_remover_regra": "gastos remover-regra ID",
    "gastos_criar_categoria": "gastos criar-categoria", "gastos_excluir_categoria": "gastos excluir-categoria",
    "gastos_restaurar_categoria": "gastos restaurar-categoria", "relatorio_exportar": "relatorio exportar",
    "gastos_criar_lancamento": "gastos criar-lancamento", "gastos_editar_lancamento": "gastos editar-lancamento",
    "gastos_ignorar": "gastos ignorar", "gastos_exportar_csv": "gastos exportar-csv",
    "importacao_desfazer": "importacao desfazer ID", "pendencia_dispensar": "pendencia dispensar TIPO CHAVE",
    "contas_fixas_listar": "contas-fixas listar", "contas_fixas_salvar": "contas-fixas salvar",
    "contas_fixas_remover": "contas-fixas remover ID",
    "orcamento_mostrar": "orcamento mostrar", "orcamento_contexto": "orcamento contexto",
    "orcamento_definir": "orcamento definir", "orcamento_remover": "orcamento remover",
    "orcamento_importar_recomendacoes": "orcamento importar-recomendacoes ARQUIVO",
    "analise_importar": "analise importar ARQUIVO", "analise_listar": "analise listar", "analise_mostrar": "analise mostrar ID",
    "recomendacoes_importar": "recomendacoes importar ARQUIVO", "recomendacoes_listar": "recomendacoes listar",
    "recomendacoes_mostrar": "recomendacoes mostrar", "alertas_listar": "alertas listar", "alertas_resolver": "alertas resolver ID",
    "backup": "backup", "atualizar_dados": "atualizar",
    "ir_contexto": "ir contexto", "ir_acoes": "ir acoes", "ir_estimativa": "ir estimativa", "ir_declaracao": "ir declaracao",
    "ir_fonte_salvar": "ir fonte", "ir_dependente_salvar": "ir dependente", "ir_previdencia_oficial": "ir previdencia-oficial",
    "ir_deducao_marcar": "ir deducao", "ir_deducao_adicionar": "ir deducao-manual",
    "ir_pendencia_resolver": "ir pendencia TIPO", "previdencia_aporte_registrar": "previdencia aporte PLANO DATA VALOR",
    "patrimonio_contexto": "patrimonio contexto", "patrimonio_salvar": "patrimonio salvar",
    "patrimonio_remover": "patrimonio remover ID", "patrimonio_simular_avaliacao": "patrimonio simular ID",
    "patrimonio_registrar_avaliacao": "patrimonio avaliar ID",
}
Ano = Annotated[int | None, Field(description="Ano-calendário (padrão: o ano atual).", ge=2020, le=2100)]

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
        metas, analise-trimestral, recomendacoes ou imposto-renda. Chame antes de uma tarefa com mais de um passo e siga o texto."""
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

    @tool(LEITURA, "Perfil do investidor")
    def perfil_investidor(ctx: Context, titular: Titular = None) -> CallToolResult:
        """Horizonte e objetivo do investidor. Se `configurado` for false ou `vencido` for true, pergunte ao usuário
        antes de qualquer análise de investimento e grave com perfil_definir."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.perfil_investidor(member=m), titular, True)

    @tool(ESCRITA, "Gravar perfil do investidor")
    def perfil_definir(
        ctx: Context,
        horizonte: Annotated[Literal["menos-de-5", "5-10", "10-20", "mais-de-20"],
                             Field(description="Por quanto tempo o dinheiro fica investido, em anos, na resposta do usuário.")],
        objetivo: Annotated[Literal["renda", "crescimento", "os-dois"],
                            Field(description="Objetivo da renda variável: renda passiva, crescimento do patrimônio ou os dois.")],
        titular: Titular = None,
    ) -> CallToolResult:
        """Grava o horizonte e o objetivo que o USUÁRIO respondeu. Nunca invente: pergunte antes."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.perfil_definir(horizonte, objetivo, member=m), titular, True)

    @tool(LONGA, "Atualizar balanços da CVM")
    async def fundamentos_atualizar(
        ctx: Context,
        tickers: Annotated[list[str] | None, Field(description="Só estes tickers; sem eles, a carteira toda.")] = None,
    ) -> CallToolResult:
        """Baixa ITR/DFP da CVM (cache semanal), atualiza valor de mercado (brapi; sem ela, cotação guardada × ações da CVM) e recalcula os avisos. Pode levar minutos:
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

    @tool(ESCRITA, "Exportar relatório")
    def relatorio_exportar(
        ctx: Context,
        periodo: Annotated[Literal["mes", "trimestre", "ano"], Field(description="Tamanho do período.")] = "mes",
        referencia: Annotated[str | None, Field(description="AAAA-MM (mês), AAAA-T1..T4 (trimestre) ou AAAA (ano); "
                                                            "um mês também serve para trimestre e ano. Sem ela, o atual.")] = None,
        arquivo: Annotated[str | None, Field(description="Caminho do .html. Sem ele, a pasta Relatorios dos dados do app.")] = None,
        mascarar: Annotated[bool, Field(description="Mascara números de conta e nomes de pessoas em Pix.")] = True,
        extrato: Annotated[bool, Field(description="Inclui todos os lançamentos do período no fim.")] = True,
        titular: Titular = None,
    ) -> CallToolResult:
        """Grava o relatório do período num arquivo HTML que abre sozinho, offline: resumo, categorias contra a média,
        orçamento, ritmo, maiores gastos, contas fixas, parcelas a vencer, receitas, patrimônio e extrato. Devolve o
        caminho e os números principais; não manda o arquivo a lugar nenhum."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.relatorio_exportar(periodo, referencia, arquivo, mascarar, extrato,
                                                                          member=m), titular, True)

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

    @tool(ESCRITA, "Criar lançamento manual")
    def gastos_criar_lancamento(
        data: Annotated[str, Field(description="Data AAAA-MM-DD.")],
        descricao: str,
        valor: Annotated[float, Field(gt=0, description="Valor em reais (positivo).")],
        ctx: Context,
        tipo: Literal["saida", "entrada"] = "saida",
        conta: Annotated[str | None, Field(description="Nome da conta ou 'dinheiro' (padrão).")] = None,
        categoria: str | None = None,
        nota: str | None = None,
        fora_do_resultado: Annotated[bool, Field(description="Conta no saldo, mas fica fora de receitas e despesas.")] = False,
        titular: Titular = None,
    ) -> CallToolResult:
        """Registra um lançamento à mão (dinheiro vivo, reembolso ou ajuste)."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.gastos_criar_lancamento(
            data, descricao, valor, tipo, conta, categoria, nota, fora_do_resultado, member=m, autor=sessao.autor(ctx)),
            titular, True)

    @tool(ESCRITA, "Editar lançamento")
    def gastos_editar_lancamento(
        lancamento_id: Annotated[int, Field(description="id de gastos_listar.")],
        ctx: Context,
        data: str | None = None,
        descricao: str | None = None,
        valor: Annotated[float | None, Field(gt=0, description="Valor em reais (positivo).")] = None,
        tipo: Literal["saida", "entrada"] | None = None,
        categoria: str | None = None,
        nota: str | None = None,
        ignorado: bool | None = None,
        fora_do_resultado: bool | None = None,
    ) -> CallToolResult:
        """Edita descrição, data, valor, categoria, nota ou flags de um lançamento existente."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_editar_lancamento(
            lancamento_id, data, descricao, valor, tipo, categoria, nota, ignorado, fora_do_resultado, autor=sessao.autor(ctx)))

    @tool(ESCRITA, "Ignorar ou tirar lançamentos do resultado")
    def gastos_ignorar(
        ids: Annotated[list[int], Field(min_length=1, description="ids de gastos_listar.")],
        ctx: Context,
        ignorado: Annotated[bool | None, Field(description="Some de saldos e relatórios.")] = None,
        fora_do_resultado: Annotated[bool | None, Field(description="Conta no saldo, sai de receitas e despesas.")] = None,
    ) -> CallToolResult:
        """Marca ou desmarca lançamentos como ignorados ou fora do resultado."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.gastos_ignorar(ids, ignorado, fora_do_resultado))

    @tool(ESCRITA, "Exportar lançamentos em CSV")
    def gastos_exportar_csv(
        ctx: Context,
        arquivo: Annotated[str | None, Field(description="Caminho do .csv. Sem ele, salva na pasta Relatorios.")] = None,
        categoria: str | None = None,
        busca: str | None = None,
        incluir_ignorados: bool = False,
        titular: Titular = None,
    ) -> CallToolResult:
        """Exporta os lançamentos em CSV local (UTF-8 com BOM, separador ';')."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.gastos_exportar_csv(
            arquivo, categoria, busca, incluir_ignorados, member=m), titular, True)

    @tool(SENSIVEL, "Desfazer importação")
    def importacao_desfazer(
        run_id: Annotated[int, Field(description="id da importação em sync_run.")],
        ctx: Context,
    ) -> CallToolResult:
        """Desfaz uma importação inteira, removendo o lote gravado. SÓ com pedido explícito do usuário."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.importacao_desfazer(run_id))

    @tool(ESCRITA, "Dispensar pendência")
    def pendencia_dispensar(
        tipo: Literal["transfer_orphan", "position", "bank"],
        chave: Annotated[str, Field(description="id do lançamento (transfer_orphan), conta|ticker (position) ou conta (bank).")],
        ctx: Context,
    ) -> CallToolResult:
        """Dispensa uma pendência de conciliação para que não seja sugerida novamente."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.pendencia_dispensar(tipo, chave))

    @tool(LEITURA, "Listar contas fixas")
    def contas_fixas_listar(
        ctx: Context,
        mes: Annotated[str | None, Field(description="AAAA-MM (padrão: mês atual).", pattern=r"^\d{4}-\d{2}$")] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Lista as contas fixas cadastradas e a agenda do mês (pago, pendente, atrasado) após baixa automática."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.contas_fixas_listar(mes, member=m), titular, True)

    @tool(ESCRITA, "Salvar conta fixa")
    def contas_fixas_salvar(
        descricao: str,
        valor: Annotated[float, Field(gt=0, description="Valor em reais.")],
        ctx: Context,
        frequencia: Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"] = "monthly",
        tipo: Literal["saida", "entrada"] = "saida",
        conta: str | None = None,
        categoria: str | None = None,
        dia: Annotated[int | None, Field(ge=1, le=31)] = None,
        inicio: str | None = None,
        fim: str | None = None,
        dia_util: bool = True,
        padrao: Annotated[str | None, Field(description="Texto no extrato para casar a baixa automática.")] = None,
        conta_fixa_id: int | None = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Cria ou atualiza uma conta fixa com baixa automática no extrato."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.contas_fixas_salvar(
            descricao, valor, frequencia, tipo, conta, categoria, dia, inicio, fim, dia_util, padrao, conta_fixa_id,
            member=m, autor=sessao.autor(ctx)), titular, True)

    @tool(SENSIVEL, "Remover conta fixa")
    def contas_fixas_remover(conta_fixa_id: int, ctx: Context) -> CallToolResult:
        """Remove uma conta fixa cadastrada. SÓ com pedido explícito do usuário."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.contas_fixas_remover(conta_fixa_id))

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

    # ---------------------------------------------------------------- imposto de renda

    @tool(LEITURA, "Imposto de renda do ano")
    def ir_contexto(ctx: Context, ano: Ano = None, titular: Titular = None) -> CallToolResult:
        """Ponto de partida do roteiro imposto-renda: perfil fiscal (fontes, dependentes), estimativa nos modelos
        completo e simplificado, PGBL que falta, apuração da bolsa (DARFs, prejuízos, pendências), deduções marcadas e
        sugeridas, previdência e o aviso de regras desatualizadas. O IR é por pessoa: sem titular, vale o principal."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.ir_contexto(ano, member=m), titular, True)

    @tool(LEITURA, "Apuração da bolsa")
    def ir_acoes(ctx: Context, ano: Ano = None, titular: Titular = None) -> CallToolResult:
        """Vendas em bolsa do ano mês a mês: preço médio por titular (todas as corretoras), isenção de R$ 20 mil,
        prejuízo compensado, imposto, IRRF, DARF e vencimento; bens e direitos em 31/12; proventos; pendências."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.ir_acoes(ano, member=m), titular, True)

    @tool(LEITURA, "Estimativa do IR")
    def ir_estimativa(
        ctx: Context, ano: Ano = None,
        pgbl_extra: Annotated[float | None, Field(description="Simula um aporte extra no PGBL, em reais.", ge=0)] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Imposto do ano nos dois modelos, o melhor, restituição ou saldo a pagar, limite do PGBL, quanto falta e
        quanto completar economiza (contra o melhor modelo), dividendos retidos, IRPFM e conciliação do salário."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.ir_estimativa(ano, pgbl_extra, member=m), titular, True)

    @tool(LEITURA, "Passo a passo da declaração")
    def ir_declaracao(
        ctx: Context,
        ano: Annotated[int | None, Field(description="Ano-calendário declarado (padrão: o ano passado).", ge=2020, le=2100)] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """O que preencher em cada ficha do programa da Receita, na ordem do programa, e o checklist de documentos."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.ir_declaracao(ano, member=m), titular, True)

    @tool(ESCRITA, "Gravar fonte de renda")
    def ir_fonte_salvar(
        ctx: Context,
        tipo: Annotated[Literal["clt", "pro_labore", "outro"], Field(description="Salário CLT, pró-labore (PJ) ou outro tributável.")],
        pagador: Annotated[str, Field(description="Empregador, a empresa do sócio ou a fonte.")],
        bruto_mensal: Annotated[float | None, Field(description="Salário ou pró-labore BRUTO por mês, em reais.", ge=0)] = None,
        ano: Ano = None,
        cnpj: str | None = None,
        mes_inicio: Annotated[int, Field(ge=1, le=12)] = 1,
        mes_fim: Annotated[int, Field(ge=1, le=12)] = 12,
        decimo_terceiro: bool | None = None,
        mes_ferias: Annotated[int | None, Field(ge=1, le=12, description="Mês das férias (soma 1/3).")] = None,
        inss_mensal: Annotated[float | None, Field(ge=0, description="INSS do holerite; sem ele, calcula.")] = None,
        irrf_ano: Annotated[float | None, Field(ge=0, description="IRRF do ano no informe; sem ele, calcula.")] = None,
        pensao_em_folha: Annotated[float | None, Field(ge=0)] = None,
        faturamento_mensal: Annotated[float | None, Field(ge=0, description="PJ: faturamento médio da empresa.")] = None,
        regime: Literal["simples_fator_r", "simples_iii", "simples_v", "outro"] | None = None,
        lucro_mensal: Annotated[float | None, Field(ge=0, description="PJ: lucro distribuído por mês.")] = None,
        fonte_id: Annotated[int | None, Field(description="Para corrigir ou remover uma fonte existente.")] = None,
        remover: bool = False,
        titular: Titular = None,
    ) -> CallToolResult:
        """Cria, corrige ou remove uma fonte de renda do perfil fiscal. Só com valores que o USUÁRIO informou
        (holerite, informe de rendimentos); nunca invente o bruto a partir do líquido do extrato."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.ir_fonte(
            ano, tipo, pagador, bruto_mensal, cnpj, mes_inicio, mes_fim, decimo_terceiro, mes_ferias, inss_mensal, irrf_ano,
            pensao_em_folha, faturamento_mensal, regime, lucro_mensal, fonte_id, remover, member=m, autor=sessao.autor(ctx)),
            titular, True)

    @tool(ESCRITA, "Gravar dependente")
    def ir_dependente_salvar(
        ctx: Context, ano: Ano = None, nome: str | None = None,
        parentesco: Literal["filho", "cônjuge", "companheiro", "enteado", "pai/mãe", "outro"] = "filho",
        nascimento: Annotated[int | None, Field(ge=1900, le=2100, description="Ano de nascimento.")] = None,
        remover_id: int | None = None, titular: Titular = None,
    ) -> CallToolResult:
        """Inclui (nome) ou remove (remover_id) um dependente do ano. O CPF não é guardado."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.ir_dependente(ano, nome, parentesco, nascimento, remover_id, member=m),
                            titular, True)

    @tool(ESCRITA, "Contribui para a previdência oficial")
    def ir_previdencia_oficial(
        ctx: Context,
        contribui: Annotated[bool | None, Field(description="true: contribui para INSS/regime próprio ou é aposentado. "
                                                            "null: deduz pelas fontes de renda.")],
        ano: Ano = None, titular: Titular = None,
    ) -> CallToolResult:
        """Condição do PGBL: sem contribuir para a previdência oficial (nem ser aposentado por ela), o PGBL não deduz."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.ir_previdencia_oficial(ano, contribui, member=m), titular, True)

    @tool(ESCRITA, "Marcar despesas dedutíveis")
    def ir_deducao_marcar(
        ctx: Context,
        ids: Annotated[list[int] | None, Field(description="Ids de lançamentos (gastos_listar).")] = None,
        tipo: Literal["saude", "educacao", "pensao", "doacao", "nenhuma"] | None = None,
        categoria: Annotated[str | None, Field(description="Sem ids: dá o tipo à categoria inteira (sem tipo, tira).")] = None,
        beneficiario: Annotated[str, Field(description="'titular' ou 'dep:<id>' de um dependente.")] = "titular",
        prestador: str | None = None,
        documento: Annotated[str | None, Field(description="CPF ou CNPJ do prestador.")] = None,
        subtipo: str | None = None,
        reembolso: Annotated[float | None, Field(ge=0)] = None,
        pela_categoria: Annotated[bool, Field(description="Volta os lançamentos para a regra da categoria.")] = False,
    ) -> CallToolResult:
        """Marca lançamentos ou uma categoria como dedução do IR. Farmácia, academia e curso livre NÃO deduzem: na
        dúvida, pergunte ao usuário. 'nenhuma' tira um lançamento das deduções."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.ir_deducao_marcar(ids, tipo, categoria, beneficiario, prestador, documento,
                                                                        subtipo, reembolso, pela_categoria, sessao.autor(ctx)))

    @tool(ESCRITA, "Despesa dedutível fora do extrato")
    def ir_deducao_adicionar(
        ctx: Context,
        data: Annotated[str | None, Field(description="AAAA-MM-DD do pagamento.")] = None,
        tipo: Literal["saude", "educacao", "pensao", "doacao"] | None = None,
        valor: Annotated[float | None, Field(gt=0)] = None,
        prestador: str | None = None, documento: str | None = None, beneficiario: str = "titular",
        subtipo: str | None = None, reembolso: Annotated[float | None, Field(ge=0)] = None, nota: str | None = None,
        remover_id: int | None = None, titular: Titular = None,
    ) -> CallToolResult:
        """Registra (ou remove, com remover_id) despesa dedutível paga fora das contas do app."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.ir_deducao_adicionar(
            data, tipo, valor, prestador, documento, beneficiario, subtipo, reembolso, nota, remover_id, member=m,
            autor=sessao.autor(ctx)), titular, True)

    @tool(ESCRITA, "Resolver pendência da bolsa")
    def ir_pendencia_resolver(
        ctx: Context,
        tipo: Literal["classe", "custo_bonificacao", "prejuizo_anterior", "irrf", "taxa", "darf_pago"],
        ticker: str | None = None,
        classe: Literal["acao", "unit", "bdr", "etf", "etf_rf", "fii", "fiagro", "outro"] | None = None,
        valor: Annotated[float | None, Field(ge=0, description="Em reais (custo por ação, prejuízo, IRRF, taxa, DARF).")] = None,
        periodo: Annotated[str | None, Field(description="AAAA (prejuízo anterior) ou AAAA-MM (irrf, taxa, darf_pago).")] = None,
        grupo: Literal["comum", "day_trade", "fii"] | None = None,
        conta: Annotated[str | None, Field(description="Conta da corretora (taxa).")] = None,
        ref_id: Annotated[int | None, Field(description="Evento da bonificação (o ref da pendência).")] = None,
        pago_em: str | None = None, titular: Titular = None,
    ) -> CallToolResult:
        """Resolve o que a apuração não sabe sozinha: classe de um ticker 11 (FII, ETF ou unit), custo da bonificação,
        prejuízo de antes do histórico (valor 0 = não tem), IRRF da nota, taxas do mês ou DARF pago."""
        return sessao.rodar(ctx, ESCRITA, lambda m: op.ir_pendencia_resolver(
            tipo, ticker, classe, valor, periodo, grupo, conta, ref_id, pago_em, member=m, autor=sessao.autor(ctx)),
            titular, True)

    @tool(ESCRITA, "Registrar aporte de previdência")
    def previdencia_aporte_registrar(
        ctx: Context,
        plano: Annotated[str, Field(description="Nome do plano (como em carteira_contexto) ou product_key.")],
        data: Annotated[str, Field(description="AAAA-MM-DD.")],
        valor: Annotated[float, Field(gt=0)],
        pagador: Annotated[Literal["participante", "empresa"], Field(description="Só o do participante deduz no PGBL.")] = "participante",
        folha: Annotated[bool, Field(description="Descontado em folha.")] = False,
        repetir_ate_dezembro: Annotated[bool, Field(description="Mesmo valor todo mês até dezembro.")] = False,
    ) -> CallToolResult:
        """Registra aportes de previdência dizendo quem pagou: o participante (deduz no PGBL até 12%) ou a empresa
        (não deduz, mas soma no plano)."""
        return sessao.rodar(ctx, ESCRITA, lambda: op.previdencia_aporte(plano, data, valor, pagador, folha,
                                                                         repetir_ate_dezembro, sessao.autor(ctx)))

    # ---------------------------------------------------------------- patrimônio (bens físicos)

    @tool(LEITURA, "Contexto de patrimônio (bens físicos)")
    def patrimonio_contexto(ctx: Context, titular: Titular = None) -> CallToolResult:
        """Lista todos os imóveis, veículos e outros bens cadastrados, última avaliação, estimativas anuais
        (IPTU, IPVA, seguro, aluguel), CDI de referência e peso no patrimônio total. Comece por aqui no roteiro patrimonio."""
        return sessao.rodar(ctx, LEITURA, lambda m: op.patrimonio_contexto(member=m), titular, True)

    @tool(ESCRITA, "Cadastrar ou atualizar bem físico")
    def patrimonio_salvar(
        ctx: Context,
        nome: Annotated[str, Field(description="Nome do bem (ex.: 'Casa Condomínio Jardins', 'Corolla XEi 2022').")],
        tipo: Literal["imovel", "veiculo", "outro"],
        subtipo: Annotated[str, Field(description="Imóvel: casa_rua, casa_condominio, apartamento, terreno, comercial. Veículo: carro, moto, utilitario.")] = "",
        valor_atual: Annotated[float, Field(ge=0, description="Valor atual estimado em reais.")] = 0,
        valor_aquisicao: Annotated[float, Field(ge=0, description="Valor pago na compra em reais.")] = 0,
        data_aquisicao: Annotated[str | None, Field(description="Data da compra AAAA-MM-DD.")] = None,
        metodo: Literal["manual", "regra", "ia"] = "manual",
        taxa_valorizacao: Annotated[float, Field(description="Taxa da regra em fração (0.06 = +6%, -0.10 = -10%).")] = 0.0,
        periodo_valorizacao: Literal["mensal", "anual"] = "anual",
        detalhes: Annotated[dict[str, Any] | None, Field(description="Atributos: bairro, cidade, uf, area_construida_m2, area_terreno_m2, quartos, vagas, padrao, conservacao, uso; ou marca, modelo, versao, ano, codigo_fipe, uf, km.")] = None,
        imposto_anual: Annotated[float, Field(ge=0, description="IPTU ou IPVA anual estimado em reais.")] = 0,
        seguro_anual: Annotated[float, Field(ge=0, description="Seguro anual estimado em reais.")] = 0,
        aluguel_mensal: Annotated[float, Field(ge=0, description="Aluguel mensal potencial ou atual em reais.")] = 0,
        manutencao_anual: Annotated[float, Field(ge=0, description="Manutenção anual estimada em reais.")] = 0,
        nota: str | None = None,
        bem_id: Annotated[int | None, Field(description="ID existente para editar; sem ele, cria um bem novo.")] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Cadastra ou atualiza um imóvel, veículo ou outro bem físico no Tabimoney."""
        return sessao.rodar(
            ctx, ESCRITA,
            lambda m: op.patrimonio_salvar(
                nome=nome, tipo=tipo, subtipo=subtipo, valor_atual=valor_atual, valor_aquisicao=valor_aquisicao,
                data_aquisicao=data_aquisicao, metodo=metodo, taxa_valorizacao=taxa_valorizacao,
                periodo_valorizacao=periodo_valorizacao, detalhes=detalhes, imposto_anual=imposto_anual,
                seguro_anual=seguro_anual, aluguel_mensal=aluguel_mensal, manutencao_anual=manutencao_anual,
                nota=nota, bem_id=bem_id, member=m, autor=sessao.autor(ctx),
            ),
            titular, True,
        )

    @tool(SENSIVEL, "Remover bem físico")
    def patrimonio_remover(ctx: Context, bem_id: Annotated[int, Field(gt=0, description="ID do bem a remover.")]) -> CallToolResult:
        """Remove (soft-delete) um bem físico do patrimônio. Só use com pedido explícito do usuário."""
        return sessao.rodar(ctx, SENSIVEL, lambda: op.patrimonio_remover(bem_id))

    @tool(LEITURA, "Simular avaliação de bem (NBR 14653-2 / FIPE)")
    def patrimonio_simular_avaliacao(
        ctx: Context,
        bem_id: Annotated[int, Field(gt=0, description="ID do bem cadastrado.")],
        comparaveis_venda: Annotated[list[dict[str, Any]] | None, Field(description="Imóvel: lista de anúncios/transações de venda com preco, area_construida_m2 (ou area_terreno_m2), fonte, url, tipo_dado ('oferta'|'transacao'), padrao, conservacao, fator_localizacao.")] = None,
        comparaveis_aluguel: Annotated[list[dict[str, Any]] | None, Field(description="Imóvel: lista opcional de comparáveis de aluguel mensal.")] = None,
        fontes_fipe: Annotated[list[dict[str, Any]] | None, Field(description="Veículo: lista de consultas FIPE com fonte, preco, mes_referencia, url.")] = None,
        aluguel_mensal: Annotated[float | None, Field(ge=0, description="Imóvel: aluguel mensal em reais (se não passou comparaveis_aluguel).")] = None,
        iptu_anual: Annotated[float | None, Field(ge=0, description="Imóvel: IPTU anual em reais.")] = None,
        seguro_anual: Annotated[float | None, Field(ge=0, description="Seguro anual em reais.")] = None,
        manutencao_anual: Annotated[float | None, Field(ge=0, description="Manutenção anual em reais.")] = None,
        ipva_aliquota: Annotated[float | None, Field(ge=0, le=0.2, description="Veículo: sobrescreve alíquota padrão da UF (ex.: 0.04 = 4%).")] = None,
        titular: Titular = None,
    ) -> CallToolResult:
        """Cálculo puro (sem gravar) de homogeneização NBR 14653-2 para imóveis (fator de oferta, área, terreno,
        padrão, conservação, expurgo de outliers, faixa e confiança) ou consenso FIPE + IPVA + TCO para veículos.
        Use sempre antes de patrimonio_registrar_avaliacao."""
        return sessao.rodar(
            ctx, LEITURA,
            lambda m: op.patrimonio_simular_avaliacao(
                bem_id=bem_id, comparaveis_venda=comparaveis_venda, comparaveis_aluguel=comparaveis_aluguel,
                fontes_fipe=fontes_fipe, aluguel_mensal=aluguel_mensal, iptu_anual=iptu_anual,
                seguro_anual=seguro_anual, manutencao_anual=manutencao_anual, ipva_aliquota=ipva_aliquota,
                member=m,
            ),
            titular, True,
        )

    @tool(ESCRITA, "Registrar avaliação de bem")
    def patrimonio_registrar_avaliacao(
        ctx: Context,
        bem_id: Annotated[int, Field(gt=0, description="ID do bem avaliado.")],
        valor: Annotated[float, Field(gt=0, description="Valor central em reais (da simulação).")],
        valor_piso: Annotated[float | None, Field(ge=0, description="Limite inferior da faixa em reais.")] = None,
        valor_teto: Annotated[float | None, Field(ge=0, description="Limite superior da faixa em reais.")] = None,
        confianca: Literal["alta", "media", "baixa", "insuficiente"] | None = None,
        comparaveis: Annotated[list[dict[str, Any]] | None, Field(description="Lista de comparáveis homogeneizados ou fontes FIPE.")] = None,
        kpis: Annotated[dict[str, Any] | None, Field(description="Dicionário de KPIs devolvido por patrimonio_simular_avaliacao.")] = None,
        fontes: Annotated[list[dict[str, Any]] | None, Field(description="Fontes consultadas [{titulo, url, data}].")] = None,
        relatorio_md: Annotated[str, Field(description="Laudo completo em Markdown seguindo modelo-relatorio-patrimonio.")] = "",
        imposto_anual: Annotated[float | None, Field(ge=0, description="IPTU ou IPVA anual estimado em reais.")] = None,
        seguro_anual: Annotated[float | None, Field(ge=0, description="Seguro anual estimado em reais.")] = None,
        aluguel_mensal: Annotated[float | None, Field(ge=0, description="Aluguel mensal estimado em reais.")] = None,
        manutencao_anual: Annotated[float | None, Field(ge=0, description="Manutenção anual estimada em reais.")] = None,
        data: Annotated[str | None, Field(description="Data da avaliação AAAA-MM-DD (padrão: hoje).")] = None,
    ) -> CallToolResult:
        """Grava a avaliação de mercado de um imóvel ou veículo (valor, faixa, comparáveis, KPIs, custos anuais e
        laudo em Markdown) no histórico e atualiza o valor corrente do bem."""
        return sessao.rodar(
            ctx, ESCRITA,
            lambda: op.patrimonio_registrar_avaliacao(
                bem_id=bem_id, valor=valor, valor_piso=valor_piso, valor_teto=valor_teto, confianca=confianca,
                comparaveis=comparaveis, kpis=kpis, fontes=fontes, relatorio_md=relatorio_md,
                imposto_anual=imposto_anual, seguro_anual=seguro_anual, aluguel_mensal=aluguel_mensal,
                manutencao_anual=manutencao_anual, data=data, autor=sessao.autor(ctx),
            ),
        )

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
