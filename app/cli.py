"""Linha de comando para o usuário e para agentes de IA sem MCP (o caminho recomendado é o servidor MCP).

    financas gastos resumo                      tendência por categoria e o que mudou
    financas gastos listar --mes 2026-08 --categoria Outros
    financas gastos recategorizar --id 812 813 --categoria Alimentação
    financas gastos regra --contem "PAGTO SALARIO" --categoria Salário
    financas fundamentos contexto EGIE3         tudo para analisar uma empresa, num JSON
    financas analise importar relatorio.json    grava relatórios, métricas e avisos do agente
    financas carteira contexto                  carteira + metas + fundamentos + últimas análises, num JSON
    financas metas mostrar --aporte 5000        balanço contra as metas e para onde vai o aporte
    financas recomendacoes importar recs.json   grava as recomendações trimestrais
    financas orcamento contexto                 metas de gastos × gastos, para a análise orçamentária
    financas orcamento importar-recomendacoes orc.json   grava as sugestões de orçamento do agente
    financas titulares                          titulares, conexões Pluggy e contas de cada um
    financas --titular Ana carteira contexto    qualquer comando só com as contas de um titular
    financas --demo carteira contexto           qualquer comando na demonstração (dados fictícios)
    financas mcp                                o servidor MCP (stdio), para o agente de IA
    financas mcp instalar --cliente claude-desktop   conecta o servidor MCP a um agente

Com mais de um titular, --titular (nome ou id) restringe carteira, metas e gastos às contas daquela pessoa;
sem ele, vale a casa toda. Metas de gastos (orçamento) são sempre da casa.

Saída sempre em JSON (UTF-8), valores monetários em reais. Nada aqui apaga dados: correções ficam em
colunas/tabelas próprias e podem ser desfeitas. As operações ficam em app/agente/operacoes.py, as mesmas do
servidor MCP. Contrato completo em docs/agente-financeiro.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from typing import Any

from app import __version__, db, demo
from app.agente import operacoes as op
from app.services import fundamentals, household, spending

_MEMBER: int | None = None  # --titular; None = a casa toda


def _out(data: Any) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _read_json(path: str) -> Any:
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"JSON inválido: {exc}") from exc


def _recategorizar(a: argparse.Namespace) -> dict[str, Any]:
    if not a.automatica and not a.categoria:
        raise SystemExit("Informe --categoria ou --automatica.")
    return op.gastos_recategorizar(a.id, a.categoria, a.automatica)


def _metas_definir(a: argparse.Namespace) -> dict[str, Any]:
    return op.metas_definir(a.reserva, a.renda_fixa, a.renda_variavel, a.internacional,
                            None if a.previdencia is None else a.previdencia == "sim", member=_MEMBER)


def _orcamento_definir(a: argparse.Namespace) -> dict[str, Any]:
    categorias = [c for c in (a.categorias or "").split(",")]
    return op.orcamento_definir(a.nome, a.limite, categorias, a.total, a.aviso, a.nota, a.autor)


def _mcp(a: argparse.Namespace) -> dict[str, Any] | None:
    from app.mcp_server import instalar

    if a.acao is None:
        from app.mcp_server import servidor

        servidor.main(demo=a.demo)
        return None
    if a.acao == "clientes":
        return {"clientes": instalar.situacao()}
    if a.acao == "config":
        return instalar.configuracao(a.cliente, demo=a.demo_mcp)
    return instalar.instalar(a.cliente, demo=a.demo_mcp)


# ---------------------------------------------------------------- argumentos

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="financas", description="Tabimoney: finanças pessoais locais (saída em JSON).")
    parser.add_argument("--version", action="version", version=f"Tabimoney {__version__}")
    parser.add_argument("--titular", help="nome ou id do titular (padrão: a casa toda)")
    parser.add_argument("--demo", action="store_true",
                        help="roda na demonstração (dados fictícios, base separada); bom para testar roteiros")
    groups = parser.add_subparsers(dest="grupo", required=True)

    def cmd(sub, name: str, func, **kwargs) -> argparse.ArgumentParser:
        p = sub.add_parser(name, **kwargs)
        p.set_defaults(func=func)
        return p

    g = groups.add_parser("gastos", help="movimentações, categorias e regras").add_subparsers(dest="acao", required=True)
    p = cmd(g, "resumo", lambda a: op.gastos_resumo(a.meses, member=_MEMBER), help="gasto por categoria mês a mês e o que mudou")
    p.add_argument("--meses", type=int, default=6)
    p = cmd(g, "listar", lambda a: op.gastos_listar(
        a.mes, a.de, a.ate, a.categoria, a.busca, a.conta, a.origem, a.so_gastos, a.limite, a.deslocamento,
        member=_MEMBER), help="lista lançamentos com filtros")
    p.add_argument("--mes", help="AAAA-MM")
    p.add_argument("--de", help="AAAA-MM-DD")
    p.add_argument("--ate", help="AAAA-MM-DD")
    p.add_argument("--categoria")
    p.add_argument("--busca", help="texto na descrição")
    p.add_argument("--conta")
    p.add_argument("--origem", choices=["auto", "regra", "manual"], help="de onde veio a categoria")
    p.add_argument("--so-gastos", action="store_true", help="só o que entra em despesas")
    p.add_argument("--limite", type=int, default=200)
    p.add_argument("--deslocamento", type=int, default=0, help="pula os N primeiros (paginação)")
    cmd(g, "categorias", lambda a: op.gastos_categorias(), help="categorias existentes, uso de cada uma e excluídas")
    p = cmd(g, "criar-categoria", lambda a: op.gastos_criar_categoria(a.nome, a.autor),
            help="cria uma categoria (idempotente: se já existe, devolve a existente)")
    p.add_argument("nome")
    p.add_argument("--autor", default="agente")
    p = cmd(g, "excluir-categoria", lambda a: op.gastos_excluir_categoria(a.nome, a.destino, a.autor),
            help="exclui uma categoria própria; em uso, exige --destino")
    p.add_argument("nome")
    p.add_argument("--destino", help="categoria que recebe lançamentos, regras e metas, ou 'automatica'")
    p.add_argument("--autor", default="agente")
    p = cmd(g, "restaurar-categoria", lambda a: op.gastos_restaurar_categoria(a.nome), help="desfaz a exclusão de uma categoria")
    p.add_argument("nome")
    p = cmd(g, "recategorizar", _recategorizar, help="corrige a categoria de lançamentos")
    p.add_argument("--id", type=int, nargs="+", required=True)
    p.add_argument("--categoria")
    p.add_argument("--automatica", action="store_true", help="volta à categoria automática")
    p = cmd(g, "regra", lambda a: op.gastos_regra(a.contem, a.categoria, a.conta, a.nota, a.autor),
            help="cria/atualiza regra 'descrição contém X → categoria'")
    p.add_argument("--contem", required=True)
    p.add_argument("--categoria", required=True)
    p.add_argument("--conta")
    p.add_argument("--nota")
    p.add_argument("--autor", default="agente")
    cmd(g, "regras", lambda a: op.gastos_regras(), help="lista regras")
    p = cmd(g, "remover-regra", lambda a: op.gastos_remover_regra(a.id))
    p.add_argument("id", type=int)

    g = groups.add_parser("carteira", help="posições com fundamentos").add_subparsers(dest="acao", required=True)
    cmd(g, "posicoes", lambda a: op.carteira_posicoes(member=_MEMBER))
    p = cmd(g, "contexto", lambda a: op.carteira_contexto(a.aporte, member=_MEMBER),
            help="tudo para recomendar: metas, posições, fundamentos, análises")
    p.add_argument("--aporte", help="valor do próximo aporte em reais")

    g = groups.add_parser("fundamentos", help="dados da CVM e indicadores").add_subparsers(dest="acao", required=True)
    p = cmd(g, "atualizar", lambda a: op.fundamentos_atualizar(a.tickers), help="baixa ITR/DFP da CVM e recalcula avisos")
    p.add_argument("tickers", nargs="*")
    p = cmd(g, "contexto", lambda a: op.fundamentos_contexto(a.ticker), help="tudo o que um agente precisa para analisar uma empresa")
    p.add_argument("ticker")

    g = groups.add_parser("analise", help="relatórios do agente").add_subparsers(dest="acao", required=True)
    p = cmd(g, "importar", lambda a: op.analise_importar(_read_json(a.arquivo), a.autor),
            help="grava relatório/métricas/avisos (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")
    p = cmd(g, "listar", lambda a: op.analise_listar(a.ticker, a.tipo, a.limite), help="lista relatórios (sem o corpo)")
    p.add_argument("--ticker")
    p.add_argument("--tipo", choices=list(fundamentals.SUBJECT_TYPES))
    p.add_argument("--limite", type=int, default=20)
    p = cmd(g, "mostrar", lambda a: op.analise_mostrar(a.id), help="relatório completo")
    p.add_argument("id", type=int)

    g = groups.add_parser("metas", help="metas de alocação e aporte").add_subparsers(dest="acao", required=True)
    p = cmd(g, "mostrar", lambda a: op.metas_mostrar(a.aporte, member=_MEMBER), help="balanço contra as metas e distribuição do aporte")
    p.add_argument("--aporte", help="valor em reais (padrão: média de sobra mensal)")
    p = cmd(g, "definir", _metas_definir, help="grava metas (percentuais de 0 a 100)")
    p.add_argument("--reserva", help="reserva de emergência em reais")
    p.add_argument("--renda-fixa", type=float)
    p.add_argument("--renda-variavel", type=float)
    p.add_argument("--internacional", type=float, help="%% da renda variável no exterior")
    p.add_argument("--previdencia", choices=["sim", "nao"], help="conta a previdência como renda fixa")
    p = cmd(g, "regiao", lambda a: op.metas_regiao(a.ticker, a.regiao), help="define se um ativo é exposição nacional ou internacional")
    p.add_argument("ticker")
    p.add_argument("regiao", choices=["nacional", "internacional", "automatica"])

    g = groups.add_parser("recomendacoes", help="recomendações trimestrais").add_subparsers(dest="acao", required=True)
    p = cmd(g, "importar", lambda a: op.recomendacoes_importar(_read_json(a.arquivo), a.autor),
            help="grava o conjunto do trimestre (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")
    cmd(g, "listar", lambda a: op.recomendacoes_listar())
    p = cmd(g, "mostrar", lambda a: op.recomendacoes_mostrar(a.id))
    p.add_argument("id", type=int, nargs="?")

    g = groups.add_parser("alertas", help="avisos de fundamentos").add_subparsers(dest="acao", required=True)
    p = cmd(g, "listar", lambda a: op.alertas_listar(a.todos))
    p.add_argument("--todos", action="store_true", help="inclui os já vistos")
    p = cmd(g, "resolver", lambda a: op.alertas_resolver(a.id))
    p.add_argument("id", type=int, nargs="+")

    g = groups.add_parser("orcamento", help="metas de gastos e recomendações orçamentárias").add_subparsers(dest="acao", required=True)
    cmd(g, "mostrar", lambda a: op.orcamento_mostrar(), help="mês corrente contra cada meta de gasto")
    p = cmd(g, "contexto", lambda a: op.orcamento_contexto(a.meses), help="tudo para a análise orçamentária do agente")
    p.add_argument("--meses", type=int, default=6)
    p = cmd(g, "definir", _orcamento_definir, help="cria ou atualiza uma meta de gasto (só com pedido do usuário)")
    p.add_argument("--nome", required=True)
    p.add_argument("--categorias", help="lista separada por vírgula (ex.: 'Alimentação,Mercado')")
    p.add_argument("--total", action="store_true", help="meta de todos os gastos do mês")
    p.add_argument("--limite", required=True, help="limite mensal em reais")
    p.add_argument("--aviso", type=float, help="%% do limite que dispara o aviso (padrão 80)")
    p.add_argument("--nota")
    p.add_argument("--autor", default="agente")
    p = cmd(g, "remover", lambda a: op.orcamento_remover(a.nome), help="remove uma meta de gasto (só com pedido do usuário)")
    p.add_argument("--nome", required=True)
    p = cmd(g, "importar-recomendacoes", lambda a: op.orcamento_importar(_read_json(a.arquivo), a.autor),
            help="grava as sugestões orçamentárias do mês (JSON; '-' lê da entrada padrão)")
    p.add_argument("arquivo")
    p.add_argument("--autor", default="agente")

    cmd(groups, "titulares", lambda a: op.titulares(), help="titulares, conexões Pluggy e contas de cada um")
    cmd(groups, "backup", lambda a: op.backup(), help="cópia da base antes de mudanças em massa")
    cmd(groups, "atualizar", lambda a: op.atualizar(), help="backup + Open Finance + cotações/CDI + balanços da CVM")

    from app.mcp_server.instalar import CLIENTES

    mcp = cmd(groups, "mcp", _mcp, help="servidor MCP para agentes de IA; sem ação, sobe o servidor (stdio)")
    g = mcp.add_subparsers(dest="acao")
    cmd(g, "clientes", _mcp, help="agentes conhecidos e se o Tabimoney está conectado em cada um")
    for name, text in (("config", "mostra a configuração e o texto para colar na IA"),
                       ("instalar", "grava a configuração no agente (com cópia do arquivo antes)")):
        p = cmd(g, name, _mcp, help=text)
        p.add_argument("--cliente", required=True, choices=list(CLIENTES))
        p.add_argument("--demo", dest="demo_mcp", action="store_true", help="a entrada da demonstração (tabimoney-demo)")
    return parser


def main(argv: list[str] | None = None) -> None:
    global _MEMBER
    db.init_db()
    args = build_parser().parse_args(argv)
    if args.grupo == "mcp":
        result = args.func(args)  # o servidor cuida da demo por conta própria
        if result is not None:
            _out(result)
        return
    if args.demo:
        if args.grupo in ("atualizar", "backup"):
            _out({"erro": "Na demonstração, atualizar e backup ficam desligados: não há dados de verdade."})
            raise SystemExit(1)
        demo.ensure()
    try:
        with demo.active() if args.demo else nullcontext():
            _MEMBER = household.resolve(args.titular) if args.titular else None
            _out(args.func(args))
    except spending.CategoryInUse as exc:
        _out(op.categoria_em_uso(exc, "repita com --destino Outros (ou outra categoria, ou 'automatica')"))
        raise SystemExit(2) from exc
    except op.ERROS as exc:
        _out({"erro": str(exc)})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
