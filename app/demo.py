"""Demonstração: o app com dados fictícios, numa base separada que nunca se mistura com a do usuário.

Quem entra na demonstração (botão nas boas-vindas do Início ou em Configurações › Geral, ou `financas --demo ...` na CLI) passa a ler e gravar em
`demo.sqlite3`, na mesma pasta de dados, e a usar um cofre de senhas em memória. A base real nem é aberta.
A troca vale por requisição (db.using_database e security.using_vault), então outra aba fora da demo continua
vendo os dados de verdade.

Os dados são gerados aqui, com datas relativas a hoje e sorteio de semente fixa: a demo nunca envelhece e sai
igual a cada geração. Ela é refeita quando muda a versão do app ou o dia, ou pelo botão "Recomeçar".

Mantenha a demo em dia: tela, aba ou recurso novo precisa de exemplo aqui. tests/test_demo.py abre todas as
páginas na demo e falha se alguma aparecer vazia.

Um casal fictício, Lucas (titular principal) e Marina, com:
- Nubank do Lucas (conta, cartão, NuInvest) e Itaú e XP da Marina, em duas conexões Pluggy;
- 12 meses de salário, gastos no cartão, contas da casa, Pix entre os dois, compras em dólar e estorno;
- ações, FIIs e ETF com histórico de cotações, proventos, uma venda com lucro e uma divergência de custódia;
- CDB, LCI, caixinha, Tesouro e previdência; metas de alocação (da casa e da Marina) e de gastos;
- balanços trimestrais das empresas, análises, recomendações e sugestões de orçamento do "agente".
"""
from __future__ import annotations

import math
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from app import __version__, db, security

FILE_NAME = "demo.sqlite3"
BUILT_KEY = "demo_built"
PRIMARY, PARTNER = "Lucas", "Marina"
ITEM_LUCAS = "de300000-0000-4000-8000-000000000001"
ITEM_MARINA = "de300000-0000-4000-8000-000000000002"
ITEM_XP = "de300000-0000-4000-8000-000000000003"


class MemoryVault:
    """Cofre de senhas em memória, com a mesma API do keyring. Nada da demo chega ao cofre do sistema."""

    class errors:  # noqa: N801 - mesmo nome do módulo keyring.errors
        class PasswordDeleteError(Exception):
            pass

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, name: str, value: str) -> None:
        self.data[(service, name)] = value

    def get_password(self, service: str, name: str) -> str | None:
        return self.data.get((service, name))

    def delete_password(self, service: str, name: str) -> None:
        if self.data.pop((service, name), None) is None:
            raise self.errors.PasswordDeleteError(name)


VAULT = MemoryVault()


def path() -> Path:
    return db.data_dir() / FILE_NAME


@contextmanager
def active() -> Iterator[Path]:
    """Dentro do bloco, o app inteiro usa a base e o cofre da demonstração."""
    with db.using_database(path()), security.using_vault(VAULT):
        yield path()


def _stamp() -> str:
    return f"{__version__}|{date.today().isoformat()}"


def is_fresh() -> bool:
    if not path().exists():
        return False
    try:
        with active():
            return db.get_setting(BUILT_KEY) == _stamp()
    except sqlite3.Error:
        return False


def ensure() -> Path:
    """Gera a demo se ela não existe ou é de outra versão ou de outro dia."""
    if not is_fresh():
        build()
    return path()


def build() -> Path:
    """Gera a demo do zero num arquivo temporário e só então substitui a anterior."""
    target = path()
    temporary = target.with_name(FILE_NAME + ".novo")
    temporary.unlink(missing_ok=True)
    VAULT.data.clear()
    with db.using_database(temporary), security.using_vault(VAULT):
        db.init_db()
        seed()
        db.set_setting(BUILT_KEY, _stamp())
    os.replace(temporary, target)
    return target


# ---------------------------------------------------------------- dados

def _cpf(base: str) -> str:
    digits = [int(d) for d in base]
    for size in (9, 10):
        total = sum(d * (size + 1 - i) for i, d in enumerate(digits))
        digits.append(total * 10 % 11 % 10)
    return "".join(map(str, digits))


def _month_day(today: date, months_back: int, day: int) -> date | None:
    year, month = today.year, today.month - months_back
    while month <= 0:
        year, month = year - 1, month + 12
    value = date(year, month, min(day, 28))
    return value if value <= today else None


def _business_days(start: date, end: date) -> list[date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _quarter_ends(today: date, count: int) -> list[date]:
    """Últimos trimestres já publicados (a CVM recebe o ITR uns 45 dias depois do fim do trimestre)."""
    cutoff = today - timedelta(days=45)
    year, quarter = cutoff.year, (cutoff.month - 1) // 3  # trimestre anterior ao corrente
    if quarter == 0:
        year, quarter = year - 1, 4
    ends = []
    for _ in range(count):
        month = quarter * 3
        ends.append(date(year, month, 30 if month in (6, 9) else 31))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return sorted(ends)


def _label(quarter_end: date) -> str:
    return f"{quarter_end.month // 3}T{str(quarter_end.year)[2:]}"


# (ticker, nome, classe, preço inicial em centavos, volatilidade diária, tendência diária)
ASSETS = [
    ("ITSA4", "Itaúsa", "Ação", 980, 0.011, 0.0006),
    ("EGIE3", "Engie Brasil", "Ação", 4150, 0.010, -0.0002),
    ("BBAS3", "Banco do Brasil", "Ação", 2600, 0.014, 0.0004),
    ("TAEE11", "Taesa", "Ação", 3450, 0.009, 0.0003),
    ("WEGE3", "WEG", "Ação", 4700, 0.013, 0.0008),
    ("PETR4", "Petrobras", "Ação", 3700, 0.016, -0.0004),
    ("HGLG11", "CSHG Logística", "FII", 15800, 0.006, 0.0002),
    ("KNRI11", "Kinea Renda Imobiliária", "FII", 14600, 0.006, 0.0001),
    ("IVVB11", "iShares S&P 500", "ETF", 31000, 0.009, 0.0007),
]
# proventos por cota/ação em centavos: (tipo, meses em que paga, valor)
INCOME_RULES = {
    "ITSA4": ("JCP", (1, 4, 7, 10), 2), "EGIE3": ("DIVIDEND", (4, 10), 120), "BBAS3": ("JCP", (3, 6, 9, 12), 45),
    "TAEE11": ("DIVIDEND", (2, 5, 8, 11), 95), "WEGE3": ("JCP", (3, 9), 18), "HGLG11": ("INCOME", tuple(range(1, 13)), 110),
    "KNRI11": ("INCOME", tuple(range(1, 13)), 100),
}
# (conta, ticker, [(dias atrás, quantidade)]); quantidade negativa é venda
TRADES = [
    (3, "ITSA4", [(330, 400), (150, 400)]),
    (3, "EGIE3", [(300, 200)]),
    (3, "BBAS3", [(250, 300)]),
    (3, "HGLG11", [(280, 40), (90, 20)]),
    (3, "IVVB11", [(200, 30), (60, 10)]),
    (3, "PETR4", [(380, 200), (120, -200)]),
    (6, "ITSA4", [(320, 300)]),
    (6, "TAEE11", [(240, 200)]),
    (6, "KNRI11", [(270, 50)]),
    (6, "WEGE3", [(180, 80)]),
]
REPORTED_EXTRA = {(6, "TAEE11"): 20}  # bonificação que a corretora mostra e as movimentações ainda não trazem


class _Seeder:
    def __init__(self, today: date) -> None:
        self.today = today
        self.rng = random.Random(2026)
        self.tx_count = 0
        self.quotes: dict[str, dict[str, int]] = {}
        self.instruments: dict[str, int] = {}

    # ------------------------------------------------------------ titulares e conexões
    def household(self) -> int:
        from app.services import household

        household.update_member(1, PRIMARY, cpf=_cpf("529982247"))
        partner = household.add_member(PARTNER, cpf=_cpf("168995350"))["id"]
        household.rename_connection(1, "Principal")
        household.add_items(1, ITEM_LUCAS, 1)
        household.add_items(1, ITEM_MARINA, partner)
        xp = household.create_connection("XP da Marina")
        household.add_items(xp, ITEM_XP, partner)
        for connection_id in (1, xp):
            id_key, secret_key = household.secret_names(connection_id)
            security.save_secret(id_key, f"demo-client-{connection_id}")
            security.save_secret(secret_key, "demo-secret")
        security.save_secret("brapi_token", "demo-token")
        db.set_setting("display_name", PRIMARY)
        db.set_setting("daily_quotes_enabled", "0")
        from app.services import updates

        updates.set_enabled(False)
        return partner

    def accounts(self, partner: int) -> None:
        accounts = [
            (1, "Nubank", "Nubank ••••4821", "BANK", f"item:{ITEM_LUCAS}:account:demo-conta", None),
            (2, "Nubank", "Nubank Cartão ••••7730", "CREDIT", f"item:{ITEM_LUCAS}:account:demo-cartao", None),
            (3, "Nubank", "Nubank / NuInvest", "INVESTMENT", f"item:{ITEM_LUCAS}:investments", None),
            (4, "Itaú", f"Itaú ••••1190 · {PARTNER}", "BANK", f"item:{ITEM_MARINA}:account:demo-conta", partner),
            (5, "Itaú", f"Itaú Cartão ••••5502 · {PARTNER}", "CREDIT", f"item:{ITEM_MARINA}:account:demo-cartao", partner),
            (6, "XP", f"XP / Investimentos · {PARTNER}", "INVESTMENT", f"item:{ITEM_XP}:investments", partner),
        ]
        with db.transaction() as con:
            for account_id, institution, name, kind, key, member in accounts:
                con.execute(
                    "INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key, "
                    "member_id) VALUES (?, ?, ?, ?, 'pluggy', ?, ?)", (account_id, institution, name, kind, key, member),
                )

    # ------------------------------------------------------------ mercado
    def market(self) -> None:
        days = _business_days(self.today - timedelta(days=420), self.today)
        with db.transaction() as con:
            for ticker, name, asset_class, price, vol, drift in ASSETS:
                cursor = con.execute(
                    "INSERT INTO instrument(ticker, name, asset_class) VALUES (?, ?, ?)", (ticker, name, asset_class)
                )
                self.instruments[ticker] = int(cursor.lastrowid)
                value, series = float(price), {}
                for day in days:
                    value *= math.exp(self.rng.gauss(drift, vol))
                    series[day.isoformat()] = int(round(value))
                self.quotes[ticker] = series
                con.executemany(
                    "INSERT INTO daily_quote(instrument_id, trade_date, close_cents, provider) VALUES (?, ?, ?, 'brapi')",
                    [(self.instruments[ticker], day, close) for day, close in series.items()],
                )
            ibov = 124000.0
            for day in days:
                ibov *= math.exp(self.rng.gauss(0.0004, 0.009))
                con.execute("INSERT INTO benchmark_quote(code, trade_date, value, provider) VALUES ('IBOV', ?, ?, 'brapi')",
                            (day.isoformat(), round(ibov, 2)))
                con.execute("INSERT INTO benchmark_quote(code, trade_date, value, provider) VALUES ('CDI', ?, ?, 'bcb')",
                            (day.isoformat(), 0.0551))

    def price(self, ticker: str, day: date) -> int:
        series = self.quotes[ticker]
        while day.isoformat() not in series:
            day -= timedelta(days=1)
        return series[day.isoformat()]

    # ------------------------------------------------------------ movimentações
    def tx(self, con, account: int, day: date | None, description: str, cents: int, category: str,
           status: str = "POSTED", original: tuple[str, int] | None = None) -> None:
        if day is None:
            return
        self.tx_count += 1
        con.execute(
            "INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, amount_cents, "
            "status, category, original_currency, original_amount_cents) VALUES (?, 'pluggy', ?, ?, ?, ?, ?, ?, ?, ?)",
            (account, f"demo-{self.tx_count}", day.isoformat(), description, cents, status, category,
             original[0] if original else None, original[1] if original else None),
        )

    def spending(self) -> None:
        r, today = self.rng, self.today
        with db.transaction() as con:
            card_by_month: dict[tuple[int, int], int] = {}

            def buy(card: int, months_back: int, day: int, description: str, low: int, high: int, category: str,
                    original: tuple[str, int] | None = None) -> None:
                when = _month_day(today, months_back, day)
                if when is None:
                    return
                cents = -r.randint(low, high) if high > low else -low
                self.tx(con, card, when, description, cents, category, original=original)
                card_by_month[(card, months_back)] = card_by_month.get((card, months_back), 0) + cents

            for m in range(12, -1, -1):
                # Lucas: cartão
                for day in (4, 12, 23):
                    buy(2, m, day, "iFood *Restaurante", 3500, 8900, "Alimentação")
                buy(2, m, 17, "Coco Bambu Restaurante", 12000, 22000, "Alimentação")
                buy(2, m, 8, "Supermercado Pão de Açúcar", 18000, 42000, "Mercado")
                buy(2, m, 22, "Supermercado Pão de Açúcar", 15000, 30000, "Mercado")
                for day in (3, 11, 19, 26):
                    buy(2, m, day, "Uber *Trip", 1500, 4500, "Transporte")
                buy(2, m, 14, "Posto Shell", 18000, 26000, "Transporte")
                buy(2, m, 2, "Netflix.com", 5590, 5590, "Assinaturas")
                buy(2, m, 2, "Spotify", 2190, 2190, "Assinaturas")
                dollars = 2000 + (m % 3) * 50
                buy(2, m, 18, "Anthropic* Claude Pro", dollars * 56 // 10, dollars * 56 // 10, "Assinaturas",
                    original=("USD", -dollars))
                buy(2, m, 21, "Petz Pet Shop", 9000, 16000, "Outros")
                if m % 2 == 0:
                    buy(2, m, 16, "Amazon Marketplace", 8000, 30000, "Compras")
                if m % 3 == 1:
                    buy(2, m, 9, "Drogasil", 3000, 9000, "Saúde")
                # Marina: cartão
                buy(5, m, 7, "Carrefour Hiper", 20000, 50000, "Mercado")
                buy(5, m, 24, "Carrefour Hiper", 15000, 35000, "Mercado")
                buy(5, m, 13, "Drogaria São Paulo", 4000, 12000, "Saúde")
                for day in (6, 20):
                    buy(5, m, day, "Rappi *Restaurante", 4000, 9000, "Alimentação")
                for day in (5, 15, 25):
                    buy(5, m, day, "99 Pop", 1200, 3800, "Transporte")
                buy(5, m, 10, "Lojas Renner", 10000, 30000, "Compras")
                buy(5, m, 1, "Disney Plus", 3390, 3390, "Assinaturas")
                buy(5, m, 12, "Alura Cursos", 9900, 9900, "Educação")
                if m % 2 == 1:
                    buy(5, m, 27, "Livraria Cultura", 6000, 15000, "Educação")
                # contas e salários
                self.tx(con, 1, _month_day(today, m, 5), "PAGTO SALARIO ACME TECNOLOGIA LTDA", 850000, "Salário")
                self.tx(con, 4, _month_day(today, m, 1), "SALARIO EMPRESA BETA SA", 650000, "Salário")
                self.tx(con, 1, _month_day(today, m, 6), "Pix enviado|Marina Souza", -150000, "Pix e transferências")
                self.tx(con, 4, _month_day(today, m, 6), "Pix recebido|Lucas Almeida", 150000, "Pix e transferências")
                self.tx(con, 1, _month_day(today, m, 7), "Aplicação RDB Caixinha Reserva", -300000, "Investimentos")
                self.tx(con, 1, _month_day(today, m, 8), "Aplicação NuInvest", -150000, "Investimentos")
                self.tx(con, 1, _month_day(today, m, 12), "SMART FIT ACADEMIA", -12990, "Outros")
                self.tx(con, 1, _month_day(today, m, 15), "Pix enviado|João Pereira", -r.randint(8000, 25000),
                        "Pix e transferências")
                self.tx(con, 4, _month_day(today, m, 3), "Aluguel Imobiliária Lar", -280000, "Casa")
                self.tx(con, 4, _month_day(today, m, 8), "Enel Distribuição Energia", -r.randint(18000, 26000), "Casa")
                self.tx(con, 4, _month_day(today, m, 9), "Vivo Fibra Internet", -12990, "Casa")
                self.tx(con, 4, _month_day(today, m, 12), "TED para XP Investimentos", -200000, "Investimentos")
            # viagem, estorno, transferência sem o outro lado e compras que ainda não fecharam
            buy(2, 4, 11, "Latam Airlines", 168000, 168000, "Viagem")
            buy(2, 4, 13, "Airbnb", 92000, 92000, "Viagem")
            self.tx(con, 2, _month_day(today, 1, 20), "Estorno Amazon Marketplace", 8990, "Compras")
            card_by_month[(2, 1)] = card_by_month.get((2, 1), 0) + 8990
            self.tx(con, 1, _month_day(today, 2, 25), "Transferência para conta Inter", -50000, "Transferência própria")
            self.tx(con, 2, today, "iFood *Restaurante", -4790, "Alimentação", status="PENDING")
            self.tx(con, 5, today + timedelta(days=30), "Magazine Luiza 3/10", -18900, "Compras", status="PENDING")
            # fatura: no dia 10, a conta paga o cartão do mês anterior
            for card, bank in ((2, 1), (5, 4)):
                for m in range(11, -1, -1):
                    due = -card_by_month.get((card, m + 1), 0)
                    when = _month_day(today, m, 10)
                    if due and when:
                        self.tx(con, bank, when, "Pagamento de fatura", -due, "Pagamento de fatura")
                        self.tx(con, card, when, "Pagamento recebido", due, "Pagamento de fatura")

    # ------------------------------------------------------------ investimentos
    def investments(self) -> None:
        today = self.today
        with db.transaction() as con:
            n = 0
            for account, ticker, trades in TRADES:
                iid = self.instruments[ticker]
                first = today - timedelta(days=max(d for d, _ in trades) + 1)
                n += 1
                con.execute(
                    "INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, event_type, "
                    "quantity_micros, amount_cents, description) VALUES (?, ?, 'pluggy', ?, ?, 'OPENING', 0, 0, "
                    "'Início do histórico')", (account, iid, f"demo-ev-{n}", first.isoformat()),
                )
                held: list[tuple[date, int]] = []
                for days_ago, quantity in trades:
                    day = today - timedelta(days=days_ago)
                    price = self.price(ticker, day)
                    n += 1
                    con.execute(
                        "INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, "
                        "event_type, quantity_micros, amount_cents, unit_price_cents) VALUES (?, ?, 'pluggy', ?, ?, ?, ?, ?, ?)",
                        (account, iid, f"demo-ev-{n}", day.isoformat(), "BUY" if quantity > 0 else "SELL",
                         quantity * 1_000_000, abs(quantity) * price, price),
                    )
                    held.append((day, quantity))
                # proventos: evento no ativo e crédito na conta de quem tem
                rule = INCOME_RULES.get(ticker)
                bank = 1 if account == 3 else 4
                for m in range(13, -1, -1):
                    pay_day = _month_day(today, m, 15)
                    if rule is None or pay_day is None or pay_day.month not in rule[1]:
                        continue
                    quantity = sum(q for d, q in held if d < pay_day - timedelta(days=10))
                    if quantity <= 0:
                        continue
                    amount = quantity * rule[2]
                    n += 1
                    con.execute(
                        "INSERT INTO investment_event(account_id, instrument_id, source, external_id, event_date, "
                        "event_type, quantity_micros, amount_cents) VALUES (?, ?, 'pluggy', ?, ?, ?, 0, ?)",
                        (account, iid, f"demo-ev-{n}", pay_day.isoformat(), rule[0], amount),
                    )
                    kind = {"JCP": "JCP", "DIVIDEND": "Dividendos", "INCOME": "Rendimento"}[rule[0]]
                    self.tx(con, bank, pay_day, f"{kind} {ticker}", amount, "Proventos")
                quantity = sum(q for _, q in held) + REPORTED_EXTRA.get((account, ticker), 0)
                if quantity > 0:
                    con.execute(
                        "INSERT INTO position_snapshot(account_id, instrument_id, source, as_of_date, quantity_micros) "
                        "VALUES (?, ?, 'pluggy', ?, ?)", (account, iid, today.isoformat(), quantity * 1_000_000),
                    )

    def fixed_income(self) -> None:
        today, daily_cdi = self.today, 0.000551
        products = [
            # (conta, chave, tipo, nome, emissor, indexador, taxa, % do CDI ou taxa anual, aplicado, dias atrás, vencimento)
            (3, "cdb-inter", "CDB", "CDB Banco Inter", "Banco Inter", "CDI", "110%", 1.10, 1000000, 330,
             today + timedelta(days=420)),
            (3, "lci-abc", "LCI", "LCI Banco ABC", "Banco ABC Brasil", "CDI", "94%", 0.94, 500000, 290,
             today + timedelta(days=75)),
            (3, "ipca-2029", "Tesouro", "Tesouro IPCA+ 2029", "Tesouro Nacional", "IPCA", "+ 7,20%", None, 800000, 400,
             date(today.year + 3, 5, 15)),
            (6, "cdb-xp", "CDB", "CDB XP Investimentos", "Banco XP", "CDI", "105%", 1.05, 1500000, 200,
             today + timedelta(days=600)),
        ]
        with db.transaction() as con:
            for account, key, kind, name, issuer, indexer, rate, cdi_share, invested, days_ago, maturity in products:
                start = today - timedelta(days=days_ago)
                for m in range(13, -1, -1):
                    as_of = _month_day(today, m, 28) if m else today
                    if as_of is None or as_of < start:
                        continue
                    business = len(_business_days(start, as_of))
                    if cdi_share is not None:
                        gross = invested * (1 + daily_cdi * cdi_share) ** business
                    else:
                        gross = invested * (1.115 ** (business / 252)) * (1 + math.sin(m) * 0.01)
                    gain = gross - invested
                    con.execute(
                        "INSERT INTO fixed_income_snapshot(account_id, source, product_key, product_type, name, issuer, "
                        "indexer, rate, maturity_date, as_of_date, invested_cents, gross_value_cents, net_value_cents, "
                        "purchase_date) VALUES (?, 'pluggy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (account, f"demo:{key}", kind, name, issuer, indexer, rate, maturity.isoformat(), as_of.isoformat(),
                         invested, int(gross), int(gross - (0 if kind == "LCI" else gain * 0.15)), start.isoformat()),
                    )
            # caixinha: recebe R$ 3.000 por mês (as "Aplicação RDB" da conta) e rende 100% do CDI
            balance = deposited = 0.0
            for m in range(12, -1, -1):
                deposit_day = _month_day(today, m, 7)
                month_end = _month_day(today, m, 28) if m else today
                balance *= (1 + daily_cdi) ** 21
                if deposit_day:
                    balance += 300000
                    deposited += 300000
                if month_end and deposited:
                    con.execute(
                        "INSERT INTO fixed_income_snapshot(account_id, source, product_key, product_type, name, issuer, "
                        "indexer, rate, as_of_date, invested_cents, gross_value_cents, net_value_cents, purchase_date) "
                        "VALUES (3, 'pluggy', 'demo:caixinha', 'Caixinha', 'Caixinha Reserva', 'Nubank', 'CDI', '100%', "
                        "?, ?, ?, ?, ?)",
                        (month_end.isoformat(), int(deposited), int(balance), int(balance - (balance - deposited) * 0.175),
                         _month_day(today, 12, 7).isoformat()),
                    )

    def pension(self) -> None:
        from app.services import pension

        start = _month_day(self.today, 12, 1) or self.today
        contributed = 1800000.0
        gross = 1950000.0
        for m in (12, 9, 6, 3, 0):
            as_of = _month_day(self.today, m, 20) if m else self.today
            if m != 12:
                contributed += 3 * 50000
                gross = gross * 1.028 + 3 * 50000
            pension.save_entry({
                "name": "Itaú Flexprev PGBL", "institution": "Itaú", "plan_type": "PGBL", "regime": "Regressivo",
                "as_of_date": as_of.isoformat(), "start_date": (start - timedelta(days=900)).isoformat(),
                "gross": f"{gross / 100:.2f}".replace(".", ","), "contributed": f"{contributed / 100:.2f}".replace(".", ","),
                "net": f"{gross * 0.93 / 100:.2f}".replace(".", ","),
            })

    def balances(self) -> None:
        """Saldo de hoje = saldo inicial + tudo o que entrou e saiu; o inicial evita conta no vermelho no passado."""
        with db.transaction() as con:
            for account, floor in ((1, 350000), (4, 250000)):
                running, lowest = 0, 0
                for (amount,) in con.execute(
                    "SELECT amount_cents FROM cash_transaction WHERE account_id = ? AND status = 'POSTED' "
                    "ORDER BY transaction_date, id", (account,),
                ).fetchall():
                    running += amount
                    lowest = min(lowest, running)
                start = max(600000, floor - lowest)
                con.execute("INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
                            "VALUES (?, 'pluggy', ?, ?)", (account, self.today.isoformat(), start + running))
            for card, limit in ((2, 1200000), (5, 900000)):
                owed = con.execute(
                    "SELECT COALESCE(SUM(amount_cents), 0) FROM cash_transaction WHERE account_id = ? "
                    "AND (status = 'POSTED' OR transaction_date <= ?)", (card, self.today.isoformat()),
                ).fetchone()[0]
                con.execute("INSERT INTO account_balance_snapshot(account_id, source, as_of_date, balance_cents) "
                            "VALUES (?, 'pluggy', ?, ?)", (card, self.today.isoformat(), owed))
                con.execute("UPDATE financial_account SET credit_limit_cents = ?, available_limit_cents = ? WHERE id = ?",
                            (limit, limit + owed, card))

    # ------------------------------------------------------------ fundamentos
    def fundamentals(self) -> list[date]:
        from app.providers import cvm
        from app.services import fundamentals

        quarters = _quarter_ends(self.today, 12)
        # (ticker, setor, financeira, ações, receita tri. inicial (R$), crescimento tri., margem líquida, PL, dívida, caixa)
        companies = [
            ("ITSA4", "Holdings diversificadas", False, 10_300_000_000, 1_900_000_000, 0.015, 0.78, 78e9, 3e9, 5e9),
            ("EGIE3", "Energia elétrica", False, 815_900_000, 2_650_000_000, -0.004, 0.16, 12e9, 22e9, 4e9),
            ("BBAS3", "Bancos", True, 5_730_000_000, 28_000_000_000, 0.012, 0.17, 190e9, 0, 0),
            ("TAEE11", "Energia elétrica", False, 1_033_000_000, 1_050_000_000, 0.010, 0.33, 9e9, 12e9, 2.5e9),
            ("WEGE3", "Máquinas e equipamentos", False, 4_196_000_000, 9_400_000_000, 0.030, 0.17, 25e9, 3e9, 7e9),
            ("PETR4", "Petróleo e gás", False, 13_044_000_000, 120_000_000_000, -0.010, 0.13, 390e9, 300e9, 60e9),
        ]
        with db.transaction() as con:
            for ticker, sector, financial, shares, revenue, growth, margin, equity, debt, cash in companies:
                iid = self.instruments[ticker]
                con.execute(
                    "INSERT INTO company_profile(instrument_id, company_name, sector, is_financial, shares_outstanding, "
                    "summary, statements_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (iid, next(a[1] for a in ASSETS if a[0] == ticker) + " S.A.", sector, int(financial), shares,
                     f"Empresa fictícia da demonstração, com números inspirados no setor de {sector.lower()}.",
                     self.today.isoformat()),
                )
                for index, quarter in enumerate(quarters):
                    factor = (1 + growth) ** index * (1 + self.rng.uniform(-0.03, 0.03))
                    q_revenue = revenue * factor
                    q_margin = margin * (1 - 0.05 * index / 12) if ticker == "PETR4" else margin
                    net_income = q_revenue * q_margin * (0.55 if ticker == "PETR4" and index >= 8 else 1)
                    metrics = {
                        "revenue": q_revenue, "net_income": net_income, "net_income_total": net_income,
                        "equity_parent": equity * (1 + 0.01 * index), "equity": equity * (1 + 0.01 * index),
                        "total_assets": (equity + debt) * 1.6 if not financial else equity * 12,
                        "dividends_paid": net_income * 0.5, "shares": shares,
                    }
                    if not financial:
                        metrics.update({
                            "ebit": q_revenue * min(q_margin * 1.5, 0.9), "da": q_revenue * 0.06, "cfo": net_income * 1.3,
                            "capex": q_revenue * 0.08, "debt": debt * (1 - 0.01 * index), "cash": cash,
                        })
                    con.executemany(
                        "INSERT INTO fundamental_metric(instrument_id, period_end, period_type, metric, value, unit, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'cvm')",
                        [(iid, quarter.isoformat(), "SNAPSHOT" if key in cvm.STOCK_KEYS else "Q", key, value,
                          fundamentals.CVM_METRICS.get(key)) for key, value in metrics.items()],
                    )
                for quarter in quarters[-4:]:
                    con.execute(
                        "INSERT INTO company_filing(instrument_id, period_end, doc_type, version, received_at, link) "
                        "VALUES (?, ?, ?, 1, ?, ?)",
                        (iid, quarter.isoformat(), "DFP" if quarter.month == 12 else "ITR",
                         (quarter + timedelta(days=40)).isoformat(), "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx"),
                    )
        db.set_setting("fundamentals_synced_at", datetime.now().isoformat(timespec="seconds"))
        fundamentals.refresh_rule_alerts()
        return quarters

    # ------------------------------------------------------------ metas, regras e o "agente"
    def plans(self, partner: int, quarters: list[date]) -> None:
        from app.services import budgets, fundamentals, investor_profile, recommendations, spending, targets

        spending.create_category("Pets")
        spending.add_rule("PETZ", "Pets", note="Criada na demonstração")
        spending.add_rule("SMART FIT", "Saúde", note="Criada na demonstração")
        last_pix = [r[0] for r in db.rows(
            "SELECT id FROM cash_transaction WHERE description = 'Pix enviado|João Pereira' ORDER BY transaction_date DESC"
        )]
        spending.set_category(last_pix[:1], "Lazer")

        for name, categories, limit in (
            ("Alimentação fora", ["Alimentação"], 60000), ("Mercado", ["Mercado"], 120000),
            ("Transporte", ["Transporte"], 45000), ("Assinaturas", ["Assinaturas"], 25000),
            ("Casa", ["Casa"], 320000), ("Total do mês", [budgets.TOTAL], 900000),
        ):
            budgets.save_budget(name, categories, limit, 0.8, author="usuario")
        targets.save(3000000, 0.40, 0.60, 0.25, True)
        targets.save(1500000, 0.50, 0.50, None, True, member=partner)
        investor_profile.save("10-20", "os-dois", today=self.today)

        period, previous = _label(quarters[-1]), _label(quarters[-2])
        month = self.today.strftime("%Y-%m")
        fundamentals.import_analysis([
            {"ticker": "EGIE3", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"EGIE3 {period}: qualidade alta, receita parada",
                "summary": "Margens estáveis e dívida sob controle, mas a receita não cresce há um ano.",
                "body_md": "## Resumo\nResultado estável, sem crescimento.\n\n## Checklist\n- [x] Dívida líquida/EBITDA "
                           "abaixo de 3x\n- [ ] Receita crescendo\n\n## Conclusão\nManter, sem novos aportes por enquanto.",
                "verdict": "justa", "score": 6.8, "fair_price": 42.0, "sources": ["Demonstrações trimestrais (demo)"]},
             "alerts": [{"code": "crescimento_parado", "severity": "atencao", "message": "Receita sem crescer há 4 trimestres.",
                         "metric": "revenue_growth", "period_end": quarters[-1].isoformat()}]},
            {"ticker": "EGIE3", "period": previous, "model": "claude-opus-5-5", "report": {
                "title": f"EGIE3 {previous}: tarifa reajustada segura o lucro", "verdict": "justa", "score": 7.0,
                "summary": "Trimestre fraco em volume, compensado pelo reajuste tarifário.", "body_md": "## Resumo\nManter."}},
            {"ticker": "ITSA4", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"ITSA4 {period}: desconto de holding ainda alto", "verdict": "barata", "score": 8.1,
                "fair_price": 12.5, "summary": "Lucro recorrente crescendo e desconto de 20% sobre as participações.",
                "body_md": "## Resumo\nBoa relação entre preço e qualidade.\n\n## Conclusão\nAportar."}},
            {"ticker": "BBAS3", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"BBAS3 {period}: ROE alto, inadimplência subindo", "verdict": "barata", "score": 7.2,
                "summary": "Rentabilidade acima de 17%, mas o agro pressiona a carteira de crédito.",
                "body_md": "## Resumo\nPreço baixo compensa o risco.\n\n## Pontos de atenção\n- Inadimplência no agro."}},
            {"ticker": "WEGE3", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"WEGE3 {period}: crescimento caro", "verdict": "cara", "score": 7.5, "fair_price": 40.0,
                "summary": "Receita crescendo 12% ao ano, mas o preço já embute anos de crescimento.",
                "body_md": "## Resumo\nEmpresa excelente, preço esticado."}},
            {"ticker": "HGLG11", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"HGLG11 {period}: vacância baixa e dividendos estáveis", "verdict": "justa", "score": 7.8,
                "summary": "Galpões com vacância de 3% e rendimento mensal estável.", "body_md": "## Resumo\nManter."}},
            {"ticker": "TAEE11", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"TAEE11 {period}: receita regulada, dividendo previsível", "verdict": "justa", "score": 7.4,
                "summary": "Transmissão com receita corrigida pela inflação e payout acima de 90%.",
                "body_md": "## Resumo\nManter.\n\n## Conciliação\nA bonificação de 20 units ainda não apareceu nas "
                           "movimentações da XP."}},
            {"ticker": "KNRI11", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"KNRI11 {period}: lajes corporativas pesam", "verdict": "justa", "score": 6.9,
                "summary": "Logística vai bem; escritórios ainda com vacância de 12%.", "body_md": "## Resumo\nManter."}},
            {"ticker": "IVVB11", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"IVVB11 {period}: a porta para o internacional", "verdict": "justa", "score": 7.6,
                "summary": "Replica o S&P 500 em reais; é o caminho mais simples para a meta internacional de 25%.",
                "body_md": "## Resumo\nAportar até a meta internacional."}},
            {"ticker": "PETR4", "period": period, "model": "claude-opus-5-5", "report": {
                "title": f"PETR4 {period}: lucro em queda, posição encerrada", "verdict": "justa", "score": 5.5,
                "summary": "O lucro 12M caiu mais de 30%; a venda de 4 meses atrás realizou lucro antes da queda.",
                "body_md": "## Resumo\nSem recompra por enquanto."}},
            {"subject": "Tesouro IPCA+ 2029", "subject_type": "renda_fixa", "period": period, "report": {
                "title": "Tesouro IPCA+ 2029: manter até o vencimento",
                "summary": "A taxa contratada de IPCA + 7,2% está acima da atual; vender antes realiza a marcação a mercado.",
                "body_md": "## Resumo\nManter até 2029."}},
            {"subject": "Itaú Flexprev PGBL", "subject_type": "previdencia", "period": period, "report": {
                "title": "Previdência: taxa de administração alta",
                "summary": "O plano rende abaixo do CDI por causa da taxa de 1,5% ao ano; vale portar para um fundo mais barato.",
                "body_md": "## Resumo\nAvaliar portabilidade."}},
        ], default_author="agente")
        recommendations.import_recommendations({
            "period": period, "title": f"{period}: mais internacional, menos petróleo", "model": "claude-opus-5-5",
            "summary": "Completar a meta internacional com IVVB11 e aportar em ITSA4, que segue barata.",
            "body_md": "## Tese do trimestre\nJuros altos favorecem bancos e elétricas.\n\n## Prioridades\n"
                       "1. Levar o internacional até 25% da renda variável.\n2. Aportar em ITSA4.",
            "changes": [
                {"action": "aumentar", "ticker": "IVVB11", "target_weight": 0.2, "conviction": 4,
                 "rationale": "Leva a exposição internacional para a meta de 25%."},
                {"action": "aumentar", "ticker": "ITSA4", "target_weight": 0.25, "conviction": 4,
                 "rationale": "Desconto de holding alto e lucro crescendo."},
                {"action": "manter", "ticker": "EGIE3", "target_weight": 0.12, "conviction": 3,
                 "rationale": "Qualidade alta, mas sem crescimento: manter sem novos aportes."},
                {"action": "comprar", "ticker": "ITUB4", "name": "Itaú Unibanco", "asset_class": "Ação",
                 "region": "nacional", "target_weight": 0.05, "conviction": 3, "fair_price": 45.0,
                 "rationale": "ROE acima de 20% com P/L abaixo de 9x."},
            ],
            "portfolios": [{
                "name": "Dividendos com qualidade", "risk_profile": "moderado",
                "description": "Parecida com a atual, com mais previsibilidade de proventos.",
                "rationale_md": "Mantém **ITSA4** e **TAEE11** e completa o internacional com **IVVB11**.",
                "items": [
                    {"ticker": "ITSA4", "target_weight": 0.3, "rationale": "Holding barata."},
                    {"ticker": "TAEE11", "target_weight": 0.25, "rationale": "Receita regulada."},
                    {"ticker": "HGLG11", "target_weight": 0.2, "rationale": "Renda mensal."},
                    {"ticker": "IVVB11", "target_weight": 0.25, "rationale": "Meta internacional."},
                ],
            }],
        }, default_author="agente")
        budgets.import_advice({
            "period": month, "title": "Alimentação fora e compras puxam o mês", "model": "claude-opus-5-5",
            "summary": "A casa gasta dentro do total, mas alimentação fora estourou em 4 dos últimos 6 meses.",
            "expected_monthly_savings": 250.0,
            "body_md": "## Diagnóstico\n- Sobra média de R$ 3 mil por mês.\n- Delivery é metade de alimentação fora.\n\n"
                       "## O que mudar\n1. Ajustar a meta de alimentação fora.\n2. Criar meta para compras.",
            "items": [
                {"action": "ajustar", "budget": "Alimentação fora", "current_limit": 600, "suggested_limit": 700,
                 "priority": 1, "rationale": "A média dos últimos 3 meses é R$ 680: a meta atual nunca é cumprida."},
                {"action": "criar", "budget": "Compras", "categories": ["Compras"], "suggested_limit": 350, "priority": 2,
                 "rationale": "Hoje sem meta; Renner e Amazon somam cerca de R$ 330 por mês."},
                {"action": "economizar", "budget": "Assinaturas", "expected_monthly_savings": 34, "priority": 3,
                 "rationale": "Netflix e Disney Plus juntos: dá para alternar mês a mês."},
            ],
        }, default_author="agente")

    def history(self) -> None:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with db.transaction() as con:
            for source, read in (("Meu Pluggy · Nubank", 312), (f"Meu Pluggy · Itaú · {PARTNER}", 268),
                                 (f"Meu Pluggy · XP · {PARTNER}", 41), ("Cotações e CDI", 9)):
                con.execute(
                    "INSERT INTO sync_run(source, started_at, finished_at, status, records_read, records_written, message) "
                    "VALUES (?, ?, ?, 'success', ?, ?, ?)",
                    (source, now, now, read, read, f"{source.split(' · ', 1)[-1]}: sincronização concluída."),
                )
            con.execute(
                "INSERT INTO reconciliation_note(entity_type, entity_key, note) VALUES ('position', ?, ?)",
                (f"XP / Investimentos · {PARTNER}|TAEE11",
                 "Bonificação de 20 units em junho: a XP já mostra, as movimentações ainda não."),
            )


def seed(today: date | None = None) -> None:
    """Grava a demonstração na base do contexto atual (use dentro de active() ou de db.using_database)."""
    seeder = _Seeder(today or date.today())
    partner = seeder.household()
    seeder.accounts(partner)
    seeder.market()
    seeder.spending()
    seeder.investments()
    seeder.fixed_income()
    seeder.pension()
    seeder.balances()
    quarters = seeder.fundamentals()
    seeder.plans(partner, quarters)
    seeder.history()
