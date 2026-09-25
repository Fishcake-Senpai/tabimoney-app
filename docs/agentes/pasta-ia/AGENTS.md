# Instruções para agentes

Esta pasta é a mesa de trabalho da IA para o **Tabimoney**, um aplicativo local de finanças pessoais. O próprio
Tabimoney cria e atualiza esta pasta sempre que é aberto; não edite os arquivos daqui (eles são substituídos).
Os dados do usuário ficam no computador dele, fora desta pasta.

## Ler e alterar dados do usuário

Use sempre a linha de comando `financas.bat` desta pasta (ex.: `.\financas.bat gastos resumo`). Ela chama o
`Tabimoney.exe`, responde em JSON e registra as correções de forma reversível. **Não edite o banco SQLite
diretamente** e não apague lançamentos. Antes de mudanças em massa, rode `.\financas.bat backup`.

Se `financas.bat` responder que o executável não foi encontrado, peça ao usuário para abrir o Tabimoney uma vez
(o caminho é atualizado ao abrir).

Comece por `.\financas.bat carteira contexto` em qualquer tarefa de investimentos. Ele traz metas, posições com
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
Arquivos JSON temporários que você gerar para importar podem ficar numa subpasta `trabalho/` desta pasta.

## Privacidade

Não envie extratos, saldos ou identificadores (CPF, números de conta) a serviços externos. Buscar informação
pública sobre empresas e títulos (CVM, relações com investidores, Tesouro, notícias) é permitido.
