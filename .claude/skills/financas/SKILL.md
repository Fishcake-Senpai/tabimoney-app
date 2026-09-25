---
name: financas
description: Ponto de entrada para qualquer pedido sobre as finanças pessoais do usuário neste projeto (gastos, categorias, metas de alocação, aportes, análise fundamentalista das ações, FIIs, renda fixa e previdência, recomendações trimestrais). Explica a ferramenta e indica qual roteiro seguir.
---

# Finanças pessoais: como usar a ferramenta

O app é local (FastAPI + SQLite). Tudo o que um agente faz passa pela CLI na raiz do projeto:
`.\financas.bat <grupo> <ação>`. A saída sai em JSON, com valores em reais e percentuais como fração.
**Nunca edite o SQLite** e não apague dados. Antes de mudanças em massa, rode `.\financas.bat backup`.

## Escolha o roteiro

| Pedido do usuário | Siga |
|---|---|
| "atualize minhas finanças", "faça minhas análises", "atualize tudo" | skill `financas-ciclo` (faz todas as etapas abaixo em ordem) |
| "olha meus gastos", "corrige categorias", "por que gastei mais" | skill `financas-gastos` |
| "analise meu orçamento", "onde economizar", "sugira metas de gastos" | skill `financas-orcamento` |
| "quanto aportar e onde", "estou balanceado?", "minhas metas" | skill `financas-metas` |
| "analisa minhas ações/FIIs/CDB", "relatório trimestral", "atualiza fundamentos" | skill `financas-analise-trimestral` |
| "o que mudar na carteira", "recomendações do trimestre", "sugere carteiras" | skill `financas-recomendacoes` (depois da análise) |

## Mapa rápido da CLI

- `atualizar`: backup + Open Finance + cotações/CDI + balanços da CVM, de uma vez.
- `carteira contexto`: fotografia completa (metas, posições com fundamentos, últimas análises, renda fixa, previdência). **Comece por aqui** em qualquer tarefa de investimentos.
- `gastos resumo | listar | recategorizar | regra | regras`
- `metas mostrar [--aporte X] | definir | regiao` (metas de alocação)
- `orcamento mostrar | contexto | importar-recomendacoes ARQ` (metas de gastos)
- `fundamentos atualizar | contexto TICKER`
- `analise importar ARQ | listar | mostrar ID`
- `recomendacoes importar ARQ | listar | mostrar [ID]`
- `alertas listar | resolver ID`

O contrato completo (formatos de JSON e regras de cálculo) está em `docs/agente-financeiro.md`.
O modelo do relatório está em `docs/agentes/modelo-relatorio-trimestral.md`, e os exemplos em `docs/agentes/exemplos/`.

## Onde o usuário vê o resultado

- **Ações e FIIs**: fundamentos e avisos.
- **Página de cada ativo**: a análise mais recente completa e o histórico.
- **Recomendações**: mudanças sugeridas e carteiras-modelo.
- **Análises**: todos os relatórios.
- **Metas**: balanço e plano de aporte.
- **Conta e cartão**: orçamento do mês, gastos e regras.

Ao terminar, diga ao usuário onde olhar.
