# Instruções para agentes

Aplicativo local de finanças pessoais (FastAPI + SQLite). Os dados são do usuário e ficam nesta máquina.

## Ler e alterar dados do usuário

Use sempre a linha de comando `financas.bat` (ou `.venv\Scripts\python.exe -m app.cli`). Ela responde em JSON e
registra as correções de forma reversível. **Não edite o SQLite diretamente** e não apague lançamentos.
Antes de mudanças em massa, rode `financas.bat backup`.

Comece por `financas.bat carteira contexto` em qualquer tarefa de investimentos. Ele traz metas, posições com
fundamentos, as últimas análises, renda fixa e previdência num JSON só.

## Roteiros

Cada tarefa tem um roteiro passo a passo. O Claude Code carrega os roteiros como skills; outros agentes devem
ler o arquivo antes de começar:

| Tarefa | Roteiro |
|---|---|
| Visão geral e qual roteiro usar | `.claude/skills/financas/SKILL.md` |
| **Ciclo completo** ("atualize minhas finanças") | `.claude/skills/financas-ciclo/SKILL.md` |
| Revisar gastos e recategorizar | `.claude/skills/financas-gastos/SKILL.md` |
| Orçamento: metas de gastos e recomendações de economia | `.claude/skills/financas-orcamento/SKILL.md` |
| Metas de alocação e onde aportar | `.claude/skills/financas-metas/SKILL.md` |
| Análise fundamentalista trimestral | `.claude/skills/financas-analise-trimestral/SKILL.md` |
| Recomendações trimestrais e carteiras-modelo | `.claude/skills/financas-recomendacoes/SKILL.md` |

O contrato (formatos de JSON e regras de cálculo) está em `docs/agente-financeiro.md`. O modelo do relatório
está em `docs/agentes/modelo-relatorio-trimestral.md`, e os exemplos válidos em `docs/agentes/exemplos/`.

## Privacidade

Não envie extratos, saldos ou identificadores (CPF, números de conta) a serviços externos. Buscar informação
pública sobre empresas e títulos (CVM, relações com investidores, Tesouro, notícias) é permitido.

## Código

- **Versão e changelog:** toda mudança entra em `[Não lançado]` no `CHANGELOG.md` no mesmo commit. A versão
  fica só em `app/__init__.py`. Numeração e lançamento: `docs/versionamento.md`.

- **Testes:** rode `pytest` (Windows: `.venv\Scripts\python.exe -m pytest`; Mac: `.venv/bin/python -m pytest`)
  antes de commitar. Tudo roda isolado: base temporária, cofre falso e sem rede (`tests/conftest.py`), então não
  mexe nos dados do usuário. Página nova já é coberta por `tests/test_paginas.py`. Mudou uma regra ou corrigiu um
  bug? Escreva o teste que teria pegado. O GitHub Actions roda a suíte em Windows e Mac e não gera executável se
  algum teste falhar.
- Dinheiro em centavos (int) no banco; quantidades em milionésimos (int). Na CLI, reais (float).
- Migrações em `migrations/NNN_*.sql`, aplicadas na inicialização; nunca altere uma migração já aplicada.
- Textos da interface em português do Brasil.
- O executável (`Tabimoney.exe` pelo `build.bat`; Windows e Mac pelo GitHub Actions) só leva os arquivos listados em
  `datas` de `packaging/tabimoney.spec`.
  Arquivo novo que o app ou a pasta da IA leem em tempo de execução precisa entrar nessa lista.
- O app roda em Windows e Mac: nada de caminho, comando ou cofre só de Windows fora de um `if os.name == "nt"`
  (pasta de dados em `db.data_dir()`, segredos em `app/security.py`).
