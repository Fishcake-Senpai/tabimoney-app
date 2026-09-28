"""Gestão a dois: titulares, várias conexões Pluggy, contas separadas por pessoa e Pix entre o casal.

O cenário de fundo é o que motivou o recurso: Gabriel e Ana têm Nubank e os dois têm ITSA4. Antes, as contas dos
dois ganhavam o mesmo nome ("Nubank / NuInvest", "Nubank Cartão") e uma posição apagava a outra.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from app import cli, db, security
from app.providers.pluggy import PluggyData, PluggyError
from app.services import accounts, analytics, household, sync, targets

from .conftest import avisos, csrf

HOJE = date.today().isoformat()
ONTEM = (date.today() - timedelta(days=1)).isoformat()
ITEM_GABRIEL = "11111111-1111-4111-8111-111111111111"
ITEM_ANA = "22222222-2222-4222-8222-222222222222"
ITEM_XP = "33333333-3333-4333-8333-333333333333"


def cpf(base: str) -> str:
    """CPF válido a partir de 9 dígitos (calcula os verificadores)."""
    digits = [int(d) for d in base]
    for size in (9, 10):
        total = sum(d * (size + 1 - i) for i, d in enumerate(digits))
        digits.append(total * 10 % 11 % 10)
    return "".join(map(str, digits))


CPF_GABRIEL = cpf("123456789")
CPF_ANA = cpf("987654321")
CPF_ESTRANHO = cpf("111444777")


# ---------------------------------------------------------------- Pluggy falso

def _party(document: str) -> dict:
    return {"documentNumber": {"type": "CPF", "value": document}}


def _bundle(item_id: str, owner: str, pix: list[dict] | None = None, quantity: int = 100) -> PluggyData:
    """Um item do Nubank: conta (número diferente por pessoa), cartão sem número e 1 ação ITSA4."""
    suffix = "0001" if owner == "gabriel" else "0002"
    bank, card = f"{owner}-bank", f"{owner}-card"
    return PluggyData(
        item={"id": item_id, "connector": {"name": "MeuPluggy"}, "lastUpdatedAt": HOJE},
        accounts=[
            {"id": bank, "type": "BANK", "number": f"99{suffix}", "balance": 1000 if owner == "gabriel" else 2500,
             "bankData": {"transferNumber": "260/0001/99"}, "updatedAt": HOJE},
            {"id": card, "type": "CREDIT", "balance": 300 if owner == "gabriel" else 450, "updatedAt": HOJE},
        ],
        transactions_by_account={bank: pix or [], card: []},
        investments=[{"id": f"{owner}-itsa", "type": "EQUITY", "subtype": "STOCK", "ticker": "ITSA4",
                      "name": "Itaúsa", "quantity": quantity}],
    )


class PluggyFalso:
    """Substitui o PluggyClient: responde por Item ID e registra com quais credenciais foi aberto."""

    itens: dict[str, PluggyData] = {}
    identidades: dict[str, str] = {}
    sessoes: list[str] = []

    def __init__(self, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            raise PluggyError("Preencha Client ID e Client Secret do Meu Pluggy.")
        if client_id == "recusado":
            raise PluggyError("Credenciais Pluggy inválidas ou sem permissão para essa conexão.")
        PluggyFalso.sessoes.append(client_id)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def identity(self, item_id: str) -> str | None:
        return PluggyFalso.identidades.get(item_id)

    def collect(self, item_id: str) -> PluggyData:
        if item_id not in PluggyFalso.itens:
            raise PluggyError("A Pluggy respondeu com HTTP 404.")
        return PluggyFalso.itens[item_id]


@pytest.fixture
def pluggy(monkeypatch):
    PluggyFalso.itens, PluggyFalso.identidades, PluggyFalso.sessoes = {}, {}, []
    monkeypatch.setattr(sync, "PluggyClient", PluggyFalso)
    return PluggyFalso


@pytest.fixture
def casal(pluggy, cofre):
    """Gabriel (principal) e Ana, os dois no mesmo app Pluggy (conexão 1), cada um com o próprio Nubank."""
    household.update_member(1, "Gabriel")
    ana = household.add_member("Ana")["id"]
    security.save_secret("pluggy_client_id", "id-casal")
    security.save_secret("pluggy_client_secret", "segredo")
    household.add_items(1, ITEM_GABRIEL, 1)
    household.add_items(1, ITEM_ANA, ana)
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel")
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", quantity=40)
    return ana


def _itsa() -> int:
    return int(db.rows("SELECT id FROM instrument WHERE ticker = 'ITSA4'")[0]["id"])


def _conta(nome: str) -> dict:
    found = db.rows("SELECT * FROM financial_account WHERE account_name = ?", (nome,))
    assert found, f"conta {nome!r} não existe; há: {[r['account_name'] for r in db.rows('SELECT account_name FROM financial_account')]}"
    return dict(found[0])


# ---------------------------------------------------------------- migração

def _base_antiga(path, item_ids: str | None, display_name: str | None = None) -> sqlite3.Connection:
    """Base na versão 008 (antes dos titulares), com a configuração antiga de Item IDs."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    for migration in sorted(db.MIGRATIONS_DIR.glob("[0-9]*_*.sql")):
        if int(migration.name.split("_")[0]) >= 9:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
    if item_ids is not None:
        connection.execute("INSERT INTO app_setting(key, value) VALUES ('pluggy_item_ids', ?)", (item_ids,))
    if display_name is not None:
        connection.execute("INSERT INTO app_setting(key, value) VALUES ('display_name', ?)", (display_name,))
    connection.execute(
        "INSERT INTO financial_account(institution, account_name, account_type, provider, external_key) "
        f"VALUES ('Nubank', 'Nubank ••••0001', 'BANK', 'pluggy', 'item:{ITEM_GABRIEL}:account:x')"
    )
    connection.commit()
    return connection


def _aplicar_009(connection: sqlite3.Connection) -> None:
    connection.executescript((db.MIGRATIONS_DIR / "009_household.sql").read_text(encoding="utf-8"))
    connection.commit()


def test_migracao_leva_item_ids_antigos_para_a_conexao_principal(tmp_path):
    con = _base_antiga(tmp_path / "antiga.sqlite3", f"{ITEM_GABRIEL}, {ITEM_ANA.upper()}", display_name="Tabim")
    _aplicar_009(con)
    itens = [tuple(r) for r in con.execute("SELECT item_id, connection_id, member_id FROM pluggy_item ORDER BY item_id")]
    assert itens == [(ITEM_GABRIEL, 1, 1), (ITEM_ANA, 1, 1)]
    assert con.execute("SELECT name FROM household_member WHERE id = 1").fetchone()[0] == "Tabim"
    assert con.execute("SELECT label FROM pluggy_connection").fetchall()[0][0] == "Principal"
    assert not con.execute("SELECT 1 FROM app_setting WHERE key = 'pluggy_item_ids'").fetchone()
    # conta antiga continua com o mesmo nome e sem titular (= principal)
    conta = con.execute("SELECT account_name, member_id FROM financial_account").fetchone()
    assert tuple(conta) == ("Nubank ••••0001", None)
    con.close()


@pytest.mark.parametrize("valor", [None, "", " "])
def test_migracao_sem_item_ids_nao_cria_itens(tmp_path, valor):
    con = _base_antiga(tmp_path / "vazia.sqlite3", valor)
    _aplicar_009(con)
    assert con.execute("SELECT COUNT(*) FROM pluggy_item").fetchone()[0] == 0
    assert con.execute("SELECT name FROM household_member").fetchone()[0] == "Eu"
    con.close()


def test_base_nova_tem_titular_principal_e_conexao_principal():
    assert [(m["id"], m["is_primary"]) for m in household.members()] == [(1, True)]
    assert [c["id"] for c in household.connections()] == [1]
    assert not household.is_shared()


def test_backup_da_versao_nova_e_valido():
    ok, motivo = db.validate_database(db.create_backup())
    assert ok, motivo


# ---------------------------------------------------------------- titulares

def test_cpf_valido_e_invalido():
    assert household.valid_cpf(CPF_GABRIEL) and household.valid_cpf("123.456.789-09")
    assert not household.valid_cpf("123.456.789-00")
    assert not household.valid_cpf("111.111.111-11")
    assert not household.valid_cpf("123")


def test_cpf_nao_fica_guardado_em_texto():
    household.add_member("Ana", CPF_ANA)
    guardado = db.rows("SELECT document_hash FROM household_member WHERE name = 'Ana'")[0][0]
    assert guardado and CPF_ANA not in guardado
    assert household.Documents().member_of(CPF_ANA) == 2
    assert household.Documents().member_of(f"{CPF_ANA[:3]}.{CPF_ANA[3:6]}.{CPF_ANA[6:9]}-{CPF_ANA[9:]}") == 2
    assert household.Documents().member_of(CPF_ESTRANHO) is None


def test_mesmo_cpf_em_dois_titulares_e_recusado():
    household.update_member(1, cpf=CPF_GABRIEL)
    with pytest.raises(ValueError, match="já é de"):
        household.add_member("Ana", CPF_GABRIEL)


@pytest.mark.parametrize("nome", ["", "Casa", "todos", "Ana · Silva", "x" * 31])
def test_nomes_invalidos(nome):
    with pytest.raises(ValueError):
        household.add_member(nome)


def test_nome_repetido_sem_diferenca_de_caixa():
    household.add_member("Ana")
    with pytest.raises(ValueError, match="Já existe"):
        household.add_member("ana")


def test_resolve_por_nome_ou_id():
    ana = household.add_member("Ána")["id"]
    assert household.resolve("ana") == ana and household.resolve(str(ana)) == ana
    assert household.resolve("casa") is None and household.resolve("") is None
    with pytest.raises(ValueError, match="não encontrado"):
        household.resolve("Bia")


def test_titular_principal_nao_e_excluido():
    with pytest.raises(ValueError, match="principal"):
        household.delete_member(1)


def test_titular_com_item_nao_e_excluido(casal):
    with pytest.raises(ValueError, match="ainda tem"):
        household.delete_member(casal)


def test_excluir_titular_sem_contas():
    bia = household.add_member("Bia")["id"]
    household.delete_member(bia)
    assert household.member(bia) is None


# ---------------------------------------------------------------- sincronização do casal

def test_dois_titulares_no_mesmo_banco_nao_se_sobrepoem(casal):
    resultado = sync.sync_pluggy()
    assert resultado["status"] == "success", resultado["message"]
    nomes = {r["account_name"] for r in db.rows("SELECT account_name FROM financial_account")}
    assert {"Nubank ••••0001", "Nubank Cartão", "Nubank / NuInvest",
            "Nubank ••••0002 · Ana", "Nubank Cartão · Ana", "Nubank / NuInvest · Ana"} <= nomes
    assert _conta("Nubank Cartão · Ana")["member_id"] == casal
    assert _conta("Nubank Cartão")["member_id"] is None

    casa = analytics.Book()
    assert casa.qty_at(_itsa(), HOJE) == 140 * 1_000_000  # 100 do Gabriel + 40 da Ana, não uma das duas
    cartoes = {a["name"]: a["balance"] for a in casa.accounts() if a["type"] == "CREDIT"}
    assert cartoes == {"Nubank Cartão": -30000, "Nubank Cartão · Ana": -45000}
    assert casa.cash_at(HOJE) == 350000


def test_visao_de_um_titular(casal):
    sync.sync_pluggy()
    gabriel, ana = analytics.Book(1), analytics.Book(casal)
    assert gabriel.qty_at(_itsa(), HOJE) == 100 * 1_000_000
    assert ana.qty_at(_itsa(), HOJE) == 40 * 1_000_000
    assert ana.cash_at(HOJE) == 250000 and gabriel.cash_at(HOJE) == 100000
    assert {a["name"] for a in ana.accounts()} == {"Nubank ••••0002 · Ana", "Nubank Cartão · Ana"}


def test_mensagem_e_historico_dizem_de_quem_e_o_item(casal):
    resultado = sync.sync_pluggy()
    assert "Nubank · Ana: sincronização concluída." in resultado["message"]
    fontes = {r[0] for r in db.rows("SELECT source FROM sync_run")}
    assert {"Meu Pluggy · Nubank", "Meu Pluggy · Nubank · Ana"} <= fontes


def test_ressincronizar_nao_duplica(casal):
    sync.sync_pluggy()
    antes = db.rows("SELECT COUNT(*) FROM financial_account")[0][0]
    sync.sync_pluggy()
    assert db.rows("SELECT COUNT(*) FROM financial_account")[0][0] == antes
    assert analytics.Book().qty_at(_itsa(), HOJE) == 140 * 1_000_000


def test_trocar_o_titular_do_item_renomeia_as_contas_e_leva_o_percentual_do_cdi(casal):
    sync.sync_pluggy()
    db.set_setting("cdi_pct:Nubank ••••0002 · Ana", "105")
    assert household.set_item_member(ITEM_ANA, 1) == 3
    assert _conta("Nubank ••••0002")["member_id"] is None
    assert db.get_setting("cdi_pct:Nubank ••••0002") == "105"
    assert not db.get_setting("cdi_pct:Nubank ••••0002 · Ana")
    # a próxima sincronização mantém o novo titular
    sync.sync_pluggy()
    assert not db.rows("SELECT 1 FROM financial_account WHERE account_name LIKE '% · Ana'")


def test_renomear_titular_reescreve_o_sufixo_e_as_regras(casal):
    sync.sync_pluggy()
    from app.services import spending

    spending.add_rule("MERCADINHO", "Mercado", "Nubank ••••0002 · Ana")
    household.update_member(casal, "Aninha")
    assert _conta("Nubank / NuInvest · Aninha")["member_id"] == casal
    assert [r["account_name"] for r in spending.rules()] == ["Nubank ••••0002 · Aninha"]
    sync.sync_pluggy()
    assert not db.rows("SELECT 1 FROM financial_account WHERE account_name LIKE '% · Ana'")


def test_renomear_o_principal_nao_mexe_nas_contas(casal):
    sync.sync_pluggy()
    household.update_member(1, "Gabi")
    assert _conta("Nubank ••••0001")["member_id"] is None


def test_item_novo_de_titular_ja_existente_muda_de_titular(casal):
    sync.sync_pluggy()
    resultado = household.add_items(1, ITEM_ANA, 1)
    assert resultado["added"] == 0
    assert _conta("Nubank ••••0002")["member_id"] is None


def test_arquivo_importado_continua_vinculado_ao_nubank_do_principal(casal):
    """Com dois Nubank conectados (um de cada), o CSV do principal ainda casa com o Nubank dele."""
    sync.sync_pluggy()
    with db.transaction() as con:
        con.execute("INSERT INTO financial_account(institution, account_name, account_type, provider, external_key) "
                    "VALUES ('Nubank', 'Nubank', 'BANK', 'ofx', 'arquivo')")
        accounts.link_accounts(con)
    assert db.rows("SELECT account_name FROM financial_account WHERE external_key = 'arquivo'")[0][0] == "Nubank ••••0001"


def test_identidade_da_pluggy_preenche_o_cpf_do_titular(casal, pluggy):
    pluggy.identidades[ITEM_ANA] = CPF_ANA
    pluggy.identidades[ITEM_GABRIEL] = CPF_GABRIEL
    sync.sync_pluggy()
    docs = household.Documents()
    assert docs.member_of(CPF_ANA) == casal and docs.member_of(CPF_GABRIEL) == 1


def test_identidade_nao_sobrescreve_cpf_cadastrado(casal, pluggy):
    household.update_member(casal, cpf=CPF_ANA)
    pluggy.identidades[ITEM_ANA] = CPF_ESTRANHO
    sync.sync_pluggy()
    assert household.Documents().member_of(CPF_ANA) == casal
    assert household.Documents().member_of(CPF_ESTRANHO) is None


# ---------------------------------------------------------------- Pix entre o casal

def _pix(tid: str, dia: str, valor: float, pagador: str | None, recebedor: str | None, descricao: str) -> dict:
    item = {"id": tid, "date": dia, "description": descricao, "amount": valor,
            "type": "DEBIT" if valor < 0 else "CREDIT", "status": "POSTED"}
    if pagador or recebedor:
        item["paymentData"] = {"payer": _party(pagador) if pagador else {}, "receiver": _party(recebedor) if recebedor else {}}
    return item


def test_pix_entre_titulares_pelo_cpf_nao_e_receita_nem_despesa(casal, pluggy):
    household.update_member(1, cpf=CPF_GABRIEL)
    household.update_member(casal, cpf=CPF_ANA)
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[
        _pix("g1", ONTEM, -300, CPF_GABRIEL, CPF_ANA, "Pix enviado Ana")])
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", pix=[
        _pix("a1", ONTEM, 300, CPF_GABRIEL, CPF_ANA, "Pix recebido Gabriel")])
    sync.sync_pluggy()
    movs = [t for t in analytics.cash_transactions() if t["description"].startswith("Pix")]
    assert {t["category"] for t in movs} == {"Transferência entre titulares"}
    assert {t["transfer_with"] for t in movs} == {"Nubank ••••0001", "Nubank ••••0002 · Ana"}
    assert analytics.cash_flow(movs) == []
    assert not analytics.unmatched_transfers(movs, "2000-01-01")


def test_pix_entre_titulares_sem_cpf_casa_pelo_valor_e_data(casal, pluggy):
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[_pix("g1", ONTEM, -250, None, None, "Pix enviado")])
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", pix=[_pix("a1", HOJE, 250, None, None, "Pix recebido")])
    sync.sync_pluggy()
    movs = [t for t in analytics.cash_transactions() if t["description"].startswith("Pix")]
    assert {t["category"] for t in movs} == {"Transferência entre titulares"}
    assert analytics.cash_flow(movs) == []


def test_pix_sem_cpf_com_dias_de_distancia_nao_casa(casal, pluggy):
    longe = (date.today() - timedelta(days=5)).isoformat()
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[_pix("g1", longe, -250, None, None, "Pix enviado")])
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", pix=[_pix("a1", HOJE, 250, None, None, "Pix recebido")])
    sync.sync_pluggy()
    movs = {t["description"]: t for t in analytics.cash_transactions() if t["description"].startswith("Pix")}
    assert movs["Pix enviado"]["category"] == "Pix e transferências" and not movs["Pix enviado"].get("transfer_with")


def test_pix_para_estranho_continua_despesa(casal, pluggy):
    household.update_member(1, cpf=CPF_GABRIEL)
    household.update_member(casal, cpf=CPF_ANA)
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[
        _pix("g1", ONTEM, -80, CPF_GABRIEL, CPF_ESTRANHO, "Pix enviado Joao")])
    sync.sync_pluggy()
    pix = next(t for t in analytics.cash_transactions() if t["description"] == "Pix enviado Joao")
    assert pix["category"] == "Pix e transferências"
    assert analytics.cash_flow([pix])[0]["out"] == 8000


def test_pix_para_titular_nao_conectado_fica_interno_e_aparece_sem_par(casal, pluggy):
    household.update_member(1, cpf=CPF_GABRIEL)
    household.update_member(casal, cpf=CPF_ANA)
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[
        _pix("g1", ONTEM, -120, CPF_GABRIEL, CPF_ANA, "Pix para a conta do Itaú da Ana")])
    sync.sync_pluggy()
    movs = analytics.cash_transactions()
    orfas = analytics.unmatched_transfers(movs, "2000-01-01")
    assert [t["description"] for t in orfas] == ["Pix para a conta do Itaú da Ana"]


def test_mesmo_cpf_nos_dois_lados_continua_transferencia_propria(casal, pluggy):
    household.update_member(1, cpf=CPF_GABRIEL)
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[
        _pix("g1", ONTEM, -500, CPF_GABRIEL, CPF_GABRIEL, "Transferência para o Itaú")])
    sync.sync_pluggy()
    t = next(t for t in analytics.cash_transactions() if t["description"] == "Transferência para o Itaú")
    assert t["category"] == "Transferência própria"


def test_visao_do_titular_so_traz_os_lancamentos_dele(casal, pluggy):
    pluggy.itens[ITEM_GABRIEL] = _bundle(ITEM_GABRIEL, "gabriel", pix=[_pix("g1", ONTEM, -250, None, None, "Pix enviado")])
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", pix=[_pix("a1", HOJE, 250, None, None, "Pix recebido")])
    sync.sync_pluggy()
    ana = analytics.cash_transactions(member=casal)
    assert [t["description"] for t in ana] == ["Pix recebido"]
    # a conciliação olhou a casa toda antes de filtrar
    assert ana[0]["category"] == "Transferência entre titulares"


# ---------------------------------------------------------------- várias conexões

def test_cada_conexao_usa_as_proprias_credenciais(casal, pluggy):
    segunda = household.create_connection("Pluggy da Ana")
    household.add_items(segunda, ITEM_ANA, casal)
    security.save_secret(*household.secret_names(segunda)[:1], "id-ana")
    security.save_secret(household.secret_names(segunda)[1], "segredo-ana")
    resultado = sync.sync_pluggy()
    assert resultado["status"] == "success"
    assert pluggy.sessoes == ["id-casal", "id-ana"]
    assert household.secret_names(1) == ("pluggy_client_id", "pluggy_client_secret")
    assert household.secret_names(segunda) == (f"pluggy_client_id:{segunda}", f"pluggy_client_secret:{segunda}")


def test_conexao_com_credencial_recusada_nao_barra_as_outras(casal, pluggy):
    segunda = household.create_connection("XP da Ana")
    household.add_items(segunda, ITEM_XP, casal)
    id_key, secret_key = household.secret_names(segunda)
    security.save_secret(id_key, "recusado")
    security.save_secret(secret_key, "x")
    resultado = sync.sync_pluggy()
    assert resultado["status"] == "partial"
    assert "XP da Ana: Credenciais Pluggy inválidas" in resultado["message"]
    assert db.rows("SELECT COUNT(*) FROM sync_run WHERE status = 'failed' AND source = 'Meu Pluggy · XP da Ana'")[0][0] == 1
    assert analytics.Book().qty_at(_itsa(), HOJE) == 140 * 1_000_000


def test_conexao_sem_credenciais_nao_barra_as_outras(casal):
    segunda = household.create_connection("Sem chave")
    household.add_items(segunda, ITEM_XP, casal)
    resultado = sync.sync_pluggy()
    assert resultado["status"] == "partial" and "Sem chave: Preencha Client ID" in resultado["message"]


def test_todas_as_conexoes_falhando_levanta_erro(pluggy, cofre):
    household.add_items(1, ITEM_GABRIEL)
    with pytest.raises(sync.SyncError, match="Client ID"):
        sync.sync_pluggy()


def test_sem_item_nenhum_pede_item_id(pluggy):
    with pytest.raises(sync.SyncError, match="Item ID"):
        sync.sync_pluggy()


def test_item_id_colado_em_outra_conexao_muda_de_conexao(casal):
    segunda = household.create_connection("Outra")
    resultado = household.add_items(segunda, f"https://dashboard.pluggy.ai/items/{ITEM_ANA}", casal)
    assert (resultado["added"], resultado["moved"]) == (0, 1)
    assert {i["item_id"]: i["connection_id"] for i in household.items()}[ITEM_ANA] == segunda


def test_excluir_conexao_mantem_contas_e_nao_exclui_a_principal(casal):
    sync.sync_pluggy()
    segunda = household.create_connection("Outra")
    household.add_items(segunda, ITEM_ANA, casal)
    assert household.delete_connection(segunda) == [f"pluggy_client_id:{segunda}", f"pluggy_client_secret:{segunda}"]
    assert ITEM_ANA not in household.item_ids()
    assert _conta("Nubank / NuInvest · Ana")
    with pytest.raises(ValueError, match="principal"):
        household.delete_connection(1)


def test_sincronizar_um_item_so(casal, pluggy):
    resultado = sync.sync_pluggy(ITEM_ANA)
    assert resultado["status"] == "success"
    assert not db.rows("SELECT 1 FROM financial_account WHERE account_name = 'Nubank ••••0001'")


# ---------------------------------------------------------------- metas por titular

def test_titular_sem_metas_proprias_usa_as_da_casa(casal):
    targets.save(3_000_000, 0.4, 0.6, None)
    metas = targets.load(casal)
    assert (metas["fixed_pct"], metas["own"]) == (0.4, False)


def test_metas_proprias_do_titular_e_voltar_para_as_da_casa(casal):
    targets.save(3_000_000, 0.4, 0.6, None)
    targets.save(1_000_000, 0.8, None, None, member=casal)
    assert targets.load(casal)["fixed_pct"] == 0.8 and targets.load(casal)["own"]
    assert targets.load()["fixed_pct"] == 0.4
    targets.clear(casal)
    assert targets.load(casal)["fixed_pct"] == 0.4


def test_balanco_do_titular_usa_as_metas_dele(casal):
    sync.sync_pluggy()
    targets.save(None, 0.5, 0.5, None)
    targets.save(None, 0.9, 0.1, None, member=casal)
    snap = targets.snapshot(analytics.Book(casal), analytics.Book(casal).assets())
    assert snap["targets"]["fixed_pct"] == 0.9


# ---------------------------------------------------------------- interface

def test_configuracoes_cadastra_titular_e_conexao(client, cofre):
    token = csrf(client)
    r = client.post("/configuracoes/titulares", data={"csrf_token": token, "name": "Ana", "cpf": CPF_ANA})
    assert ("success", "Ana cadastrado(a) como titular.") in avisos(r.text)
    ana = household.resolve("Ana")
    r = client.post("/configuracoes/pluggy", data={
        "csrf_token": token, "label": "Pluggy da Ana", "client_id": "id-ana", "client_secret": "seg",
        "item_ids": ITEM_ANA, "member_id": str(ana),
    })
    assert avisos(r.text)[0][0] == "success"
    conexao = next(c for c in household.connections() if c["label"] == "Pluggy da Ana")
    assert cofre.dados[(security.SERVICE_NAME, f"pluggy_client_id:{conexao['id']}")] == "id-ana"
    assert [(i["item_id"], i["member_id"]) for i in conexao["items"]] == [(ITEM_ANA, ana)]
    pagina = client.get("/configuracoes").text
    assert "Pluggy da Ana" in pagina and "Ana" in pagina


def test_conexao_nova_sem_credenciais_e_recusada(client):
    r = client.post("/configuracoes/pluggy", data={"csrf_token": csrf(client), "label": "X", "item_ids": ITEM_ANA})
    assert avisos(r.text)[0][0] == "error"
    assert [c["id"] for c in household.connections()] == [1]


def test_cpf_invalido_pela_interface(client):
    r = client.post("/configuracoes/titulares", data={"csrf_token": csrf(client), "name": "Ana", "cpf": "123"})
    assert ("error", "CPF inválido. Confira os 11 dígitos.") in avisos(r.text)


def test_excluir_conexao_pela_interface_apaga_os_segredos(client, cofre):
    token = csrf(client)
    client.post("/configuracoes/pluggy", data={"csrf_token": token, "label": "Extra", "client_id": "a", "client_secret": "b"})
    extra = next(c for c in household.connections() if c["label"] == "Extra")["id"]
    client.post("/configuracoes/pluggy/excluir", data={"csrf_token": token, "connection_id": str(extra)})
    assert not any(k[1].endswith(f":{extra}") for k in cofre.dados)


def test_trocar_titular_do_item_pela_interface(client, casal):
    sync.sync_pluggy()
    r = client.post("/configuracoes/pluggy/item", data={"csrf_token": csrf(client), "item_id": ITEM_ANA, "member_id": "1"})
    assert ("success", "Item agora é de Gabriel; 3 conta(s) atualizada(s).") in avisos(r.text)


def test_seletor_so_aparece_com_dois_titulares(client):
    assert 'class="member-switch"' not in client.get("/").text
    household.add_member("Ana")
    assert 'class="member-switch"' in client.get("/").text


def test_seletor_filtra_as_telas(client, casal):
    sync.sync_pluggy()
    token = csrf(client)
    client.post("/titular", data={"csrf_token": token, "member": str(casal), "back": "/contas"})
    pagina = client.get("/contas").text
    assert "Mostrando só as contas de <b>Ana</b>" in pagina
    assert "Nubank ••••0002 · Ana" in pagina and "Nubank ••••0001" not in pagina
    client.post("/titular", data={"csrf_token": token, "member": "casa"})
    pagina = client.get("/contas").text
    assert "Nubank ••••0001" in pagina and "Mostrando só" not in pagina


def test_metas_pela_interface_na_visao_do_titular(client, casal):
    token = csrf(client)
    client.post("/titular", data={"csrf_token": token, "member": str(casal)})
    r = client.post("/metas", data={"csrf_token": token, "reserve": "10.000", "fixed_pct": "70"})
    assert ("success", "Metas de Ana salvas.") in avisos(r.text)
    assert targets.load(casal)["fixed_pct"] == 0.7 and targets.load()["fixed_pct"] is None
    client.post("/metas", data={"csrf_token": token, "use_household": "on"})
    assert not targets.load(casal)["own"]


def test_titular_escolhido_e_excluido_volta_para_a_casa(client):
    bia = household.add_member("Bia")["id"]
    token = csrf(client)
    client.post("/titular", data={"csrf_token": token, "member": str(bia)})
    client.post("/configuracoes/titulares/excluir", data={"csrf_token": token, "member_id": str(bia)})
    assert "Mostrando só" not in client.get("/").text


def test_seletor_recusa_voltar_para_fora_do_app(client):
    household.add_member("Ana")
    r = client.post("/titular", data={"csrf_token": csrf(client), "member": "casa", "back": "//exemplo.com"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


PAGINAS = ["/", "/carteira", "/ativo/ITSA4", "/metas", "/recomendacoes", "/renda-fixa", "/rendimentos",
           "/previdencia", "/contas", "/conciliacao", "/configuracoes", "/importar"]


@pytest.mark.parametrize("rota", PAGINAS)
@pytest.mark.parametrize("visao", ["casa", "ana"])
def test_paginas_abrem_na_visao_da_casa_e_do_titular(client, casal, rota, visao):
    sync.sync_pluggy()
    client.post("/titular", data={"csrf_token": csrf(client), "member": visao})
    resposta = client.get(rota)
    assert resposta.status_code == 200, f"{rota} ({visao}) respondeu {resposta.status_code}"


# ---------------------------------------------------------------- linha de comando

def _json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_cli_titulares(capsys, casal):
    sync.sync_pluggy()
    cli.main(["titulares"])
    saida = _json(capsys)
    ana = next(t for t in saida["titulares"] if t["nome"] == "Ana")
    assert "Nubank / NuInvest · Ana" in {c["conta"] for c in ana["contas"]}
    assert saida["conexoes_pluggy"][0]["itens"][1]["titular"] == "Ana"
    assert saida["visao_da_casa"] is True
    assert "segredo" not in json.dumps(saida)


def test_cli_carteira_por_titular(capsys, casal):
    sync.sync_pluggy()
    cli.main(["--titular", "ana", "carteira", "posicoes"])
    assert [p["quantidade"] for p in _json(capsys)["posicoes"]] == [40]
    cli.main(["carteira", "posicoes"])
    assert [p["quantidade"] for p in _json(capsys)["posicoes"]] == [140]


def test_cli_contexto_diz_de_quem_e(capsys, casal):
    sync.sync_pluggy()
    cli.main(["--titular", "Ana", "carteira", "contexto"])
    saida = _json(capsys)
    assert saida["titular"] == "Ana" and saida["titulares"] == ["Gabriel", "Ana"]
    assert saida["metas_e_balanco"]["metas"]["de"] == "casa (titular sem metas próprias)"


def test_cli_gastos_trazem_o_titular(capsys, casal, pluggy):
    pluggy.itens[ITEM_ANA] = _bundle(ITEM_ANA, "ana", pix=[_pix("a1", HOJE, -35, None, None, "Padaria")])
    sync.sync_pluggy()
    cli.main(["--titular", "Ana", "gastos", "listar"])
    assert [(t["descricao"], t["titular"]) for t in _json(capsys)["lancamentos"]] == [("Padaria", "Ana")]


def test_cli_metas_do_titular(capsys, casal):
    cli.main(["--titular", "Ana", "metas", "definir", "--renda-fixa", "60"])
    capsys.readouterr()
    assert targets.load(casal)["fixed_pct"] == 0.6 and targets.load()["fixed_pct"] is None


def test_cli_titular_desconhecido(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--titular", "Zé", "carteira", "posicoes"])
    assert "não encontrado" in _json(capsys)["erro"]
