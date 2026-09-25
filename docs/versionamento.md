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

## Como lançar uma versão

1. Confira que `[Não lançado]` descreve tudo o que entra.
2. Escolha o número pelas regras acima e atualize `__version__` em `app/__init__.py`.
3. No `CHANGELOG.md`:
   - renomeie `[Não lançado]` para `[X.Y.Z] - AAAA-MM-DD` e crie uma seção `[Não lançado]` vazia acima dela;
   - atualize os links de comparação no fim do arquivo.
4. Teste abrindo o app com uma cópia da base (`financas backup`) e passando pelas telas principais.
5. Faça o commit `chore(release): vX.Y.Z` e crie a tag: `git tag -a vX.Y.Z -m "Tabimoney X.Y.Z"`.
6. Envie o commit e a tag (`git push --follow-tags`). O GitHub Actions gera e testa as versões Windows, Mac
   Apple Silicon e Mac Intel e publica o *Release* da tag com os três zips (app, `LEIA-ME.txt` e manual). É o
   link desse Release que vai para os amigos. Confira em *Actions* se as três passaram.
7. Opcional, no Windows: rode `build.bat`, abra o `dist\Tabimoney.exe`, clique de novo (tem que reiniciar) e
   encerre pelo menu.

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
