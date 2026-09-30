# Spec: servidor MCP do Tabimoney

- **Status:** implementada (fases 0 a 4); fase 5 avaliada e adiada (seção 10)
- **Data:** 2026-09-29
- **Versão-alvo:** 0.13.0
- **Autor:** Gabriel Tabim (com Claude)

## 1. Problema

Antes, a IA trabalhava no Tabimoney assim: o usuário abria o agente (Claude Code, Codex…) **numa pasta
específica**, a raiz do repositório ou a pasta da IA (`%USERPROFILE%\Tabimoney`, mantida por
`app/agent_workspace.py`). Lá o agente achava `AGENTS.md`, as skills (`.claude/skills/financas*`) e o atalho
`financas.bat`, e executava a CLI pelo terminal.

Isso funcionava, mas cobrava caro do usuário:

1. **Dependia da pasta.** Fora dela o agente não sabia que o Tabimoney existe. Não dava para perguntar "quanto
   gastei com mercado?" no Claude Desktop, no Cursor ou numa conversa aberta sobre outro assunto.
2. **Dependia de terminal.** O agente precisava de permissão de shell, montar linhas de comando com aspas certas
   (Windows × Mac, `.bat` × `.sh`) e salvar JSON em arquivo temporário para importar. Clientes sem shell (Claude
   Desktop, apps de chat) ficavam de fora.
3. **Skills só no Claude Code.** Outros agentes liam `AGENTS.md` e tinham que ir atrás dos arquivos sozinhos.
4. **Sem permissões finas.** Para o agente, tudo era "rodar um comando". O cliente não diferenciava ler gastos de
   apagar uma meta.

## 2. Proposta

Um **servidor MCP local** (Model Context Protocol) embutido no próprio app. O agente do usuário se conecta a ele e
recebe:

- **ferramentas (tools)** tipadas, com esquema JSON, descrição e marcação de leitura/escrita;
- **roteiros** (as antigas skills) servidos pelo próprio servidor, como *prompts* MCP e pela ferramenta `roteiro`;
- **documentos** (contrato, modelo do relatório, exemplos) como *resources*.

Continua **sem chat embutido e sem chave de API**: quem pensa é o agente que o usuário já usa e já paga. O
Tabimoney só entrega dados e recebe resultados. Tudo fica na máquina, com transporte `stdio`, sem porta aberta.

### Por que vale a pena

| Antes (pasta + CLI) | Com MCP |
|---|---|
| Só funcionava com o agente aberto na pasta certa | Funciona em qualquer conversa, em qualquer pasta |
| Precisava de shell | Qualquer cliente MCP: Claude Desktop, Claude Code, Codex, Cursor, VS Code, Gemini CLI… |
| Skills só no Claude Code | Roteiros servidos pelo servidor, para todos os clientes |
| JSON de importação em arquivo temporário | O agente passa o objeto direto como argumento, com esquema |
| Aprovação por comando de shell | Aprovação por ferramenta; leituras podem ser liberadas de vez |
| Instruções na pasta podiam ficar velhas | Servidor, ferramentas e roteiros saem do mesmo binário, sempre na mesma versão |

### Limites

- **Chats na web não alcançam o servidor.** claude.ai, ChatGPT e similares no navegador não enxergam um servidor
  `stdio` local. Levar o servidor para a internet contraria a premissa do app (dados na máquina); fora do escopo.
- **Os dados vão para o provedor da IA**, como já acontecia pela CLI. É decisão do usuário (inclusive se permite
  ou não o uso para treinamento, na conta dele); o app não exibe aviso sobre isso.
- **Cada cliente suporta partes diferentes do MCP.** Ferramentas funcionam em todos; *prompts* e *resources*, não.
  Por isso tudo o que importa também fica acessível por ferramenta (5.4).

## 3. Onde o MCP mora

**No próprio app, no mesmo repositório e no mesmo binário.** Não é um pacote separado (pip/npm) nem outro repo.

```
Tabimoney.exe mcp [--demo]                        # executável (Windows e Mac)
financas.bat mcp  /  ./financas.sh mcp            # rodando pelo código (--demo antes de mcp: financas --demo mcp)
.venv\Scripts\python.exe -m app.mcp_server [--demo]
```

Motivos:

- O servidor precisa da base, das migrações e de `app/services`. Um pacote separado duplicaria isso.
- Quem usa o executável não tem Python. O `Tabimoney.exe` já leva tudo, e já tinha o subcomando `cli`.
- Versão única: atualizar o app atualiza ferramentas, esquemas e roteiros juntos.
- O usuário "baixa e coloca na IA" em dois passos: baixa o Tabimoney e clica em **Conectar** (seção 7).

### Estrutura de código

```
app/
  agente/
    __init__.py               # ROTEIROS e roteiro(nome): carrega os roteiros (cabeçalho com título e descrição)
    operacoes.py              # funções que devolvem dict; a CLI e o MCP chamam as mesmas
    esquemas.py               # modelos pydantic das importações (documentam campos; regras ficam nos serviços)
    roteiros/*.md             # FONTE ÚNICA dos roteiros
  mcp_server/                 # não chamar de app/mcp, para não confundir com o SDK `mcp`
    __main__.py               # python -m app.mcp_server [--demo]
    servidor.py               # MCPServer: instruções, prompts, resources, log, console escondido no Windows
    ferramentas.py            # as 36 ferramentas, Sessao (demo, titular, backup, autor, registro de uso), EQUIVALENTE_CLI
    tarefas.py                # operações longas numa thread (atualizar, fundamentos)
    instalar.py               # configuração, instalação, texto para a IA, situação, reparo de caminho, registro de uso
  cli.py                      # casca: argparse → operacoes → JSON; grupo `mcp`
  launch.py                   # `Tabimoney.exe mcp`; ao abrir, instalar.reparar()
```

## 4. Protocolo e tecnologia

- **SDK:** `mcp` oficial em Python, **2.x** (`mcp>=2.2,<3`). Na 2.x o `FastMCP` virou
  `mcp.server.mcpserver.MCPServer`. O SDK negocia a versão do protocolo: clientes antigos pelo `initialize`
  (2025-11-25) e novos pela 2026-07-28; os testes rodam os dois modos.
- **Transporte:** `stdio`. O cliente abre o processo e fala por stdin/stdout. Não abre porta, não precisa de token,
  e o processo morre com a sessão do cliente.
- **Um processo por cliente.** Eles coexistem com o app aberto (servidor web + agendador), igual à CLI.
- **stdout é sagrado.** O SDK 2.x já desvia o descritor 1 para o stderr enquanto serve, então um `print` perdido
  não quebra o protocolo. Log em `data_dir()/logs/mcp.log`. `tests/test_mcp_stdio.py` conversa com o servidor num
  processo à parte.
- **Saída das ferramentas:** só texto, com o JSON compacto (`separators=(",", ":")`), 30% menor que o da CLI.
  **Mudança em relação à proposta:** sem `structuredContent`. Mandar o mesmo JSON duas vezes dobraria os tokens
  em clientes que mostram os dois ao modelo, e as ferramentas não declaram esquema de saída. Mesmas convenções da
  CLI: dinheiro em reais, percentuais como fração, datas ISO, chaves em português.
- **Erros:** o SDK esconde a mensagem de exceções comuns ("Error executing tool"). `Sessao.rodar` converte os erros
  dos serviços em `ToolError`, que chega ao agente com a mensagem em português.
- **Dependências no executável:** `collect_submodules("mcp")`, `mcp_types` e `opentelemetry` em `hiddenimports`,
  metadados de `mcp` e `opentelemetry-api`, e `app/agente/roteiros` em `datas` do `packaging/tabimoney.spec`.

## 5. Superfície do servidor

### 5.1 Instruções do servidor

`servidor.INSTRUCOES`: o que é o Tabimoney, unidades, "chame `roteiro` antes de uma tarefa com mais de um passo",
"comece por `carteira_contexto`", a lista das ferramentas destrutivas (só com pedido explícito), o backup
automático e a regra de privacidade. Na demo, um aviso a mais: dados fictícios, nunca apresentar como do usuário.

### 5.2 Ferramentas

36 ferramentas, nomes em `snake_case` e português, seguindo os grupos da CLI. As que dependem de titular aceitam
`titular` (nome). A tabela completa, com o tipo e o comando equivalente, está no contrato
(`docs/agente-financeiro.md`, seção "Servidor MCP"), e um teste garante que ela lista todas.

| Tipo | Anotação | Ferramentas |
|---|---|---|
| Leitura | `readOnlyHint` | `status`, `roteiro`, `tarefa_status`, `titulares`, `carteira_contexto`, `carteira_posicoes`, `fundamentos_contexto`, `metas_mostrar`, `gastos_resumo`, `gastos_listar`, `gastos_categorias`, `gastos_regras`, `orcamento_mostrar`, `orcamento_contexto`, `analise_listar`, `analise_mostrar`, `recomendacoes_listar`, `recomendacoes_mostrar`, `alertas_listar` |
| Escrita reversível | `destructiveHint: false` | `gastos_recategorizar`, `gastos_criar_regra`, `gastos_criar_categoria`, `gastos_restaurar_categoria`, `metas_regiao`, `alertas_resolver`, `analise_importar`, `recomendacoes_importar`, `orcamento_importar_recomendacoes`, `backup` |
| Sensível | `destructiveHint: true` | `metas_definir`, `orcamento_definir`, `orcamento_remover`, `gastos_excluir_categoria`, `gastos_remover_regra` |
| Longa | `openWorldHint`, `idempotentHint` | `atualizar_dados`, `fundamentos_atualizar` |

- **Importações** recebem o objeto (`relatorios` ou `conjunto`) com os modelos de `app/agente/esquemas.py`: cada
  campo com descrição e valores aceitos, campos extras passam adiante, e as regras ficam nos serviços (mensagens em
  português, lote inválido recusado inteiro).
- **Valores em reais** chegam como número e viram texto com duas casas antes do `parse_amount` (que lê "12.345"
  como doze mil, como se escreve no Brasil). Há teste.
- **Tarefas longas** esperam até 25 s mandando progresso (`report_progress`); se não terminarem, devolvem
  `tarefa_id` para `tarefa_status`. Chamar de novo enquanto roda devolve a mesma tarefa. A thread roda no
  contexto da chamada (base da demo, se for o caso).
- **Ficam fora do MCP:** credenciais (Pluggy, cofre), importação de extrato por arquivo e apagar lançamentos (que
  não existe).

### 5.3 Prompts (os roteiros como comandos)

| Prompt | Argumentos | Roteiro |
|---|---|---|
| `ciclo` | `titular` | Ciclo completo |
| `revisar_gastos` | `mes`, `titular` | Gastos e recategorização |
| `orcamento` | `mes` | Análise orçamentária |
| `onde_aportar` | `aporte`, `titular` | Metas de alocação |
| `analise_trimestral` | `tickers`, `titular` | Análise fundamentalista |
| `recomendacoes` | `aporte`, `titular` | Recomendações do trimestre |

Todos opcionais. O texto do prompt traz os parâmetros informados e o roteiro inteiro.

### 5.4 Roteiros: fonte única e acesso por ferramenta

Os roteiros saíram de `.claude/skills/*/SKILL.md` e moram em `app/agente/roteiros/*.md`, escritos em termos de
**ferramentas** (`carteira_contexto`), não de linhas de comando. Chegam ao agente por três caminhos: prompt MCP,
ferramenta `roteiro(nome)` (funciona em qualquer cliente; as instruções mandam chamá-la) e resource
`tabimoney://roteiros/{nome}`. Um teste falha se um roteiro citar ferramenta que não existe ou mencionar
`financas.bat`.

### 5.5 Resources

| URI | Conteúdo |
|---|---|
| `tabimoney://docs/contrato` | `docs/agente-financeiro.md` (reescrito com a seção do MCP) |
| `tabimoney://docs/modelo-relatorio-trimestral` | `docs/agentes/modelo-relatorio-trimestral.md` |
| `tabimoney://exemplos/{analise-trimestral,recomendacoes,orcamento}` | JSONs de `docs/agentes/exemplos/` |
| `tabimoney://roteiros/{nome}` | Roteiros |

Dados do usuário **não** viram resource: ficam só em ferramentas, que todos os clientes suportam e o usuário
aprova.

### 5.6 Tamanho das respostas

Medido na demo antes da mudança (JSON com `indent=2` da CLI):

| Comando | Bytes | ~tokens |
|---|---|---|
| `carteira contexto` | 17.7 k | 5 k |
| `orcamento contexto` | 20.1 k | 6 k |
| `fundamentos contexto EGIE3` | 17.6 k | 5 k |
| `gastos resumo` | 10.5 k | 3 k |
| `gastos listar --limite 200` | **78.4 k** | **~25 k** |

O Claude Code avisa acima de 10 mil tokens por resposta e corta em 25 mil. Implementado:

- `gastos_listar` com padrão `limite=50` (máximo 200), `deslocamento` e `proximo_deslocamento` (**mudança:**
  deslocamento no lugar de cursor opaco, mais simples de o agente usar e igual na CLI), e `campos` para a versão
  enxuta;
- JSON compacto no MCP;
- `test_respostas_cabem_no_limite_dos_clientes`: extrapola a carteira da demo para 40 ativos e exige menos de
  80 mil caracteres; a página padrão de lançamentos precisa ficar abaixo de 40 mil.

## 6. Segurança, privacidade e proteção dos dados

- **Mesmas garantias da CLI:** nada apaga lançamentos; correções ficam em colunas e tabelas próprias; importações
  inválidas recusam o lote inteiro.
- **Backup automático:** antes da primeira escrita de cada sessão (fora da demo), com o caminho em
  `backup_automatico` na resposta.
- **Autoria:** o autor é o `clientInfo.name` do cliente (ex.: `claude-code`); sem ele, `agente`.
- **Nada de segredo sai:** um teste grava chave Pluggy, token brapi e CPF, chama todas as leituras e procura esses
  valores nas respostas.
- **Texto de banco é dado não confiável.** Descrições de lançamento vêm de terceiros e podem tentar instruir o
  modelo. As defesas: nenhuma ferramenta apaga lançamentos, as sensíveis pedem confirmação no cliente, backup
  automático e autoria registrada.
- **Demo separada:** `mcp --demo` serve a base de demonstração, numa entrada à parte (`tabimoney-demo`). Na demo,
  `atualizar_dados` e `backup` são recusados, e as escritas não tocam na base real (teste).

## 7. Instalação no cliente ("baixar e colocar na IA")

### 7.1 Configurações › Conectar à IA

Seção `#ia` das Configurações (que passaram a ter uma seção por vez, edição em janela e ajuda no **?**). Para cada
cliente: a situação (Conectado, Caminho antigo, Não conectado, Não
encontrado neste computador, Configuração com erro), o último uso ("usou há 5 min"), **Conectar** /
**Reconectar** / **Atualizar caminho**, **Desconectar** e o ícone `</>` (conectar à mão, numa janela).

| Cliente | Automático (botão Conectar) | À mão |
|---|---|---|
| **Claude Desktop** | Grava `mcpServers.tabimoney` em `claude_desktop_config.json` (Windows `%APPDATA%\Claude\` ou a pasta virtualizada da versão da Microsoft Store; Mac `~/Library/Application Support/Claude/`) | Trecho do JSON |
| **Claude Code** | Roda `claude mcp remove` + `claude mcp add tabimoney --scope user -- <exe> mcp`, se `claude` estiver no PATH | O comando |
| **Codex** | Troca só a tabela `[mcp_servers.tabimoney]` em `~/.codex/config.toml` (ou `$CODEX_HOME`) | `codex mcp add …` e o trecho TOML |
| **Cursor** | Grava em `~/.cursor/mcp.json` | Link `cursor://anysphere.cursor-deeplink/mcp/install?…` e o trecho |
| **VS Code (Copilot)** | Grava `servers.tabimoney` (com `"type": "stdio"`) no `mcp.json` do usuário | Link `vscode:mcp/install?…` e o trecho |
| **Gemini CLI** | Grava em `~/.gemini/settings.json` | Trecho do JSON |

Em todos os arquivos: só a entrada do Tabimoney muda, o resto fica igual, uma cópia vai para
`<arquivo>.antes-do-tabimoney` antes de gravar, e um arquivo com JSON/TOML quebrado não é tocado (a tela manda
usar o texto para a IA).

**Texto para colar na IA** (acrescentado a pedido): se o automático falhar, ou para um agente fora da lista, a tela
mostra um pedido pronto (`instalar.texto_para_ia`). Ele traz o nome do servidor, a entrada (comando, argumentos,
ambiente), onde fica a configuração de cada cliente conhecido, a regra de não mexer nos outros servidores e fazer
cópia, o teste final (chamar `status`) e o pedido de não ler dados financeiros durante a configuração. Cada
cliente também tem a sua versão em `financas mcp config`.

Também no cartão: **Demonstração para a IA** (conectar `tabimoney-demo` num agente, e o texto da demo) e exemplos
do que pedir. **Mudança:** sem aviso de privacidade (decisão do usuário, seção 12). Na demo do app, a situação é
fictícia (nada das configurações reais aparece), e conectar fica desligado.

### 7.2 CLI `financas mcp`

```
financas mcp                                      # sobe o servidor (stdio)
financas mcp clientes                             # situação de cada agente
financas mcp config --cliente claude-code         # entrada, trecho, comando, link e texto para a IA
financas mcp instalar --cliente claude-desktop [--demo]
```

Rodando pelo código, a entrada aponta para o Python do `.venv` com `-m app.mcp_server` e `PYTHONPATH` na raiz.

### 7.3 Executável que muda de lugar

1. **Implementado:** ao abrir, `instalar.reparar()` confere os clientes de arquivo e corrige o caminho das entradas
   `tabimoney`/`tabimoney-demo` que apontam para um `Tabimoney.exe`/`Tabimoney` diferente do atual. Entrada feita
   pelo código (Python) ou à mão não é tocada. Só roda no executável.
2. **Implementado:** a tela mostra **Caminho antigo** quando a entrada não bate com o executável atual, e
   **Atualizar caminho** refaz (para o Claude Code, por `claude mcp add`).
3. Descartado: o lançador estável em `%USERPROFILE%\Tabimoney\` (`.cmd`), porque clientes que iniciam o processo
   sem shell não executam `.cmd` de forma confiável no Windows; o reparo resolve o mesmo problema.

## 8. Pasta da IA e skills (transição)

- **Skills aposentadas** (decisão do usuário): `.claude/skills/financas*` saiu do repositório; os roteiros estão em
  `app/agente/roteiros`.
- **Pasta da IA, versão de transição (esta):** continua sendo criada, com um `AGENTS.md` que aponta para
  **Conectar à IA**, os roteiros em `roteiros/`, uma tabela ferramenta → comando gerada de `EQUIVALENTE_CLI`, o
  contrato e o `financas.bat`. As skills antigas que a 0.12 gravou lá são apagadas (só as `financas*`).
- **Próxima versão:** `agent_workspace.py` sai, e `launch.open_app` para de chamá-lo.
- **A CLI fica.** É útil ao usuário e aos testes, e serve de plano B para agentes sem MCP.

## 9. Testes

- **`tests/test_mcp.py`** (cliente em memória do SDK): catálogo (título, descrição, anotação coerente, toda
  ferramenta com equivalente na CLI), instruções, toda leitura na demo, mesma resposta da CLI (8 casos, inclusive
  titular), paginação e `campos`, titular desconhecido, tamanho das respostas, backup automático só na primeira
  escrita, importação dos exemplos com o cliente como autor (protocolo antigo e novo), lote inválido recusado,
  categoria em uso, valor em reais sem virar milhar, demo recusa atualizar/backup, escrita na demo não toca a base
  real, tarefas longas (em andamento, rápida, com falha), roteiros só citam ferramentas que existem, prompts,
  resources, nenhum segredo, registro de uso, contrato lista todas as ferramentas.
- **`tests/test_mcp_stdio.py`**: o servidor num processo à parte, por `python -m app.mcp_server` e por
  `python -m app.launch mcp`.
- **`tests/test_mcp_instalar.py`**: configuração e texto de cada cliente, mescla sem apagar, cópia, JSON quebrado
  intocado, VS Code, demo separada, Codex TOML (troca só a tabela, não duplica, remove), Claude Code pelo comando
  (sucesso, ausente, recusa), situação, reparo, registro de uso, a tela (conectar, desconectar, falha indica o
  texto, demo fictícia e bloqueada) e `financas mcp`.
- **e2e:** copiar o texto para a IA (área de transferência), conectar/desconectar o Claude Desktop pela tela, e o
  comando do Claude Code em **Conectar à mão**. A tela de celular já é coberta.
- **Isolamento:** `conftest.py` e o servidor de e2e apontam `APPDATA`, `XDG_CONFIG_HOME` e o home para pastas
  temporárias, tiram `CODEX_HOME` e trocam `instalar._which`, para `claude` e `codex` nunca rodarem de verdade.
- **Manual, antes do Release:** Claude Desktop e Claude Code no Windows e no Mac conectam ao exe e rodam o prompt
  `ciclo` na demo (R1 e R2 no ambiente real).

## 10. Fases

| Fase | Situação |
|---|---|
| **0. Camada comum** | Feita. Saída da CLI igual em 21 comandos de leitura na demo; a única diferença é o novo `proximo_deslocamento` quando há mais lançamentos |
| **Spike** | Feito: `Tabimoney.exe mcp` gerado no Windows e testado por stdio (partida, 36 ferramentas, roteiros e contrato empacotados). Falta o teste com o Claude Desktop de verdade e o build de Mac (no CI) |
| **1. Servidor de leitura** | Feita |
| **2. Escrita** | Feita |
| **3. Conectar à IA** | Feita, com o texto para colar na IA |
| **4. Migração dos roteiros** | Feita |
| **5. Extras** | Avaliada e adiada, item a item (abaixo) |

**Fase 5, por que ficou de fora:**

- **Pacote `.mcpb`:** o botão **Conectar** já instala no Claude Desktop em um clique. O `.mcpb` levaria uma
  segunda cópia do executável dentro do pacote (dobra o download) e, no Mac, um binário sem assinatura extraído
  pelo Claude cai na quarentena do Gatekeeper. Reavaliar se o app ganhar assinatura.
- **Plugin do Claude Code num marketplace deste repo:** o `.mcp.json` de um plugin precisa de um comando que
  funcione em qualquer máquina, mas o caminho do executável muda de pessoa para pessoa e de sistema para sistema
  (`.exe` × `.app`), e o plugin não tem como descobrir. O botão (que roda `claude mcp add`) e o comando pronto
  cobrem o caso.
- **Transporte HTTP no app aberto:** abriria uma superfície de rede num app financeiro (exige token, checagem de
  `Origin`/`Host` contra DNS rebinding) e só funcionaria com o app aberto. Todos os clientes da lista falam stdio.
  Reavaliar se aparecer um cliente que só aceite URL.

## 11. Riscos

| # | Risco | Situação |
|---|---|---|
| R1 | **Janela de console no Windows** quando um cliente gráfico abre o exe (`console=True`) | Mitigado: no modo `mcp`, se o console é só do exe (este processo e o carregador do PyInstaller), a janela é escondida (`servidor._esconder_console`); vindo de um terminal, fica como está. Pode piscar ao abrir. Confirmar no Claude Desktop antes do Release |
| R2 | **Partida lenta do exe onefile** | Medido no build de Windows: 1,8 a 2,4 s até o cliente conectar; as chamadas seguintes levam milissegundos. Aceitável |
| R3 | **stdout poluído** | Resolvido pelo SDK 2.x (desvia o descritor 1 enquanto serve) e coberto pelo teste de stdio |
| R4 | **SQLite com vários escritores** | Como na CLI: `busy_timeout` de 20 s. WAL não foi ligado (o backup copia pela API de backup do SQLite; reavaliar se aparecer "database is locked") |
| R5 | **Respostas grandes** | Paginação, `campos`, JSON compacto e teste de tamanho |
| R6 | **Tempo limite** em operações longas | Tarefas com espera curta, progresso e `tarefa_status` |
| R7 | **Suporte desigual** a prompts e resources | Tudo acessível por ferramenta; `roteiro` + instruções |
| R8 | **Formato de configuração dos clientes muda** | Isolado em `instalar.CLIENTES`/`arquivo_config`, com testes por cliente; texto para a IA sempre disponível |
| R9 | **Dependência nova** pesa no exe | `mcp` 2.x puxa `pydantic` (já havia), `starlette`/`uvicorn` (já havia), `opentelemetry-api`, `jsonschema`, `pyjwt`, `pywin32` e `httpx2`. Exe de Windows com tudo: 31,5 MB. O build pegou um problema: `collect_submodules("mcp")` importava `mcp.cli`, que exige `typer`; o `.spec` filtra `mcp.cli` e `mcp.server.fastmcp` |

## 12. Decisões

1. **Aposentar skills e pasta da IA:** aposentar, com uma versão de transição (esta).
2. **Demo:** servidor separado (`mcp --demo`, entrada `tabimoney-demo`).
3. **Gravar na configuração dos clientes:** sim, com cópia do arquivo antes, pelo botão (a confirmação é o clique).
4. **Aviso de privacidade na tela:** não. Deixar dados para treinamento ou não é decisão do usuário na conta dele.
5. **Versão manual além da automática:** sim: **Conectar à mão** por cliente e o **texto para colar na IA**.
6. **Tarefas longas:** no processo MCP.
7. **Nomes:** `tabimoney` e `tabimoney-demo`.
