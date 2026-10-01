# Instruções para agentes

Aplicativo local de finanças pessoais (FastAPI + SQLite). Os dados são do usuário e ficam nesta máquina.

## Ler e alterar dados do usuário

O caminho principal é o **servidor MCP `tabimoney`** (`app/mcp_server`). Se você tem as ferramentas dele
(`status`, `roteiro`, `carteira_contexto`…), use-as. Para conectar: **Configurações › Conectar à IA** no app, ou
`financas.bat mcp instalar --cliente claude-code` (clientes: `financas.bat mcp clientes`).

Sem MCP, use a linha de comando `financas.bat` (ou `.venv\Scripts\python.exe -m app.cli`), que chama as mesmas
operações (`app/agente/operacoes.py`). As duas respondem em JSON e registram as correções de forma reversível.
**Não edite o SQLite diretamente** e não apague lançamentos. Antes de mudanças em massa, faça backup (o servidor
MCP faz sozinho antes da primeira mudança da sessão; na CLI, `financas.bat backup`).

Comece por `carteira_contexto` (ou `financas.bat carteira contexto`) em qualquer tarefa de investimentos. Ele traz
metas, posições com fundamentos, as últimas análises, renda fixa e previdência num JSON só.

## Roteiros

Cada tarefa tem um roteiro passo a passo em `app/agente/roteiros/` (a fonte única). O servidor MCP entrega os
roteiros pela ferramenta `roteiro`, como prompts e como resources; sem MCP, leia o arquivo antes de começar. Eles
citam as ferramentas do MCP; `EQUIVALENTE_CLI` em `app/mcp_server/ferramentas.py` diz o comando da CLI de cada uma.

| Tarefa | Roteiro |
|---|---|
| Visão geral e qual roteiro usar | `app/agente/roteiros/visao-geral.md` |
| **Ciclo completo** ("atualize minhas finanças") | `app/agente/roteiros/ciclo.md` |
| Revisar gastos e recategorizar | `app/agente/roteiros/gastos.md` |
| Orçamento: metas de gastos e recomendações de economia | `app/agente/roteiros/orcamento.md` |
| Metas de alocação e onde aportar | `app/agente/roteiros/metas.md` |
| Análise completa de um ativo (tese de longo prazo, método Investidor Sardinha) | `app/agente/roteiros/analise-ativo.md` |
| Acompanhamento trimestral das teses | `app/agente/roteiros/analise-trimestral.md` |
| Recomendações trimestrais e carteiras-modelo | `app/agente/roteiros/recomendacoes.md` |

O contrato (formatos de JSON e regras de cálculo) está em `docs/agente-financeiro.md`. Os modelos dos relatórios
estão em `docs/agentes/modelo-relatorio-tese.md` e `docs/agentes/modelo-relatorio-trimestral.md`, e os exemplos
válidos em `docs/agentes/exemplos/`.

## Privacidade

Não envie extratos, saldos ou identificadores (CPF, números de conta) a serviços externos. Buscar informação
pública sobre empresas e títulos (CVM, relações com investidores, Tesouro, notícias) é permitido.

## Código

- **Versão e changelog:** toda mudança entra em `[Não lançado]` no `CHANGELOG.md` no mesmo commit. A versão
  fica só em `app/__init__.py`. Numeração e lançamento: `docs/versionamento.md`.

- **Agentes (MCP e CLI):** operação nova entra em `app/agente/operacoes.py` e ganha as duas portas: a ferramenta em
  `app/mcp_server/ferramentas.py` (com tipo, descrição e `EQUIVALENTE_CLI`) e o comando em `app/cli.py`. Mudou o
  que o agente deve fazer? Atualize o roteiro em `app/agente/roteiros/`. `tests/test_mcp.py` confere catálogo,
  anotações, paridade com a CLI e se os roteiros só citam ferramentas que existem.
- **Testes:** rode `pytest` (Windows: `.venv\Scripts\python.exe -m pytest`; Mac: `.venv/bin/python -m pytest`)
  antes de commitar. Tudo roda isolado: base temporária, cofre falso e sem rede (`tests/conftest.py`), então não
  mexe nos dados do usuário. Página nova já é coberta por `tests/test_paginas.py`. Mudou uma regra ou corrigiu um
  bug? Escreva o teste que teria pegado. Tela ou formulário novo? Cubra também em `tests/e2e` (navegador de
  verdade; precisa de `requirements-e2e.txt` e `python -m playwright install chromium`).
- **Demonstração (`app/demo.py`):** toda tela, aba ou recurso novo ganha exemplos fictícios na demo, no mesmo
  commit. `tests/test_demo.py` abre todas as páginas na demo e falha se alguma aparecer vazia; os testes de
  navegador (`tests/e2e`) usam os mesmos dados. Dados só inventados: nada da base do usuário vai para a demo.
- **Branches:** trabalhe na `dev` (ou numa branch saindo dela). Nunca faça commit direto na `main`: ela só recebe
  merge da `dev` por PR, com o check **Testes ok** do GitHub Actions passando. O merge na `main` gera os
  executáveis e, se a versão de `app/__init__.py` ainda não tiver tag, publica o Release. Fluxo completo em
  `docs/versionamento.md`.
- Dinheiro em centavos (int) no banco; quantidades em milionésimos (int). Na CLI, reais (float).
- Migrações em `migrations/NNN_*.sql`, aplicadas na inicialização; nunca altere uma migração já aplicada.
- Textos da interface em português do Brasil.
- O executável (`Tabimoney.exe` pelo `build.bat`; Windows e Mac pelo GitHub Actions) só leva os arquivos listados em
  `datas` de `packaging/tabimoney.spec`.
  Arquivo novo que o app ou a pasta da IA leem em tempo de execução precisa entrar nessa lista.
- O app roda em Windows e Mac: nada de caminho, comando ou cofre só de Windows fora de um `if os.name == "nt"`
  (pasta de dados em `db.data_dir()`, segredos em `app/security.py`).
