# Modelo do relatório trimestral (campo `body_md`)

Use sempre estas seções, nesta ordem, para que o histórico de cada ativo seja comparável trimestre a trimestre.
Seja factual: cada número tem de vir do `financas fundamentos contexto` ou de uma fonte citada em `sources`.
Omita a seção que não se aplica ao tipo de ativo (ex.: dívida para bancos) e diga por quê em uma linha.

```markdown
## Resumo
Três a cinco linhas: o que aconteceu no trimestre, se a tese continua de pé e a leitura de preço.

## Resultado do trimestre
| Indicador | 2T26 | 2T25 | Variação |
|---|---|---|---|
| Receita | R$ 10,1 bi | R$ 10,2 bi | −0,6% |
| EBIT | ... | ... | ... |
| Lucro líquido | ... | ... | ... |
| Margem líquida | ... | ... | ... |
Efeitos não recorrentes e o que explica a variação.

## Qualidade e rentabilidade
ROE (e ROIC, se calcular), margens, conversão de caixa (caixa operacional ÷ lucro) e a tendência dos últimos
4 a 8 trimestres.

## Endividamento
Dívida líquida/EBITDA, perfil e custo da dívida. Para bancos: índice de Basileia e inadimplência, se o release trouxer.

## Proventos
Payout, dividend yield, previsibilidade e se o pagamento cabe no lucro e no caixa.

## Valuation
P/L, P/VP e EV/EBITDA contra o próprio histórico e contra 2 ou 3 pares. Preço justo e método (múltiplo, fluxo
de caixa descontado ou Gordon), com as premissas.

## Riscos e gatilhos
- Riscos que podem quebrar a tese.
- Eventos a acompanhar no próximo trimestre.

## Mudanças desde o último relatório
O que mudou em relação ao relatório anterior (`financas analise mostrar ID`): tese, preço justo, veredito.

## Checklist
- [x] Lucro 12M crescendo ou estável
- [ ] ROE acima de 15%
- [x] Dívida líquida/EBITDA abaixo de 2,5x (não financeiras)
- [x] Payout sustentável (abaixo de 100%)
- [ ] Preço abaixo do preço justo

## Conclusão
Veredito (barata, justa ou cara), nota de 0 a 10 e o que fazer com a posição, **respeitando as metas de alocação
do usuário** (`financas metas mostrar`).
```

Para **renda fixa** (subject_type `renda_fixa`), use: Resumo; Taxa contratada × taxa de mercado atual; Risco de
crédito do emissor e FGC; Liquidez e vencimento; Imposto e marcação a mercado; Conclusão (manter, resgatar
no vencimento, trocar por qual alternativa).

Para **ETFs e FIIs**, troque as seções de demonstrações por: índice ou portfólio, taxa de administração, liquidez,
histórico de proventos, vacância e alavancagem (FIIs) e desconto ou prêmio sobre o valor patrimonial.
