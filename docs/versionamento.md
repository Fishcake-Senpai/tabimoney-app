# Versionamento e lançamentos

Este guia é para quem mantém o Tabimoney e publica versões, inclusive agentes de IA que mexem no código.

## Onde fica a versão

| Onde | O quê |
|---|---|
| `app/__init__.py` | `__version__`, a **única** fonte da versão |
| `CHANGELOG.md` | O que mudou em cada versão, para quem usa |
| Tag do git | `vX.Y.Z` no commit do lançamento |
| App | Rodapé do menu lateral, `financas --version` e a janela do `run.bat` |

## Regras de numeração ([SemVer](https://semver.org/lang/pt-BR/))

`MAIOR.MENOR.CORREÇÃO`, por exemplo `0.9.0`.

- **CORREÇÃO** (`0.9.1`): corrige um erro sem mudar comportamento esperado nem formato de dados.
- **MENOR** (`0.10.0`): funcionalidade nova, tela nova, comando novo, migração nova da base.
- **MAIOR** (`1.0.0`, `2.0.0`): quebra algo de quem já usa, como:
  - um comando da CLI ou um campo do contrato com agentes (`docs/agente-financeiro.md`) removido ou renomeado;
  - uma base antiga que deixa de abrir sem passo manual.

Enquanto a versão começar com `0.`, o projeto está em desenvolvimento inicial e mudanças que quebram sobem só a
MENOR. A `1.0.0` marca a primeira versão pública estável para amigos baixarem.

## O changelog

- Toda mudança entra na seção **`[Não lançado]`** do `CHANGELOG.md` no mesmo commit que a implementa.
- Use os grupos do Keep a Changelog: **Adicionado**, **Alterado**, **Descontinuado**, **Removido**, **Corrigido**, **Segurança**.
- Escreva para quem usa o app, em português, uma linha por mudança. Detalhe técnico vai no commit.

## Migrações da base

- Mudança no esquema = arquivo novo `migrations/NNN_descricao.sql`, com o número seguinte.
- Nunca altere uma migração que já foi lançada: quem atualizar perde a mudança.
- As migrações rodam sozinhas ao abrir o app, e a restauração de backup recusa bases de versão mais nova.

## Branches e testes

| Branch | Para quê |
|---|---|
| `dev` | Onde o trabalho acontece. Todo push roda o workflow **Testes**. Features maiores podem sair numa branch própria (`feat/...`) com PR para a `dev`. |
| `main` | O que está lançado ou prestes a ser lançado. Só recebe merge da `dev` por PR, com o check **Testes ok** passando. |

O workflow **Testes** (`.github/workflows/testes.yml`) roda em todo push na `dev` e em todo PR:

- `pytest` em Windows e Mac (unidade, telas pelo TestClient, CLI, plataforma);
- testes de navegador (`tests/e2e`, Playwright com Chromium) no Linux; nas falhas, capturas e traces ficam em
  *Artifacts* (`resultados-e2e`; abra o trace em <https://trace.playwright.dev>);
- **Testes ok**, que só passa se os dois anteriores passaram. É o check que a regra da `main` exige.

### Regra da `main` (uma vez, no GitHub)

Em *Settings › Rules › Rulesets › New branch ruleset*:

1. **Ruleset name:** `main protegida` · **Enforcement status:** Active.
2. **Target branches:** *Add target › Include default branch* (a `main`).
3. Marque **Restrict deletions** e **Block force pushes**.
4. Marque **Require a pull request before merging**, com *Required approvals* = 0 (quem mantém é uma pessoa só).
5. Marque **Require status checks to pass** e adicione o check **Testes ok** (ele só aparece na lista depois de
   rodar uma vez, então faça o primeiro push na `dev` antes). Marque também *Require branches to be up to date
   before merging*.
6. Em *Bypass list*, deixe vazio. Numa emergência dá para desativar a regra por alguns minutos.

## Como lançar uma versão

O lançamento acontece no merge da `dev` na `main`. Quem decide é o número da versão: se `__version__` ainda não
tem tag, o merge publica o Release; se já tem, o merge só gera os executáveis (ficam em *Actions › Artifacts*).

1. Na `dev`, confira que `[Não lançado]` descreve tudo o que entra.
2. Escolha o número pelas regras acima e atualize `__version__` em `app/__init__.py`.
3. No `CHANGELOG.md`:
   - renomeie `[Não lançado]` para `[X.Y.Z] - AAAA-MM-DD` e crie uma seção `[Não lançado]` vazia acima dela;
   - atualize os links de comparação no fim do arquivo.
4. Teste abrindo o app com uma cópia da base (`financas backup`) e passando pelas telas principais.
5. Faça o commit `chore(release): vX.Y.Z` na `dev` e envie (`git push`). Espere o **Testes** ficar verde.
6. Abra o PR `dev → main` (título `Tabimoney X.Y.Z`) e faça o merge quando o **Testes ok** passar. Use *Create
   a merge commit*, para a `dev` e a `main` continuarem com o mesmo histórico.
7. O workflow **Gerar executáveis** confere que o CHANGELOG tem a seção `## [X.Y.Z]`, gera e testa as versões
   Windows, Mac Apple Silicon e Mac Intel (no Windows, inclusive a atualização com um clique e a reversão, de ponta a
   ponta, com um Release falso: leva uns 3 minutos),
   cria a tag `vX.Y.Z` e publica o *Release* com os três zips (app, `LEIA-ME.txt` e manual) e o
   `SHA256SUMS.txt`. É o link desse Release que vai para os amigos. Não crie a tag à mão.
8. Opcional, no Windows: rode `build.bat`, abra o `dist\Tabimoney.exe`, clique de novo (tem que reiniciar) e
   encerre pelo menu.

Merge na `main` sem subir a versão (uma correção de documentação, por exemplo) não publica nada novo: quem usa o
app só recebe aviso de versão nova quando há Release.

## Atualização com um clique: o contrato entre versões

No Windows, o botão **Atualizar agora** (`app/services/atualizador.py`) envolve duas versões: a instalada baixa,
troca o executável e vigia; a nova sobe e limpa. Por isso estas peças não podem mudar de sentido entre versões
(detalhes na §10 de `docs/superpowers/specs/2026-10-07-atualizacao-automatica.md`):

- os nomes dos assets do Release (`Tabimoney-X.Y.Z-windows.zip`, com o `Tabimoney.exe` na raiz) e o
  `SHA256SUMS.txt` no formato do `sha256sum`;
- as flags `--versao`, `--apos-atualizacao` e `--vigiar-atualizacao`;
- a rota `GET /atualizacao/estado` e o arquivo `atualizacao.json` na pasta de dados (campos novos podem entrar);
- os nomes `Tabimoney.anterior.exe`, `Tabimoney.novo.exe` e `Tabimoney.falhou.exe`.

Um Release sem `SHA256SUMS.txt` faz o app voltar ao botão Baixar.

## Antes de tornar o repositório público

- **Licença:** Apache 2.0 (`LICENSE`), com a marca fora da licença (seção Licença do README).
- **Dados pessoais:** confira que nada pessoal está versionado. A base, os backups e os segredos ficam fora do
  repositório (`%LOCALAPPDATA%`, Credential Manager e `.gitignore`), mas revise exemplos, capturas de tela e o
  histórico do git:
  `git log -p | findstr /i "cpf conta saldo"` e busque seu nome, empresa e números de conta.
- **Links:** os rodapés do `CHANGELOG.md` apontam para `Fishcake-Senpai/tabimoney-app`; eles só funcionam depois que as tags `vX.Y.Z` existirem.
- **README para quem baixa:** requisitos (Windows, Python 3.11+), como rodar (`run.bat`), como conectar o Open
  Finance e o aviso de que os dados ficam só na máquina.
- **Fonte e marca:** a Inter é distribuída sob a SIL Open Font License (`app/static/fonts/LICENSE-Inter.txt`).
  A marca Tabimoney (`app/static/brand/`) é do autor e fica fora da licença; o manual de marca (`manual_marca/`) não é versionado.
