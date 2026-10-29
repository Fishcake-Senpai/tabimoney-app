"""Números da Receita por ano-calendário, num lugar só (spec §1.2), e as contas que dependem só deles.

Cada ano diz de onde vieram os valores e o que ainda falta conferir no texto oficial (`a_confirmar`). Quando a
Receita publica o programa e o Perguntas e Respostas da declaração (todo ano, em março), revise este arquivo e os
testes dele (tests/test_ir_parametros.py) e suba EXERCICIO_CONFIRMADO. Enquanto isso não acontece, o app avisa a
partir de abril que os parâmetros podem estar desatualizados (alerta_calendario).

Dinheiro em centavos (int). Alíquotas em Decimal; o imposto sai da tabela com a parcela a deduzir (como a Receita
calcula), arredondado meio para cima no centavo. A tabela anual de 2026 ainda não foi publicada: as parcelas vêm da
continuidade da tabela (cada faixa começa onde a anterior termina), que é como as anuais oficiais sempre saíram.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
Faixas = tuple[tuple[int | None, Decimal], ...]  # INSS: (limite superior da faixa em centavos ou None, alíquota)
Tabela = tuple[tuple[int | None, Decimal, int], ...]  # IR: (limite superior, alíquota, parcela a deduzir em centavos)

# Último exercício (ano da declaração) cujos parâmetros foram conferidos com a publicação oficial da Receita.
# Exercício 2026 = ano-calendário 2025: Perguntas e Respostas IRPF 2026, v1.0 de 23/04/2026.
EXERCICIO_CONFIRMADO = 2026


@dataclass(frozen=True)
class Parametros:
    ano: int                                   # ano-calendário
    tabela_anual: Tabela
    tabela_mensal: dict[int, Tabela]           # mês → tabela (2025 mudou em maio)
    desconto_simplificado_mensal: dict[int, int]
    simplificado_pct: Decimal
    simplificado_limite: int
    dependente_anual: int
    dependente_mensal: int
    educacao_limite: int
    pgbl_pct: Decimal
    doacoes_pct: Decimal
    inss_faixas: Faixas                        # empregado, progressivo
    inss_ci_aliquota: Decimal                  # contribuinte individual (pró-labore)
    inss_teto_base: int
    redutor_mensal: tuple[int, int, int, Decimal, Decimal] | None = None  # (isento até, teto, fim, a, b): a − b × renda
    redutor_anual: tuple[int, int, int, Decimal, Decimal] | None = None
    dividendos_limite_mensal: int | None = None  # retenção de 10% acima disto (mesma empresa, mesmo mês)
    dividendos_aliquota: Decimal = D("0")
    irpfm_inicio: int | None = None            # renda total a partir da qual há tributação mínima
    irpfm_cheio: int | None = None             # renda total da alíquota máxima (10%)
    obrigatoriedade: dict[str, int] = field(default_factory=dict)
    fonte: str = ""
    a_confirmar: tuple[str, ...] = ()


def _faixas(*faixas: tuple[str | None, str]) -> Faixas:
    return tuple((None if limite is None else int(D(limite) * 100), D(aliquota)) for limite, aliquota in faixas)


def _tabela(*faixas: tuple[str | None, str, str]) -> Tabela:
    """Tabela do IR como a Receita publica: faixa, alíquota e parcela a deduzir."""
    return tuple((None if limite is None else int(D(limite) * 100), D(aliquota), int(D(parcela) * 100))
                 for limite, aliquota, parcela in faixas)


_MENSAL_2025_JAN_ABR = _tabela(("2259.20", "0", "0"), ("2826.65", "0.075", "169.44"), ("3751.05", "0.15", "381.44"),
                               ("4664.68", "0.225", "662.77"), (None, "0.275", "896.00"))
_MENSAL_DESDE_MAIO_2025 = _tabela(("2428.80", "0", "0"), ("2826.65", "0.075", "182.16"), ("3751.05", "0.15", "394.16"),
                                  ("4664.68", "0.225", "675.49"), (None, "0.275", "908.73"))
_RV = {
    "aliquota_comum": D("0.15"), "aliquota_day_trade": D("0.20"), "aliquota_fii": D("0.20"),
    "irrf_comum": D("0.00005"), "irrf_day_trade": D("0.01"), "irrf_minimo": 100,
    "isencao_acoes_mensal": 2_000_000, "darf_minimo": 1000, "darf_codigo": "6015",
}

PARAMETROS: dict[int, Parametros] = {
    2025: Parametros(
        ano=2025,
        tabela_anual=_tabela(("28467.20", "0", "0"), ("33919.80", "0.075", "2135.04"), ("45012.60", "0.15", "4679.03"),
                             ("55976.16", "0.225", "8054.97"), (None, "0.275", "10853.78")),
        tabela_mensal={m: _MENSAL_2025_JAN_ABR if m <= 4 else _MENSAL_DESDE_MAIO_2025 for m in range(1, 13)},
        desconto_simplificado_mensal={m: 56480 if m <= 4 else 60720 for m in range(1, 13)},
        simplificado_pct=D("0.20"), simplificado_limite=1_675_434,
        dependente_anual=227_508, dependente_mensal=18_959, educacao_limite=356_150,
        pgbl_pct=D("0.12"), doacoes_pct=D("0.06"),
        inss_faixas=_faixas(("1518.00", "0.075"), ("2793.88", "0.09"), ("4190.83", "0.12"), ("8157.41", "0.14")),
        inss_ci_aliquota=D("0.11"), inss_teto_base=815_741,
        obrigatoriedade={"tributaveis": 3_558_400, "isentos": 20_000_000, "vendas_bolsa": 4_000_000, "bens": 80_000_000},
        fonte="Perguntas e Respostas IRPF 2026 (Receita, 23/04/2026); Lei 15.191/2025",
        a_confirmar=("tabela INSS 2025 (Portaria MPS/MF de jan/2025)",),
    ),
    2026: Parametros(
        ano=2026,
        tabela_anual=_tabela(("29145.60", "0", "0"), ("33919.80", "0.075", "2185.92"), ("45012.60", "0.15", "4729.91"),
                             ("55976.16", "0.225", "8105.85"), (None, "0.275", "10904.66")),
        tabela_mensal={m: _MENSAL_DESDE_MAIO_2025 for m in range(1, 13)},
        desconto_simplificado_mensal={m: 60720 for m in range(1, 13)},
        simplificado_pct=D("0.20"), simplificado_limite=1_764_000,
        dependente_anual=227_508, dependente_mensal=18_959, educacao_limite=356_150,
        pgbl_pct=D("0.12"), doacoes_pct=D("0.06"),
        inss_faixas=_faixas(("1621.00", "0.075"), ("2902.84", "0.09"), ("4354.27", "0.12"), ("8475.55", "0.14")),
        inss_ci_aliquota=D("0.11"), inss_teto_base=847_555,
        redutor_mensal=(500_000, 31_289, 735_000, D("978.62"), D("0.133145")),
        redutor_anual=(6_000_000, 269_415, 8_820_000, D("8429.73"), D("0.095575")),
        dividendos_limite_mensal=5_000_000, dividendos_aliquota=D("0.10"),
        irpfm_inicio=60_000_000, irpfm_cheio=120_000_000,
        obrigatoriedade={"tributaveis": 3_558_400, "isentos": 20_000_000, "vendas_bolsa": 4_000_000, "bens": 80_000_000},
        fonte="Lei 15.270/2025 (redutor, dividendos, IRPFM, simplificado de 17.640); tabela mensal da Lei 15.191/2025",
        a_confirmar=(
            "tabela anual (12 × a mensal)", "limite do desconto simplificado (17.640,00)",
            "tabela INSS 2026 (Portaria Interministerial MPS/MF nº 13/2026)",
            "limites de obrigatoriedade da declaração 2027 (repetidos de 2026)",
        ),
    ),
}
RENDA_VARIAVEL = _RV


def anos() -> list[int]:
    return sorted(PARAMETROS)


def para(ano: int) -> Parametros:
    """Parâmetros do ano-calendário. Ano sem tabela usa o mais próximo (a tela avisa que é projeção)."""
    if ano in PARAMETROS:
        return PARAMETROS[ano]
    return PARAMETROS[max(PARAMETROS) if ano > max(PARAMETROS) else min(PARAMETROS)]


def projetado(ano: int) -> bool:
    return ano not in PARAMETROS


def alerta_calendario(hoje: date | None = None) -> dict[str, str] | None:
    """Passado março do ano Y, a declaração Y já tem regras publicadas. Se os parâmetros conferidos não chegam ao
    exercício Y, o app pode estar calculando com números velhos: avisa até uma versão nova trazer a revisão."""
    hoje = hoje or date.today()
    exercicio = hoje.year if hoje.month >= 4 else hoje.year - 1
    if EXERCICIO_CONFIRMADO >= exercicio:
        return None
    return {
        "exercicio": str(exercicio), "ano_calendario": str(exercicio - 1),
        "titulo": f"Regras do IR {exercicio} podem estar desatualizadas",
        "texto": (f"A Receita publica em março as regras da declaração {exercicio} (ano-calendário {exercicio - 1}). "
                  f"Os números do Tabimoney foram conferidos até a declaração {EXERCICIO_CONFIRMADO}. Atualize o app; "
                  "este aviso some quando a atualização trouxer os parâmetros revisados."),
    }


# ---------------------------------------------------------------- contas

def centavos(valor: Decimal) -> int:
    return int(valor.quantize(D("1"), ROUND_HALF_UP))


def imposto(base: int, tabela: Tabela) -> int:
    """Imposto pela tabela, como a Receita calcula: base × alíquota da faixa − parcela a deduzir."""
    for limite, aliquota, parcela in tabela:
        if limite is None or base <= limite:
            return max(0, centavos(D(base) * aliquota) - parcela)
    return 0


def por_faixas(base: int, faixas: Faixas) -> int:
    """INSS por fatias: cada alíquota só sobre a parte do salário dentro da faixa."""
    total, anterior = D(0), 0
    for limite, aliquota in faixas:
        topo = base if limite is None else min(base, limite)
        if topo > anterior:
            total += D(topo - anterior) * aliquota
        if limite is None or base <= limite:
            break
        anterior = limite
    return centavos(total)


def aliquota_marginal(base: int, tabela: Tabela) -> Decimal:
    for limite, aliquota, _ in tabela:
        if limite is None or base <= limite:
            return aliquota
    return tabela[-1][1]


def _reducao(regra: tuple[int, int, int, Decimal, Decimal] | None, rendimento: int, imposto: int) -> int:
    if regra is None or imposto <= 0:
        return 0
    isento_ate, teto, fim, a, b = regra
    if rendimento <= isento_ate:
        return min(imposto, teto)
    if rendimento <= fim:
        valor = centavos((a - b * D(rendimento) / 100) * 100)
        return max(0, min(imposto, valor))
    return 0


def reducao_mensal(p: Parametros, rendimento_bruto: int, imposto: int) -> int:
    """Lei 15.270, art. 3º-A: sobre o rendimento tributável BRUTO do mês, limitada ao imposto da tabela."""
    return _reducao(p.redutor_mensal, rendimento_bruto, imposto)


def reducao_anual(p: Parametros, rendimentos_tributaveis: int, imposto: int) -> int:
    """Lei 15.270, art. 11-A: sobre os rendimentos tributáveis do ajuste (antes das deduções)."""
    return _reducao(p.redutor_anual, rendimentos_tributaveis, imposto)


def inss_empregado(p: Parametros, salario: int) -> int:
    return por_faixas(min(salario, p.inss_teto_base), p.inss_faixas)


def inss_teto_empregado(p: Parametros) -> int:
    return por_faixas(p.inss_teto_base, p.inss_faixas)


def inss_pro_labore(p: Parametros, pro_labore: int) -> int:
    return centavos(D(min(pro_labore, p.inss_teto_base)) * p.inss_ci_aliquota)


def irrf_mensal(p: Parametros, mes: int, bruto: int, deducoes: int) -> dict[str, int]:
    """Retenção do mês: base com as deduções legais ou o desconto simplificado mensal, o que for maior; tabela;
    redução sobre o bruto."""
    usadas = max(deducoes, p.desconto_simplificado_mensal[mes])
    base = max(0, bruto - usadas)
    devido = imposto(base, p.tabela_mensal[mes])
    reducao = reducao_mensal(p, bruto, devido)
    return {"base": base, "deducoes": usadas, "imposto": devido, "reducao": reducao, "irrf": devido - reducao}


def aliquota_irpfm(p: Parametros, renda_total: int) -> Decimal:
    """(renda ÷ 60.000) − 10, em %, de 0 a 10%."""
    if p.irpfm_inicio is None or renda_total <= p.irpfm_inicio:
        return D(0)
    if renda_total >= (p.irpfm_cheio or 0):
        return D("0.10")
    return max(D(0), min(D("0.10"), (D(renda_total) / D(6_000_000) - 10) / 100))
