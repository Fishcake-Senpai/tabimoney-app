"""Histórico completo: contas recentes não cortam investimentos antigos."""
import json
import re
from datetime import date

import pytest

from app import db
from app.services import analytics, spending


@pytest.fixture
def historico():
    with db.transaction() as con:
        con.executemany(
            "INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
            "VALUES (?, 'Fictício', ?, ?, 'manual', ?)",
            [(1, 'Corretora', 'INVESTMENT', 'invest'), (2, 'Banco', 'BANK', 'bank')],
        )
        con.execute("INSERT INTO instrument(id, ticker, name, asset_class) VALUES (1, 'TEST3', 'Fictícia', 'Ação')")
        con.execute(
            "INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
            "VALUES (1, 1, 'manual', '2023-09-01', 1000000)"
        )
        con.executemany(
            "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) VALUES (1, ?, ?, 'manual')",
            [('2023-09-01', 10000), ('2025-09-01', 11000), ('2025-09-30', 12000), ('2025-10-01', 12000)],
        )
        con.execute(
            "INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
            "VALUES (2, 'manual', '2025-10-02', 100000)"
        )
        con.execute(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', 'salary', '2025-10-01', 'Salário', 1000, 'Salário')"
        )
    return analytics.Book()


def payload(response, name):
    return json.loads(re.search(r'<script[^>]*id="' + name + r'"[^>]*>(.*?)</script>', response.text, re.S)[1])


def test_conta_recente_nao_corta_setembro_da_carteira(historico, client):
    points = payload(client.get('/carteira'), 'data-returns')['series']
    assert points[0]['d'] == '2023-09-01'
    assert next(p['r'] for p in points if p['d'] == '2025-09-30') == pytest.approx(12000 / 11000 - 1)
    assert historico.twr('2023-08-31') == pytest.approx(0.2)
    invested = payload(client.get('/investimentos'), 'data-invested-total')
    assert invested[0]['d'] == '2023-09-01'


def test_patrimonio_nao_inventa_saldo_antes_da_cobertura(historico, client):
    points = payload(client.get('/'), 'data-net-worth')
    assert points[0]['d'] == '2025-10-01'
    assert points[0]['nw'] == 112000
    assert 'Histórico do patrimônio disponível desde' in client.get('/').text


def test_cartao_recem_conectado_sem_movimentos_nao_corta_patrimonio(historico, client):
    # Regressão: um cartão conectado ontem, sem lançamentos, escondia um ano de patrimônio.
    with db.transaction() as con:
        con.execute(
            "INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
            "VALUES (3, 'Fictício', 'Cartão', 'CREDIT', 'manual', 'card')"
        )
        con.execute(
            "INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
            "VALUES (3, 'manual', '2026-09-23', -5000)"
        )
    points = payload(client.get('/'), 'data-net-worth')
    assert points[0]['d'] == '2025-10-01'


def test_fluxo_e_categoria_preservam_mais_de_tres_anos():
    tx = [dict(id=i, transaction_date=f'{year}-{month:02d}-01', amount_cents=-100,
               category='Mercado', description='Compra', account_name='Banco', account_type='BANK', status='POSTED')
          for i, (year, month) in enumerate((y, m) for y in range(2022, 2026) for m in range(1, 13))]
    detail = spending.category_detail(tx, 'Mercado', today=date(2025, 12, 15))
    assert len(detail['months']) == 48
    flow = analytics.cash_flow(tx, months=None)
    assert len(flow) == 48 and flow[0] == {'m': '2022-01', 'in': 0, 'out': 100, 'net': -100}
    detail = spending.category_detail(tx, 'Mercado', today=date(2025, 12, 15))
    assert len(detail['months']) == 48
    assert detail['avg12'] == 100


def test_gastos_permite_navegar_a_mes_mais_antigo_que_12m(client, historico):
    with db.transaction() as con:
        con.execute(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', 'old', '2023-09-01', 'Compra', -500, 'Mercado')"
        )
        con.executemany(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', ?, ?, 'Compra', -500, 'Mercado')",
            [(f'older-{m}', f'2024-{m:02d}-01') for m in range(1, 13)],
        )
    response = client.get('/contas?mes=2023-09')
    points = payload(response, 'data-cash-flow')
    assert points[0]['m'] == '2023-09' and points[0]['out'] == 500


def test_rentabilidade_mensal_sem_corte(historico):
    months = historico.monthly_returns(months=None)
    assert months[0]['m'] == '2023-09'


@pytest.mark.parametrize('day, months, expected', [
    ('2026-10-31', 1, '2026-09-30'),
    ('2024-03-31', 1, '2024-02-29'),
    ('2024-02-29', 12, '2023-02-28'),
    ('2026-10-01', 36, '2023-10-01'),
])
def test_periodos_respeitam_calendario(day, months, expected):
    assert analytics._shift_months(day, months) == expected


def test_pix_em_fim_de_semana_nao_altera_volatilidade(historico):
    from datetime import timedelta
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(35)]
    with db.transaction() as con:
        con.execute('DELETE FROM daily_quote')
        con.executemany(
            "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) VALUES (1, ?, ?, 'manual')",
            [(d.isoformat(), 10000 + (i % 2) * 100) for i, d in enumerate(d for d in days if d.weekday() < 5)],
        )
    before = analytics.Book().risk()['volatility']
    with db.transaction() as con:
        con.executemany(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', ?, ?, 'Compra', -100, 'Mercado')",
            [(f'weekend-{i}', d.isoformat()) for i, d in enumerate(days) if d.weekday() >= 5],
        )
    assert before is not None
    assert analytics.Book().risk()['volatility'] == pytest.approx(before)


def test_atualizar_mercado_preserva_cotacoes_antigas(historico, monkeypatch):
    from app.services import sync
    monkeypatch.setattr(sync, '_fetch_history', lambda ticker, token: [('2026-10-01', 13000)])
    monkeypatch.setattr(sync, 'cdi_daily_rates', lambda since: [('2026-10-01', 0.05)])
    assert sync.sync_daily_quotes()['status'] == 'success'
    book = analytics.Book()
    assert book.quote_dates[1][0] == '2023-09-01'
    assert book.quote_values[1][0] == 10000
    assert book.quote_dates[1][-1] == '2026-10-01'
    assert book.quote_values[1][-1] == 13000


def test_extrato_antigo_nao_cria_investimento_com_cotacao_futura(historico, client):
    with db.transaction() as con:
        con.execute(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', 'earliest', '2022-01-01', 'Salário', 100, 'Salário')"
        )
    book = analytics.Book()
    # O extrato de 2022 não cria pontos de investimento antes da primeira posição e cotação.
    assert book.series(full_history=True)[0]['d'] == '2023-09-01'
    assert book.series()[0]['d'] == '2023-09-01'
    assert book.windows()['Início'] == '2023-09-01'
    assert payload(client.get('/carteira'), 'data-returns')['series'][0]['d'] == '2023-09-01'


def test_volatilidade_preserva_provento_entre_pregoes(historico):
    import math
    from datetime import timedelta
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(35)]
    with db.transaction() as con:
        con.execute('DELETE FROM daily_quote')
        con.executemany(
            "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) VALUES (1, ?, 10000, 'manual')",
            [(d.isoformat(),) for d in days if d.weekday() < 5],
        )
        con.execute(
            "INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, "
            "event_type, amount_cents) VALUES (1, 1, 'manual', 'div', '2026-01-11', 'DIVIDEND', 100)"
        )
        con.execute(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
            "amount_cents, category) VALUES (2, 'manual', 'div', '2026-01-11', 'Provento', 100, 'Proventos')"
        )
    # 25 pregões: um retorno de 1%, 24 retornos zero; desvio amostral = 1% / sqrt(25).
    assert analytics.Book().risk()['volatility'] == pytest.approx(0.01 * math.sqrt(252 / 25))



def test_ativo_com_cotacoes_recentes_nao_cria_salto(historico):
    # Regressão: a brapi grátis só traz 3 meses de cotações; o ativo já estava na carteira antes delas.
    with db.transaction() as con:
        con.execute("INSERT INTO instrument(id, ticker, name, asset_class) VALUES (2, 'TEST4', 'Fictícia B', 'Ação')")
        con.execute(
            "INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
            "VALUES (1, 2, 'manual', '2023-09-01', 10000000)"
        )
        con.execute(
            "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) "
            "VALUES (2, '2025-10-01', 100000, 'manual')"
        )
    book = analytics.Book()
    points = book.series(full_history=True)
    assert points[0]['eq'] == 10000 + 10 * 100000
    assert all(p['cap'] == points[0]['cap'] for p in points)
    # Só TEST3 subiu (100 → 120): o retorno é diluído pelo TEST4, não os 20% de TEST3 sozinho.
    assert book.twr('2023-08-31') == pytest.approx((12000 + 1_000_000) / (10000 + 1_000_000) - 1)
