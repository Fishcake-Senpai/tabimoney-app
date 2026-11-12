# IA e MCP

O Tabimoney tem um servidor [MCP](https://modelcontextprotocol.io) embutido. Conectado a ele, o seu agente de IA
ganha as ferramentas do app em qualquer conversa e em qualquer pasta: lê gastos, carteira e metas, grava análises,
recomendações e correções de categoria.

Não existe chat embutido nem chave de API: quem pensa é a IA que você já usa, e as operações rodam nesta máquina.

## Conectar

1. Abra **Configurações › Conectar à IA**.
2. Escolha o seu agente:
   - **Claude Desktop, Cursor, VS Code, Gemini CLI e Codex:** clique em **Conectar**. O app grava a entrada
     `tabimoney` na configuração do agente, sem mexer no resto e guardando uma cópia do arquivo antes. Depois,
     reinicie o agente.
   - **Claude Code:** **Conectar** roda `claude mcp add` por você. Sem o comando `claude` no PATH, copie o comando
     mostrado no ícone `</>` e rode no terminal.
   - **Outro agente, ou deu errado:** em **Configurar pela própria IA**, copie o texto pronto e cole em uma conversa.
     O próprio agente faz a configuração.

Rodando pelo código, o app aponta o agente para o Python do `.venv` (`python -m app.mcp_server`). No executável, ele
aponta para o próprio `Tabimoney.exe mcp`.

## O que pedir

Os roteiros do app viram comandos no Claude Code (`/mcp__tabimoney__ciclo`, por exemplo) e prompts no MCP. Exemplos:

- “Atualize minhas finanças.” — ciclo completo: sincronizar, revisar gastos, analisar a carteira e resumir.
- “Revise meus gastos do mês.” — recategorização e comparação com a média.
- “Onde devo aportar?” — plano de aporte dentro das metas.
- “Analise a EGIE3 para o longo prazo.” — tese completa.
- “Faça o acompanhamento trimestral das minhas teses.”
- “Monte as recomendações do trimestre.”
- “Como está meu imposto de renda?”

Os roteiros ficam em `app/agente/roteiros/` e são a fonte única do passo a passo. A visão geral está em
`app/agente/roteiros/visao-geral.md`.

## O que o agente pode fazer

O servidor expõe ferramentas de leitura, escrita reversível, escrita sensível e tarefas longas:

- **Leitura:** status, carteira, gastos, metas, fundamentos, imposto, análises e recomendações.
- **Escrita reversível:** recategorizar lançamentos, criar regras e categorias, importar análises, recomendações e
  orçamento, ajustar a região de um ativo, definir perfil.
- **Sensível:** alterar metas de alocação, remover regras e categorias, definir orçamento. Essas ferramentas só
  rodam com pedido explícito e confirmação no agente.
- **Longa:** atualizar dados e fundamentos. Se passarem de ~25 segundos, devolvem uma tarefa e podem ser acompanhadas
  por `tarefa_status`.

O agente nunca edita o SQLite diretamente. As operações são as mesmas da linha de comando, em
`app/agente/operacoes.py`, e toda resposta sai em JSON.

## Proteções

- **Backup automático:** antes da primeira escrita de cada sessão, o servidor faz uma cópia da base e devolve o
  caminho.
- **Correções reversíveis:** recategorizações e regras podem ser desfeitas.
- **Autor:** análises, regras, categorias, metas e recomendações gravadas pelo MCP levam o nome do cliente
  (`claude-code`, por exemplo), não um autor genérico.
- **Lançamentos não são apagados:** as ferramentas sensíveis podem remover regras, categorias e metas, sempre com
  confirmação no agente.
- **Rede só nas atualizações:** as ferramentas leem e gravam os dados locais. As tarefas de atualização usam as
  mesmas fontes do app (Pluggy, brapi, CVM e Banco Central); para pesquisar notícias e dados públicos, o agente usa
  as ferramentas dele.

## Demonstração

A entrada `tabimoney-demo` (em **Conectar à IA › Demonstração**) liga a IA aos dados fictícios, para testar um
pedido antes de usar com os seus. Nela, atualizar e backup são recusados.

## Linha de comando

Quem não usa MCP pode chamar as mesmas operações pela CLI, com saída em JSON:

```bash
financas.bat gastos resumo
financas.bat gastos regra --contem "UBER" --categoria Transporte
financas.bat carteira contexto
financas.bat fundamentos contexto EGIE3
financas.bat analise importar relatorio.json
financas.bat mcp instalar --cliente claude-desktop
```

No Mac, troque `financas.bat` por `./financas.sh` ou use
`/Applications/Tabimoney.app/Contents/MacOS/Tabimoney cli …`.

O contrato completo — ferramentas, comandos equivalentes, formatos JSON e regras de cálculo — está em
[Contrato com agentes](../agente-financeiro.md). Os modelos de relatório e os exemplos válidos ficam em
[Modelos de relatório](../agentes/modelo-relatorio-tese.md) e [Exemplos JSON](../agentes/exemplos/).

## Mudou o executável de pasta?

Ao abrir, o Tabimoney corrige sozinho o caminho nas configurações que ele gravou. No Claude Code, a tela avisa
**Caminho antigo** e **Atualizar caminho** refaz a conexão.

## Limitações

- **Chats no navegador** (claude.ai, ChatGPT) não enxergam um servidor local. Use o app de desktop ou o terminal.
- **O provedor da IA recebe o que você envia na conversa.** O MCP roda localmente, mas o modelo não. Não peça para
  enviar extratos, saldos ou identificadores a serviços externos; para pesquisar informação pública de empresas, o
  agente pode usar a web normalmente.
- **A pasta antiga da IA** (`%USERPROFILE%\Tabimoney`) continua sendo criada nesta versão, para a transição, com um
  aviso para usar o MCP e os roteiros. Ela sai em uma versão futura.

Para conectar os bancos e importar arquivos, veja [Conexões e importação](conexoes-e-importacao.md).
