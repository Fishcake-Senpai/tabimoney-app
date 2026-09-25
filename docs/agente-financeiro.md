# Contrato com agentes de IA

Este documento é para quem conecta um agente de IA (Claude Code, Codex, um script agendado) ao aplicativo.
O agente lê dados e grava correções, análises e recomendações pela linha de comando `financas`
(`financas.bat` na raiz, `.venv\Scripts\python.exe -m app.cli` ou `Tabimoney.exe cli`). Ele nunca edita o SQLite diretamente.
Toda saída sai em JSON UTF-8, com valores em reais e percentuais e pesos como fração (`0.153` = 15,3%).

Roteiros passo a passo (skills):

| Tarefa | Skill |
|---|---|
| Visão geral e escolha do roteiro | `.claude/skills/financas/SKILL.md` |
| Ciclo completo: atualizar dados, analisar, recomendar e resumir | `.claude/skills/financas-ciclo/SKILL.md` |
| Revisar gastos e recategorizar | `.claude/skills/financas-gastos/SKILL.md` |
| Orçamento: metas de gastos e recomendações de economia | `.claude/skills/financas-orcamento/SKILL.md` |
| Metas de alocação e onde aportar | `.claude/skills/financas-metas/SKILL.md` |
| Análise fundamentalista trimestral (ações, FIIs, renda fixa) | `.claude/skills/financas-analise-trimestral/SKILL.md` |
| Recomendações trimestrais e carteiras-modelo | `.claude/skills/financas-recomendacoes/SKILL.md` |

O modelo do relatório está em `docs/agentes/modelo-relatorio-trimestral.md`. Os exemplos de JSON válidos
estão em `docs/agentes/exemplos/`.

## 1. Gastos e categorias

| Comando | Para quê |
|---|---|
| `financas gastos resumo [--meses 6]` | Gasto por categoria mês a mês, variação do último mês fechado contra a média dos 3 anteriores e os lançamentos que puxaram cada mudança |
| `financas gastos listar --mes 2026-08 [--categoria X] [--busca txt] [--conta Nubank] [--origem auto\|regra\|manual] [--so-gastos]` | Lançamentos com `id`, categoria efetiva e categoria automática |
| `financas gastos categorias` | Categorias existentes, o uso de cada uma e as excluídas; as internas (fora de receita e despesa) vêm à parte |
| `financas gastos criar-categoria "Delivery"` | Cria uma categoria; se já existe em qualquer grafia, devolve a existente com `criada: false` |
| `financas gastos excluir-categoria "Delivery" --destino Outros` | Exclui uma categoria própria. Em uso e sem `--destino`, é bloqueada (sai com código 2 e mostra o que depende dela). `--destino automatica` devolve os lançamentos à categoria automática. As padrão não podem ser excluídas |
| `financas gastos restaurar-categoria "Delivery"` | Desfaz a exclusão: o que ainda está no destino volta para a categoria |
| `financas gastos recategorizar --id 812 813 --categoria Alimentação` | Corrige lançamentos específicos (`--automatica` desfaz) |
| `financas gastos regra --contem "PAGTO SALARIO" --categoria Salário [--conta ...] [--nota "..."]` | Regra permanente, que vale para lançamentos antigos e futuros |
| `financas gastos regras` / `financas gastos remover-regra ID` | Lista ou remove regras |

A categoria efetiva segue esta ordem: **manual** > **regra** (a de texto mais longo) > **automática**. Sincronizar
de novo não desfaz as correções. Categorias internas (`Investimentos`, `Pagamento de fatura`,
`Transferência própria`) não contam como receita nem como despesa.

## 2. Metas de alocação

| Comando | Para quê |
|---|---|
| `financas metas mostrar [--aporte 5000]` | Metas, balanço atual, desvios, avisos e para onde vai o aporte (sem aporte: média de sobra mensal) |
| `financas metas definir [--reserva 30000] [--renda-fixa 40] [--renda-variavel 60] [--internacional 30] [--previdencia sim\|nao]` | Grava metas. Só faça isso com pedido explícito do usuário |
| `financas metas regiao TICKER nacional\|internacional\|automatica` | Corrige a exposição de um ativo |

As regras do cálculo:

- A **reserva de emergência** é uma meta em reais, formada pelo caixa em conta menos a fatura em aberto.
  O caixa acima da meta conta como renda fixa.
- As metas de **renda fixa** e **renda variável** valem sobre o *investível* (tudo menos a reserva) e somam 100%.
  A previdência entra na renda fixa se `previdencia_conta_como_renda_fixa`.
- A meta **internacional** é a fatia da renda variável que fica no exterior: BDRs e ETFs de índice externo
  (IVVB11, NASD11, QBTC11…), com correção por ativo.
- O **plano de aporte** nunca vende: completa a reserva e depois reforça as classes abaixo da meta, na
  proporção do que falta. `aporte_para_equilibrar_sem_vender` é o valor mínimo para zerar os excessos.

Toda recomendação de carteira precisa respeitar essas metas ou dizer explicitamente por que propõe desviar delas.

## 3. Carteira e fundamentos

| Comando | Para quê |
|---|---|
| `financas carteira contexto [--aporte X]` | **Ponto de partida do agente**: metas e balanço, posições com fundamentos, avisos e a última análise de cada ativo, renda fixa, previdência, caixa e a recomendação anterior |
| `financas carteira posicoes` | Versão curta, só com as posições |
| `financas fundamentos atualizar [TICKER ...]` | Baixa ITR/DFP da CVM (cache semanal) e recalcula os avisos por regras |
| `financas fundamentos contexto TICKER` | Tudo sobre uma empresa: perfil, indicadores, série trimestral, links da CVM, avisos e relatórios anteriores |
| `financas analise listar [--ticker X] [--tipo ativo\|renda_fixa\|previdencia\|carteira]` | Relatórios guardados (sem o corpo) |
| `financas analise mostrar ID` | Relatório completo, para comparar com o trimestre anterior |
| `financas alertas listar` / `financas alertas resolver ID` | Avisos |
| `financas backup` | Cópia da base antes de mudanças em massa |
| `financas atualizar` | Backup + Open Finance + cotações/CDI + balanços da CVM, com o resultado de cada etapa |

As fontes dos dados:

- **CVM**: demonstrações oficiais (ITR/DFP). Em `quarters`, os fluxos (receita, EBIT, lucro, caixa operacional,
  capex, dividendos pagos) são do trimestre isolado; os saldos (ativo, patrimônio, caixa, dívida, ações) são na
  data. Os campos `*_ttm` somam 12 meses.
- **brapi (plano gratuito)**: preço, valor de mercado, setor e descrição.
- Bancos e seguradoras (`is_financial`) não têm EBIT, EBITDA nem dívida líquida.
- ETFs e FIIs não têm dados da CVM; analise-os pelo índice, pelos relatórios gerenciais e pelos proventos.

## 4. Relatórios de análise (`financas analise importar arquivo.json`)

Um objeto ou uma lista (exemplo em `docs/agentes/exemplos/analise-trimestral.json`):

```json
{
  "ticker": "EGIE3",
  "period": "2T26",
  "model": "claude-opus-5-5",
  "report": {
    "kind": "trimestral",
    "title": "EGIE3 2T26: qualidade alta, preço esticado",
    "summary": "Uma ou duas frases com a conclusão.",
    "body_md": "## Resumo\n...(modelo em docs/agentes/modelo-relatorio-trimestral.md)",
    "verdict": "cara",
    "score": 6.8,
    "fair_price": 38.40,
    "sources": ["https://www.rad.cvm.gov.br/...", "Release de resultados 2T26"]
  },
  "metrics": [{"metric": "roic", "value": 0.27, "period_end": "2026-06-30", "period_type": "TTM", "unit": "fração"}],
  "alerts": [{"code": "crescimento_parado", "severity": "atencao", "message": "Receita sem crescer há 4 trimestres.",
              "period_end": "2026-06-30"}]
}
```

- **Assunto:** use `ticker` para ação, FII, ETF ou BDR da carteira. Para renda fixa ou previdência, omita
  `ticker` e informe `"subject": "Tesouro IPCA+ 2029"` e `"subject_type": "renda_fixa"` (ou `"previdencia"`).
  Para a carteira toda, use `"subject_type": "carteira"`.
- **Histórico:** um relatório por assunto, período (`2T26`), tipo (`kind`) e autor. Reimportar a mesma
  combinação substitui a versão; os períodos anteriores ficam guardados no histórico, que a tela do ativo e
  `/analises` exibem.
- **Corpo (`body_md`):** Markdown com títulos (`##`), listas, checklists (`- [x]`), tabelas, citações e links
  `https://`. HTML é exibido como texto. Siga o modelo para que todos os relatórios tenham as mesmas seções.
- **Campos de leitura:** `verdict` aceita `barata`, `justa`, `cara` ou `null`; `score` vai de 0 a 10;
  `fair_price` vem em reais por ação/unit.
- **Métricas e avisos exigem ticker.** Métricas usam `snake_case` e `period_type` igual a `Q`, `TTM` ou
  `SNAPSHOT`; avisos usam `severity` igual a `critico`, `atencao`, `info` ou `positivo`, e o mesmo `code` +
  `period_end` atualiza em vez de duplicar.
- **Validação:** um item inválido recusa o lote inteiro, sem gravar metade.

## 5. Recomendações trimestrais (`financas recomendacoes importar arquivo.json`)

Um conjunto por trimestre (exemplo em `docs/agentes/exemplos/recomendacoes.json`):

```json
{
  "period": "3T26",
  "title": "3T26: menos commodities, mais internacional",
  "summary": "Conclusão em duas frases.",
  "body_md": "## Tese do trimestre\n...\n## Como isso encaixa nas metas\n...",
  "model": "claude-opus-5-5",
  "sources": ["..."],
  "changes": [
    {"action": "reduzir", "ticker": "CSNA3", "target_weight": 0.02, "conviction": 4, "rationale": "..."},
    {"action": "comprar", "ticker": "ITUB4", "name": "Itaú Unibanco", "asset_class": "Ação", "region": "nacional",
     "target_weight": 0.05, "conviction": 4, "fair_price": 45.0, "rationale": "..."}
  ],
  "portfolios": [
    {"name": "Dividendos com qualidade", "risk_profile": "moderado", "description": "...", "rationale_md": "...",
     "items": [{"ticker": "PSSA3", "target_weight": 0.3, "rationale": "..."}, {"ticker": "ALUP11", "target_weight": 0.7}]}
  ]
}
```

- `changes` são as mudanças na carteira atual. `action` aceita `comprar`, `aumentar`, `manter`, `reduzir`,
  `vender` ou `incluir`.
- `target_weight` é o peso dentro da **renda variável** (0.05 ou 5 = 5%).
- `conviction` vai de 1 a 5, e `fair_price` vem em reais.
- `portfolios` são carteiras-modelo de renda variável com o perfil do usuário. Os pesos de cada uma somam 100%.
  A tela mostra quanto o usuário já tem de cada carteira (sobreposição) e o que falta.
- Itens sem ticker (ex.: um título de renda fixa) usam `name`.
- Reimportar o mesmo `period` e autor substitui o conjunto; trimestres anteriores ficam no histórico.

## 6. Metas de gastos e recomendações orçamentárias

| Comando | Para quê |
|---|---|
| `financas orcamento mostrar` | Mês corrente contra cada meta: gasto, projeção, situação, quanto cabe por dia e histórico de 6 meses |
| `financas orcamento contexto [--meses 6]` | **Ponto de partida da análise**: orçamento, receitas e despesas por mês, gasto por categoria, o que mudou, metas sugeridas pela média e a recomendação anterior |
| `financas orcamento definir --nome X --categorias "A,B" --limite 1200 [--aviso 80]` / `--total` | Cria ou atualiza uma meta. Só com pedido explícito do usuário |
| `financas orcamento remover --nome X` | Remove uma meta. Só com pedido explícito do usuário |
| `financas orcamento importar-recomendacoes arquivo.json` | Grava as recomendações do mês (exemplo em `docs/agentes/exemplos/orcamento.json`) |

As regras de cálculo:

- **Gasto:** o mesmo de Conta e cartão (saídas menos estornos, sem movimentos internos).
- **Categorias:** cada uma pertence a no máximo uma meta. A meta com `"*"` (`--total`) acompanha todos os gastos do mês.
- **Situação da meta:**
  - `estourou`: o gasto passou do limite;
  - `risco`: a projeção passa do limite ou o gasto chegou ao % de aviso;
  - `ok`: nenhum dos dois.
- **Projeção:** o gasto até hoje levado ao mês inteiro; antes do 5º dia, vale o maior entre o gasto e a média de 3 meses.

Formato de `importar-recomendacoes`:

```json
{
  "period": "2026-09",
  "title": "Setembro: Pix e alimentação fora puxam o orçamento",
  "summary": "Duas ou três frases com o diagnóstico.",
  "body_md": "## Diagnóstico\n...\n## O que mudar\n...",
  "expected_monthly_savings": 420.0,
  "model": "claude-opus-5-5",
  "items": [
    {"action": "ajustar", "budget": "Alimentação fora", "current_limit": 1350, "suggested_limit": 1200,
     "expected_monthly_savings": 150, "priority": 1, "rationale": "..."},
    {"action": "criar", "budget": "Assinaturas", "categories": ["Assinaturas"], "suggested_limit": 60, "priority": 3,
     "rationale": "..."},
    {"action": "economizar", "budget": "Pix e outros", "expected_monthly_savings": 270, "priority": 2, "rationale": "..."}
  ]
}
```

- `action` aceita `criar`, `ajustar`, `manter`, `remover` ou `economizar`. Os tipos que mudam metas (`criar`,
  `ajustar`, `remover`) ganham botão "Aplicar"; `economizar` é orientação sem mudar meta.
- Valores em reais. `suggested_limit` é obrigatório em `criar` e `ajustar`; `categories` é obrigatório em `criar`.
- Um conjunto por mês e autor: reimportar substitui. Um item inválido recusa o lote inteiro.
