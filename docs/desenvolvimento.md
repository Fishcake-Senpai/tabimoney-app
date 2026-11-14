# Desenvolvimento

Este guia é para quem vai rodar o Tabimoney pelo código, entender a arquitetura, escrever testes ou gerar o
executável. Para instalar e usar o app, comece em [Instalação e atualização](guia/instalacao.md).

## Requisitos

- Python 3.11 ou mais recente (no Windows, com o launcher `py` habilitado).
- Windows 10/11 ou macOS 11+.
- Git, se você for clonar o repositório.

## Rodar pelo código

**Windows:**

```bat
run.bat
```

**macOS:**

```bash
./run.command
```

Na primeira vez, o script cria o `.venv` e instala as dependências. Depois, abre o app como o executável: o
servidor fica em segundo plano e clicar de novo reinicia.

Para ver o log na tela e encerrar com `Ctrl+C`:

```bash
.venv\Scripts\python.exe -m app.launch --primeiro-plano   # Windows
.venv/bin/python -m app.launch --primeiro-plano           # macOS
```

A linha de comando usa as mesmas operações do app:

```bash
financas.bat gastos resumo          # Windows
./financas.sh gastos resumo         # macOS
```

## Estrutura

```text
app/
  main.py              rotas FastAPI e montagem das telas
  launch.py            ponto de entrada do executável e do run.bat
  cli.py               linha de comando
  db.py                conexão SQLCipher, migrações e pasta de dados
  db_crypto.py         chave, perfil SQLCipher, fingerprint e migração verificada
  security.py          cofre nativo (Credential Manager / Keychain)
  demo.py              dados fictícios da demonstração
  templates/           Jinja2
  static/              CSS, JavaScript, fonte e marca
  services/            regras de negócio (analytics, gastos, metas, IR, sync…)
  providers/           Pluggy, brapi, Banco Central, CVM e Yahoo
  agente/              operações, esquemas e roteiros dos agentes
  mcp_server/          servidor MCP, ferramentas e instalador nos clientes
migrations/            esquema SQLite, sempre em arquivos numerados
tests/                 pytest, TestClient e testes de navegador
packaging/             PyInstaller, manual de conexões e entrada do executável
docs/                  documentação pública e recursos dos agentes
```

### Como as camadas conversam

- **Interface:** `app/main.py` recebe a requisição, valida o CSRF e chama os serviços. As telas são templates
  Jinja2; o JavaScript é progressivo e não depende de framework.
- **Serviços:** `app/services/` concentram as regras de cálculo, importação, conciliação e análise. Nenhuma regra
  deve ficar duplicada no template.
- **Provedores:** `app/providers/` isolam as APIs externas. Se uma fonte cair, o serviço decide o fallback.
- **Operações dos agentes:** `app/agente/operacoes.py` é a porta única para leitura e escrita feita por IA. O MCP
  (`app/mcp_server/`) e a CLI (`app/cli.py`) chamam as mesmas funções.
- **Base:** `app/db.py` abre o SQLCipher e aplica as migrações na inicialização. A chave, o perfil criptográfico, o
  fingerprint e a migração de uma base plaintext ficam em `app/db_crypto.py`. A pasta de dados depende do sistema
  operacional (`db.data_dir()`), nunca de um caminho fixo.
- **Criptografia:** toda conexão passa por `db_crypto.connect()`. A chave de 32 bytes fica no cofre nativo; o app
  usa a forma raw do SQLCipher no dia a dia. Nunca logue a chave.

### Convenções de dados

- Dinheiro em **centavos** (`int`) no banco.
- Quantidades em **milionésimos** (`int`).
- Na CLI, valores em **reais** (`float`), porque é a interface para humanos e agentes.
- Alíquotas e percentuais em `Decimal` no cálculo; pesos como fração (`0.153` = 15,3%).
- Migrações em `migrations/NNN_*.sql`, com o número seguinte. **Nunca altere uma migração já aplicada**: quem
  atualiza perde a mudança.

## Testes

A suíte inteira roda isolada: base temporária, cofre falso e sem rede (`tests/conftest.py`). Ela não toca nos seus
dados.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

No Windows, use `.venv\Scripts\python.exe -m pytest`. A suíte é isolada e, com a base criptografada, leva alguns
minutos.

### Testes de navegador

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest tests/e2e
```

O servidor de teste usa a porta **8799**, então o Tabimoney do dia a dia pode ficar aberto na 8765. Os testes abrem
um Chromium de verdade e conferem menus, formulários, JavaScript e a tela do celular. Em caso de falha, capturas e
traces ficam em `test-results/` (ou nos *Artifacts* do GitHub Actions).

### O que todo mundo precisa saber antes de mudar código

- **Bug:** escreva primeiro o teste que reproduz a falha; ele deve falhar antes da correção e ficar na suíte para
  sempre.
- **Comportamento novo ou regra alterada:** teste automatizado no mesmo commit.
- **Base/criptografia:** `tests/test_db_crypto.py` cobre chave, migração, rollback, backup e restauração. Teste
  também uma falha de migração e uma restauração de backup plaintext antigo.
- **Tela ou formulário novo:** cubra também em `tests/e2e`.
- **Tela, aba ou recurso novo:** adicione exemplos fictícios em `app/demo.py`. `tests/test_demo.py` falha se alguma
  página aparecer vazia na demonstração.
- **Página nova:** `tests/test_paginas.py` já abre todas as páginas com a base vazia e com dados de exemplo.
- **Ferramenta MCP ou comando novo:** adicione a operação em `app/agente/operacoes.py`, a ferramenta em
  `app/mcp_server/ferramentas.py` (com tipo, descrição e `EQUIVALENTE_CLI`) e o comando em `app/cli.py`.
  `tests/test_mcp.py` confere o catálogo, as anotações, a paridade com a CLI e os roteiros.
- **Mudou o que o agente deve fazer?** Atualize o roteiro em `app/agente/roteiros/` e, se necessário, o contrato em
  `docs/agente-financeiro.md`.

## Documentação

- O índice público é [docs/README.md](README.md). Todo documento novo precisa entrar nele; `tests/test_docs.py`
  falha se uma página ficar fora do índice ou se um link relativo quebrar.
- O README é a porta de entrada comercial: visão geral, capturas, download e links. Detalhe técnico vai para os
  guias.
- `docs/agentes/` e `docs/agente-financeiro.md` são lidos em tempo de execução pelo servidor MCP. **Não mova esses
  arquivos sem atualizar** `app/mcp_server/servidor.py`, `packaging/tabimoney.spec` e os testes.
- `docs/versionamento.md` é o guia de manutenção e release.
- Textos da interface em português do Brasil.

## Demo

A demonstração é um casal fictício (Lucas e Marina) com dados em todas as telas. Ela usa um banco separado
(`demo.sqlite3`) e um cofre de senhas em memória. Nada do que você fizer na demo chega aos seus dados.

- Os exemplos ficam em `app/demo.py`.
- `tests/test_demo.py` abre todas as páginas na demo e falha se alguma aparecer vazia.
- Os testes de navegador usam os mesmos dados.
- Nunca copie dados reais para a demo.

## Gerar o executável

1. Rode `run.bat` uma vez para criar o `.venv`.
2. Rode `build.bat`.

O build leva de 1 a 3 minutos e gera:

- `dist\Tabimoney.exe` (cerca de 33 MB), que pode ser enviado direto;
- `dist\Manual-de-conexoes.html`, o manual ilustrado que ensina a criar as chaves do Meu Pluggy e da brapi;
- `dist\Tabimoney-<versão>.zip`, com o executável, o `LEIA-ME.txt` e o manual.

O `packaging\tabimoney.spec` define o que entra no executável: templates, arquivos estáticos, migrações, roteiros e
os documentos dos agentes. **Arquivo novo que o app leia em tempo de execução precisa entrar na lista `datas`.**

O PyInstaller só gera o app de Mac rodando em um Mac. Por isso, as três versões são geradas pelo GitHub Actions
(`.github/workflows/executaveis.yml`):

- a cada push na `main` que mexe no app, ele gera e testa Windows, Mac Apple Silicon e Mac Intel;
- numa tag `vX.Y.Z`, publica o Release com os três zips e o `SHA256SUMS.txt`;
- para rodar à mão: **Actions › Gerar executáveis › Run workflow**.

O passo a passo de release está em [Versionamento](versionamento.md).

## Branches e contribuição

| Branch | Para quê |
|---|---|
| `dev` | Onde o trabalho acontece. Todo push roda o workflow **Testes**. |
| `main` | O que está lançado. Só recebe merge da `dev` por PR, com o check **Testes ok** passando. |

Features maiores podem sair em uma branch própria (`feat/...`) com PR para a `dev`. O merge na `main` gera os
executáveis e, se a versão for nova, publica o Release.

## Compatibilidade

O app roda em Windows e macOS. Nada de caminho, comando ou cofre exclusivo de Windows fora de um
`if os.name == "nt"`:

- pasta de dados: `db.data_dir()`;
- segredos: `app/security.py`;
- abertura do navegador e encerramento do processo: `app/launch.py`.

Testes de plataforma (`tests/test_plataforma.py`) conferem os caminhos e os arquivos empacotados.

## Licença

Apache 2.0 (`LICENSE`). A marca Tabimoney fica fora da licença do código; veja o README.
