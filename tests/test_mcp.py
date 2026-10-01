"""Servidor MCP (app/mcp_server): ferramentas, anotações, paridade com a CLI, importações, backup, autoria,
tarefas longas, roteiros, resources e nenhum segredo nas respostas.

Roda o servidor no mesmo processo, com o cliente em memória do SDK, sobre a base temporária do conftest.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path

import pytest
from mcp import Client
from mcp_types import Implementation

from app import agente, cli, db, demo
from app.agente import operacoes as op
from app.mcp_server import ferramentas, servidor, tarefas

from .conftest import rodar_async

ROOT = Path(__file__).resolve().parent.parent
EXEMPLOS = ROOT / "docs" / "agentes" / "exemplos"
CLIENTE = Implementation(name="teste-agente", version="1.0")
SENSIVEIS = {"metas_definir", "orcamento_definir", "orcamento_remover", "gastos_excluir_categoria", "gastos_remover_regra"}


def _rodar(na_demo: bool, passos, mode: str = "legacy"):
    """Abre uma sessão com um servidor novo e roda `passos(cliente)` (uma corrotina)."""
    if na_demo:
        demo.ensure()

    async def principal():
        async with Client(servidor.criar(na_demo), client_info=CLIENTE, mode=mode) as c:
            return await passos(c)

    return rodar_async(principal)


def _dados(resultado) -> dict:
    assert not resultado.is_error, resultado.content[0].text
    return json.loads(resultado.content[0].text)


def _cli(capsys, *args: str) -> dict:
    capsys.readouterr()
    cli.main(list(args))
    return json.loads(capsys.readouterr().out)


@pytest.fixture(autouse=True)
def tarefas_limpas():
    tarefas.limpar()
    yield
    tarefas.limpar()


# ---------------------------------------------------------------- catálogo

def test_toda_ferramenta_tem_titulo_descricao_anotacao_e_equivalente_na_cli():
    async def passos(c):
        return (await c.list_tools()).tools

    tools = _rodar(False, passos)
    nomes = {t.name for t in tools}
    assert nomes == set(ferramentas.EQUIVALENTE_CLI) == set(ferramentas.TIPOS)
    for t in tools:
        assert t.title and t.description and len(t.description) > 30, t.name
        assert t.annotations is not None, t.name
        assert t.annotations.read_only_hint == (ferramentas.TIPOS[t.name] == ferramentas.LEITURA), t.name
        assert bool(t.annotations.destructive_hint) == (t.name in SENSIVEIS), t.name
        assert "ctx" not in json.dumps(t.input_schema), t.name  # o contexto não vira parâmetro


def test_instrucoes_mandam_chamar_o_roteiro():
    async def passos(c):
        return c.instructions

    texto = _rodar(False, passos)
    assert "`roteiro`" in texto and "carteira_contexto" in texto
    assert "DEMONSTRAÇÃO" in _rodar(True, passos)


# ---------------------------------------------------------------- leituras

def _argumentos_de_leitura() -> dict[str, dict]:
    with demo.active():
        ticker = op.carteira_contexto()["renda_variavel"]["posicoes"][0]["ticker"]
        relatorio = op.analise_listar(limite=1)["relatorios"][0]["id"]
    return {"fundamentos_contexto": {"ticker": ticker}, "analise_mostrar": {"relatorio_id": relatorio},
            "roteiro": {"nome": "ciclo"}}


def test_toda_leitura_responde_na_demo():
    demo.ensure()
    argumentos = _argumentos_de_leitura()
    leituras = [n for n, tipo in ferramentas.TIPOS.items() if tipo == ferramentas.LEITURA and n != "tarefa_status"]

    async def passos(c):
        return {n: await c.call_tool(n, argumentos.get(n, {})) for n in leituras}

    for nome, resultado in _rodar(True, passos).items():
        dados = _dados(resultado)
        assert dados, nome


@pytest.mark.parametrize(("ferramenta", "argumentos", "comando"), [
    ("carteira_contexto", {"aporte": 5000}, ["carteira", "contexto", "--aporte", "5000"]),
    ("carteira_contexto", {"titular": "Marina"}, ["--titular", "Marina", "carteira", "contexto"]),
    ("orcamento_contexto", {}, ["orcamento", "contexto"]),
    ("gastos_resumo", {"meses": 3}, ["gastos", "resumo", "--meses", "3"]),
    ("metas_mostrar", {}, ["metas", "mostrar"]),
    ("perfil_investidor", {}, ["perfil", "mostrar"]),
    ("gastos_categorias", {}, ["gastos", "categorias"]),
    ("titulares", {}, ["titulares"]),
    ("gastos_listar", {"limite": 30, "so_gastos": True}, ["gastos", "listar", "--limite", "30", "--so-gastos"]),
])
def test_mesma_resposta_da_cli(capsys, ferramenta, argumentos, comando):
    """As duas portas chamam as mesmas operações (app/agente/operacoes.py)."""
    async def passos(c):
        return _dados(await c.call_tool(ferramenta, argumentos))

    assert _rodar(True, passos) == _cli(capsys, "--demo", *comando)


def test_lista_de_lancamentos_paginada_e_enxuta():
    async def passos(c):
        primeira = _dados(await c.call_tool("gastos_listar", {"limite": 5, "campos": ["data", "valor"]}))
        segunda = _dados(await c.call_tool("gastos_listar", {"limite": 5, "deslocamento": primeira["proximo_deslocamento"]}))
        return primeira, segunda

    primeira, segunda = _rodar(True, passos)
    assert len(primeira["lancamentos"]) == 5 and primeira["proximo_deslocamento"] == 5
    assert set(primeira["lancamentos"][0]) == {"id", "data", "valor"}
    assert not {t["id"] for t in primeira["lancamentos"]} & {t["id"] for t in segunda["lancamentos"]}


def test_titular_desconhecido_da_erro_claro():
    async def passos(c):
        return await c.call_tool("carteira_contexto", {"titular": "Ninguém"})

    resultado = _rodar(True, passos)
    assert resultado.is_error and "Titular não encontrado: Ninguém" in resultado.content[0].text


def test_respostas_cabem_no_limite_dos_clientes():
    """O Claude Code corta respostas acima de ~25 mil tokens (~100 mil caracteres). Com 40 ativos, a carteira
    completa precisa caber com folga; a página padrão de lançamentos também."""
    demo.ensure()

    async def passos(c):
        return (await c.call_tool("carteira_contexto", {})).content[0].text, \
               (await c.call_tool("gastos_listar", {})).content[0].text

    carteira, lancamentos = _rodar(True, passos)
    dados = json.loads(carteira)
    posicoes = dados["renda_variavel"]["posicoes"]
    por_ativo = len(json.dumps(posicoes, ensure_ascii=False, separators=(",", ":"))) / len(posicoes)
    estimativa_40 = len(carteira) - por_ativo * len(posicoes) + por_ativo * 40
    assert estimativa_40 < 80_000
    assert len(lancamentos) < 40_000
    assert "\n" not in carteira  # JSON compacto


# ---------------------------------------------------------------- escrita

def test_backup_automatico_so_antes_da_primeira_escrita(dados_exemplo):
    async def passos(c):
        leitura = _dados(await c.call_tool("gastos_categorias", {}))
        primeira = _dados(await c.call_tool("gastos_criar_categoria", {"nome": "Pets"}))
        segunda = _dados(await c.call_tool("gastos_criar_categoria", {"nome": "Viagens"}))
        return leitura, primeira, segunda

    leitura, primeira, segunda = _rodar(False, passos)
    assert "backup_automatico" not in leitura
    assert Path(primeira["backup_automatico"]).is_file()
    assert "backup_automatico" not in segunda
    assert len(list((db.data_dir() / "backups").glob("*.sqlite3"))) == 1


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_importa_os_exemplos_com_o_cliente_como_autor(mode):
    """Os exemplos da documentação passam pelos esquemas das ferramentas, e o autor é o nome do cliente."""
    analises = json.loads((EXEMPLOS / "analise-trimestral.json").read_text(encoding="utf-8"))
    analises += json.loads((EXEMPLOS / "analise-ativo.json").read_text(encoding="utf-8"))
    recomendacoes = json.loads((EXEMPLOS / "recomendacoes.json").read_text(encoding="utf-8"))
    orcamento = json.loads((EXEMPLOS / "orcamento.json").read_text(encoding="utf-8"))

    async def passos(c):
        a = await c.call_tool("analise_importar", {"relatorios": analises})
        r = await c.call_tool("recomendacoes_importar", {"conjunto": recomendacoes})
        o = await c.call_tool("orcamento_importar_recomendacoes", {"conjunto": orcamento})
        lista = await c.call_tool("analise_listar", {"limite": 100})
        return a, r, o, lista

    a, r, o, lista = _rodar(True, passos, mode)
    _dados(a), _dados(r), _dados(o)
    autores = {x["author"] for x in _dados(lista)["relatorios"]}
    assert "teste-agente" in autores
    assert {"tese", "trimestral"} <= {x["kind"] for x in _dados(lista)["relatorios"] if x["author"] == "teste-agente"}


def test_item_invalido_recusa_o_lote_inteiro():
    demo.ensure()
    analises = json.loads((EXEMPLOS / "analise-trimestral.json").read_text(encoding="utf-8"))
    analises[-1]["report"]["verdict"] = "baratíssima"
    with demo.active():
        antes = len(op.analise_listar(limite=100)["relatorios"])

    async def passos(c):
        return await c.call_tool("analise_importar", {"relatorios": analises})

    resultado = _rodar(True, passos)
    assert resultado.is_error and "verdict" in resultado.content[0].text
    with demo.active():
        assert len(op.analise_listar(limite=100)["relatorios"]) == antes


def test_excluir_categoria_em_uso_explica_o_que_depende_dela(dados_exemplo):
    from app.services import analytics, spending

    spending.create_category("Delivery")
    spending.set_category([analytics.cash_transactions()[0]["id"]], "Delivery")

    async def passos(c):
        return await c.call_tool("gastos_excluir_categoria", {"nome": "Delivery"})

    resultado = _rodar(False, passos)
    assert resultado.is_error
    texto = resultado.content[0].text
    detalhe = json.loads(texto[texto.index("{"):])
    assert detalhe["lancamentos_corrigidos"] == 1 and "destino" in detalhe["dica"]


def test_valores_em_reais_nao_viram_milhar():
    """parse_amount lê '12.345' como doze mil; um float das ferramentas não pode cair nessa armadilha."""
    async def passos(c):
        _dados(await c.call_tool("gastos_criar_categoria", {"nome": "Cafés"}))
        return _dados(await c.call_tool("orcamento_definir", {"nome": "Café", "limite": 12.345, "categorias": ["Cafés"]}))

    _rodar(True, passos)
    with demo.active():
        meta = next(m for m in op.orcamento_mostrar()["metas"] if m["nome"] == "Café")
    assert meta["limite"] == 12.35


def test_demo_recusa_atualizar_e_backup():
    async def passos(c):
        return await c.call_tool("atualizar_dados", {}), await c.call_tool("backup", {})

    for resultado in _rodar(True, passos):
        assert resultado.is_error and "demonstração" in resultado.content[0].text


def test_escrita_na_demo_nao_toca_na_base_real(dados_exemplo):
    from app.services import spending

    async def passos(c):
        return _dados(await c.call_tool("gastos_criar_categoria", {"nome": "Só na demo"}))

    _rodar(True, passos)
    assert "Só na demo" not in spending.known_categories()
    assert not (db.data_dir() / "backups").exists()


# ---------------------------------------------------------------- tarefas longas

def test_atualizar_devolve_tarefa_e_termina_depois(monkeypatch):
    liberar = threading.Event()

    def atualizar_lento(progresso=None):
        progresso("open_finance")
        liberar.wait(5)
        return {"ok": True}

    monkeypatch.setattr(op, "atualizar", atualizar_lento)
    monkeypatch.setattr(ferramentas, "ESPERA_TAREFA", 0)

    async def passos(c):
        inicio = _dados(await c.call_tool("atualizar_dados", {}))
        repetida = _dados(await c.call_tool("atualizar_dados", {}))
        liberar.set()
        for _ in range(100):
            fim = _dados(await c.call_tool("tarefa_status", {"tarefa_id": inicio["tarefa_id"]}))
            if fim["situacao"] != "rodando":
                break
            await asyncio.sleep(0.05)
        return inicio, repetida, fim

    inicio, repetida, fim = _rodar(False, passos)
    assert inicio["situacao"] == "rodando" and "tarefa_status" in inicio["dica"]
    assert repetida["tarefa_id"] == inicio["tarefa_id"]  # não começa outra igual
    assert fim["situacao"] == "concluida" and fim["resultado"] == {"ok": True}


def test_tarefa_rapida_ja_volta_com_o_resultado(monkeypatch):
    monkeypatch.setattr(op, "fundamentos_atualizar", lambda tickers=None: {"atualizados": tickers})

    async def passos(c):
        return _dados(await c.call_tool("fundamentos_atualizar", {"tickers": ["EGIE3"]}))

    dados = _rodar(False, passos)
    assert dados["situacao"] == "concluida" and dados["resultado"] == {"atualizados": ["EGIE3"]}


def test_tarefa_com_falha_traz_a_mensagem(monkeypatch):
    def quebra(tickers=None):
        raise RuntimeError("CVM fora do ar")

    monkeypatch.setattr(op, "fundamentos_atualizar", quebra)

    async def passos(c):
        return _dados(await c.call_tool("fundamentos_atualizar", {}))

    dados = _rodar(False, passos)
    assert dados["situacao"] == "falhou" and dados["erro"] == "CVM fora do ar"


# ---------------------------------------------------------------- roteiros, prompts e resources

def test_roteiros_so_citam_ferramentas_que_existem():
    padrao = re.compile(r"`((?:gastos|carteira|metas|perfil|orcamento|analise|recomendacoes|alertas|fundamentos|atualizar|tarefa)_[a-z_]+)`")
    campos = {"tarefa_id", "metas_e_balanco", "metas_sugeridas_pela_media"}  # campos das respostas, não ferramentas
    servidor.criar(False)
    for nome in agente.ROTEIROS:
        texto = agente.roteiro(nome)["texto"]
        for citada in set(padrao.findall(texto)) - campos:
            assert citada in ferramentas.TIPOS, f"{nome}: {citada}"
        assert "financas.bat" not in texto, nome  # roteiro novo não depende de shell


def test_prompts_trazem_o_roteiro_e_os_parametros():
    async def passos(c):
        prompts = (await c.list_prompts()).prompts
        aporte = await c.get_prompt("onde_aportar", {"aporte": "3000", "titular": "Marina"})
        ciclo = await c.get_prompt("ciclo", {})
        return prompts, aporte, ciclo

    prompts, aporte, ciclo = _rodar(False, passos)
    assert {p.name for p in prompts} == set(servidor.PROMPTS)
    assert all(p.description for p in prompts)
    texto = aporte.messages[0].content.text
    assert "- aporte: 3000" in texto and "- titular: Marina" in texto and "metas_mostrar" in texto
    assert "Parâmetros" not in ciclo.messages[0].content.text


def test_resources_abrem():
    async def passos(c):
        uris = [str(r.uri) for r in (await c.list_resources()).resources]
        return {u: (await c.read_resource(u)).contents[0].text for u in uris}

    conteudos = _rodar(False, passos)
    assert len(conteudos) == len(servidor.RESOURCES) + len(agente.ROTEIROS)
    assert all(conteudos.values())
    json.loads(conteudos["tabimoney://exemplos/recomendacoes"])


# ---------------------------------------------------------------- privacidade e registro de uso

def test_nenhum_segredo_nas_respostas(dados_exemplo, cofre):
    from app import security
    from app.services import household

    security.save_secret("pluggy_client_secret", "SEGREDO-PLUGGY-123")
    security.save_secret("brapi_token", "TOKEN-BRAPI-456")
    household.add_member("Ana", "529.982.247-25")
    leituras = [n for n, tipo in ferramentas.TIPOS.items()
                if tipo == ferramentas.LEITURA and n not in {"tarefa_status", "fundamentos_contexto", "analise_mostrar"}]

    async def passos(c):
        return [(await c.call_tool(n, {"nome": "ciclo"} if n == "roteiro" else {})).content[0].text for n in leituras]

    tudo = "\n".join(_rodar(False, passos))
    for proibido in ("SEGREDO-PLUGGY-123", "TOKEN-BRAPI-456", "529.982.247-25", "52998224725"):
        assert proibido not in tudo


def test_registra_o_uso_para_a_tela_de_conexao():
    from app.mcp_server import instalar

    async def passos(c):
        return await c.call_tool("status", {})

    _rodar(False, passos)
    uso = instalar.ultimo_uso()
    assert uso[0]["cliente"] == "teste-agente" and uso[0]["demo"] is False


def test_contrato_lista_todas_as_ferramentas():
    contrato = (ROOT / "docs" / "agente-financeiro.md").read_text(encoding="utf-8")
    for nome in ferramentas.EQUIVALENTE_CLI:
        assert f"| `{nome}` |" in contrato, nome
