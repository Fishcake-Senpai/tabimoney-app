"""Gestão de patrimônio físico (imóveis, veículos e outros bens) com avaliação por IA.

Inclui:
- Cadastro e regras de valorização/depreciação com histórico;
- Motor de homogeneização de imóveis baseado na ABNT NBR 14653-2 / IBAPE (fator de oferta,
  área, terreno, padrão construtivo, conservação, localização, expurgo de outliers, faixa e confiança);
- Consenso FIPE multi-fonte, tabela de alíquotas de IPVA por UF e TCO mensal para veículos;
- KPIs patrimoniais (preço/m², rental yield bruto, Cap Rate/NOI, custo de carregamento,
  custo de oportunidade vs. CDI líquido e IPCA, concentração no patrimônio);
- Criação rápida de Contas Fixas a partir de IPTU, IPVA e Seguro estimados.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from typing import Any

from app.db import rows, transaction
from app.services import recurring


def _one(sql: str, params: tuple[Any, ...] = ()) -> Any:
    data = rows(sql, params)
    return data[0] if data else None

ASSET_TYPES: dict[str, str] = {
    "imovel": "Imóvel",
    "veiculo": "Veículo",
    "outro": "Outro bem",
}

ASSET_SUBTYPES: dict[str, dict[str, str]] = {
    "imovel": {
        "casa_rua": "Casa (rua)",
        "casa_condominio": "Casa em condomínio",
        "apartamento": "Apartamento",
        "terreno": "Terreno",
        "comercial": "Imóvel comercial",
    },
    "veiculo": {
        "carro": "Carro",
        "moto": "Moto",
        "utilitario": "Utilitário / Caminhonete",
    },
    "outro": {
        "outro": "Outro bem",
    },
}

VALUATION_METHODS: dict[str, str] = {
    "manual": "Manual",
    "regra": "Regra de valorização",
    "ia": "Avaliação da IA",
}

GROWTH_PERIODS: dict[str, str] = {
    "mensal": "ao mês",
    "anual": "ao ano",
}

PROPERTY_STANDARDS: dict[str, tuple[str, float]] = {
    "economico": ("Econômico", 0.85),
    "medio": ("Médio", 1.00),
    "medio_alto": ("Médio-alto", 1.12),
    "alto": ("Alto padrão", 1.25),
}

PROPERTY_CONSERVATION: dict[str, tuple[str, float]] = {
    "precisa_reforma": ("Precisa de reforma", 0.85),
    "original_bom": ("Original bem conservado", 0.95),
    "reformado": ("Reformado / atualizado", 1.05),
    "novo": ("Novo / recém-entregue", 1.10),
}

PROPERTY_USES: dict[str, str] = {
    "moradia": "Moradia própria",
    "alugado": "Alugado (renda)",
    "vazio": "Vazio / investimento",
    "veraneio": "Veraneio / lazer",
}

CONFIDENCE_LABELS: dict[str, str] = {
    "alta": "Alta",
    "media": "Média",
    "baixa": "Baixa",
    "insuficiente": "Insuficiente",
}

# Alíquotas típicas de IPVA por UF para veículos de passeio (carro) e motos (fração decimal).
# Referência: legislação estadual padrão; a IA pode sobrescrever se o estado tiver regra específica
# (ex.: carro elétrico, híbrido, GNV ou isenção por idade).
IPVA_ALIQUOTA_UF: dict[str, dict[str, float]] = {
    "AC": {"carro": 0.02, "moto": 0.01, "utilitario": 0.02},
    "AL": {"carro": 0.0325, "moto": 0.02, "utilitario": 0.0325},
    "AP": {"carro": 0.03, "moto": 0.015, "utilitario": 0.03},
    "AM": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "BA": {"carro": 0.025, "moto": 0.01, "utilitario": 0.025},
    "CE": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "DF": {"carro": 0.035, "moto": 0.02, "utilitario": 0.035},
    "ES": {"carro": 0.02, "moto": 0.01, "utilitario": 0.02},
    "GO": {"carro": 0.0345, "moto": 0.03, "utilitario": 0.0345},
    "MA": {"carro": 0.025, "moto": 0.02, "utilitario": 0.025},
    "MT": {"carro": 0.03, "moto": 0.025, "utilitario": 0.03},
    "MS": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "MG": {"carro": 0.04, "moto": 0.02, "utilitario": 0.04},
    "PA": {"carro": 0.025, "moto": 0.01, "utilitario": 0.025},
    "PB": {"carro": 0.025, "moto": 0.025, "utilitario": 0.025},
    "PE": {"carro": 0.024, "moto": 0.02, "utilitario": 0.024},
    "PI": {"carro": 0.025, "moto": 0.02, "utilitario": 0.025},
    "RJ": {"carro": 0.04, "moto": 0.02, "utilitario": 0.04},
    "RN": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "RS": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "RO": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "RR": {"carro": 0.03, "moto": 0.02, "utilitario": 0.03},
    "SC": {"carro": 0.02, "moto": 0.01, "utilitario": 0.02},
    "SP": {"carro": 0.04, "moto": 0.02, "utilitario": 0.04},
    "SE": {"carro": 0.025, "moto": 0.02, "utilitario": 0.025},
    "TO": {"carro": 0.02, "moto": 0.02, "utilitario": 0.02},
}

DEFAULT_CDI_ANNUAL = 0.125
DEFAULT_IPCA_ANNUAL = 0.045
IR_RENDA_FIXA_LP = 0.15


# ---------------------------------------------------------------- utilitários

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clean_date(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()[:10]
    date.fromisoformat(s)
    return s


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return fallback


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Percentil linear (0 <= p <= 1) sobre lista já ordenada."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def cdi_12m_atual() -> tuple[float, str]:
    """Lê o CDI acumulado dos últimos 12 meses de benchmark_quote; se ausente, usa referência padrão."""
    data = rows("SELECT trade_date, value FROM benchmark_quote WHERE code = 'CDI' ORDER BY trade_date")
    if len(data) >= 20:
        last_date = data[-1]["trade_date"]
        cutoff = (date.fromisoformat(last_date) - timedelta(days=365)).isoformat()
        recent = [r for r in data if r["trade_date"] >= cutoff]
        if len(recent) >= 2:
            v0, v1 = float(recent[0]["value"]), float(recent[-1]["value"])
            if v0 > 0:
                days = max(1, (date.fromisoformat(recent[-1]["trade_date"]) - date.fromisoformat(recent[0]["trade_date"])).days)
                factor = v1 / v0
                annualized = (factor ** (365.0 / days)) - 1.0 if days < 340 else factor - 1.0
                if 0.0 < annualized < 0.5:
                    return round(annualized, 4), "banco_cdi"
    return DEFAULT_CDI_ANNUAL, "padrao"


def valor_projetado_regra(
    base_cents: int,
    rate_bps: int,
    period: str,
    start_date_iso: str | None,
    ref_date: date | None = None,
) -> int:
    """Projeta valor composto a partir de base_cents, taxa em bps e data inicial."""
    if base_cents <= 0 or not rate_bps or not start_date_iso:
        return max(0, int(base_cents))
    ref = ref_date or date.today()
    try:
        start = date.fromisoformat(start_date_iso)
    except ValueError:
        return max(0, int(base_cents))
    days = (ref - start).days
    if days <= 0:
        return max(0, int(base_cents))
    rate = rate_bps / 10000.0
    if period == "mensal":
        periods = days / 30.4375
    else:
        periods = days / 365.25
    factor = max(0.0, 1.0 + rate) ** periods
    return max(0, int(round(base_cents * factor)))


def effective_value_cents(asset: dict[str, Any], ref_date: date | None = None) -> int:
    """Valor corrente efetivo do bem (aplica regra de valorização se method == 'regra')."""
    if asset.get("valuation_method") == "regra":
        base = int(asset.get("acquisition_cents") or asset.get("current_value_cents") or 0)
        start = asset.get("growth_start_date") or asset.get("acquisition_date")
        return valor_projetado_regra(
            base,
            int(asset.get("growth_rate_bps") or 0),
            asset.get("growth_period") or "anual",
            start,
            ref_date=ref_date,
        )
    return max(0, int(asset.get("current_value_cents") or 0))


# ---------------------------------------------------------------- CRUD

def _hydrate_asset(row: Any, latest_val: dict[str, Any] | None = None, ref_date: date | None = None) -> dict[str, Any]:
    item = dict(row)
    item["details"] = _json_loads(item.get("details_json"), {})
    item["asset_type_label"] = ASSET_TYPES.get(item["asset_type"], item["asset_type"])
    subtypes = ASSET_SUBTYPES.get(item["asset_type"], {})
    item["subtype_label"] = subtypes.get(item.get("subtype") or "", item.get("subtype") or item["asset_type_label"])
    item["valuation_method_label"] = VALUATION_METHODS.get(item["valuation_method"], item["valuation_method"])
    item["effective_value_cents"] = effective_value_cents(item, ref_date=ref_date)
    acq = int(item.get("acquisition_cents") or 0)
    eff = item["effective_value_cents"]
    item["gain_cents"] = (eff - acq) if acq > 0 else None
    item["gain_pct"] = ((eff / acq) - 1.0) if acq > 0 else None
    item["annual_carrying_cents"] = (
        int(item.get("estimated_annual_tax_cents") or 0)
        + int(item.get("estimated_annual_insurance_cents") or 0)
        + int(item.get("estimated_annual_maintenance_cents") or 0)
    )
    item["latest_valuation"] = latest_val
    return item


def list_valuations(asset_id: int, limit: int = 20) -> list[dict[str, Any]]:
    data = rows(
        "SELECT * FROM asset_valuation WHERE asset_id = ? ORDER BY evaluated_at DESC, id DESC LIMIT ?",
        (int(asset_id), int(limit)),
    )
    out = []
    for r in data:
        v = dict(r)
        v["comparables"] = _json_loads(v.get("comparables_json"), [])
        v["kpis"] = _json_loads(v.get("kpis_json"), {})
        v["sources"] = _json_loads(v.get("sources_json"), [])
        v["confidence_label"] = CONFIDENCE_LABELS.get(v.get("confidence") or "", v.get("confidence") or "")
        out.append(v)
    return out


def list_assets(
    member: int | None = None,
    include_sold: bool = False,
    ref_date: date | None = None,
) -> list[dict[str, Any]]:
    where = ["a.deleted_at IS NULL"]
    params: list[Any] = []
    if not include_sold:
        where.append("a.status = 'ativo'")
    if member is not None:
        where.append("COALESCE(a.member_id, 1) = ?")
        params.append(int(member))
    data = rows(
        f"SELECT a.*, m.name AS member_name FROM physical_asset a "
        f"LEFT JOIN household_member m ON m.id = a.member_id "
        f"WHERE {' AND '.join(where)} ORDER BY a.asset_type, a.name",
        tuple(params),
    )
    if not data:
        return []
    ids = [int(r["id"]) for r in data]
    placeholders = ",".join("?" for _ in ids)
    val_rows = rows(
        f"SELECT * FROM asset_valuation WHERE asset_id IN ({placeholders}) ORDER BY evaluated_at DESC, id DESC",
        tuple(ids),
    )
    latest_by_asset: dict[int, dict[str, Any]] = {}
    for vr in val_rows:
        aid = int(vr["asset_id"])
        if aid not in latest_by_asset:
            v = dict(vr)
            v["comparables"] = _json_loads(v.get("comparables_json"), [])
            v["kpis"] = _json_loads(v.get("kpis_json"), {})
            v["sources"] = _json_loads(v.get("sources_json"), [])
            v["confidence_label"] = CONFIDENCE_LABELS.get(v.get("confidence") or "", v.get("confidence") or "")
            latest_by_asset[aid] = v
    return [_hydrate_asset(r, latest_by_asset.get(int(r["id"])), ref_date=ref_date) for r in data]


def get_asset(asset_id: int, ref_date: date | None = None) -> dict[str, Any] | None:
    r = _one(
        "SELECT a.*, m.name AS member_name FROM physical_asset a "
        "LEFT JOIN household_member m ON m.id = a.member_id "
        "WHERE a.id = ? AND a.deleted_at IS NULL",
        (int(asset_id),),
    )
    if not r:
        return None
    vals = list_valuations(int(asset_id), limit=20)
    asset = _hydrate_asset(r, vals[0] if vals else None, ref_date=ref_date)
    asset["valuations"] = vals
    return asset


def save_asset(
    *,
    name: str,
    asset_type: str,
    subtype: str = "",
    current_value_cents: int = 0,
    acquisition_cents: int = 0,
    acquisition_date: str | None = None,
    valuation_method: str = "manual",
    growth_rate_bps: int = 0,
    growth_period: str = "anual",
    growth_start_date: str | None = None,
    details: dict[str, Any] | None = None,
    estimated_annual_tax_cents: int = 0,
    estimated_annual_insurance_cents: int = 0,
    estimated_monthly_rent_cents: int = 0,
    estimated_annual_maintenance_cents: int = 0,
    status: str = "ativo",
    note: str | None = None,
    member_id: int | None = None,
    asset_id: int | None = None,
    author: str = "usuario",
) -> dict[str, Any]:
    """Cria ou atualiza um bem físico."""
    clean_name = " ".join((name or "").split())[:120]
    if not clean_name:
        raise ValueError("Informe o nome do bem.")
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"Tipo inválido: {asset_type!r}. Use: {', '.join(ASSET_TYPES)}.")
    if valuation_method not in VALUATION_METHODS:
        raise ValueError(f"Método de avaliação inválido: {valuation_method!r}.")
    if growth_period not in GROWTH_PERIODS:
        raise ValueError(f"Período da regra inválido: {growth_period!r}.")
    if status not in ("ativo", "vendido"):
        raise ValueError(f"Status inválido: {status!r}.")

    valid_subtypes = ASSET_SUBTYPES.get(asset_type, {})
    clean_subtype = subtype if subtype in valid_subtypes else (next(iter(valid_subtypes), ""))
    iso_acq = _clean_date(acquisition_date)
    iso_growth = _clean_date(growth_start_date) or iso_acq
    cur_cents = max(0, int(current_value_cents))
    acq_cents = max(0, int(acquisition_cents))
    if cur_cents == 0 and acq_cents > 0:
        cur_cents = acq_cents
    clean_details = details if isinstance(details, dict) else {}
    details_json = json.dumps(clean_details, ensure_ascii=False)
    clean_note = " ".join((note or "").split())[:500] or None
    mid = int(member_id or 1)

    with transaction() as conn:
        if asset_id:
            found = conn.execute(
                "SELECT id, current_value_cents FROM physical_asset WHERE id = ? AND deleted_at IS NULL",
                (int(asset_id),),
            ).fetchone()
            if not found:
                raise ValueError("Bem não encontrado.")
            conn.execute(
                "UPDATE physical_asset SET member_id = ?, asset_type = ?, subtype = ?, name = ?, status = ?, "
                "acquisition_date = ?, acquisition_cents = ?, current_value_cents = ?, valuation_method = ?, "
                "growth_rate_bps = ?, growth_period = ?, growth_start_date = ?, details_json = ?, "
                "estimated_annual_tax_cents = ?, estimated_annual_insurance_cents = ?, "
                "estimated_monthly_rent_cents = ?, estimated_annual_maintenance_cents = ?, "
                "note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    mid, asset_type, clean_subtype, clean_name, status,
                    iso_acq, acq_cents, cur_cents, valuation_method,
                    int(growth_rate_bps), growth_period, iso_growth, details_json,
                    max(0, int(estimated_annual_tax_cents)),
                    max(0, int(estimated_annual_insurance_cents)),
                    max(0, int(estimated_monthly_rent_cents)),
                    max(0, int(estimated_annual_maintenance_cents)),
                    clean_note, int(asset_id),
                ),
            )
            aid = int(asset_id)
        else:
            cur = conn.execute(
                "INSERT INTO physical_asset("
                "member_id, asset_type, subtype, name, status, acquisition_date, acquisition_cents, "
                "current_value_cents, valuation_method, growth_rate_bps, growth_period, growth_start_date, "
                "details_json, estimated_annual_tax_cents, estimated_annual_insurance_cents, "
                "estimated_monthly_rent_cents, estimated_annual_maintenance_cents, note, author"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mid, asset_type, clean_subtype, clean_name, status, iso_acq, acq_cents,
                    cur_cents, valuation_method, int(growth_rate_bps), growth_period, iso_growth,
                    details_json,
                    max(0, int(estimated_annual_tax_cents)),
                    max(0, int(estimated_annual_insurance_cents)),
                    max(0, int(estimated_monthly_rent_cents)),
                    max(0, int(estimated_annual_maintenance_cents)),
                    clean_note, author,
                ),
            )
            aid = int(cur.lastrowid)
            if cur_cents > 0:
                conn.execute(
                    "INSERT INTO asset_valuation(asset_id, evaluated_at, source, value_cents, author, report_md) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (aid, date.today().isoformat(), "regra" if valuation_method == "regra" else "manual", cur_cents, author, ""),
                )
    return get_asset(aid)  # type: ignore[return-value]


def delete_asset(asset_id: int) -> dict[str, Any]:
    """Exclusão reversível (soft-delete) de um bem."""
    found = _one("SELECT id, name FROM physical_asset WHERE id = ? AND deleted_at IS NULL", (int(asset_id),))
    if not found:
        raise ValueError("Bem não encontrado.")
    with transaction() as conn:
        conn.execute("UPDATE physical_asset SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (int(asset_id),))
    return {"id": int(found["id"]), "name": found["name"], "removed": True}


# ---------------------------------------------------------------- Motor NBR 14653-2 (Imóveis)

def _factor_for_choice(table: dict[str, tuple[str, float]], eval_key: str | None, comp_key: str | None) -> float:
    e_val = table.get((eval_key or "medio").lower(), ("", 1.0))[1]
    c_val = table.get((comp_key or eval_key or "medio").lower(), ("", e_val))[1]
    if c_val <= 0:
        return 1.0
    return e_val / c_val


def homogeneizar_comparaveis_imovel(
    asset: dict[str, Any],
    comparaveis: list[dict[str, Any]],
    *,
    objetivo: str = "venda",
    fator_oferta_padrao: float | None = None,
) -> dict[str, Any]:
    """Aplica o Método Comparativo Direto por Fatores (ABNT NBR 14653-2 / IBAPE).

    Args:
        asset: dicionário do imóvel avaliando (com `subtype` e `details`).
        comparaveis: lista de anúncios/transações comparáveis em reais.
        objetivo: 'venda' (padrão, F_oferta=0.90) ou 'aluguel' (F_oferta=0.97).
        fator_oferta_padrao: sobrescreve o fator de oferta para dados do tipo 'oferta'.
    """
    details = asset.get("details") or {}
    subtype = asset.get("subtype") or ""
    is_terreno = subtype == "terreno"
    is_casa = subtype in ("casa_rua", "casa_condominio")

    area_eval = float(details.get("area_terreno_m2") if is_terreno else details.get("area_construida_m2") or 0)
    terreno_eval = float(details.get("area_terreno_m2") or 0)
    if area_eval <= 0:
        raise ValueError(
            "Cadastre a área do terreno (m²)" if is_terreno else "Cadastre a área construída/privativa (m²) do imóvel."
        )

    default_offer = fator_oferta_padrao if fator_oferta_padrao is not None else (0.97 if objetivo == "aluguel" else 0.90)
    padrao_eval = details.get("padrao") or "medio"
    conserv_eval = details.get("conservacao") or "original_bom"

    processados: list[dict[str, Any]] = []
    for idx, comp in enumerate(comparaveis or [], start=1):
        preco = float(comp.get("preco") or 0)
        area_comp = float(
            comp.get("area_terreno_m2") if is_terreno else (comp.get("area_construida_m2") or comp.get("area_m2") or 0)
        )
        if preco <= 0 or area_comp <= 0:
            processados.append({
                "indice": idx,
                "fonte": comp.get("fonte") or "",
                "url": comp.get("url") or "",
                "descartado": True,
                "motivo_descarte": "preço ou área inválidos",
            })
            continue

        tipo_dado = str(comp.get("tipo_dado") or "oferta").lower()
        f_oferta = 1.0 if tipo_dado in ("transacao", "fechado", "contrato") else float(
            comp.get("fator_oferta") or default_offer
        )
        f_oferta = _clamp(f_oferta, 0.75, 1.05)

        pu_bruto = preco / area_comp
        pu_ajustado = pu_bruto * f_oferta

        # Fator área (elasticidade de escala ~0.25: imóveis maiores tendem a ter R$/m² ligeiramente menor)
        f_area = _clamp((area_comp / area_eval) ** 0.25, 0.88, 1.12)

        # Fator terreno (para casas): ajusta diferença de proporção de terreno
        f_terreno = 1.0
        terreno_comp = float(comp.get("area_terreno_m2") or 0)
        if is_casa and terreno_eval > 0 and terreno_comp > 0:
            ratio_eval = terreno_eval / area_eval
            ratio_comp = terreno_comp / area_comp
            if ratio_comp > 0:
                f_terreno = _clamp((ratio_eval / ratio_comp) ** 0.20, 0.85, 1.15)

        f_padrao = 1.0 if is_terreno else _factor_for_choice(PROPERTY_STANDARDS, padrao_eval, comp.get("padrao"))
        f_conserv = 1.0 if is_terreno else _factor_for_choice(PROPERTY_CONSERVATION, conserv_eval, comp.get("conservacao"))
        f_local = _clamp(float(comp.get("fator_localizacao") or 1.0), 0.90, 1.10)

        f_total_bruto = f_area * f_terreno * f_padrao * f_conserv * f_local
        # Boa prática NBR 14653-2: limitar amplitude acumulada dos fatores a [0.80, 1.25]
        f_total = _clamp(f_total_bruto, 0.80, 1.25)
        pu_hom = pu_ajustado * f_total

        processados.append({
            "indice": idx,
            "fonte": comp.get("fonte") or "",
            "url": comp.get("url") or "",
            "tipo_dado": tipo_dado,
            "preco": round(preco, 2),
            "area_m2": round(area_comp, 2),
            "area_terreno_m2": round(terreno_comp, 2) if terreno_comp > 0 else None,
            "quartos": comp.get("quartos"),
            "vagas": comp.get("vagas"),
            "padrao": comp.get("padrao"),
            "conservacao": comp.get("conservacao"),
            "observacao": comp.get("observacao") or "",
            "pu_bruto": round(pu_bruto, 2),
            "f_oferta": round(f_oferta, 4),
            "f_area": round(f_area, 4),
            "f_terreno": round(f_terreno, 4),
            "f_padrao": round(f_padrao, 4),
            "f_conservacao": round(f_conserv, 4),
            "f_localizacao": round(f_local, 4),
            "f_total": round(f_total, 4),
            "pu_homogeneizado": round(pu_hom, 2),
            "descartado": False,
            "motivo_descarte": None,
        })

    ativos = [p for p in processados if not p["descartado"]]
    if not ativos:
        raise ValueError("Nenhum comparável válido com preço e área positivos.")

    # Expurgo de outliers (IQR com banda mínima de ±20% sobre a mediana para n >= 6; ±30% para amostras menores)
    pus = sorted(p["pu_homogeneizado"] for p in ativos)
    med = statistics.median(pus)
    if len(pus) >= 6:
        q1 = _percentile(pus, 0.25)
        q3 = _percentile(pus, 0.75)
        iqr = q3 - q1
        lo_lim = min(q1 - 1.5 * iqr, med * 0.80)
        hi_lim = max(q3 + 1.5 * iqr, med * 1.20)
    else:
        lo_lim = med * 0.70
        hi_lim = med * 1.30

    for p in ativos:
        if p["pu_homogeneizado"] < lo_lim or p["pu_homogeneizado"] > hi_lim:
            p["descartado"] = True
            p["motivo_descarte"] = "outlier (fora do intervalo estatístico)"

    validos = [p for p in processados if not p["descartado"]]
    if not validos:
        # fallback de segurança: se tudo foi marcado, mantém os ativos originais
        for p in ativos:
            p["descartado"] = False
            p["motivo_descarte"] = None
        validos = ativos

    pus_validos = sorted(p["pu_homogeneizado"] for p in validos)
    mediana_pu = statistics.median(pus_validos)
    media_pu = statistics.mean(pus_validos)
    stdev_pu = statistics.stdev(pus_validos) if len(pus_validos) >= 2 else 0.0
    cv = (stdev_pu / media_pu) if media_pu > 0 else 0.0

    if len(pus_validos) >= 5:
        piso_pu = _percentile(pus_validos, 0.25)
        teto_pu = _percentile(pus_validos, 0.75)
        # Garante faixa mínima de ±5% para não sugerir precisão irreal
        piso_pu = min(piso_pu, mediana_pu * 0.95)
        teto_pu = max(teto_pu, mediana_pu * 1.05)
    else:
        piso_pu = mediana_pu * 0.90
        teto_pu = mediana_pu * 1.10

    fontes_distintas = {p["fonte"].strip().lower() for p in validos if p.get("fonte")}
    n_validos = len(validos)
    if n_validos >= 8 and cv <= 0.15 and len(fontes_distintas) >= 2:
        confianca = "alta"
    elif n_validos >= 5 and cv <= 0.25:
        confianca = "media"
    elif n_validos >= 3:
        confianca = "baixa"
    else:
        confianca = "insuficiente"

    central_cents = int(round(mediana_pu * area_eval * 100))
    piso_cents = int(round(piso_pu * area_eval * 100))
    teto_cents = int(round(teto_pu * area_eval * 100))

    return {
        "objetivo": objetivo,
        "area_referencia_m2": area_eval,
        "valor_central_cents": central_cents,
        "valor_piso_cents": piso_cents,
        "valor_teto_cents": teto_cents,
        "preco_m2_central_cents": int(round(mediana_pu * 100)),
        "preco_m2_media_cents": int(round(media_pu * 100)),
        "coeficiente_variacao": round(cv, 4),
        "grau_confianca": confianca,
        "amostras_totais": len(processados),
        "amostras_validas": n_validos,
        "amostras_descartadas": len(processados) - n_validos,
        "fontes_distintas": len(fontes_distintas),
        "comparaveis": processados,
    }


# ---------------------------------------------------------------- KPIs de Imóvel e Veículo

def calcular_kpis_imovel(
    asset: dict[str, Any],
    *,
    valor_mercado_cents: int,
    aluguel_mensal_cents: int = 0,
    iptu_anual_cents: int = 0,
    seguro_anual_cents: int = 0,
    manutencao_anual_cents: int = 0,
    condominio_mensal_cents: int = 0,
    taxa_adm_pct: float = 0.08,
    vacancia_pct: float = 0.0833,
    patrimonio_liquido_total_cents: int = 0,
    cdi_anual: float | None = None,
    ipca_anual: float = DEFAULT_IPCA_ANNUAL,
) -> dict[str, Any]:
    """Calcula todos os KPIs patrimoniais de um imóvel."""
    details = asset.get("details") or {}
    subtype = asset.get("subtype") or ""
    uso = details.get("uso") or "moradia"
    area_const = float(details.get("area_construida_m2") or 0)
    area_terr = float(details.get("area_terreno_m2") or 0)
    acq_cents = int(asset.get("acquisition_cents") or 0)
    acq_date = asset.get("acquisition_date")

    if cdi_anual is None:
        cdi_anual, cdi_fonte = cdi_12m_atual()
    else:
        cdi_fonte = "informado"
    cdi_liquido = cdi_anual * (1.0 - IR_RENDA_FIXA_LP)

    # Manutenção padrão caso não informada: 0.5% a.a. apto, 0.8% a.a. casa, 0.2% terreno
    if manutencao_anual_cents <= 0 and valor_mercado_cents > 0:
        taxa_manut = 0.002 if subtype == "terreno" else (0.005 if subtype == "apartamento" else 0.008)
        manutencao_anual_cents = int(round(valor_mercado_cents * taxa_manut))

    # Seguro residencial padrão se não informado: ~0.10% a.a. (exceto terreno)
    if seguro_anual_cents <= 0 and valor_mercado_cents > 0 and subtype != "terreno":
        seguro_anual_cents = int(round(valor_mercado_cents * 0.001))

    aluguel_anual_bruto = aluguel_mensal_cents * 12
    rental_yield_bruto = (aluguel_anual_bruto / valor_mercado_cents) if valor_mercado_cents > 0 and aluguel_anual_bruto > 0 else None

    # NOI (Net Operating Income): para imóvel de renda desconta adm, vacância, seguro, manutenção e IPTU/cond. no período vago
    if aluguel_anual_bruto > 0 and valor_mercado_cents > 0:
        if uso == "alugado":
            perda_vacancia = aluguel_anual_bruto * vacancia_pct
            taxa_adm = (aluguel_anual_bruto - perda_vacancia) * taxa_adm_pct
            custos_vago = (iptu_anual_cents + condominio_mensal_cents * 12) * vacancia_pct
            noi_anual = aluguel_anual_bruto - perda_vacancia - taxa_adm - custos_vago - manutencao_anual_cents - seguro_anual_cents
        else:
            # Para moradia própria: aluguel implícito economizado menos custos anuais de propriedade (IPTU, seguro, manutenção)
            noi_anual = aluguel_anual_bruto - iptu_anual_cents - manutencao_anual_cents - seguro_anual_cents
        cap_rate_liquido = noi_anual / valor_mercado_cents
    else:
        noi_anual = 0.0
        cap_rate_liquido = None

    # Valorização nominal e anualizada desde a compra
    valorizacao_nominal = ((valor_mercado_cents / acq_cents) - 1.0) if acq_cents > 0 else None
    valorizacao_anualizada = None
    valorizacao_real_anual = None
    if acq_cents > 0 and acq_date:
        try:
            anos = (date.today() - date.fromisoformat(acq_date)).days / 365.25
            if anos >= 0.25 and valor_mercado_cents > 0:
                valorizacao_anualizada = ((valor_mercado_cents / acq_cents) ** (1.0 / anos)) - 1.0
                valorizacao_real_anual = ((1.0 + valorizacao_anualizada) / (1.0 + ipca_anual)) - 1.0
        except ValueError:
            pass

    custo_carregamento_anual = (
        iptu_anual_cents
        + seguro_anual_cents
        + manutencao_anual_cents
        + (condominio_mensal_cents * 12 if uso != "alugado" else int(round(condominio_mensal_cents * 12 * vacancia_pct)))
    )

    retorno_total_estimado = None
    spread_vs_cdi_liquido = None
    if cap_rate_liquido is not None:
        val_anual = valorizacao_anualizada if valorizacao_anualizada is not None else ipca_anual
        retorno_total_estimado = cap_rate_liquido + val_anual
        spread_vs_cdi_liquido = retorno_total_estimado - cdi_liquido

    concentracao = (
        valor_mercado_cents / patrimonio_liquido_total_cents
        if patrimonio_liquido_total_cents > 0
        else None
    )

    return {
        "tipo": "imovel",
        "uso": uso,
        "preco_m2_construido": round((valor_mercado_cents / 100.0) / area_const, 2) if area_const > 0 else None,
        "preco_m2_terreno": round((valor_mercado_cents / 100.0) / area_terr, 2) if area_terr > 0 else None,
        "valorizacao_nominal": round(valorizacao_nominal, 4) if valorizacao_nominal is not None else None,
        "valorizacao_anualizada": round(valorizacao_anualizada, 4) if valorizacao_anualizada is not None else None,
        "valorizacao_real_anual": round(valorizacao_real_anual, 4) if valorizacao_real_anual is not None else None,
        "aluguel_mensal_estimado": round(aluguel_mensal_cents / 100.0, 2),
        "rental_yield_bruto": round(rental_yield_bruto, 4) if rental_yield_bruto is not None else None,
        "noi_anual": round(noi_anual / 100.0, 2),
        "cap_rate_liquido": round(cap_rate_liquido, 4) if cap_rate_liquido is not None else None,
        "iptu_anual_estimado": round(iptu_anual_cents / 100.0, 2),
        "seguro_anual_estimado": round(seguro_anual_cents / 100.0, 2),
        "manutencao_anual_estimada": round(manutencao_anual_cents / 100.0, 2),
        "custo_carregamento_anual": round(custo_carregamento_anual / 100.0, 2),
        "cdi_anual_referencia": round(cdi_anual, 4),
        "cdi_liquido_referencia": round(cdi_liquido, 4),
        "cdi_fonte": cdi_fonte,
        "ipca_anual_referencia": round(ipca_anual, 4),
        "retorno_total_estimado": round(retorno_total_estimado, 4) if retorno_total_estimado is not None else None,
        "spread_vs_cdi_liquido": round(spread_vs_cdi_liquido, 4) if spread_vs_cdi_liquido is not None else None,
        "concentracao_patrimonio": round(concentracao, 4) if concentracao is not None else None,
    }


def aliquota_ipva(uf: str | None, subtype: str = "carro") -> float:
    """Devolve alíquota típica de IPVA para a UF e subtipo (padrão 3% se UF não informada)."""
    key = (uf or "").strip().upper()
    row = IPVA_ALIQUOTA_UF.get(key)
    if not row:
        return 0.02 if subtype == "moto" else 0.03
    return row.get(subtype, row["carro"])


def simular_avaliacao_veiculo(
    asset: dict[str, Any],
    *,
    fontes_fipe: list[dict[str, Any]],
    seguro_anual_cents: int | None = None,
    ipva_aliquota: float | None = None,
    manutencao_anual_cents: int | None = None,
    licenciamento_anual_cents: int = 16000,
    patrimonio_liquido_total_cents: int = 0,
) -> dict[str, Any]:
    """Consolida FIPE de múltiplas fontes, calcula IPVA pela UF, depreciação e TCO mensal."""
    precos = [float(f.get("preco") or 0) for f in (fontes_fipe or []) if float(f.get("preco") or 0) > 0]
    if not precos:
        raise ValueError("Informe ao menos uma consulta FIPE com preço válido.")

    precos.sort()
    mediana = statistics.median(precos)
    piso = min(precos) if len(precos) >= 2 else mediana * 0.97
    teto = max(precos) if len(precos) >= 2 else mediana * 1.03
    valor_cents = int(round(mediana * 100))

    fontes_nomes = {str(f.get("fonte") or "").strip().lower() for f in fontes_fipe if f.get("fonte")}
    if len(precos) >= 2 and len(fontes_nomes) >= 2:
        confianca = "alta"
    elif len(precos) >= 1:
        confianca = "media"
    else:
        confianca = "insuficiente"

    details = asset.get("details") or {}
    uf = details.get("uf") or ""
    subtype = asset.get("subtype") or "carro"
    aliq = float(ipva_aliquota) if ipva_aliquota is not None else aliquota_ipva(uf, subtype)
    ipva_cents = int(round(valor_cents * aliq))

    if seguro_anual_cents is None:
        seguro_anual_cents = int(asset.get("estimated_annual_insurance_cents") or round(valor_cents * 0.05))
    if manutencao_anual_cents is None:
        manutencao_anual_cents = int(asset.get("estimated_annual_maintenance_cents") or round(valor_cents * 0.03))

    acq_cents = int(asset.get("acquisition_cents") or 0)
    acq_date = asset.get("acquisition_date")
    depreciacao_total_cents = (valor_cents - acq_cents) if acq_cents > 0 else None
    depreciacao_total_pct = ((valor_cents / acq_cents) - 1.0) if acq_cents > 0 else None
    depreciacao_anual_cents = None
    depreciacao_anual_pct = None
    if acq_cents > 0 and acq_date:
        try:
            anos = (date.today() - date.fromisoformat(acq_date)).days / 365.25
            if anos >= 0.25 and valor_cents > 0:
                depreciacao_anual_pct = ((valor_cents / acq_cents) ** (1.0 / anos)) - 1.0
                depreciacao_anual_cents = int(round(max(0.0, -depreciacao_anual_pct) * valor_cents))
        except ValueError:
            pass
    if depreciacao_anual_cents is None:
        # fallback conservador: 8% a.a. de depreciação para TCO
        depreciacao_anual_cents = int(round(valor_cents * 0.08))

    custo_fixo_anual_cents = ipva_cents + seguro_anual_cents + manutencao_anual_cents + licenciamento_anual_cents
    tco_anual_cents = custo_fixo_anual_cents + depreciacao_anual_cents
    concentracao = (valor_cents / patrimonio_liquido_total_cents) if patrimonio_liquido_total_cents > 0 else None

    kpis = {
        "tipo": "veiculo",
        "uf": uf.upper() or None,
        "codigo_fipe": details.get("codigo_fipe"),
        "aliquota_ipva": round(aliq, 4),
        "ipva_anual_estimado": round(ipva_cents / 100.0, 2),
        "seguro_anual_estimado": round(seguro_anual_cents / 100.0, 2),
        "manutencao_anual_estimada": round(manutencao_anual_cents / 100.0, 2),
        "licenciamento_anual_estimado": round(licenciamento_anual_cents / 100.0, 2),
        "custo_fixo_anual": round(custo_fixo_anual_cents / 100.0, 2),
        "depreciacao_total": round(depreciacao_total_cents / 100.0, 2) if depreciacao_total_cents is not None else None,
        "depreciacao_total_pct": round(depreciacao_total_pct, 4) if depreciacao_total_pct is not None else None,
        "depreciacao_anual_estimada": round(depreciacao_anual_cents / 100.0, 2),
        "depreciacao_anual_pct": round(depreciacao_anual_pct, 4) if depreciacao_anual_pct is not None else None,
        "tco_anual": round(tco_anual_cents / 100.0, 2),
        "tco_mensal": round((tco_anual_cents / 12.0) / 100.0, 2),
        "concentracao_patrimonio": round(concentracao, 4) if concentracao is not None else None,
    }

    return {
        "valor_central_cents": valor_cents,
        "valor_piso_cents": int(round(piso * 100)),
        "valor_teto_cents": int(round(teto * 100)),
        "grau_confianca": confianca,
        "fontes_fipe": fontes_fipe,
        "estimated_annual_tax_cents": ipva_cents,
        "estimated_annual_insurance_cents": seguro_anual_cents,
        "estimated_annual_maintenance_cents": manutencao_anual_cents,
        "kpis": kpis,
    }


def simular_avaliacao(
    asset_id: int,
    *,
    comparaveis_venda: list[dict[str, Any]] | None = None,
    comparaveis_aluguel: list[dict[str, Any]] | None = None,
    fontes_fipe: list[dict[str, Any]] | None = None,
    aluguel_mensal_reais: float | None = None,
    iptu_anual_reais: float | None = None,
    seguro_anual_reais: float | None = None,
    manutencao_anual_reais: float | None = None,
    ipva_aliquota: float | None = None,
    patrimonio_liquido_total_cents: int = 0,
) -> dict[str, Any]:
    """Cálculo puro (sem gravar no banco) para a IA validar números e KPIs antes de registrar."""
    asset = get_asset(asset_id)
    if not asset:
        raise ValueError("Bem não encontrado.")

    if asset["asset_type"] == "veiculo":
        sim = simular_avaliacao_veiculo(
            asset,
            fontes_fipe=fontes_fipe or [],
            seguro_anual_cents=int(round(seguro_anual_reais * 100)) if seguro_anual_reais is not None else None,
            ipva_aliquota=ipva_aliquota,
            manutencao_anual_cents=int(round(manutencao_anual_reais * 100)) if manutencao_anual_reais is not None else None,
            patrimonio_liquido_total_cents=patrimonio_liquido_total_cents,
        )
        return {
            "asset_id": asset["id"],
            "name": asset["name"],
            "asset_type": asset["asset_type"],
            "valor_central": round(sim["valor_central_cents"] / 100.0, 2),
            "valor_piso": round(sim["valor_piso_cents"] / 100.0, 2),
            "valor_teto": round(sim["valor_teto_cents"] / 100.0, 2),
            "grau_confianca": sim["grau_confianca"],
            "comparaveis": sim["fontes_fipe"],
            "kpis": sim["kpis"],
            "estimativas": {
                "imposto_anual": round(sim["estimated_annual_tax_cents"] / 100.0, 2),
                "seguro_anual": round(sim["estimated_annual_insurance_cents"] / 100.0, 2),
                "manutencao_anual": round(sim["estimated_annual_maintenance_cents"] / 100.0, 2),
                "aluguel_mensal": 0.0,
            },
        }

    # Imóvel (ou outro bem com comparáveis)
    hom_venda = homogeneizar_comparaveis_imovel(asset, comparaveis_venda or [], objetivo="venda")
    hom_aluguel = None
    if comparaveis_aluguel:
        hom_aluguel = homogeneizar_comparaveis_imovel(asset, comparaveis_aluguel, objetivo="aluguel")
        aluguel_cents = hom_aluguel["valor_central_cents"]
    elif aluguel_mensal_reais is not None:
        aluguel_cents = int(round(max(0.0, aluguel_mensal_reais) * 100))
    else:
        aluguel_cents = int(asset.get("estimated_monthly_rent_cents") or 0)

    details = asset.get("details") or {}
    condo_cents = int(round(float(details.get("condominio_mensal") or 0) * 100))
    iptu_cents = (
        int(round(max(0.0, iptu_anual_reais) * 100))
        if iptu_anual_reais is not None
        else int(asset.get("estimated_annual_tax_cents") or round(float(details.get("iptu_anual") or 0) * 100))
    )
    seguro_cents = (
        int(round(max(0.0, seguro_anual_reais) * 100))
        if seguro_anual_reais is not None
        else int(asset.get("estimated_annual_insurance_cents") or 0)
    )
    manut_cents = (
        int(round(max(0.0, manutencao_anual_reais) * 100))
        if manutencao_anual_reais is not None
        else int(asset.get("estimated_annual_maintenance_cents") or 0)
    )

    kpis = calcular_kpis_imovel(
        asset,
        valor_mercado_cents=hom_venda["valor_central_cents"],
        aluguel_mensal_cents=aluguel_cents,
        iptu_anual_cents=iptu_cents,
        seguro_anual_cents=seguro_cents,
        manutencao_anual_cents=manut_cents,
        condominio_mensal_cents=condo_cents,
        patrimonio_liquido_total_cents=patrimonio_liquido_total_cents,
    )

    return {
        "asset_id": asset["id"],
        "name": asset["name"],
        "asset_type": asset["asset_type"],
        "valor_central": round(hom_venda["valor_central_cents"] / 100.0, 2),
        "valor_piso": round(hom_venda["valor_piso_cents"] / 100.0, 2),
        "valor_teto": round(hom_venda["valor_teto_cents"] / 100.0, 2),
        "grau_confianca": hom_venda["grau_confianca"],
        "homogeneizacao_venda": hom_venda,
        "homogeneizacao_aluguel": hom_aluguel,
        "comparaveis": hom_venda["comparaveis"],
        "kpis": kpis,
        "estimativas": {
            "imposto_anual": kpis["iptu_anual_estimado"],
            "seguro_anual": kpis["seguro_anual_estimado"],
            "manutencao_anual": kpis["manutencao_anual_estimada"],
            "aluguel_mensal": kpis["aluguel_mensal_estimado"],
        },
    }


def registrar_avaliacao(
    asset_id: int,
    *,
    value_cents: int,
    value_low_cents: int | None = None,
    value_high_cents: int | None = None,
    confidence: str | None = None,
    comparables: list[dict[str, Any]] | None = None,
    kpis: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    report_md: str = "",
    estimated_annual_tax_cents: int | None = None,
    estimated_annual_insurance_cents: int | None = None,
    estimated_monthly_rent_cents: int | None = None,
    estimated_annual_maintenance_cents: int | None = None,
    evaluated_at: str | None = None,
    source: str = "ia",
    author: str = "agente",
) -> dict[str, Any]:
    """Grava uma nova avaliação no histórico e atualiza o valor corrente e estimativas do bem."""
    asset = get_asset(asset_id)
    if not asset:
        raise ValueError("Bem não encontrado.")
    if value_cents <= 0:
        raise ValueError("O valor da avaliação precisa ser positivo.")
    if confidence and confidence not in CONFIDENCE_LABELS:
        raise ValueError(f"Grau de confiança inválido: {confidence!r}.")
    if source not in ("manual", "regra", "ia"):
        raise ValueError(f"Origem inválida: {source!r}.")
    iso_date = _clean_date(evaluated_at) or date.today().isoformat()

    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO asset_valuation("
            "asset_id, evaluated_at, source, value_cents, value_low_cents, value_high_cents, "
            "confidence, comparables_json, kpis_json, sources_json, report_md, author"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(asset_id),
                iso_date,
                source,
                int(value_cents),
                int(value_low_cents) if value_low_cents is not None else None,
                int(value_high_cents) if value_high_cents is not None else None,
                confidence,
                json.dumps(comparables or [], ensure_ascii=False),
                json.dumps(kpis or {}, ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
                (report_md or "").strip(),
                author,
            ),
        )
        vid = int(cur.lastrowid)

        updates = ["current_value_cents = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [int(value_cents)]
        if source == "ia":
            updates.append("valuation_method = 'ia'")
        if estimated_annual_tax_cents is not None:
            updates.append("estimated_annual_tax_cents = ?")
            params.append(max(0, int(estimated_annual_tax_cents)))
        if estimated_annual_insurance_cents is not None:
            updates.append("estimated_annual_insurance_cents = ?")
            params.append(max(0, int(estimated_annual_insurance_cents)))
        if estimated_monthly_rent_cents is not None:
            updates.append("estimated_monthly_rent_cents = ?")
            params.append(max(0, int(estimated_monthly_rent_cents)))
        if estimated_annual_maintenance_cents is not None:
            updates.append("estimated_annual_maintenance_cents = ?")
            params.append(max(0, int(estimated_annual_maintenance_cents)))
        params.append(int(asset_id))
        conn.execute(f"UPDATE physical_asset SET {', '.join(updates)} WHERE id = ?", tuple(params))

    return {"valuation_id": vid, "asset": get_asset(asset_id)}


# ---------------------------------------------------------------- Atalho: Conta Fixa (IPTU / IPVA / Seguro)

def criar_conta_fixa_do_bem(
    asset_id: int,
    *,
    kind: str,
    account_id: int | str | None = None,
    start_date: str | None = None,
    frequency: str = "yearly",
    author: str = "usuario",
) -> dict[str, Any]:
    """Cria uma Conta Fixa recorrente a partir do IPTU, IPVA ou Seguro estimado do bem."""
    asset = get_asset(asset_id)
    if not asset:
        raise ValueError("Bem não encontrado.")
    if kind not in ("imposto", "seguro"):
        raise ValueError("Tipo de conta fixa inválido: use 'imposto' (IPTU/IPVA) ou 'seguro'.")

    is_veiculo = asset["asset_type"] == "veiculo"
    if kind == "imposto":
        annual_cents = int(asset.get("estimated_annual_tax_cents") or 0)
        label = f"{'IPVA' if is_veiculo else 'IPTU'} — {asset['name']}"
        category = "Transporte" if is_veiculo else "Moradia"
    else:
        annual_cents = int(asset.get("estimated_annual_insurance_cents") or 0)
        label = f"Seguro — {asset['name']}"
        category = "Transporte" if is_veiculo else "Moradia"

    if annual_cents <= 0:
        raise ValueError("Esse bem ainda não tem valor estimado para criar a conta fixa.")

    amount_cents = -int(round(annual_cents / 12.0)) if frequency == "monthly" else -annual_cents
    iso_start = _clean_date(start_date) or date(date.today().year + 1, 1, 15).isoformat()
    return recurring.save_recurring(
        account_id=account_id,
        description=label,
        amount_cents=amount_cents,
        frequency=frequency,
        start_date=iso_start,
        category=category,
        adjust_business_day=True,
        note=f"Gerado a partir de Patrimônio ({asset['name']})",
        member=int(asset.get("member_id") or 1),
        author=author,
    )


# ---------------------------------------------------------------- Resumo consolidado

def summary(member: int | None = None, ref_date: date | None = None) -> dict[str, Any]:
    """Resumo completo de bens físicos para telas, Início e contexto da IA."""
    assets = list_assets(member=member, include_sold=False, ref_date=ref_date)
    imoveis = [a for a in assets if a["asset_type"] == "imovel"]
    veiculos = [a for a in assets if a["asset_type"] == "veiculo"]
    outros = [a for a in assets if a["asset_type"] == "outro"]

    total_cents = sum(a["effective_value_cents"] for a in assets)
    imoveis_cents = sum(a["effective_value_cents"] for a in imoveis)
    veiculos_cents = sum(a["effective_value_cents"] for a in veiculos)
    outros_cents = sum(a["effective_value_cents"] for a in outros)
    aquisicao_cents = sum(int(a.get("acquisition_cents") or 0) for a in assets)

    tax_cents = sum(int(a.get("estimated_annual_tax_cents") or 0) for a in assets)
    ins_cents = sum(int(a.get("estimated_annual_insurance_cents") or 0) for a in assets)
    maint_cents = sum(int(a.get("estimated_annual_maintenance_cents") or 0) for a in assets)
    rent_monthly_cents = sum(int(a.get("estimated_monthly_rent_cents") or 0) for a in imoveis)

    return {
        "count": len(assets),
        "total_cents": total_cents,
        "imoveis_cents": imoveis_cents,
        "veiculos_cents": veiculos_cents,
        "outros_cents": outros_cents,
        "acquisition_cents": aquisicao_cents,
        "gain_cents": (total_cents - aquisicao_cents) if aquisicao_cents > 0 else None,
        "estimated_annual_tax_cents": tax_cents,
        "estimated_annual_insurance_cents": ins_cents,
        "estimated_annual_maintenance_cents": maint_cents,
        "estimated_annual_carrying_cents": tax_cents + ins_cents + maint_cents,
        "estimated_monthly_rent_cents": rent_monthly_cents,
        "assets": assets,
        "imoveis": imoveis,
        "veiculos": veiculos,
        "outros": outros,
    }
