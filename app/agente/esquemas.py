"""Esquemas das importações do agente (análises, recomendações e orçamento), para o servidor MCP.

Servem para o agente saber o formato: cada campo tem descrição e valores aceitos. As regras continuam nos
serviços (fundamentals.import_analysis, recommendations.import_recommendations, budgets.import_advice), que dão
as mensagens de erro em português; aqui nada é recusado além do tipo básico, e campos extras passam adiante.
Exemplos completos em docs/agentes/exemplos/.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")

    def dados(self) -> dict[str, Any]:
        """O que o agente mandou, sem os campos que ele não informou."""
        return self.model_dump(exclude_unset=True)


# ---------------------------------------------------------------- análise trimestral

class Relatorio(_Base):
    title: str = Field(description="Título curto com a conclusão (ex.: 'EGIE3 2T26: qualidade alta, preço esticado').")
    summary: str = Field(description="Uma ou duas frases com a conclusão.")
    body_md: str = Field(description="Relatório completo em Markdown, com as seções do modelo "
                                     "(resource tabimoney://docs/modelo-relatorio-trimestral).")
    kind: str | None = Field(None, description="Tipo do relatório; padrão 'trimestral'.")
    verdict: str | None = Field(None, description="'barata', 'justa', 'cara' ou null.")
    score: float | None = Field(None, description="Nota de 0 a 10.")
    fair_price: float | None = Field(None, description="Preço justo em reais por ação/cota.")
    sources: list[str] | None = Field(None, description="Links (https://) e documentos de onde vieram os números "
                                                        "que não estão no contexto.")


class Metrica(_Base):
    metric: str = Field(description="Nome em snake_case (ex.: 'roic', 'pl_medio_5a').")
    value: float
    period_end: str = Field(description="AAAA-MM-DD.")
    period_type: str = Field(description="'Q', 'TTM' ou 'SNAPSHOT'.")
    unit: str | None = Field(None, description="Ex.: 'fração', 'R$', 'x'.")


class Aviso(_Base):
    code: str = Field(description="Código em snake_case; o mesmo code + period_end atualiza em vez de duplicar.")
    severity: str = Field(description="'critico', 'atencao', 'info' ou 'positivo'.")
    message: str
    period_end: str | None = Field(None, description="AAAA-MM-DD.")


class ItemAnalise(_Base):
    period: str = Field(description="Trimestre do último balanço, ex.: '2T26' (abril a junho de 2026).")
    report: Relatorio
    ticker: str | None = Field(None, description="Para ação, FII, ETF ou BDR da carteira.")
    subject: str | None = Field(None, description="Sem ticker: nome do título de renda fixa, do plano de previdência "
                                                  "ou 'Carteira'.")
    subject_type: str | None = Field(None, description="'ativo' (padrão com ticker), 'renda_fixa', 'previdencia' ou 'carteira'.")
    model: str | None = Field(None, description="Modelo de IA que escreveu (ex.: 'claude-opus-5-5').")
    metrics: list[Metrica] | None = Field(None, description="Métricas que o app não calcula. Exigem ticker.")
    alerts: list[Aviso] | None = Field(None, description="Só o que muda uma decisão. Exigem ticker.")


# ---------------------------------------------------------------- recomendações trimestrais

class Mudanca(_Base):
    action: str = Field(description="'comprar', 'aumentar', 'manter', 'reduzir', 'vender' ou 'incluir'.")
    ticker: str | None = None
    name: str | None = Field(None, description="Obrigatório em ativo novo ou item sem ticker (ex.: título de renda fixa).")
    asset_class: str | None = Field(None, description="Em ativo novo, ex.: 'Ação', 'FII', 'ETF', 'BDR'.")
    region: str | None = Field(None, description="Em ativo novo: 'nacional' ou 'internacional'.")
    target_weight: float | None = Field(None, description="Peso na renda variável depois da mudança (0.05 ou 5 = 5%).")
    conviction: int | None = Field(None, description="1 a 5.")
    fair_price: float | None = Field(None, description="Em reais.")
    rationale: str = Field(description="Uma a três frases com números do relatório.")


class ItemCarteira(_Base):
    ticker: str | None = None
    name: str | None = None
    target_weight: float = Field(description="Peso na carteira-modelo; os itens somam 100%.")
    rationale: str | None = None


class CarteiraModelo(_Base):
    name: str
    risk_profile: str | None = Field(None, description="Ex.: 'conservador', 'moderado', 'arrojado'.")
    description: str | None = None
    rationale_md: str | None = None
    items: list[ItemCarteira]


class ConjuntoRecomendacoes(_Base):
    period: str = Field(description="Trimestre, ex.: '3T26'. O mesmo período e autor substitui a versão anterior.")
    title: str
    summary: str
    body_md: str = Field(description="Seções: Tese do trimestre, Como isso encaixa nas metas, Prioridades para os "
                                     "próximos aportes, Riscos, O que mudou desde a recomendação anterior.")
    changes: list[Mudanca] = Field(default_factory=list, description="Mudanças na carteira atual.")
    portfolios: list[CarteiraModelo] = Field(default_factory=list, description="De 1 a 3 carteiras-modelo.")
    model: str | None = None
    sources: list[str] | None = None


# ---------------------------------------------------------------- recomendações orçamentárias

class ItemOrcamento(_Base):
    action: str = Field(description="'criar', 'ajustar', 'manter', 'remover' ou 'economizar' (orientação sem mudar meta).")
    budget: str = Field(description="Nome da meta; o mesmo da meta existente em ajustar, manter e remover.")
    categories: list[str] | None = Field(None, description="Obrigatório em criar; em ajustar, só se mudar. Use os nomes "
                                                           "de gastos_categorias; internas não entram.")
    current_limit: float | None = Field(None, description="Em reais.")
    suggested_limit: float | None = Field(None, description="Em reais; obrigatório em criar e ajustar.")
    expected_monthly_savings: float | None = Field(None, description="Em reais por mês.")
    priority: int | None = Field(None, description="1 (alta) a 3 (baixa).")
    rationale: str = Field(description="Uma a três frases com números do contexto.")


class ConjuntoOrcamento(_Base):
    period: str = Field(description="Mês analisado, AAAA-MM. O mesmo mês e autor substitui a versão anterior.")
    title: str
    summary: str
    body_md: str
    items: list[ItemOrcamento] = Field(description="De 3 a 7 itens.")
    expected_monthly_savings: float | None = Field(None, description="Soma da economia dos itens, em reais por mês.")
    model: str | None = None
