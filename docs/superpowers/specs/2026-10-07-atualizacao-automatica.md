# Atualização com um clique

Data: 2026-10-07 · Estado: **fases 0 e 1 implementadas** (Windows), em `[Não lançado]`. Decisões da §13: vigia
(C), base restaurada na reversão, só SHA-256 por enquanto, Mac depois, sem aba nova ao reabrir, manual não é
trocado.

## 1. Objetivo

Hoje o aviso de versão nova (sino › "Tabimoney X disponível") tem um botão **Baixar** que abre o zip do Release no
navegador. Daí em diante o trabalho é de quem usa: extrair o zip, achar o executável antigo, encerrar o app,
substituir o arquivo e abrir de novo. No Mac ainda tem o aviso da Apple. Para os amigos que usam o app, essa é a
parte que falha.

A proposta é trocar esse botão por **Atualizar agora**: o app baixa a versão nova, confere o arquivo, faz backup da
base, coloca o executável novo no lugar do antigo e reabre sozinho. A página mostra o progresso e recarrega na
versão nova. Se algo der errado no meio do caminho, o app volta para a versão anterior e avisa.

**Resposta curta à pergunta "dá para fazer?": dá, nas duas plataformas**, sem instalador e sem assinatura paga. O
mecanismo é o mesmo que ferramentas como `go-selfupdate`/`minio/selfupdate` usam: renomear o executável que está
rodando e pôr o novo no nome dele. As ressalvas estão na §6 (casos em que o app volta para o botão "Baixar") e na
§8 (segurança).

### O que não muda

- A pasta dos dados (`db.data_dir()`), o cofre de segredos e a base: atualizar nunca mexe neles, só no executável.
- O caminho do executável: o novo fica **no mesmo lugar e com o mesmo nome**. Com isso, os atalhos, as conexões com
  a IA (`instalar.reparar()`) e a pasta da IA continuam valendo sem passo extra.
- O aviso continua opcional (Configurações › Atualizações) e nada é baixado sem o clique.
- Quem roda pelo código (`run.bat`, não `frozen`) continua com a mensagem de `git pull`.

### Critérios de sucesso

| Critério | Meta |
|---|---|
| Cliques do aviso até a versão nova aberta | **2** (Atualizar agora → confirmar) |
| Tempo total com internet comum (zip de ~40 MB) | **< 1 min** |
| Atualização interrompida (queda de luz, antivírus, erro na versão nova) | app **abre** na versão antiga ou na nova, nunca fica sem executável |
| Dados após uma reversão | base igual ao backup feito antes da troca |
| Primeira abertura da versão nova no Mac | **sem** o aviso "Abrir mesmo assim" (ver §6.2) |

## 2. Como funciona hoje

| Peça | Onde | O que faz |
|---|---|---|
| Verificação | `app/services/updates.py` | A cada 12 h consulta `releases/latest` do GitHub e guarda `version`, `url`, `download_url` (o zip da plataforma) |
| Aviso | `app/templates/base.html` (popover do sino) | "Baixar" (link do zip), "Novidades" e "Dispensar" |
| Abrir/reiniciar | `app/launch.py` › `open_app()` | Encerra o servidor aberto (token do `tabimoney.lock`), sobe `exe --servidor` desacoplado e abre o navegador |
| Trava | `data_dir()/tabimoney.lock` | `pid`, `token`, `version`, `exe` (caminho do executável) do servidor que está rodando |
| Backup | `db.create_backup()` | Cópia consistente da base em `data_dir()/backups/` |
| Release | `.github/workflows/executaveis.yml` | Três zips: `Tabimoney-X.Y.Z-windows.zip` (`Tabimoney.exe` de arquivo único), `…-mac-apple-silicon.zip` e `…-mac-intel.zip` (`Tabimoney.app` em pasta), cada um com `LEIA-ME.txt` e manual |

Quase tudo o que a atualização automática precisa já existe: saber a versão nova e o zip certo, saber qual
executável está rodando (`lock["exe"]`), encerrar o servidor com segurança e fazer backup. O que falta é baixar,
conferir, trocar o arquivo e reiniciar.

## 3. Por que a troca é possível

| Plataforma | Fato que permite a troca | Consequência |
|---|---|---|
| Windows | Um `.exe` em execução **não pode ser apagado nem sobrescrito, mas pode ser renomeado** na mesma pasta. | Renomeia `Tabimoney.exe` → `Tabimoney.anterior.exe` com o app rodando e põe o novo no nome livre. Os processos antigos continuam rodando do arquivo renomeado. |
| Mac | O `.app` é uma pasta. Renomear ou mover uma pasta não afeta processos que já estão rodando a partir dela (semântica Unix). | Mesma troca: `Tabimoney.app` → `Tabimoney.anterior.app`, o novo entra no lugar. |
| Ambas | O arquivo baixado pelo próprio app (via `httpx`) **não recebe a marca de "veio da internet"** (Mark-of-the-Web no Windows, `com.apple.quarantine` no Mac). | Sem SmartScreen e sem Gatekeeper na versão nova. Isso melhora muito a experiência, mas a conferência de integridade passa a ser responsabilidade nossa (§8). |

## 4. Alternativas consideradas

| | Como funciona | Prós | Contras |
|---|---|---|---|
| **A. O servidor troca e reinicia** | O servidor antigo baixa, renomeia a si mesmo, põe o novo no lugar e executa o novo, que encerra o antigo (`stop_previous`). | Simples, pouco código novo. | Se a versão nova não subir, ninguém desfaz a troca. O app fica quebrado até a pessoa baixar à mão. |
| **B. O executável novo instala a si mesmo** (a ideia original) | O antigo baixa e roda o novo a partir de uma pasta temporária com `--instalar-sobre <antigo>`. O novo espera o antigo sair, se copia por cima e reabre. | É o modelo mental natural: "o novo acha o antigo e substitui". | A lógica de instalação e de reversão roda no código **novo**, que ainda não foi testado nesta máquina. Se ele tiver um bug que impede subir, também pode ter um na reversão. |
| **C. Troca pelo app atual, vigia pela versão antiga** *(recomendada)* | Como em A, mas antes de reiniciar o app antigo dispara um **vigia**: o próprio executável antigo, com `--vigiar-atualizacao`. Ele espera a versão nova responder e, se ela não subir em 2 min, desfaz a troca e restaura a base. | A reversão roda em código que já está provado nesta máquina. O código novo só precisa subir. | Um processo a mais e um pequeno contrato entre versões (§10). |
| D. Biblioteca ou instalador pronto (Squirrel, MSIX, Sparkle, `tufup`) | Instalador com atualizador próprio. | Resolvido por terceiros. | Exige instalador e, no caso de MSIX e Sparkle, assinatura de código. Muda a forma de distribuir ("extraia e dê dois cliques"). `PyUpdater` foi abandonado. `tufup` é viável, mas o esquema TUF é grande demais para um app de uma pessoa. |

**Recomendação: C.** Ela custa pouco mais que A e é a única em que um bug na versão nova não deixa o app quebrado.
A ideia de B ("o novo encontra o antigo") continua valendo do ponto de vista de quem usa. Só a responsabilidade
fica com quem já está provado nesta máquina.

## 5. Fluxo recomendado

```mermaid
sequenceDiagram
    actor U as Pessoa
    participant S as Servidor antigo (vX)
    participant G as GitHub Release
    participant V as Vigia (exe antigo)
    participant N as Tabimoney novo (vY)

    U->>S: Atualizar agora (POST /atualizacao/instalar)
    S->>G: baixa o zip e o SHA256SUMS.txt
    S->>S: confere o hash, extrai só o executável, roda "novo --versao" = vY?
    S->>S: backup da base; grava atualizacao.json
    S->>S: copia o novo para o lado do antigo; renomeia antigo → .anterior e novo → nome original
    S->>V: inicia ".anterior --vigiar-atualizacao" (desacoplado)
    S->>S: encerra
    V->>N: abre o executável no caminho original (--apos-atualizacao)
    N->>N: migrações, servidor sobe, trava com version = vY
    V->>V: espera porta aberta e trava com vY (até 120 s)
    alt subiu
        V->>V: marca "concluida" e sai
        N->>N: na próxima limpeza, apaga .anterior e a pasta de preparo
    else não subiu
        V->>N: encerra (ou finaliza o processo)
        V->>V: desfaz a troca, restaura a base do backup
        V->>V: abre a versão antiga e marca "revertida"
    end
    U->>U: a página de progresso recarrega na versão em uso
```

### 5.1 Passo a passo (servidor antigo)

Roda numa thread de fundo. O estado fica em memória para a página de progresso e em `data_dir()/atualizacao.json`
para sobreviver ao reinício.

1. **Pré-checagens** (antes de baixar qualquer coisa; se alguma falhar, cai no botão "Baixar" de hoje com o motivo):
   app `frozen`, fora da demo, plataforma com zip no Release, versão do Release **maior** que a atual, pasta do
   executável gravável (cria e apaga um arquivo de teste), executável fora de pasta temporária ou translocada
   (§6), espaço livre de pelo menos 3× o tamanho do zip.
2. **Baixar** o zip e o `SHA256SUMS.txt` do mesmo Release para `data_dir()/atualizacoes/<versão>/`, em streaming,
   com progresso (o `Content-Length`). Só aceita URLs de `github.com` e `*.githubusercontent.com` (confere o host
   final depois dos redirecionamentos) e limita o tamanho a 300 MB.
3. **Conferir** o SHA-256 do zip com a linha correspondente do `SHA256SUMS.txt`. Se não bater, apaga e para.
4. **Extrair só o executável**: `Tabimoney.exe` no Windows, `Tabimoney.app/**` no Mac (com `ditto -x -k`, que
   preserva links e permissões). Ignora outros nomes e rejeita caminhos com `..` (zip-slip).
5. **Testar** o executável extraído: `novo --versao` precisa responder exatamente a versão esperada em até 60 s
   (o exe de arquivo único leva alguns segundos para extrair). Isso pega arquivo corrompido, executável errado e
   antivírus que apagou o arquivo.
6. **Backup** da base com `db.create_backup()`, igual ao que o servidor MCP faz. O caminho vai para o marcador.
7. **Copiar para o lado** do executável atual com nome temporário: `Tabimoney.novo.exe` ou `Tabimoney.novo.app`.
   Copiar para a mesma pasta antes garante que os renomes do passo 9 fiquem no mesmo disco e sejam instantâneos.
   A pasta de preparo pode estar em outro disco, por exemplo com o exe em `D:`.
8. **Gravar o marcador** `atualizacao.json` com `estado: "trocando"` (formato na §10).
9. **Trocar** com dois renomes: atual → `Tabimoney.anterior.exe`; `Tabimoney.novo.exe` → `Tabimoney.exe`. Cada
   renome tenta de novo por até 10 s, porque antivírus e OneDrive seguram arquivos por instantes. Se o segundo
   renome falhar, desfaz o primeiro e para: **nunca fica sem `Tabimoney.exe`**.
10. **Disparar o vigia**: `Tabimoney.anterior.exe --vigiar-atualizacao`, desacoplado como em `open_app()`
    (`CREATE_NO_WINDOW` no Windows, `start_new_session` no Mac, `PYINSTALLER_RESET_ENVIRONMENT=1`).
11. **Encerrar** o servidor antigo (`_schedule_shutdown`).

### 5.2 Vigia (código da versão antiga)

1. Espera a porta 8765 fechar (até 30 s; se não fechar, finaliza o pid da trava).
2. Abre o executável no caminho original com `--apos-atualizacao`: o `open_app()` normal da versão nova, que já
   sincroniza a pasta da IA e repara as conexões, mas **sem abrir aba nova** no navegador, porque a página de
   progresso já está aberta.
3. Espera até 120 s pela porta aberta **e** pela trava com `version` igual à nova.
4. **Sucesso:** marca `concluida` e sai.
5. **Falha:** encerra a versão nova (token da trava ou `_kill`), renomeia `Tabimoney.exe` → `Tabimoney.falhou.exe`
   e `Tabimoney.anterior.exe` → `Tabimoney.exe`, restaura a base do backup (substitui o arquivo e apaga o
   `-journal` que sobrar), abre a versão antiga e marca `revertida` com o motivo (último trecho do log da versão
   nova).

### 5.3 Versão nova, depois de subir

- Na inicialização e na rotina de 30 min de `updates.scheduler`, tenta apagar `Tabimoney.anterior.*`,
  `Tabimoney.falhou.*` e a pasta de preparo. No Windows, o `.anterior.exe` fica preso enquanto houver processo
  rodando dele (o vigia, ou o servidor MCP que um agente de IA abriu antes da troca). Por isso a limpeza só tenta e
  deixa para a próxima vez.
- Com o marcador em `concluida`, mostra uma vez a mensagem "Atualizado para o Tabimoney Y" com o link de Novidades.
  Se houver agente de IA conectado, acrescenta: "Reinicie o seu agente de IA para ele usar a versão nova."

## 6. Detalhes por plataforma

### 6.1 Windows

| Situação | O que acontece |
|---|---|
| Exe numa pasta normal (Documentos, Desktop, `C:\Tabimoney`) | Atualiza. |
| Exe rodando de dentro do zip ou de `%TEMP%` | Pré-checagem falha: "Mova o Tabimoney.exe para uma pasta sua (ex.: Documentos) e abra de lá." |
| Exe em `Program Files` (sem permissão de escrita) | Pré-checagem falha e o app volta ao "Baixar". Elevar privilégio (UAC) fica fora do escopo. |
| Pasta sincronizada pelo OneDrive | Funciona na maioria das vezes. Os renomes tentam de novo por alguns segundos e, se falharem, nada mudou. |
| Antivírus apaga ou bloqueia o exe novo (falso positivo comum em PyInstaller) | O teste `--versao` (passo 5) falha antes da troca: "O antivírus bloqueou o arquivo novo. Baixe manualmente." |
| Agente de IA com o servidor MCP aberto | Continua rodando a versão antiga (o arquivo renomeado) até o agente reiniciar. Na próxima vez, o agente abre a nova, no mesmo caminho. |
| SmartScreen | Não aparece: o download do app não leva a marca da internet. |

O exe é de **arquivo único**: o processo do servidor é o bootloader mais um filho, os dois rodando do mesmo
`Tabimoney.exe`. Os dois continuam funcionando depois do renome, porque o Windows mantém o arquivo mapeado.

### 6.2 Mac

| Situação | O que acontece |
|---|---|
| `Tabimoney.app` em `/Applications` (usuário administrador) | Atualiza. A raiz do bundle é `Path(sys.executable).parents[2]`. |
| Usuário padrão sem permissão em `/Applications` | Pré-checagem de escrita falha e o app volta ao "Baixar". |
| **App Translocation** (app aberto direto de Downloads, ainda em quarentena) | `sys.executable` contém `/AppTranslocation/`: o app roda de uma cópia só leitura. Pré-checagem falha: "Arraste o Tabimoney para Aplicativos e abra de lá." |
| Gatekeeper | Não aparece na versão nova: sem `com.apple.quarantine`. O PyInstaller já assina ad-hoc, o que o Apple Silicon exige. Como verificação extra, vale `codesign --verify --deep` no passo 5. |
| Porta-chaves | **Ressalva conhecida.** A permissão "Sempre Permitir" fica presa à assinatura ad-hoc, que muda a cada build. Depois de cada atualização (manual ou automática), o Mac pergunta de novo. Corrigir isso exige uma identidade de assinatura estável e fica fora do escopo. A tela de "Atualizado" avisa. |
| Build Intel em Mac com chip Apple (Rosetta) | `platform_suffix()` já escolhe o zip de Apple Silicon, então a atualização também corrige a arquitetura. |

A cópia para o lado (passo 7) usa `ditto origem destino`, não `shutil.copytree`, para preservar links simbólicos,
permissões e a assinatura do bundle.

## 7. Interface

### 7.1 Aviso (popover do sino)

| Situação | Botões |
|---|---|
| Pode atualizar sozinho | **Atualizar agora** (primário) · Novidades · Dispensar · link pequeno "baixar manualmente" |
| Pré-checagem falhou | **Baixar** (como hoje) · Novidades · Dispensar, com o motivo numa linha (ex.: "Mova o app para uma pasta sua para atualizar com um clique.") |
| Rodando pelo código | Como hoje (`git pull`) |

"Atualizar agora" é um formulário POST com CSRF e `data-confirm`: *"Atualizar para o Tabimoney Y? O app baixa a
versão nova (N MB), faz um backup dos seus dados e reinicia. Leva cerca de um minuto."*

### 7.2 Página de progresso (`/atualizacao`)

Uma tela simples com o mascote e uma lista de etapas:

1. Baixando… 45% (18 de 40 MB)
2. Conferindo o arquivo
3. Fazendo backup dos seus dados
4. Reiniciando o Tabimoney
5. Pronto: abre a Visão geral com a mensagem de atualizado

A página consulta `GET /atualizacao/estado` (JSON) a cada segundo. Enquanto o servidor reinicia, a consulta falha
e a página mostra "Reiniciando…" e continua tentando. Quem responde depois é a versão nova (ou a antiga, se houve
reversão), lendo o mesmo `atualizacao.json`. Depois de 3 min sem resposta, mostra o que fazer: "Abra o Tabimoney
de novo pelo atalho."

**CSP:** hoje é `connect-src 'none'`, o que bloqueia o `fetch`. Só esta página recebe `connect-src 'self'`. Um
`<meta refresh>` não serve: com o servidor fora do ar, o navegador mostra a página de erro e para de recarregar.

### 7.3 Erros e reversão

| Quando | Mensagem | Estado do app |
|---|---|---|
| Antes da troca (download, hash, teste) | "Não deu para atualizar: {motivo}. Nada mudou." + Baixar manualmente | Versão antiga, rodando |
| Versão nova não subiu (reversão) | "A versão Y não abriu neste computador. Voltamos para a X e seus dados estão como antes. Baixe manualmente ou tente mais tarde." | Versão antiga, base restaurada |
| Reversão também falhou (raro) | O vigia grava o motivo no marcador e no log. Ao abrir, a mensagem explica e aponta o backup. | Ver §9 |

Depois de uma reversão, "Atualizar agora" some **para aquela versão** e fica só "Baixar". Assim o app não entra
num laço de tentativas.

### 7.4 Configurações › Atualizações

Acrescenta a última tentativa ("Atualizado da 0.16.0 para a 0.17.0 em 07/10 às 14:32" ou o motivo da falha).
Fica para depois: "Baixar em segundo plano quando houver versão nova", para o clique só trocar e reiniciar.

## 8. Segurança e integridade

- **Mesma confiança do download manual.** O app não é assinado, então o download pelo navegador também não tem
  verificação além do HTTPS do GitHub. A atualização automática não piora isso, mas tira o SmartScreen e o
  Gatekeeper do caminho, que eram o último "tem certeza?". Por isso a conferência é obrigatória.
- **Fase 1: SHA-256.** O workflow passa a publicar `SHA256SUMS.txt` no Release (uma linha por zip, gerada no job
  `release`). Isso pega download corrompido ou truncado e troca de arquivo no caminho. Não protege contra quem
  controle a conta do GitHub, porque o hash vem do mesmo Release.
- **Opcional, depois: assinatura Ed25519 (estilo minisign).** A chave pública fica embutida no app. A privada
  fica **fora** do GitHub: o mantenedor assina o `SHA256SUMS.txt` localmente depois que o CI publica e sobe o
  `.minisig`. Uma chave guardada em *secret* do Actions protege pouco contra conta comprometida, porque quem tem a
  conta consegue rodar workflow. Custo: um passo manual em cada lançamento. Decisão em aberto (§13).
- **Hosts permitidos:** só `github.com` e `*.githubusercontent.com`, também depois dos redirecionamentos. O
  `download_url` vem da API do GitHub, mas o app confere de novo antes de usar.
- **Endpoints:** `POST /atualizacao/instalar` exige CSRF e já está protegido pelo `LocalOnlyMiddleware`. Na demo,
  `_demo_blocked`. Não exige token extra: quem consegue fazer POST local com CSRF já controla o app.
- **Sem dados do usuário na rede:** os pedidos são os mesmos da verificação de hoje (API do GitHub e o download),
  com o `User-Agent` `Tabimoney/X`.
- **Não vira operação de agente.** Não entra no MCP nem na CLI na fase 1. Uma IA não deve trocar o executável que
  ela mesma usa no meio de uma conversa. Por isso a regra de "operação nova ganha MCP e CLI" do `AGENTS.md` não se
  aplica.

## 9. Dados

- **Backup sempre** antes da troca (passo 6), guardado em `backups/` como os demais.
- **Migrações:** a versão nova aplica as suas ao subir (`init_db`). Se o vigia reverter, a base volta para o
  backup, que está no esquema antigo. Caso contrário, a versão antiga rodaria numa base com migrações que ela não
  conhece. O `validate_database` recusa isso na restauração manual, mas o `init_db` não detecta.
- **Janela de perda na reversão:** o que for gravado entre o backup e a reversão (no máximo ~2 min, só por agente
  de IA via MCP) se perde. Aceitável, porque a reversão é rara, e documentado na mensagem.
- **Reversão que falha:** a versão antiga já está de volta no nome original antes de a base ser restaurada. No pior
  caso, o app abre na versão antiga com a base migrada (a mesma situação de hoje quando alguém volta de versão à
  mão), e a mensagem aponta o backup para restaurar em Configurações.
- **Downgrade nunca:** só atualiza se a versão do Release for maior que a atual (`parse_version`).

## 10. Contrato entre versões

A troca envolve duas versões: a antiga baixa, troca e vigia; a nova sobe e limpa. O que uma espera da outra precisa
ficar estável, porque a 0.17 vai atualizar para versões que ainda não existem. O contrato é pequeno de propósito:

| Item | Quem escreve | Quem lê | Regra |
|---|---|---|---|
| `exe --versao` | qualquer | versão antiga (passo 5) | Já existe. Imprime só a versão. |
| `exe --apos-atualizacao` | — | versão nova | Abre como `open_app()`, sem abrir aba nova. Versão que não conhece a flag deve tratá-la como abertura normal (ver abaixo). |
| `exe --vigiar-atualizacao` | — | versão antiga (ela mesma) | Interno: a mesma versão escreve e lê. |
| `tabimoney.lock` | servidor | vigia | Já existe. O vigia usa `version` e `pid`. |
| `atualizacao.json` | antiga e vigia | nova e antiga | Campos abaixo. Campos novos podem entrar; os existentes não mudam de sentido. |
| Nomes `Tabimoney.anterior.*`, `Tabimoney.novo.*`, `Tabimoney.falhou.*` | antiga e vigia | nova (limpeza) | Fixos. |

```json
{
  "de": "0.17.0", "para": "0.18.0",
  "exe": "C:\\Users\\…\\Tabimoney.exe",
  "anterior": "C:\\Users\\…\\Tabimoney.anterior.exe",
  "backup": "…\\backups\\financas-backup-20261007-143201.sqlite3",
  "estado": "baixando | conferindo | preparando | trocando | reiniciando | concluida | revertida | falhou",
  "progresso": 0.45, "motivo": null,
  "iniciado_em": "2026-10-07T14:31:50-03:00", "atualizado_em": "…"
}
```

**Compatibilidade da flag:** hoje, `main()` em `launch.py` cai em `open_app()` para qualquer argumento que não
conhece. Isso já serve de rede de segurança: se uma versão futura deixar de entender `--apos-atualizacao`, ela
abre normalmente e só abre uma aba a mais.

**A primeira atualização é manual.** Quem está na 0.16 precisa baixar a versão com este recurso à mão. Só dela
para a seguinte o botão funciona. As notas daquele Release devem dizer isso.

## 11. Mudanças no código

| Arquivo | Mudança |
|---|---|
| `app/services/atualizador.py` (novo) | Pré-checagens, download com progresso, hash, extração, teste `--versao`, troca e reversão (funções puras sobre caminhos, para testar com arquivos falsos), marcador e limpeza. `updates.py` continua só verificando. |
| `app/launch.py` | `--vigiar-atualizacao` e `--apos-atualizacao` (o `open_app(abrir_navegador=False)`); limpeza dos `.anterior` ao abrir. |
| `app/services/updates.py` | `status()` passa a dizer se dá para atualizar com um clique (`auto: bool`, `motivo`) e o tamanho do zip (`size` do asset). |
| `app/main.py` | `POST /atualizacao/instalar`, `GET /atualizacao` (página), `GET /atualizacao/estado` (JSON), CSP própria da página, mensagem de "Atualizado" ou "Revertido" lida do marcador. |
| `app/templates/base.html`, `atualizacao.html` (novo), `settings.html` | Botões do aviso, página de progresso, última tentativa. |
| `app/static/app.js` | Consulta do estado na página de progresso. |
| `.github/workflows/executaveis.yml` | `SHA256SUMS.txt` no Release e o teste de atualização de verdade (§12). |
| `packaging/LEIA-ME.txt`, `LEIA-ME-mac.txt` | "Atualizar: clique em Atualizar agora no aviso. Se não aparecer, substitua o arquivo como antes." |
| `docs/versionamento.md` | O `SHA256SUMS.txt` e o contrato da §10, que não pode quebrar entre versões. |
| `CHANGELOG.md` | Entrada em `[Não lançado]`. É funcionalidade nova, então sobe a MENOR. |
| `app/demo.py` | Nada a mostrar: na demo o aviso de versão já fica escondido e `/atualizacao` redireciona. Confirmar se o `test_demo.py` aceita uma página que redireciona sem atualização em andamento, ou se ela entra na lista de exceções. |
| `packaging/tabimoney.spec` | Nada: o template novo já entra pela pasta `app/templates`. |

## 12. Testes

- **Unidade** (`tests/test_atualizador.py`, sem rede: `httpx` com transporte falso):
  hash que não bate; host fora da lista; zip com `..`; zip sem o executável; tamanho acima do limite; pré-checagens
  (pasta sem escrita, caminho em `%TEMP%`, `/AppTranslocation/`, demo, não `frozen`); troca em `tmp_path` com
  arquivos falsos, incluindo falha no segundo renome (tem que desfazer o primeiro); vigia com funções injetadas
  ("subiu", "não subiu" → reverte arquivos e base); limpeza que tolera arquivo preso; versão igual ou menor
  recusada.
- **Telas:** `POST /atualizacao/instalar` exige CSRF, é bloqueado na demo e recusado fora do `frozen`;
  `/atualizacao/estado` devolve cada estado; o aviso mostra "Atualizar agora" ou "Baixar" conforme `auto`.
- **Navegador (`tests/e2e`):** a página de progresso com um servidor de teste que avança os estados, cai e volta
  (confere a mensagem "Reiniciando…" e o redirecionamento final).
- **Executável de verdade (CI, `executaveis.yml`):** depois do teste rápido de hoje, copia o exe gerado para
  `antigo/`, sobe um servidor HTTP local com um "Release" falso (zip do próprio build + `SHA256SUMS.txt`) e roda a
  atualização ponta a ponta. A URL da API vem de uma variável de ambiente aceita **só** se apontar para
  `127.0.0.1`. Confere: o exe foi trocado, o servidor voltou, a base tem backup e o `.anterior` some na limpeza.
  Um segundo cenário usa um "novo" que sai com erro ao subir e confere a reversão. Os dois rodam em Windows e Mac.

## 13. Decisões em aberto

1. **Alternativa C (vigia)?** Ou A, mais simples, aceitando que um bug de inicialização na versão nova obriga a
   baixar à mão.
2. **Restaurar a base na reversão automaticamente?** Recomendo sim (§9), aceitando perder o que um agente de IA
   gravou na janela de ~2 min.
3. **Assinatura Ed25519 agora ou depois?** Recomendo começar só com SHA-256 e decidir a assinatura antes da `1.0.0`
   (primeira versão pública para amigos).
4. **Mac junto com o Windows?** Recomendo Windows primeiro (o caso mais comum entre os amigos e o mais simples de
   testar daqui). O Mac entra na versão seguinte, depois de rodar no CI.
5. **Aba nova ao reabrir?** Recomendo não abrir (`--apos-atualizacao`), porque a página de progresso já está
   aberta. Se a pessoa fechou a aba, abre pelo atalho como sempre.
6. **Atualizar também o `Manual-de-conexoes.html`** que estiver ao lado do executável? Pequeno ganho e um arquivo a
   mais para trocar. Recomendo não.

## 14. Fases

| Fase | Entrega | Tamanho |
|---|---|---|
| 0 | `SHA256SUMS.txt` no Release. Pode sair já na próxima versão, mesmo sem o resto. | Pequeno |
| 1 | Windows completo: botão, progresso, troca, vigia e reversão, testes e teste de executável no CI. | Médio |
| 2 | Mac (`ditto`, translocação, permissão em `/Applications`, aviso do Porta-chaves). | Pequeno a médio |
| 3 (opcional) | Download em segundo plano, assinatura Ed25519, histórico de atualizações em Configurações. | — |
