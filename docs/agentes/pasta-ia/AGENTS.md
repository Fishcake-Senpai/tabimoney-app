# Instruções para agentes

Esta pasta é a antiga mesa de trabalho da IA para o **Tabimoney**, um aplicativo local de finanças pessoais. O
próprio Tabimoney cria e atualiza esta pasta sempre que é aberto; não edite os arquivos daqui (eles são
substituídos). Os dados do usuário ficam no computador dele, fora desta pasta.

## O Tabimoney agora se conecta por MCP

O jeito recomendado de usar a IA com o Tabimoney é o **servidor MCP**: o agente ganha as ferramentas do Tabimoney
em qualquer conversa e em qualquer pasta, sem terminal. Para conectar, o usuário abre o Tabimoney em
**Configurações › Conectar à IA** e clica em **Conectar** no agente dele (Claude Desktop, Claude Code, Codex,
Cursor, VS Code, Gemini CLI), ou copia o texto pronto e cola na IA.

**Se você já tem as ferramentas do servidor `tabimoney`** (ex.: `carteira_contexto`, `roteiro`), use-as e ignore o
resto deste arquivo.

Esta pasta continua funcionando nesta versão, para a transição, e deixa de existir numa versão futura.

## Sem MCP: pela linha de comando

Use a linha de comando `financas.bat` desta pasta (ex.: `.\financas.bat gastos resumo`). Ela chama o
`Tabimoney.exe`, responde em JSON e registra as correções de forma reversível. **Não edite o banco SQLite
diretamente** e não apague lançamentos. Antes de mudanças em massa, rode `.\financas.bat backup`.

Se `financas.bat` responder que o executável não foi encontrado, peça ao usuário para abrir o Tabimoney uma vez
(o caminho é atualizado ao abrir).

Os roteiros de cada tarefa estão em `roteiros/` (comece por `roteiros/visao-geral.md`). Eles foram escritos para
as ferramentas do MCP; a tabela abaixo diz qual comando faz o mesmo. As importações recebem um arquivo JSON:
salve o conteúdo numa subpasta `trabalho/` desta pasta e passe o caminho.

{{TABELA}}

O contrato (formatos de JSON e regras de cálculo) está em `docs/agente-financeiro.md`. O modelo do relatório está
em `docs/agentes/modelo-relatorio-trimestral.md`, e os exemplos válidos em `docs/agentes/exemplos/`.

## Privacidade

Não envie extratos, saldos ou identificadores (CPF, números de conta) a serviços externos. Buscar informação
pública sobre empresas e títulos (CVM, relações com investidores, Tesouro, notícias) é permitido.
