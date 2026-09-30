---
titulo: Análise fundamentalista trimestral
descricao: Faz a análise fundamentalista trimestral de cada ativo (ações, FIIs, ETFs, renda fixa, previdência) e grava relatórios completos, métricas e avisos no app, com histórico por trimestre.
---

# Análise fundamentalista trimestral

Saída esperada: **um relatório por ativo e por trimestre**, gravado no app, no formato do modelo
`tabimoney://docs/modelo-relatorio-trimestral`. O usuário lê o relatório completo na página do ativo, e os
trimestres anteriores ficam no histórico.

## Passos

1. **Dados frescos:** chame `fundamentos_atualizar`. A CVM publica semanalmente e o cache evita baixar de novo; na
   primeira vez leva alguns minutos. Se devolver `tarefa_id`, acompanhe com `tarefa_status`.
2. **Fotografia:** chame `carteira_contexto`. Ela traz as posições, as metas, a `ultima_analise` de cada ativo, a
   renda fixa e a previdência.
3. **Para cada ação ou unit com `fundamentos`:**
   1. Chame `fundamentos_contexto` com o ticker para obter indicadores, a série `quarters` (fluxos do trimestre
      isolado, `*_ttm` em 12 meses), os `filings` (links do ITR/DFP na CVM), os avisos e os relatórios anteriores.
   2. Se houver relatório anterior, chame `analise_mostrar` e compare.
   3. Leia o documento mais recente (link em `filings`) e o release de resultados da empresa, se estiver disponível.
   4. Escreva o `body_md` com as seções do modelo e números conferidos. Qualquer número que não venha do contexto
      precisa estar em `sources`.
   5. Decida `verdict` (`barata`, `justa` ou `cara`) comparando com o próprio histórico **e** com pares, e informe
      `score` (0–10) e `fair_price` com o método.
   6. Acrescente `metrics` que o app não calcula (ex.: `roic`, `pl_medio_5a`, `crescimento_lpa_3a`) e `alerts` só
      para o que muda uma decisão. As regras automáticas já cobrem lucro caindo, ROE baixo, dívida e payout.
4. **ETFs e FIIs** (sem dados da CVM): use `ticker` e o modelo adaptado (índice, taxa, proventos, vacância e
   alavancagem nos FIIs).
5. **Renda fixa e previdência:** um relatório por título relevante, sem `ticker`, com `subject` = nome do produto e
   `subject_type` = `renda_fixa` (ou `previdencia`). Os dados estão em `carteira_contexto` → `renda_fixa` /
   `previdencia`.
6. **Gravação:** chame `analise_importar` com a lista de relatórios (exemplo em
   `tabimoney://exemplos/analise-trimestral`). Se der erro, corrija o item indicado e grave de novo; nada é gravado
   pela metade.
7. **Resumo ao usuário:** uma tabela ativo → veredito → nota → o que mudou desde o trimestre anterior, os avisos
   novos e a sugestão de seguir com o roteiro `recomendacoes`.

## Padrões

- O período é o trimestre do último balanço: `2T26` = abril a junho de 2026. Regravar o mesmo período substitui a
  versão.
- Não repita nas conclusões o que as regras automáticas já dizem; interprete.
- Seja explícito sobre incerteza e dados faltando (ex.: "a CVM ainda não tem o 3T26").
- Não recomende compra ou venda aqui; isso é papel do roteiro `recomendacoes`, que considera as metas.
