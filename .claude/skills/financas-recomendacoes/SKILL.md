---
name: financas-recomendacoes
description: Montar as recomendações trimestrais da carteira de ações e FIIs do usuário (mudanças na carteira atual e carteiras-modelo com o perfil dele), respeitando as metas de alocação, e gravar na área Recomendações do app. Use depois da análise trimestral ou quando o usuário pedir sugestões de mudança na carteira.
---

# Recomendações trimestrais

Pré-requisito: relatórios do trimestre gravados (skill `financas-analise-trimestral`). Se `ultima_analise` estiver
vazia ou for de trimestre anterior para a maioria dos ativos, faça a análise primeiro ou avise o usuário.

## Passos

1. Rode `.\financas.bat carteira contexto --aporte <valor>` (use o aporte citado pelo usuário ou
   `aporte_mensal_sugerido`). Isso traz:
   - `metas_e_balanco`: metas, desvios e plano de aporte por classe. **As recomendações têm de caber aqui.**
   - `renda_variavel.posicoes`: peso na renda variável, fundamentos, avisos e a última análise de cada ativo.
   - `recomendacao_anterior`: compare com ela (`.\financas.bat recomendacoes mostrar`).
2. **Entenda o perfil do usuário** pela carteira atual (setores, peso em dividendos × crescimento, exposição
   internacional, concentração). As carteiras-modelo precisam parecer algo que ele montaria, só que mais bem
   fundamentado neste trimestre.
3. **Mudanças na carteira atual (`changes`)**:
   - Uma linha por ativo que muda: `reduzir` ou `vender` quando o fundamento piorou ou o preço passou do justo;
     `aumentar` ou `comprar` quando está barato e cabe na meta; `manter` só para posições relevantes que o usuário
     pode questionar.
   - `target_weight` é o peso na renda variável depois da mudança, e `conviction` vai de 1 a 5.
   - Em `rationale`, uma a três frases apoiadas em números do relatório.
   - Ativos novos entram com `comprar` e trazem `name`, `asset_class` e `region`.
   - Priorize movimentos feitos **com aportes** (o plano da ferramenta não vende). Sugira venda só com motivo forte.
4. **Carteiras-modelo (`portfolios`)**: de 1 a 3, cada uma com nome, `risk_profile`, `description`, `rationale_md`
   e `items` com pesos que somam 100%.
   - Parta dos ativos que o usuário já tem e troque os mais fracos.
   - Respeite a meta internacional dentro da renda variável.
5. **Tese (`body_md`)**: use as seções "Tese do trimestre", "Como isso encaixa nas metas" (cite reserva, renda fixa ×
   variável e internacional), "Prioridades para os próximos aportes", "Riscos" e "O que mudou desde a recomendação anterior".
6. **Gravação:** monte o JSON (exemplo em `docs/agentes/exemplos/recomendacoes.json`) com `period` no formato `3T26`
   e rode `.\financas.bat recomendacoes importar caminho.json`. O mesmo período substitui a versão; os trimestres
   anteriores ficam no histórico.
7. **Resposta ao usuário:** três a cinco bullets com as mudanças principais, a carteira-modelo mais próxima da dele
   e a lembrança de que tudo está em **Recomendações** (`/recomendacoes`).

## Limites

- As recomendações são sugestões fundamentadas, não ordens. Deixe claro o horizonte (trimestre) e os riscos.
- Não recomende produtos sem ticker verificável, com exceção de títulos de renda fixa descritos em `name`.
- Não mude as metas do usuário; se achar que elas deveriam mudar, sugira no texto.
