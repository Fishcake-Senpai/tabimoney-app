---
titulo: Recomendações de aporte (longo prazo)
descricao: Monta as recomendações da carteira de ações, FIIs e exterior para o horizonte do usuário (pesos-alvo pela nota de qualidade, aportes nos ativos mais abaixo do peso, venda só com tese quebrada) e as carteiras-modelo, respeitando as metas de alocação, e grava em Sugestões.
---

# Recomendações de aporte (longo prazo)

O método é o de quem fica 10 ou 20 anos (inspirado em Raul Sena, o Investidor Sardinha, e no Diagrama do Cerrado):
**a carteira converge para o alvo com aportes**, os pesos vêm da qualidade de cada ativo e a venda é exceção.

Pré-requisitos: perfil do investidor e teses gravados (roteiros `analise-ativo` e `analise-trimestral`). Se a
maioria dos ativos não tem tese, faça as análises primeiro ou avise o usuário.

## Passos

1. **Perfil:** `perfil_investidor`. Sem perfil ou vencido, pergunte e grave com `perfil_definir`. Com horizonte
   `menos-de-5`, não recomende renda variável: indique o roteiro `metas`.
2. `carteira_contexto` com `aporte` (o valor citado pelo usuário ou `aporte_mensal_sugerido`). Isso traz:
   - `metas_e_balanco`: metas, desvios e plano de aporte por classe. **As recomendações têm de caber aqui.**
   - `renda_variavel.posicoes`: peso, fundamentos, avisos e a última análise de cada ativo.
   - `recomendacao_anterior`: compare com ela (`recomendacoes_mostrar`).
3. **Notas:** para cada ativo, a nota de qualidade (sim − não) e o `score` da tese mais recente (`analise_listar`,
   `analise_mostrar`; métrica `nota_qualidade`). Ativo sem tese não recebe peso-alvo; diga isso.
4. **Pesos-alvo pelo método de notas**, dentro de cada classe da renda variável (ações Brasil, FIIs, exterior):
   - entram só ativos com **nota > 0** e filtro de entrada aprovado (métrica `filtro_entrada`);
   - peso-alvo na classe = nota do ativo ÷ soma das notas da classe;
   - `target_weight` (peso na renda variável) = peso-alvo na classe × peso da classe na renda variável hoje (ou na
     meta internacional, para o exterior).
5. **Para onde vai o próximo aporte:**
   - entre classes, o plano de aporte de `metas_e_balanco` (já vem pronto e nunca vende);
   - dentro da classe, para os ativos **mais abaixo do peso-alvo**, na proporção do que falta;
   - `verdict` `cara`: o ativo sai da fila deste aporte (volta no próximo); `barata`: sobe na fila.
6. **Mudanças na carteira (`changes`):**
   - `aumentar` ou `comprar`: os ativos que recebem o aporte, com o valor sugerido no `rationale`;
   - `manter`: posição relevante sem aporte agora (cara, ou já no peso-alvo); diga quando volta a receber;
   - `reduzir` ou `vender`: **só** com um destes motivos, escrito no `rationale`:
     1. a tese quebrou (gatilho disparou, nota ≤ 0, prejuízo sem causa pontual, fraude, estatização, perda da
        vantagem competitiva);
     2. a análise original estava errada (fato que já existia e não foi visto);
     3. troca de um ativo complementar por um núcleo da mesma classe, quando só aportes levariam anos para corrigir.

     Preço alto sozinho **nunca** é motivo de venda. Toda venda lembra que o ganho pode gerar imposto e pede para o
     usuário conferir a regra vigente.
   - `conviction` pelo `score`: ≥ 9 → 5; ≥ 8 → 4; ≥ 6,5 → 3; ≥ 5 → 2; abaixo → 1.
   - Ativo novo só entra com tese gravada (`analise-ativo`) e traz `name`, `asset_class` e `region`.
7. **Carteiras-modelo (`portfolios`)**: de 1 a 3, cada uma com nome, `risk_profile`, `description`, `rationale_md`
   e `items` com pesos que somam 100%.
   - Parta do núcleo do usuário (score ≥ 8) e complete com ativos núcleo que ele ainda não tem.
   - Respeite a meta internacional dentro da renda variável e o objetivo do perfil (renda, crescimento ou os dois).
8. **Tese (`body_md`)**, com estas seções: "Horizonte e objetivo" (do perfil), "Como isso encaixa nas metas" (reserva,
   renda fixa × variável, internacional), "Pesos-alvo pelo método de notas" (tabela ativo → nota → peso-alvo → peso
   hoje → falta), "Para onde vai o próximo aporte", "Riscos" e "O que mudou desde a recomendação anterior".
9. **Gravação:** `recomendacoes_importar` com o conjunto (exemplo em `tabimoney://exemplos/recomendacoes`), `period`
   no formato `3T26`. O mesmo período substitui a versão; os anteriores ficam no histórico.
10. **Resposta ao usuário:** três a cinco bullets (para onde vai o aporte, o que fica parado e por quê, venda só se
    houver tese quebrada), a carteira-modelo mais próxima da dele e a lembrança de que tudo está em **Sugestões**.

## Limites

- São sugestões fundamentadas, não ordens. Deixe claro o horizonte do usuário e os riscos.
- Não recomende produtos sem ticker verificável, com exceção de títulos de renda fixa descritos em `name`.
- Não mude as metas nem o perfil do usuário por conta própria; se achar que deveriam mudar, sugira no texto.
