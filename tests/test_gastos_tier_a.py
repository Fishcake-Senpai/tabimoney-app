"""Testes das features de fundação de Gastos (Tier A):
1. Criar e editar lançamento à mão (+ sugestões de descrição e exclusão reversível)
2. Ignorar lançamento e tirar do resultado (por lançamento e por categoria)
3. Recategorizar em lote pela interface
4. Desfazer uma importação (caixa + posições/eventos de investimento)
5. Exportar lançamentos em CSV (todos, filtrados e selecionados)
6. Pendências que não voltam (dispensar + expiração de 2 meses)
7. Contas fixas com baixa automática (frequências, dia útil, baixa no OFX/CSV sem duplicar)
8. Comprovantes nos lançamentos (upload, download, contagem, exclusão e validação)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import db
from app.agente import operacoes as op
from app.services import analytics, recurring, smart_import, spending
from app.services import transactions as tx_service


def _csrf(client, path="/contas/lancamentos"):
    resp = client.get(path)
    assert resp.status_code == 200
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    assert m, f"csrf_token não encontrado em {path}"
    return m.group(1)


# ---------------------------------------------------------------- 1. Criar e editar lançamento à mão

def test_criar_editar_excluir_lancamento_manual(client):
    created = tx_service.create_transaction(
        account_id="dinheiro",
        transaction_date="2026-11-10",
        description="Padaria do Bairro",
        amount_cents=-2350,
        category="Alimentação",
        note="Pão e café",
    )
    assert created["source"] == "manual"
    assert created["amount_cents"] == -2350
    assert created["account_name"] == tx_service.CASH_ACCOUNT_NAME

    # Sugestões de descrição trazem o lançamento criado
    assert "Padaria do Bairro" in tx_service.description_suggestions("padaria")

    # Editar data, descrição, valor, nota e categoria
    updated = tx_service.update_transaction(
        created["id"],
        transaction_date="2026-11-11",
        description="Padaria Central",
        amount_cents=-3000,
        category="Mercado",
        note="Atualizado",
    )
    assert updated["description"] == "Padaria Central"
    assert updated["transaction_date"] == "2026-11-11"
    assert updated["amount_cents"] == -3000
    assert updated["category"] == "Mercado"
    assert updated["note"] == "Atualizado"

    # Via rota web
    token = _csrf(client)
    resp = client.post(
        "/contas/lancamentos/novo",
        data={
            "csrf_token": token, "account_id": "dinheiro", "transaction_date": "2026-11-12",
            "description": "Reembolso amigo", "amount": "50,00", "kind": "in", "category": "Outros",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    txs = analytics.cash_transactions()
    assert any(t["description"] == "Reembolso amigo" and t["amount_cents"] == 5000 for t in txs)

    # Exclusão reversível de lançamento manual
    res = tx_service.delete_transaction(created["id"])
    assert res["excluido"] is True
    assert all(t["id"] != created["id"] for t in analytics.cash_transactions())


# ---------------------------------------------------------------- 2. Ignorar / tirar do resultado

def test_ignorar_e_tirar_do_resultado():
    t1 = tx_service.create_transaction(
        account_id="dinheiro", transaction_date="2026-11-05",
        description="Almoço", amount_cents=-5000, category="Alimentação",
    )
    t2 = tx_service.create_transaction(
        account_id="dinheiro", transaction_date="2026-11-06",
        description="Compra de terceiro", amount_cents=-12000, category="Compras",
        exclude_from_pnl=True,
    )
    t3 = tx_service.create_transaction(
        account_id="dinheiro", transaction_date="2026-11-07",
        description="Estorno duplicado", amount_cents=-8000, category="Compras",
    )
    tx_service.set_flags([t3["id"]], is_ignored=True)

    # Sem include_ignored: t3 some completamente
    visible = analytics.cash_transactions()
    ids = {t["id"] for t in visible}
    assert t1["id"] in ids and t2["id"] in ids and t3["id"] not in ids

    # Com include_ignored: t3 aparece marcado
    all_tx = analytics.cash_transactions(include_ignored=True)
    assert any(t["id"] == t3["id"] and t["is_ignored"] for t in all_tx)

    # Fluxo de caixa e gastos por categoria só contam t1 (R$ 50)
    flow = analytics.cash_flow(visible)
    assert flow[-1]["out"] == 5000
    by_cat = analytics.spending_by_category(visible, "2026-11-01")
    assert sum(c["value"] for c in by_cat) == 5000

    # Categoria marcada como fora do resultado também sai do P&L
    tx_service.set_category_exclude_from_pnl("Alimentação", True)
    visible2 = analytics.cash_transactions()
    assert analytics.spending_by_category(visible2, "2026-11-01") == []


# ---------------------------------------------------------------- 3. Recategorizar em lote

def test_recategorizar_em_lote_web(client):
    t1 = tx_service.create_transaction(account_id="dinheiro", transaction_date="2026-11-01", description="Item A", amount_cents=-1000, category="Outros")
    t2 = tx_service.create_transaction(account_id="dinheiro", transaction_date="2026-11-02", description="Item B", amount_cents=-2000, category="Outros")
    token = _csrf(client)
    resp = client.post(
        "/contas/lancamentos/lote",
        data={"csrf_token": token, "ids": [str(t1["id"]), str(t2["id"])], "action": "recategorizar", "category": "Lazer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    by_id = {t["id"]: t for t in analytics.cash_transactions()}
    assert by_id[t1["id"]]["category"] == "Lazer"
    assert by_id[t2["id"]]["category"] == "Lazer"


# ---------------------------------------------------------------- 4. Desfazer importação

def test_desfazer_importacao_csv_e_reimportar():
    csv_bytes = (
        "Data,Valor,Identificador,Descrição\n"
        "01/11/2026,-45.90,id-undo-1,Uber Viagem\n"
        "02/11/2026,-120.00,id-undo-2,Supermercado Extra\n"
    ).encode("utf-8")
    res = smart_import.import_file("extrato_nubank.csv", csv_bytes)
    assert res.count == 2
    assert len(analytics.cash_transactions()) == 2

    run = db.rows("SELECT id, undone_at FROM sync_run ORDER BY id DESC LIMIT 1")[0]
    assert run["undone_at"] is None

    undone = tx_service.undo_import(run["id"])
    assert undone["lancamentos"] == 2
    assert analytics.cash_transactions() == []

    # Não pode desfazer duas vezes
    with pytest.raises(ValueError, match="já foi desfeita"):
        tx_service.undo_import(run["id"])

    # Reimportar o mesmo arquivo restaura os lançamentos (limpa deleted_at)
    res2 = smart_import.import_file("extrato_nubank.csv", csv_bytes)
    assert res2.count == 2
    assert len(analytics.cash_transactions()) == 2


# ---------------------------------------------------------------- 5. Exportar CSV

def test_exportar_csv_web_e_lote(client):
    t1 = tx_service.create_transaction(account_id="dinheiro", transaction_date="2026-11-03", description="Café", amount_cents=-1550, category="Alimentação")
    t2 = tx_service.create_transaction(account_id="dinheiro", transaction_date="2026-11-04", description="Cinema", amount_cents=-4200, category="Lazer")

    resp = client.get("/csv/lancamentos.csv?categoria=Lazer")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "Cinema" in text and "Café" not in text
    assert "-42,00" in text

    token = _csrf(client)
    resp_sel = client.post(
        "/contas/lancamentos/lote",
        data={"csrf_token": token, "ids": [str(t1["id"])], "action": "csv"},
    )
    assert resp_sel.status_code == 200
    text_sel = resp_sel.content.decode("utf-8-sig")
    assert "Café" in text_sel and "Cinema" not in text_sel


# ---------------------------------------------------------------- 6. Pendências que não voltam

def test_pendencias_dispensadas_e_expiracao():
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    old_date = (date.today() - timedelta(days=75)).isoformat()
    t_recent = tx_service.create_transaction(
        account_id="dinheiro", transaction_date=recent_date,
        description="Transferência própria recente", amount_cents=-50000, category="Transferência própria",
    )
    tx_service.create_transaction(
        account_id="dinheiro", transaction_date=old_date,
        description="Transferência própria antiga", amount_cents=-30000, category="Transferência própria",
    )

    txs = analytics.cash_transactions()
    orphan_since = (date.today() - timedelta(days=tx_service.PENDING_EXPIRY_DAYS)).isoformat()
    orphans = analytics.unmatched_transfers(txs, orphan_since, dismissed=tx_service.dismissed_keys("transfer_orphan"))
    # A antiga (> 60 dias) já expirou; só a recente aparece
    assert [o["id"] for o in orphans] == [t_recent["id"]]

    # Dispensar tira da fila permanentemente
    tx_service.dismiss_pending("transfer_orphan", str(t_recent["id"]))
    orphans_after = analytics.unmatched_transfers(txs, orphan_since, dismissed=tx_service.dismissed_keys("transfer_orphan"))
    assert orphans_after == []


# ---------------------------------------------------------------- 7. Contas fixas com baixa automática

def test_contas_fixas_dia_util_e_baixa_automatica():
    # 2026-11-07 é sábado -> com adjust_business_day vira segunda 2026-11-09
    assert recurring.adjust_to_business_day(date(2026, 11, 7)) == date(2026, 11, 9)
    assert recurring.adjust_to_business_day(date(2026, 11, 8)) == date(2026, 11, 9)

    aid = tx_service.ensure_cash_account()
    rec = recurring.save_recurring(
        account_id=aid,
        description="Internet Fibra",
        amount_cents=-13990,
        frequency="monthly",
        day_of_month=7,
        start_date="2026-11-01",
        category="Casa",
        adjust_business_day=True,
        match_pattern="VIVO FIBRA",
    )

    sched_before = recurring.month_schedule("2026-11", today=date(2026, 11, 10))
    assert len(sched_before["items"]) == 1
    assert sched_before["items"][0]["due_date"] == "2026-11-09"
    assert sched_before["items"][0]["status"] == "atrasado"
    assert sched_before["total_pending_cents"] == 13990

    # Chega o lançamento real no extrato -> baixa automática sem duplicar
    tx = tx_service.create_transaction(
        account_id=aid, transaction_date="2026-11-09",
        description="PAGTO VIVO FIBRA 11/2026", amount_cents=-13990,
    )
    matched = recurring.match_recurring(window_start=date(2026, 11, 1), window_end=date(2026, 11, 30), today=date(2026, 11, 10))
    assert matched == 1

    sched_after = recurring.month_schedule("2026-11", today=date(2026, 11, 10))
    assert sched_after["items"][0]["status"] == "pago"
    assert sched_after["items"][0]["transaction_id"] == tx["id"]
    assert sched_after["total_paid_cents"] == 13990
    assert sched_after["total_pending_cents"] == 0
    # Só existe 1 lançamento (não duplicou)
    assert len(analytics.cash_transactions()) == 1


# ---------------------------------------------------------------- 8. Comprovantes nos lançamentos

def test_comprovantes_upload_download_exclusao(client):
    tx = tx_service.create_transaction(
        account_id="dinheiro", transaction_date="2026-11-15",
        description="Consulta médica", amount_cents=-35000, category="Saúde",
    )
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    token = _csrf(client)
    resp = client.post(
        f"/contas/lancamentos/{tx['id']}/comprovantes",
        data={"csrf_token": token, "back": "/contas/lancamentos"},
        files={"file": ("recibo_medico.png", png_bytes, "image/png")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    atts = tx_service.list_attachments(tx["id"])
    assert len(atts) == 1
    assert atts[0]["filename"] == "recibo_medico.png"

    # Contagem aparece em cash_transactions
    tx_row = next(t for t in analytics.cash_transactions() if t["id"] == tx["id"])
    assert tx_row["attachment_count"] == 1

    # Download devolve o arquivo
    dl = client.get(f"/comprovantes/{atts[0]['id']}")
    assert dl.status_code == 200
    assert dl.content == png_bytes

    # Tipo inválido é rejeitado
    with pytest.raises(ValueError, match="Tipo de arquivo"):
        tx_service.add_attachment(tx["id"], "script.exe", b"MZ")

    # Exclusão remove da lista
    tx_service.delete_attachment(atts[0]["id"])
    assert tx_service.list_attachments(tx["id"]) == []


# ---------------------------------------------------------------- Operações de agente (MCP/CLI)

def test_operacoes_agente_tier_a(tmp_path):
    created = op.gastos_criar_lancamento("2026-11-18", "Farmácia", 89.9, tipo="saida", categoria="Saúde")
    assert created["valor"] == -89.9
    edited = op.gastos_editar_lancamento(created["id"], nota="Receita médica")
    assert edited["nota"] == "Receita médica"
    ign = op.gastos_ignorar([created["id"]], fora_do_resultado=True)
    assert ign["atualizados"] == 1
    csv_res = op.gastos_exportar_csv(arquivo=str(tmp_path / "out.csv"))
    assert csv_res["lancamentos"] == 1
    assert (tmp_path / "out.csv").exists()

    fixa = op.contas_fixas_salvar("Academia", 129.9, frequencia="monthly", dia=10, categoria="Saúde")
    listed = op.contas_fixas_listar("2026-11")
    assert any(c["id"] == fixa["id"] for c in listed["cadastradas"])
    removed = op.contas_fixas_remover(fixa["id"])
    assert removed["excluida"] is True
