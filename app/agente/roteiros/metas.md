---
titulo: Metas de alocação e plano de aporte
descricao: Consulta ou ajusta as metas de alocação (reserva de emergência, renda fixa × variável, nacional × internacional) e diz quanto aportar em cada classe para equilibrar a carteira sem vender.
---

# Metas de alocação e plano de aporte

1. Chame `metas_mostrar` (com `aporte` se o usuário citar um valor). Leia:
   - `reserva`: meta e quanto falta. A reserva é o caixa em conta menos a fatura em aberto.
   - `classes`: atual × meta em % e em reais, e o desvio em p.p.
   - `plano_de_aporte.destino`: quanto vai para cada classe. Ele nunca vende: completa a reserva primeiro, depois
     reforça as classes abaixo da meta.
   - `aporte_para_equilibrar_sem_vender` e `aporte_mensal_sugerido`, que é a média de sobra dos últimos 3 meses.
   - `exposicao_por_ativo`: qual ativo conta como nacional ou internacional.
2. Se `configurado` for `false`, pergunte ao usuário as metas antes de sugerir qualquer coisa. Nunca invente metas.
   Veja também o horizonte (`perfil_investidor`): com menos de 5 anos, a prioridade é reserva e renda fixa, e
   ações e FIIs não cabem no prazo; diga isso.
3. **Para definir metas** (só com pedido explícito): `metas_definir` com `reserva`, `renda_fixa`, `renda_variavel`,
   `internacional` e `previdencia`. Os percentuais vão de 0 a 100, e renda fixa + variável = 100.
4. **Exposição errada** (ex.: um ETF de ações americanas marcado como nacional): `metas_regiao` com o ticker e
   `internacional`.
5. **Para sugerir ativos dentro de cada classe**, use a última recomendação (`recomendacoes_mostrar`) ou as teses
   (`analise_listar`). Se não houver, diga isso e ofereça seguir os roteiros `analise-trimestral` e
   `recomendacoes`.

A resposta deve trazer:

- uma tabela classe → hoje → meta → aporte sugerido;
- a observação de que o plano não vende nada; se vender resolveria mais rápido, diga quanto e deixe a decisão ao
  usuário;
- o lembrete de que o usuário vê tudo em **Metas**, inclusive com outro valor de aporte.
