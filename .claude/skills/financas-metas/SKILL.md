---
name: financas-metas
description: Consultar ou ajustar as metas de alocação do usuário (reserva de emergência, renda fixa × variável, nacional × internacional) e dizer quanto aportar em cada classe para equilibrar a carteira sem vender. Use quando o usuário perguntar onde aportar, se está balanceado ou quiser definir metas.
---

# Metas de alocação e plano de aporte

1. Rode `.\financas.bat metas mostrar` (ou `--aporte 5000` com o valor que o usuário citar). Leia:
   - `reserva`: meta e quanto falta. A reserva é o caixa em conta menos a fatura em aberto.
   - `classes`: atual × meta em % e em reais, e o desvio em p.p.
   - `plano_de_aporte.destino`: quanto vai para cada classe. Ele nunca vende: completa a reserva primeiro,
     depois reforça as classes abaixo da meta.
   - `aporte_para_equilibrar_sem_vender` e `aporte_mensal_sugerido`, que é a média de sobra dos últimos 3 meses.
   - `exposicao_por_ativo`: qual ativo conta como nacional ou internacional.
2. Se `configurado` for `false`, pergunte ao usuário as metas antes de sugerir qualquer coisa. Nunca invente metas.
3. **Para definir metas** (só com pedido explícito): `.\financas.bat metas definir --reserva 30000 --renda-fixa 40 --renda-variavel 60 --internacional 30 [--previdencia sim|nao]`.
   Os percentuais vão de 0 a 100, e renda fixa + variável = 100.
4. **Exposição errada** (ex.: um ETF de ações americanas marcado como nacional): `.\financas.bat metas regiao TICKER internacional`.
5. **Para sugerir ativos dentro de cada classe**, use a última recomendação (`.\financas.bat recomendacoes mostrar`)
   ou os relatórios (`analise listar`). Se não houver, diga isso e ofereça rodar a skill `financas-analise-trimestral`.

A resposta deve trazer:

- uma tabela classe → hoje → meta → aporte sugerido;
- a observação de que o plano não vende nada; se vender resolveria mais rápido, diga quanto e deixe a decisão ao usuário;
- o lembrete de que o usuário vê tudo em **Metas** (`/metas`), inclusive com outro valor de aporte.
