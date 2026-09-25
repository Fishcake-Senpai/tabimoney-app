---
name: financas-orcamento
description: Analisar os gastos do usuário junto com as metas de gastos (orçamento mensal por grupo) e gravar recomendações orçamentárias no app, como cortes, ajustes de metas, metas novas e ações de economia, que o usuário aplica com um clique. Use quando o usuário pedir para analisar gastos e orçamento, sugerir metas de gastos ou dizer onde economizar.
---

# Análise orçamentária

O resultado é um conjunto de recomendações do mês, gravado com `.\financas.bat orcamento importar-recomendacoes`.
Ele aparece em **Recomendações** e no bloco **Orçamento do mês** de Conta e cartão, com botão "Aplicar" para
criar, ajustar ou remover metas. **Não mude metas diretamente:** quem decide é o usuário, pelo botão.

## Passos

1. **Contexto:** rode `.\financas.bat orcamento contexto`. Ele traz:
   - `orcamento.metas`: por meta, limite, gasto no mês, projeção, situação (`ok`, `risco`, `estourou`),
     taxa de acerto nos últimos 6 meses e média de 3 meses;
   - `categorias_sem_meta`: gasto que nenhuma meta acompanha;
   - `receitas_e_despesas_por_mes`: quanto sobra por mês;
   - `gasto_por_categoria` e `o_que_mudou`: tendência e os lançamentos que puxaram cada mudança;
   - `metas_sugeridas_pela_media` e `recomendacao_anterior` (o que foi sugerido e se o usuário aplicou).
2. **Categorias confiáveis:** se "Outros" ou "Pix e transferências" forem grandes, olhe
   `.\financas.bat gastos listar --categoria Outros --mes AAAA-MM`. Categoria errada distorce o orçamento; sugira
   a correção no texto ou use a skill `financas-gastos` se o usuário pedir.
3. **Diagnóstico:** analise cada meta.
   - **Estoura sempre:** a taxa de acerto é baixa e a média fica acima do limite. A meta é irreal ou o hábito
     mudou; proponha `ajustar` com um limite alcançável, ou `economizar` com uma ação concreta.
   - **Sobra sempre:** a média fica bem abaixo do limite. Proponha `ajustar` para baixo; o dinheiro liberado vai
     para as metas de investimento (`.\financas.bat metas mostrar`).
   - **Gasto grande sem meta:** proponha `criar`.
   - **Duas metas pequenas e parecidas:** proponha juntar (`remover` uma e `ajustar` a outra com as categorias somadas).
4. **Economia:** calcule `expected_monthly_savings` com base nos números do contexto, de forma conservadora.
   A soma dos itens entra em `expected_monthly_savings` do conjunto.
5. **Priorize:** `priority` 1 para o que mais pesa em reais ou estourou, 3 para ajuste fino. De 3 a 7 itens.
6. **Grave:** monte o JSON (exemplo em `docs/agentes/exemplos/orcamento.json`) com `period` = mês analisado
   (`AAAA-MM`) e rode `.\financas.bat orcamento importar-recomendacoes caminho.json`. Reimportar o mesmo mês
   substitui a versão anterior.
7. **Responda ao usuário** com:
   - como está o mês (gasto × orçamento, quanto cabe por dia);
   - as 3 sugestões principais, com a economia estimada;
   - onde aplicar: **Conta e cartão → Orçamento do mês** ou **Recomendações**.

## Formato dos itens

| Campo | Uso |
|---|---|
| `action` | `criar`, `ajustar`, `manter`, `remover` ou `economizar` (orientação sem mudar meta) |
| `budget` | Nome da meta; o mesmo nome da meta existente para `ajustar`, `manter` e `remover` |
| `categories` | Obrigatório em `criar`; em `ajustar`, só se mudar as categorias. Use nomes de `financas gastos categorias` |
| `current_limit` / `suggested_limit` | Em reais; `suggested_limit` é obrigatório em `criar` e `ajustar` |
| `expected_monthly_savings` | Em reais por mês, se houver |
| `priority` | 1 (alta) a 3 (baixa) |
| `rationale` | Uma a três frases com números do contexto |

Regras que o app valida:

- cada categoria pertence a uma meta só;
- categorias internas (`Investimentos`, `Pagamento de fatura`, `Transferência própria`) não entram em metas;
- um item inválido recusa o lote inteiro.
