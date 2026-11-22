"""Testes de Gestão de Patrimônio com IA (imóveis NBR 14653-2, veículos FIPE/TCO, UI, MCP/CLI e Contas Fixas)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import cli
from app.agente import operacoes as op
from app.services import patrimonio, recurring

from .conftest import csrf

EXEMPLOS = Path(__file__).resolve().parent.parent / "docs" / "agentes" / "exemplos"


# ---------------------------------------------------------------- CRUD e regra de valorização

def test_crud_bem_e_regra_de_valorizacao():
    inicio = (date.today() - timedelta(days=730)).isoformat()  # ~2 anos
    bem = patrimonio.save_asset(
        name="Terreno Litoral",
        asset_type="imovel",
        subtype="terreno",
        acquisition_cents=50000000,  # R$ 500.000
        acquisition_date=inicio,
        valuation_method="regra",
        growth_rate_bps=600,  # +6% ao ano
        growth_period="anual",
        details={"bairro": "Riviera", "cidade": "Bertioga", "uf": "SP", "area_terreno_m2": 400},
    )
    assert bem["id"] > 0
    # 500.000 * 1.06^2 ≈ 561.800 (tolerância de arredondamento de dias bissextos)
    assert 56000000 <= bem["effective_value_cents"] <= 56300000
    assert bem["gain_cents"] > 5000000

    res = patrimonio.delete_asset(bem["id"])
    assert res["removed"] is True
    assert patrimonio.get_asset(bem["id"]) is None


# ---------------------------------------------------------------- Motor NBR 14653-2 (Casa e Apartamento)

def test_homogeneizacao_casa_nbr14653_expurga_outlier_e_calcula_kpis():
    casa = patrimonio.save_asset(
        name="Casa Condomínio Jardins",
        asset_type="imovel",
        subtype="casa_condominio",
        acquisition_cents=72000000,
        acquisition_date=(date.today() - timedelta(days=1095)).isoformat(),  # 3 anos
        details={
            "bairro": "Jardins",
            "cidade": "Campinas",
            "uf": "SP",
            "area_construida_m2": 200,
            "area_terreno_m2": 360,
            "quartos": 3,
            "vagas": 2,
            "padrao": "medio_alto",
            "conservacao": "reformado",
            "uso": "moradia",
            "condominio_mensal": 750,
        },
    )

    comparaveis = [
        {"fonte": "ZAP Imóveis", "tipo_dado": "oferta", "preco": 1100000, "area_construida_m2": 200, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "VivaReal", "tipo_dado": "oferta", "preco": 1080000, "area_construida_m2": 195, "area_terreno_m2": 350, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "Imovelweb", "tipo_dado": "oferta", "preco": 1150000, "area_construida_m2": 210, "area_terreno_m2": 380, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "QuintoAndar", "tipo_dado": "transacao", "preco": 980000, "area_construida_m2": 200, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "ZAP Imóveis", "tipo_dado": "oferta", "preco": 1050000, "area_construida_m2": 190, "area_terreno_m2": 340, "padrao": "medio_alto", "conservacao": "original_bom"},
        {"fonte": "VivaReal", "tipo_dado": "oferta", "preco": 1120000, "area_construida_m2": 205, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "OLX", "tipo_dado": "oferta", "preco": 1090000, "area_construida_m2": 200, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
        {"fonte": "Loft", "tipo_dado": "oferta", "preco": 1110000, "area_construida_m2": 200, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
        # Outlier absurdo (preço dobrado) — precisa ser descartado
        {"fonte": "ZAP Imóveis", "tipo_dado": "oferta", "preco": 2400000, "area_construida_m2": 200, "area_terreno_m2": 360, "padrao": "medio_alto", "conservacao": "reformado"},
    ]

    sim = patrimonio.simular_avaliacao(
        casa["id"],
        comparaveis_venda=comparaveis,
        aluguel_mensal_reais=5000,
        iptu_anual_reais=4200,
        seguro_anual_reais=1000,
        patrimonio_liquido_total_cents=200000000,
    )

    assert sim["grau_confianca"] == "alta"
    hom = sim["homogeneizacao_venda"]
    assert hom["amostras_validas"] == 8
    assert hom["amostras_descartadas"] == 1
    # Ofertas de ~1,10M * 0,90 ≈ 990k; transação de 980k * 1,00 = 980k -> central ~980k–1,00M
    assert 950000 <= sim["valor_central"] <= 1030000
    assert sim["valor_piso"] < sim["valor_central"] < sim["valor_teto"]

    kpis = sim["kpis"]
    assert kpis["preco_m2_construido"] > 4500
    assert kpis["preco_m2_terreno"] > 2500
    assert 0.055 <= kpis["rental_yield_bruto"] <= 0.065
    assert kpis["cap_rate_liquido"] < kpis["rental_yield_bruto"]
    assert kpis["valorizacao_nominal"] > 0.30
    assert kpis["concentracao_patrimonio"] == pytest.approx((sim["valor_central"] * 100) / 200000000, rel=1e-2)

    # Todos os fatores acumulados respeitam [0.80, 1.25]
    for c in hom["comparaveis"]:
        assert 0.80 <= c["f_total"] <= 1.25


def test_homogeneizacao_confianca_insuficiente_com_poucas_amostras():
    apto = patrimonio.save_asset(
        name="Apto Studio",
        asset_type="imovel",
        subtype="apartamento",
        details={"area_construida_m2": 40, "padrao": "medio", "conservacao": "novo"},
    )
    sim = patrimonio.simular_avaliacao(
        apto["id"],
        comparaveis_venda=[
            {"fonte": "ZAP", "preco": 400000, "area_construida_m2": 40},
            {"fonte": "ZAP", "preco": 420000, "area_construida_m2": 42},
        ],
    )
    assert sim["grau_confianca"] == "insuficiente"


# ---------------------------------------------------------------- Motor de Veículos (FIPE + IPVA + TCO)

def test_simulacao_veiculo_fipe_ipva_uf_e_tco():
    carro = patrimonio.save_asset(
        name="Honda Civic Touring 2021",
        asset_type="veiculo",
        subtype="carro",
        acquisition_cents=15000000,
        acquisition_date=(date.today() - timedelta(days=730)).isoformat(),
        details={"marca": "Honda", "modelo": "Civic Touring 1.5 Turbo", "ano": 2021, "codigo_fipe": "014096-1", "uf": "SC"},
    )
    sim = patrimonio.simular_avaliacao(
        carro["id"],
        fontes_fipe=[
            {"fonte": "Tabela FIPE oficial", "preco": 130000, "mes_referencia": "2026-11"},
            {"fonte": "Mobiauto FIPE", "preco": 132000, "mes_referencia": "2026-11"},
        ],
        seguro_anual_reais=5200,
    )
    assert sim["valor_central"] == 131000.0
    assert sim["grau_confianca"] == "alta"
    # SC tem alíquota de 2% para carro -> 2% de 131.000 = 2.620
    assert sim["kpis"]["aliquota_ipva"] == 0.02
    assert sim["kpis"]["ipva_anual_estimado"] == 2620.0
    assert sim["kpis"]["tco_mensal"] > 1000.0


# ---------------------------------------------------------------- Atalho para Conta Fixa

def test_criar_conta_fixa_de_iptu_e_seguro():
    imovel = patrimonio.save_asset(
        name="Casa Centro",
        asset_type="imovel",
        subtype="casa_rua",
        current_value_cents=60000000,
        estimated_annual_tax_cents=240000,
        estimated_annual_insurance_cents=60000,
    )
    rec_iptu = patrimonio.criar_conta_fixa_do_bem(imovel["id"], kind="imposto", frequency="yearly")
    assert rec_iptu["description"] == "IPTU — Casa Centro"
    assert rec_iptu["amount_cents"] == -240000
    assert rec_iptu["frequency"] == "yearly"

    rec_seg = patrimonio.criar_conta_fixa_do_bem(imovel["id"], kind="seguro", frequency="monthly")
    assert rec_seg["description"] == "Seguro — Casa Centro"
    assert rec_seg["amount_cents"] == -5000  # 600 / 12
    assert len(recurring.list_recurring()) == 2


# ---------------------------------------------------------------- Fluxo UI (FastAPI)

def test_rotas_web_patrimonio_e_integracao_inicio(client):
    token = csrf(client)
    r = client.post(
        "/patrimonio/salvar",
        data={
            "csrf_token": token,
            "name": "Apartamento Jardins",
            "asset_type": "imovel",
            "subtype": "apartamento",
            "current_value": "900000,00",
            "acquisition_value": "750000,00",
            "bairro": "Jardins",
            "cidade": "São Paulo",
            "uf": "SP",
            "area_construida_m2": "90",
            "estimated_annual_tax": "3600,00",
            "estimated_annual_insurance": "900,00",
            "estimated_monthly_rent": "4800,00",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Apartamento Jardins" in r.text

    # Início exibe o card de Bens físicos
    inicio = client.get("/")
    assert inicio.status_code == 200
    assert "Bens físicos" in inicio.text

    # Atalho de conta fixa funciona pela rota web
    bem_id = patrimonio.list_assets()[0]["id"]
    r_cf = client.post(
        "/patrimonio/conta-fixa",
        data={"csrf_token": token, "asset_id": str(bem_id), "kind": "imposto", "frequency": "yearly"},
        follow_redirects=True,
    )
    assert r_cf.status_code == 200
    assert "Conta fixa" in r_cf.text


# ---------------------------------------------------------------- Operações do Agente e CLI + Exemplos JSON

def test_fluxo_agente_cli_e_exemplos_validos(capsys):
    criado = op.patrimonio_salvar(
        nome="Casa Exemplo",
        tipo="imovel",
        subtipo="casa_condominio",
        valor_aquisicao=700000,
        detalhes={"area_construida_m2": 180, "area_terreno_m2": 300, "padrao": "medio_alto", "conservacao": "reformado"},
    )
    bem_id = criado["id"]

    # Valida gravação usando o exemplo JSON oficial de imóvel
    exemplo_imovel = EXEMPLOS / "avaliacao-imovel.json"
    capsys.readouterr()
    cli.main(["patrimonio", "avaliar", str(bem_id), "--arquivo", str(exemplo_imovel)])
    out = json.loads(capsys.readouterr().out)
    assert out["bem"]["valor_atual"] == 920000.0
    assert out["bem"]["ultima_avaliacao"]["confianca"] == "alta"

    # Valida contexto pela CLI
    capsys.readouterr()
    cli.main(["patrimonio", "contexto"])
    ctx = json.loads(capsys.readouterr().out)
    assert ctx["resumo"]["patrimonio_bens"] == 920000.0
    assert len(ctx["bens"]) == 1

    # Valida gravação usando o exemplo JSON oficial de veículo
    carro = op.patrimonio_salvar(
        nome="Corolla Exemplo",
        tipo="veiculo",
        subtipo="carro",
        detalhes={"marca": "Toyota", "modelo": "Corolla XEi", "ano": 2022, "uf": "SP"},
    )
    exemplo_veiculo = EXEMPLOS / "avaliacao-veiculo.json"
    capsys.readouterr()
    cli.main(["patrimonio", "avaliar", str(carro["id"]), "--arquivo", str(exemplo_veiculo)])
    out_v = json.loads(capsys.readouterr().out)
    assert out_v["bem"]["valor_atual"] == 124500.0


def test_connection_scope_reutiliza_conexao_e_fecha_ao_sair(monkeypatch):
    from app import db

    aberturas = []
    orig_connect = db.connect

    def contar_connect(path=None):
        conn = orig_connect(path)
        aberturas.append(conn)
        return conn

    monkeypatch.setattr(db, "connect", contar_connect)
    with db.connection_scope():
        db.rows("SELECT 1")
        db.rows("SELECT 2")
        db.rows("SELECT 3")
    assert len(aberturas) == 1
    # Ao sair do escopo, a conexão foi fechada
    with pytest.raises(Exception):
        aberturas[0].execute("SELECT 1")

