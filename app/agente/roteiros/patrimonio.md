---
titulo: Gestão e avaliação de patrimônio (imóveis e veículos)
descricao: Pesquisa valor de mercado de imóveis (método comparativo NBR 14653-2 com homogeneização e KPIs) e veículos (FIPE multi-fonte, IPVA, seguro e TCO), simula os cálculos no app e grava o laudo e as estimativas anuais.
---

# Gestão e avaliação de patrimônio (imóveis e veículos)

Este roteiro avalia bens físicos cadastrados no Tabimoney (imóveis e veículos) com rigor técnico, privacidade e
cálculos feitos pelo próprio app (`patrimonio_simular_avaliacao`). **Nunca calcule homogeneização, mediana,
outliers ou KPIs de cabeça**: passe as amostras coletadas para `patrimonio_simular_avaliacao` e use os números
devolvidos no laudo.

## Regras de privacidade (obrigatórias)

- **Imóveis:** nunca envie endereço completo (rua com número), nome do proprietário, matrícula ou CPF em buscas
  externas. Pesquise apenas por `tipo + condomínio ou bairro + cidade/UF + faixa de área + quartos`.
- **Veículos:** nunca envie placa, RENAVAM, chassi ou CPF. Pesquise apenas por `marca + modelo + versão + ano + UF`.

## Passo 1 — Fotografia atual

1. Chame `patrimonio_contexto` (com `titular`, se a tarefa for de uma pessoa).
2. Se o bem que o usuário citou ainda não estiver cadastrado, pergunte os dados mínimos necessários e cadastre com
   `patrimonio_salvar`:
   - **Imóvel:** nome, subtipo (`casa_rua`, `casa_condominio`, `apartamento`, `terreno`, `comercial`), bairro/condomínio,
     cidade, UF, área construída (m²), área do terreno (m², obrigatório para casas/terrenos), quartos, vagas, padrão
     (`economico`, `medio`, `medio_alto`, `alto`), conservação (`precisa_reforma`, `original_bom`, `reformado`, `novo`),
     uso (`moradia`, `alugado`, `vazio`, `veraneio`), condomínio mensal e IPTU atual (se o usuário tiver o carnê).
   - **Veículo:** nome, subtipo (`carro`, `moto`, `utilitario`), marca, modelo/versão exata, ano-modelo, código FIPE
     (se souber) e UF de emplacamento.

## Passo 2A — Pesquisa de Imóvel (ABNT NBR 14653-2 adaptada)

Siga o **Método Comparativo Direto de Dados de Mercado** em camadas:

1. **Coleta de comparáveis de VENDA** (meta: **8 a 12** anúncios; mínimo **5** para confiança média; de pelo menos
   **2 portais distintos** entre ZAP Imóveis, VivaReal, QuintoAndar, Imovelweb, OLX, Loft, Chaves na Mão ou imobiliárias locais):
   - **Camada 1 (ouro):** mesmo condomínio (para apartamentos e casas em condomínio) ou mesma microrregião/rua de padrão
     equivalente, mesmo subtipo e área dentro de **±20%**.
   - **Camada 2 (prata):** mesmo bairro, mesmo subtipo (**nunca misture `casa_condominio` com `casa_rua`, nem casa com
     apartamento**), área dentro de **±30%**, quartos ±1.
   - **Camada 3 (fallback para pouca oferta):** bairros vizinhos equivalentes + índice FipeZAP / QuintoAndar do bairro ou
     cidade como referência macro (registre isso nas observações).
   - Para cada amostra, extraia: `fonte`, `url`, `tipo_dado` (`"oferta"` para anúncio ou `"transacao"` se for preço
     fechado comprovado), `preco` (em reais), `area_construida_m2` (e `area_terreno_m2` para casas/terrenos), `quartos`,
     `vagas`, `padrao`, `conservacao`, `fator_localizacao` (opcional entre `0.90` e `1.10`, com justificativa na
     `observacao` para piscina, reforma premium, rua barulhenta etc.).
2. **Coleta de ALUGUEL de mercado:**
   - Ideal: colete **3 a 6 comparáveis de locação** no mesmo condomínio/bairro e passe em `comparaveis_aluguel`.
   - Fallback: se não houver oferta de locação suficiente, pesquise o **Rental Yield médio** da cidade/bairro (FipeZAP ou
     QuintoAndar) e informe `aluguel_mensal` estimado.
3. **Pesquisa de IPTU, Seguro e Manutenção:**
   - Se o usuário já cadastrou o IPTU real do carnê, mantenha-o (ou atualize pelo reajuste municipal conhecido).
   - Sem carnê, pesquise a alíquota residencial de IPTU do município e estime sobre ~70% do valor de mercado (explique no
     laudo que é estimativa sem PGV oficial).
   - Seguro residencial típico (~0,10% a.a.) e manutenção (0,5% a.a. apto / 0,8% a.a. casa) são preenchidos
     automaticamente pelo simulador se você não informar valores reais.
4. **Simulação obrigatória:** chame `patrimonio_simular_avaliacao` passando `bem_id`, `comparaveis_venda`,
   `comparaveis_aluguel` (ou `aluguel_mensal`), `iptu_anual` e `seguro_anual`.
   - O Tabimoney aplica automaticamente o **Fator de Oferta** (`0,90` venda IBAPE / `0,97` aluguel QuintoAndar),
     `F_area`, `F_terreno` (casas), `F_padrao`, `F_conservacao`, limita o fator acumulado a `[0,80, 1,25]`, expurga
     **outliers** (IQR / ±30%), calcula **piso–mediana–teto**, **grau de confiança** e todos os **KPIs** (preço/m²,
     Rental Yield bruto, Cap Rate/NOI, custo de carregamento, valorização real vs. IPCA, spread vs. CDI líquido e
     concentração no patrimônio).
   - Se `grau_confianca` vier `baixa` ou `insuficiente` por excesso de outliers ou poucas amostras, faça uma segunda rodada
     de busca antes de gravar — se ainda assim o mercado local for raso, registre claramente a limitação no laudo.

## Passo 2B — Pesquisa de Veículo (FIPE multi-fonte + IPVA + Seguro + TCO)

1. **Tabela FIPE em 2+ fontes:** pesquise o valor FIPE vigente para marca, modelo, versão exata, combustível e
   ano-modelo (e código FIPE, se disponível) em pelo menos **2 fontes distintas** (ex.: Tabela FIPE oficial / fipe.org.br,
   Mobiauto, iCarros, Webmotors, KBB Brasil).
2. **IPVA e Seguro:**
   - O simulador já conhece a alíquota padrão de IPVA de todas as 27 UFs. Pesquise se há regra especial para o modelo na
     UF (ex.: isenção por idade do veículo, alíquota reduzida para híbrido/elétrico ou GNV) e passe `ipva_aliquota` se
     diferir do padrão.
   - Pesquise o preço médio de seguro anual para o modelo/ano na UF/capital (ou use o valor real da apólice se o usuário
     informou).
3. **Simulação obrigatória:** chame `patrimonio_simular_avaliacao` passando `bem_id`, `fontes_fipe`, `seguro_anual` e
   (se aplicável) `ipva_aliquota` e `manutencao_anual`.

## Passo 3 — Laudo e Gravação

1. Monte o `relatorio_md` seguindo exatamente o modelo `tabimoney://docs/modelo-relatorio-patrimonio` (usando os números
   exatos devolvidos por `patrimonio_simular_avaliacao`).
2. Grave com `patrimonio_registrar_avaliacao`, enviando:
   - `valor`, `valor_piso`, `valor_teto`, `confianca`, `comparaveis` e `kpis` da simulação;
   - `imposto_anual`, `seguro_anual`, `aluguel_mensal` e `manutencao_anual` de `estimativas`;
   - `fontes` (lista com `titulo`, `url`, `data`) e `relatorio_md`.

## Passo 4 — Resumo ao usuário

Entregue uma resposta objetiva com:
1. **Valor estimado (piso · central · teto)** e **grau de confiança** (quantas amostras válidas / quantos outliers descartados).
2. **Principais KPIs:**
   - Imóvel: R$/m², Rental Yield bruto, Cap Rate líquido, IPTU/custos anuais, spread vs. CDI líquido e peso no patrimônio.
   - Veículo: FIPE consenso, IPVA estimado, seguro, depreciação anual e **TCO mensal**.
3. **Lembrete prático:** avise que o laudo completo está em **Patrimônio** (`/patrimonio`) e que lá ele pode clicar em um
   botão para transformar o IPTU/IPVA/Seguro em **Conta Fixa** anual.
