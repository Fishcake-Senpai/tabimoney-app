# Modelo de laudo de avaliação patrimonial (campo `relatorio_md`)

Use sempre estas seções para que os laudos fiquem legíveis na tela **Patrimônio** (`/patrimonio`) e comparáveis ao
longo do tempo. Todos os números devem vir de `patrimonio_simular_avaliacao` (nunca calculados de cabeça).

## Modelo para Imóvel

```markdown
## Resumo executivo
- **Valor de mercado estimado:** R$ 920.000 (faixa: R$ 874.000 – R$ 966.000) · **Confiança:** alta (8 amostras válidas, 1 outlier descartado, 3 portais).
- **Preço unitário:** R$ 5.111/m² construído · R$ 3.067/m² terreno.
- **Aluguel de mercado:** R$ 4.600/mês (Rental Yield bruto 6,0% a.a. · Cap Rate líquido 4,4% a.a.).
- **Custos anuais estimados:** IPTU R$ 3.800 · Seguro R$ 920 · Manutenção R$ 7.360 (carregamento total: R$ 12.080/ano).

## Metodologia e comparáveis (ABNT NBR 14653-2)
Breve explicação das camadas de busca usadas (mesmo condomínio/bairro), do fator de oferta aplicado (0,90 para ofertas de venda; 0,97 para locação), dos fatores de homogeneização (área, terreno, padrão e conservação) e do motivo de eventual descarte de outliers.

## Leitura dos KPIs e custo de oportunidade
- **Valorização:** nominal +27,8% desde a compra (+6,3% a.a., ganho real de +1,7% a.a. acima do IPCA).
- **Retorno vs. CDI líquido:** Cap Rate + valorização vs. CDI líquido de 15% IR. Para moradia própria, comentar o aluguel implícito economizado versus o custo de capital.
- **Liquidez e concentração:** peso do imóvel no patrimônio total e alerta se concentrado acima de 50–60%.

## Pontos de atenção e próximos passos
- Fatores que podem valorizar ou pressionar o imóvel na região (infraestrutura, oferta de lançamentos, liquidez).
- Quando reavaliar (ex.: a cada 6 a 12 meses ou após reforma relevante).
```

## Modelo para Veículo

```markdown
## Resumo executivo
- **Valor FIPE (consenso):** R$ 124.500 (faixa: R$ 123.800 – R$ 125.200) · **Confiança:** alta (2 fontes, código FIPE 002111-3).
- **Custos fixos anuais estimados:** IPVA (SP, 4%) R$ 4.980 · Seguro R$ 5.800 · Licenciamento R$ 160 · Manutenção R$ 3.735.
- **Custo Total de Posse (TCO):** R$ 2.052/mês (incluindo depreciação anual estimada).

## Depreciação e posicionamento de mercado
Comparação com o valor de aquisição (depreciação total e anualizada) e comentários sobre liquidez e demanda do modelo/versão.

## Pontos de atenção
- Desconto para pagamento à vista do IPVA em janeiro ou isenções estaduais aplicáveis.
- Sugestão de registrar IPVA e Seguro em Contas Fixas para diluir o impacto no orçamento.
```
