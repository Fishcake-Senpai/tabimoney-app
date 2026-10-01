from __future__ import annotations

import re
import unicodedata

# Categorias que não são receita nem despesa: dinheiro mudando de lugar dentro do próprio patrimônio
# (ou do patrimônio da casa: o Pix entre titulares).
OWN_TRANSFER = "Transferência própria"
HOUSEHOLD_TRANSFER = "Transferência entre titulares"
INTERNAL_CATEGORIES = {"Investimentos", "Pagamento de fatura", OWN_TRANSFER, HOUSEHOLD_TRANSFER}
# Entradas que contam como receita; qualquer outra entrada positiva é estorno e abate a despesa da categoria.
INCOME_CATEGORIES = {"Salário", "Proventos", "Rendimentos", "Pix e transferências", "Outros"}

# Ícone (Lucide, app/static/icons.svg) de cada categoria nas listas do app. Categoria criada pelo usuário usa o
# ícone escolhido ao criar; sem escolha, o de uma palavra conhecida do nome (CATEGORY_ICON_HINTS) ou o genérico.
CATEGORY_ICONS = {
    "Casa": "house", "Mercado": "shopping-cart", "Alimentação": "utensils", "Transporte": "car", "Saúde": "heart-pulse",
    "Compras": "shopping-bag", "Assinaturas": "repeat", "Lazer": "ticket", "Educação": "graduation-cap",
    "Viagem": "plane", "Pets": "paw-print", "Impostos e taxas": "landmark", "Pix e transferências": "arrow-left-right",
    "Salário": "briefcase", "Proventos": "coins", "Rendimentos": "piggy-bank", "Investimentos": "trending-up",
    "Pagamento de fatura": "credit-card", OWN_TRANSFER: "repeat-2", HOUSEHOLD_TRANSFER: "users-round",
    "Outros": "circle-dashed",
}
CATEGORY_ICON_HINTS = [
    (("pet", "cachorro", "gato", "veterin"), "paw-print"), (("delivery", "ifood", "restaurante", "comida"), "utensils"),
    (("academia", "esporte", "treino", "gym"), "dumbbell"), (("bebe", "filho", "crianca", "escola"), "baby"),
    (("presente", "doacao"), "gift"), (("combustivel", "gasolina", "posto"), "fuel"), (("celular", "telefone"), "smartphone"),
    (("cafe",), "coffee"), (("livro", "leitura"), "book-open"), (("roupa", "vestuario"), "shirt"),
    (("jogo", "game"), "gamepad-2"), (("farmacia", "remedio"), "pill"), (("internet", "wifi"), "wifi"),
    (("luz", "energia"), "zap"), (("agua",), "droplet"), (("streaming", "tv"), "tv"), (("carro", "uber", "taxi"), "car"),
    (("onibus", "metro", "transporte"), "bus"), (("bike", "bicicleta"), "bike"), (("manutencao", "reforma", "conserto"), "wrench"),
    (("musica", "show"), "music"), (("cinema", "filme"), "film"), (("beleza", "cabelo", "salao"), "scissors"),
    (("viagem", "hotel", "passagem"), "plane"), (("jardim", "planta"), "sprout"), (("trabalho", "escritorio"), "laptop"),
]
# Opções do seletor de ícone ao criar uma categoria.
CATEGORY_ICON_CHOICES = [
    "circle-dashed", "house", "shopping-cart", "utensils", "coffee", "car", "fuel", "bus", "bike", "plane",
    "heart-pulse", "pill", "dumbbell", "shopping-bag", "shirt", "gift", "repeat", "tv", "music", "film", "ticket",
    "gamepad-2", "graduation-cap", "book-open", "baby", "paw-print", "smartphone", "wifi", "zap", "droplet",
    "wrench", "scissors", "sprout", "laptop", "briefcase", "landmark", "piggy-bank", "hand-coins",
]


def category_icon(name: str | None, chosen: str | None = None) -> str:
    """Nome do ícone de uma categoria: o escolhido, o padrão, o de uma palavra do nome ou o genérico."""
    if chosen and chosen in CATEGORY_ICON_CHOICES:
        return chosen
    if not name:
        return "circle-dashed"
    if name in CATEGORY_ICONS:
        return CATEGORY_ICONS[name]
    key = _plain(name)
    return next((icon for words, icon in CATEGORY_ICON_HINTS if any(w in key for w in words)), "circle-dashed")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


# Estas vêm antes da categoria da origem, que costuma errar nelas (a Pluggy chama compra de ações de "Shopping").
# Por isso casam só no início de palavra: "lca" não pega "calçados".
_STRONG_RULES: list[tuple[str, tuple[str, ...]]] = [
    # Ex.: a Pluggy rotulou um "Salário <EMPRESA> ENERGIA" como conta de luz.
    ("Salário", ("salario", "pagto salario", "pagamento de salario", "folha de pagamento")),
    ("Pagamento de fatura", (
        "pagamento de fatura", "pagamento recebido", "pagamento da fatura", "pagto fatura", "pag fatura",
        "fatura cartao", "pagamento cartao", "pgto fatura",
    )),
    ("Proventos", (
        "valor recebido de investimentos", "dividendo", "juros sobre capital", "rendimento fii", "rend pago", "rendimentos",
    )),
    ("Investimentos", (
        "aplicacao", "resgate", "caixinha", "nuinvest", "nu invest", "tesouro direto", "cdb", "rdb", "lci", "lca",
        "corretora", "renda variavel", "renda fixa", "previdencia", "pgbl", "vgbl", "prev priv", "itauprev",
        "aplic ", "resg ",
    )),
]

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Salário", ("salario", "folha", "proventos pgto", "pagamento de salario", "remuneracao")),
    ("Mercado", ("supermerc", "mercado", "carrefour", "assai", "atacad", "pao de acucar", "hortifruti", "sams club")),
    ("Alimentação", ("ifood", "ifd*", "restaurante", "padaria", "lanchonete", "burger", "mcdonald", "pizza", "rappi", "cafe", "bar ")),
    ("Transporte", ("uber", "99app", "99 ", "posto", "shell", "ipiranga", "petrobras", "estaciona", "sem parar", "veloe", "metro", "cptm")),
    ("Assinaturas", ("netflix", "spotify", "prime video", "amazonprime", "disney", "hbo", "max.com", "youtube", "apple.com", "google one", "icloud", "deezer", "globoplay")),
    ("Saúde", ("farmacia", "drogasil", "droga raia", "raia", "pague menos", "drogaria", "hospital", "clinica", "laborat", "unimed", "amil")),
    ("Compras", ("amazon", "mercadolivre", "mercado livre", "shopee", "magalu", "magazine", "americanas", "aliexpress", "shein", "casas bahia")),
    ("Viagem", ("latam", "gol linhas", "azul linhas", "airbnb", "booking", "hotel", "decolar", "123milhas")),
    ("Casa", ("energia", "enel", "cemig", "copel", "light", "sabesp", "agua", "condominio", "aluguel", "claro", "vivo", "tim ", "internet")),
    ("Educação", ("escola", "faculdade", "curso", "udemy", "alura", "livraria")),
    ("Impostos e taxas", ("iof", "tarifa", "juros", "multa", "darf", "ipva", "iptu", "anuidade")),
    ("Pix e transferências", ("pix", "transferencia", "ted", "doc ")),
]

# Categorias da Pluggy (em inglês) que mapeiam sem ambiguidade. As genéricas de transferência ficam de fora
# e caem nas regras por descrição.
PLUGGY_CATEGORIES = {
    "Salary": "Salário", "Retirement": "Salário",
    "Proceeds interests and dividends": "Proventos",
    "Investments": "Investimentos", "Automatic investment": "Investimentos", "Fixed income": "Investimentos",
    "Mutual funds": "Investimentos", "Variable income": "Investimentos", "Margin": "Investimentos",
    "Pension": "Investimentos", "Transfer - Investment": "Investimentos",
    "Credit card payment": "Pagamento de fatura",
    "Same person transfer": "Transferência própria",
    "Groceries": "Mercado",
    "Eating out": "Alimentação", "Food delivery": "Alimentação", "Food and drinks": "Alimentação",
    "Transportation": "Transporte", "Taxi and ride-hailing": "Transporte", "Gas stations": "Transporte",
    "Parking": "Transporte", "Public transportation": "Transporte", "Vehicle maintenance": "Transporte",
    "Tolls and in vehicle payment": "Transporte", "Vehicle insurance": "Transporte",
    "Pharmacy": "Saúde", "Healthcare": "Saúde", "Health insurance": "Saúde", "Hospital clinics and labs": "Saúde",
    "Dentist": "Saúde", "Optometry": "Saúde", "Wellness and fitness": "Saúde", "Gyms and fitness centers": "Saúde",
    "Online shopping": "Compras", "Shopping": "Compras", "Clothing": "Compras", "Electronics": "Compras",
    "Bookstore": "Compras", "Sports goods": "Compras", "Pet supplies and vet": "Compras", "Gifts": "Compras",
    "Travel": "Viagem", "Accomodation": "Viagem", "Airport and airlines": "Viagem",
    "Housing": "Casa", "Utilities": "Casa", "Electricity": "Casa", "Water": "Casa", "Rent": "Casa",
    "Houseware": "Casa", "Telecommunications": "Casa", "Internet": "Casa", "Mobile": "Casa",
    "Education": "Educação", "University": "Educação", "School": "Educação", "Language courses": "Educação",
    "Digital services": "Assinaturas", "Video streaming": "Assinaturas", "Music streaming": "Assinaturas",
    "Leisure": "Lazer", "Cinema, theater and concerts": "Lazer", "Gambling": "Lazer",
    "Taxes": "Impostos e taxas", "Bank fees": "Impostos e taxas", "Tax on financial operations": "Impostos e taxas",
    "Interests charged": "Impostos e taxas", "Late payment and overdraft costs": "Impostos e taxas",
    "Income taxes": "Impostos e taxas", "Taxes on investments": "Impostos e taxas",
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _compile(rules: list[tuple[str, tuple[str, ...]]]) -> list[tuple[str, re.Pattern[str]]]:
    return [
        (category, re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in keywords) + ")"))
        for category, keywords in rules
    ]


_STRONG = _compile(_STRONG_RULES)


def categorize(description: str, source_category: str | None = None) -> str:
    """Regras fortes (salário, fatura, proventos, investimentos) > categoria da origem > regras por descrição."""
    text = _normalize(description or "")
    for category, pattern in _STRONG:
        if pattern.search(text):
            return category
    if source_category and source_category.strip():
        return source_category.strip().capitalize()
    for category, keywords in _RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "Outros"
