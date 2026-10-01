# Tabimoney — finanças sérias (mais ou menos)

Aplicação local de finanças pessoais. A identidade visual (logo, mascote, paleta verde sobre fundo escuro e a fonte Inter) segue um manual de marca que não é distribuído com o código. Os ícones do app e do navegador ficam em `app/static/brand/`, e a fonte Inter em `app/static/fonts/`, servida localmente (licença OFL em `LICENSE-Inter.txt`).

Aplicativo pessoal para acompanhar saldos dos bancos (Nubank, Itaú…), posições de investimento e cotações diárias. A interface abre no navegador, mas o servidor aceita conexões somente em `127.0.0.1`. O banco SQLite fica no perfil local do Windows; não há GitHub, hospedagem ou cópia de dados na nuvem.

As chamadas autorizadas do Open Finance e da fonte de preços saem desta máquina para os provedores correspondentes. O banco e os dados normalizados permanecem locais.

## Iniciar

Há dois jeitos de usar: o **executável**, para quem só quer usar o app, e o **código**, para quem vai mexer
nele. Os dois guardam os dados no mesmo lugar e funcionam do mesmo jeito. Funciona no **Windows** e no **Mac**
(chip Apple ou Intel). Os executáveis de cada versão ficam nos
[Releases](https://github.com/Fishcake-Senpai/tabimoney-app/releases) do GitHub.

### Com o executável (para amigos, sem instalar nada)

O `Tabimoney.exe` é um arquivo só, com o Python e tudo o que o app precisa dentro. Não precisa de Python, Git,
nem de terminal. Pode ser mandado por WhatsApp, e-mail ou pendrive.

1. **Receba o arquivo.** Se veio o `.zip`, clique com o botão direito › **Extrair tudo**. Guarde o
   `Tabimoney.exe` numa pasta sua, por exemplo em `Documentos`. Não rode de dentro do `.zip`.
2. **Dê dois cliques no `Tabimoney.exe`.** Uma janelinha mostra o progresso e fecha sozinha. O app abre no
   navegador em `http://127.0.0.1:8765`.
3. **Primeira vez: aviso do Windows.** Pode aparecer *"O Windows protegeu o computador"* (SmartScreen). Clique
   em **Mais informações** › **Executar assim mesmo**. O aviso aparece porque o arquivo não tem assinatura
   digital paga, e só é mostrado uma vez.
4. **Atalho (opcional):** botão direito no `Tabimoney.exe` › *Enviar para* › *Área de trabalho (criar atalho)*.

| Quero… | Como |
|---|---|
| Abrir | Dois cliques no `Tabimoney.exe` (ou no atalho). |
| Reiniciar | Dois cliques de novo. O app aberto é encerrado com segurança e abre outra vez. |
| Atualizar | O app avisa no topo quando sai versão nova, com o botão **Baixar**. Substitua o `Tabimoney.exe` pelo novo e abra. Os dados ficam; a base é atualizada sozinha. |
| Encerrar | No app, rodapé do menu lateral › **Encerrar**. Fechar a aba do navegador não encerra. |
| Apagar tudo | Encerre o app e apague a pasta `%LOCALAPPDATA%\FinancasPessoais`. |

Onde fica cada coisa:

- **Dados:** `%LOCALAPPDATA%\FinancasPessoais`. Lá ficam o banco, os backups e os registros de erro em `logs\`.
  Nada vai para a nuvem.
- **Senhas e chaves** (Pluggy, brapi): no Gerenciador de Credenciais do Windows.
- **IA:** conecte o seu agente (Claude, Codex, Cursor…) em **Configurações › Conectar à IA**. Veja
  [Usar a IA (servidor MCP)](#usar-a-ia-servidor-mcp).

Se algo der errado:

- *"A porta 8765 está ocupada"*: outra cópia do Tabimoney está aberta pelo `run.bat`, ou outro programa usa a
  porta. Feche a outra janela ou reinicie o computador.
- **O antivírus apagou o arquivo:** alguns antivírus desconfiam de programas feitos em Python e sem assinatura.
  Restaure o arquivo da quarentena e marque como confiável.
- **Investigar:** abra um terminal na pasta do exe e rode `Tabimoney.exe --primeiro-plano` para ver o log na
  tela.

### No Mac

1. Nos [Releases](https://github.com/Fishcake-Senpai/tabimoney-app/releases), baixe o zip do seu Mac:
   `…-mac-apple-silicon.zip` (chip M1, M2, M3 ou M4) ou `…-mac-intel.zip`. O chip aparece em  › Sobre este Mac.
2. Extraia e arraste o `Tabimoney.app` para **Aplicativos**.
3. **Primeira vez:** o app não tem assinatura paga da Apple, então o Mac bloqueia.
   - No macOS 15 (Sequoia) ou mais novo: tente abrir e feche o aviso. Depois, em **Ajustes do Sistema ›
     Privacidade e Segurança**, clique em **Abrir Mesmo Assim** e abra de novo.
   - No macOS 14 ou mais antigo: botão direito › **Abrir** › **Abrir**.
   - Se o Mac disser que o app "está danificado": `xattr -dr com.apple.quarantine /Applications/Tabimoney.app`.
4. Dois cliques abrem o app no navegador. No Mac não aparece janela de progresso; se der erro, surge uma caixa
   de diálogo. Clicar de novo reinicia, e **Encerrar** fica no rodapé do menu lateral, como no Windows.

No Mac, os dados ficam em `~/Library/Application Support/Tabimoney` e as chaves no **Porta-chaves (Keychain)**.
Na primeira vez que salvar uma chave, o Mac pode pedir permissão: escolha **Sempre Permitir**. A linha de comando
é `/Applications/Tabimoney.app/Contents/MacOS/Tabimoney cli …`, e o servidor MCP é o mesmo caminho com `mcp`.

### Com o código (para desenvolver)

1. Instale Python 3.11 ou mais recente (no Windows, mantenha o launcher `py` habilitado).
2. **Windows:** execute `run.bat`. **Mac:** execute `run.command` (dois cliques no Finder abrem o Terminal).
   Na primeira vez, ele cria o `.venv` e instala as dependências. Depois, abre o app como o executável: o
   servidor fica em segundo plano, e clicar de novo reinicia.
3. Para ver o log na tela (e encerrar com `Ctrl+C`), rode `python -m app.launch --primeiro-plano` com o Python
   do `.venv`.
4. Linha de comando: `financas.bat` no Windows, `./financas.sh` no Mac.
5. Testes: `python -m pip install -r requirements-dev.txt` uma vez e depois `python -m pytest` (com o Python do
   `.venv`). Levam menos de 15 segundos e rodam isolados: base temporária, cofre de senhas falso e sem internet.
   Nunca tocam nos seus dados. `tests/test_paginas.py` abre todas as páginas do app com a base vazia e com dados de
   exemplo, então página nova já entra no teste.
6. Testes de navegador (`tests/e2e`): `python -m pip install -r requirements-e2e.txt` e
   `python -m playwright install chromium` uma vez. Depois, o mesmo `python -m pytest` também sobe o app num
   Chromium e confere menus, formulários, JavaScript e a tela do celular. Feche o Tabimoney antes: com a porta
   8765 ocupada, esses testes são pulados.
7. Branches: o trabalho vai para a `dev`; a `main` só recebe merge da `dev` por PR, depois que o check **Testes
   ok** passa. O merge na `main` gera os executáveis e, se a versão for nova, publica o Release
   ([docs/versionamento.md](docs/versionamento.md)).

### Gerar o executável

1. Rode `run.bat` uma vez, para criar o `.venv`.
2. Rode `build.bat`. Leva de 1 a 3 minutos e gera:
   - `dist\Tabimoney.exe` (cerca de 23 MB): pode mandar direto;
   - `dist\Manual-de-conexoes.html`: o manual ilustrado que ensina a criar as chaves do Meu Pluggy e da brapi e a
     colar no app. É um arquivo só, com imagens e fonte embutidas, e abre offline;
   - `dist\Tabimoney-<versão>.zip`: o exe, o `LEIA-ME.txt` e o manual. É isso que vai para os amigos.

O manual é gerado a partir de `packaging\manual\manual.html`. As capturas em `packaging\manual\imagens\` já
estão com os dados pessoais cobertos. Para trocar as capturas, tire as novas, rode
`.venv\Scripts\python.exe packaging\manual\redigir.py <pasta-das-capturas>` (ajuste as áreas em `SHOTS` se
mudarem) e confira as imagens antes de commitar. Nunca versione as capturas originais.

**Mac, e as três versões de uma vez:** o PyInstaller só gera o app de Mac rodando num Mac. Por isso, quem gera
as versões é o GitHub Actions (`.github/workflows/executaveis.yml`), em máquinas Windows, Mac Apple Silicon e
Mac Intel do próprio GitHub.

- **A cada push na `main` que mexe no app:** ele gera as três versões e testa cada uma (versão, linha de comando,
  servidor respondendo e encerramento pelo token). Os zips ficam em *Actions › execução › Artifacts*.
- **Numa tag `vX.Y.Z`:** além disso, ele publica o Release com os três zips. O link do Release é o que você manda
  para os amigos.
- **Para rodar à mão:** *Actions › Gerar executáveis › Run workflow*.

O `packaging\tabimoney.spec` define o que vai dentro do exe: templates, arquivos estáticos, migrações, roteiros
e docs da IA. Arquivo novo que o app precise ler em tempo de execução tem que entrar na lista `datas` desse
arquivo. O mesmo exe tem quatro modos:

| Comando | O que faz |
|---|---|
| `Tabimoney.exe` | Abre o app (reinicia se já estiver aberto). |
| `Tabimoney.exe cli gastos resumo` | Linha de comando, igual ao `financas.bat`. |
| `Tabimoney.exe mcp [--demo]` | Servidor MCP (stdio), que o agente de IA abre sozinho. |
| `Tabimoney.exe --primeiro-plano` | Servidor na janela atual, com log na tela. |

### Usar a IA (servidor MCP)

O Tabimoney traz um servidor [MCP](https://modelcontextprotocol.io) dentro do próprio executável. Conectado a
ele, o seu agente de IA ganha as ferramentas do Tabimoney em qualquer conversa e em qualquer pasta: lê gastos,
carteira e metas e grava análises, recomendações e correções de categoria. Não há chat embutido nem chave de
API: quem pensa é a IA que você já usa, e tudo roda nesta máquina.

Para conectar, abra **Configurações › Conectar à IA**:

- **Claude Desktop, Cursor, VS Code, Gemini CLI e Codex:** clique em **Conectar**. O app grava a entrada
  `tabimoney` na configuração do agente, sem mexer no resto e guardando uma cópia do arquivo antes. Depois,
  reinicie o agente.
- **Claude Code:** **Conectar** roda `claude mcp add` por você; sem o comando `claude` no PATH, copie o comando
  mostrado no ícone `</>` (conectar à mão).
- **Deu errado, ou o seu agente não está na lista:** em **Configurar pela própria IA**, copie o texto e cole numa conversa. O
  próprio agente faz a configuração.

Depois, peça, por exemplo: *"atualize minhas finanças"*, *"revise meus gastos do mês"* ou *"onde devo
aportar?"*. No Claude Code, os roteiros também aparecem como comandos (`/mcp__tabimoney__ciclo`).

A IA usa as mesmas proteções do app: nada é apagado, as correções podem ser desfeitas, o servidor faz backup
antes da primeira mudança de cada conversa e grava o nome do agente como autor de cada análise ou regra. As
ferramentas que mudam metas ou apagam regras pedem confirmação no agente.

**Demonstração:** a entrada `tabimoney-demo` (em **Conectar à IA › Demonstração**) liga a IA aos dados
fictícios, para testar um pedido antes de usar com os seus.

**Trocou o exe de pasta?** Ao abrir, o Tabimoney corrige sozinho o caminho nas configurações que ele gravou. No
Claude Code, a tela avisa **Caminho antigo** e **Atualizar caminho** refaz a conexão.

Chats no navegador (claude.ai, ChatGPT) não enxergam um servidor local; use o app de desktop ou o terminal.

A antiga **pasta da IA** (`%USERPROFILE%\Tabimoney`) continua sendo criada nesta versão, para a transição, com
um aviso para usar o MCP e os roteiros em `roteiros\`. Ela sai numa versão futura.

O agendador diário de preços roda enquanto o aplicativo estiver aberto. Por padrão, ele tenta buscar os fechamentos depois de 19h30 (horário de Brasília). Também é possível atualizar manualmente no painel.

## Aviso de versão nova

Ao abrir e a cada 12 horas, o app consulta o último [Release](https://github.com/Fishcake-Senpai/tabimoney-app/releases)
publicado no GitHub. Se houver versão mais nova que a instalada, o sino da barra do topo ganha um aviso, com
**Baixar** (já com o zip do seu sistema: Windows, Mac Apple Silicon ou Mac Intel), **Novidades**
e **Dispensar**, que esconde o aviso daquela versão; a próxima volta a avisar. Rodando pelo código, o aviso pede
`git pull` em vez do download.

A consulta é um pedido comum à API pública do GitHub e não envia nenhum dado seu. Sem internet, o aviso não
aparece. Em **Configurações › Atualizações** dá para desligar o aviso, ver a última verificação e verificar na
hora. O código fica em `app/services/updates.py`.

## Demonstração

Para ver o app antes de conectar os bancos, clique em **Ver demonstração** nas boas-vindas do Início (base vazia) ou em **Configurações › Geral**. Abre um casal fictício
(Lucas e Marina) com todas as telas preenchidas: contas, cartões, carteira, renda fixa, previdência, metas,
análises e recomendações. A demo usa uma base separada (`demo.sqlite3`, na pasta de dados) e um cofre de senhas
só dela, então seus dados não aparecem e nada do que você fizer na demo chega a eles. **Recomeçar** volta tudo ao
original, e **Sair da demo** volta aos seus dados. Na linha de comando: `financas --demo carteira contexto`.

Quem mexe no código: exemplos novos entram em `app/demo.py`, e `tests/test_demo.py` falha se alguma tela
aparecer vazia na demo.

## Conectar os bancos pelo Meu Pluggy

1. Crie uma conta pessoal no [Meu Pluggy](https://meu.pluggy.ai) e conecte cada banco (ex.: Nubank e Itaú) pelo fluxo de consentimento do Open Finance.
2. No [Dashboard Pluggy](https://dashboard.pluggy.ai), em **Aplicações › Novo**, crie a sua aplicação (ex.: *Tabimoney*). Não use a *Pluggy Demo App*. Na linha da sua aplicação, copie o `Client ID` e o `Client Secret`. Depois, clique em ▷, use **Conectar Conta › MeuPluggy** para cada banco e copie o `Item ID` de cada item. O passo a passo ilustrado está no manual de conexões (`dist\Manual-de-conexoes.html`, gerado pelo `build.bat`, e dentro do zip de distribuição).
3. Abra **Configurações** no aplicativo, informe esses valores na conexão **Principal** (Item IDs separados por vírgula) e salve. Client ID, Secret e Item IDs têm que ser da mesma aplicação. A instituição de cada item é reconhecida pelo código do banco da conta.
4. No painel, escolha **Open Finance**. Cada item sincroniza separadamente: um item com falha não impede os demais.

### Gestão a dois

Cada pessoa conecta os próprios bancos no Meu Pluggy, porque o consentimento do Open Finance é dado pelo titular da conta. Em **Configurações › Titulares**, cadastre a outra pessoa (o CPF é opcional). Depois, adicione os Item IDs dela escolhendo o titular. Se ela tem o próprio app no Dashboard Pluggy, crie uma **Nova conexão** com o Client ID e o Secret dela; se usa o mesmo app, basta colar os Item IDs na conexão Principal.

- As contas de quem não é o titular principal ganham o sufixo " · Nome" (ex.: "Nubank Cartão · Ana"), então dois Nubank não se misturam.
- O seletor **Casa / cada pessoa** na barra do topo filtra todas as telas. Cada titular pode ter metas de alocação próprias; as metas de gastos são da casa.
- O Pix entre titulares vira *Transferência entre titulares*, que fica fora de receitas e despesas: pelo CPF dos dois lados ou, sem CPF, quando a saída de um e a entrada do outro têm o mesmo valor em até 1 dia.
- Arquivos importados (OFX, CSV, B3) entram como do titular principal.

Client ID, Client Secret e token da brapi são guardados no cofre de senhas do sistema via Keyring (Credential Manager no Windows, Porta-chaves no Mac). A aplicação cria uma chave de API Pluggy temporária para a sincronização e não pede senha do Nubank. O Meu Pluggy mantém seu consentimento e atualiza as conexões no ciclo diário do próprio serviço.

A sincronização consulta contas, movimentações, posições e operações de investimento que a conexão disponibilizar. A API B3 para a Área do Investidor não tem acesso direto para pessoa física; a custódia do MVP usa o que vier pelo Open Finance ou a importação manual de posição. Consulte o [FAQ da B3 for Developers](https://developers.b3.com.br/faq).

Sinais: toda saída é negativa e toda entrada positiva, em conta e cartão. No cartão a Pluggy manda compra positiva e pagamento/estorno negativo; o campo `type` (DEBIT/CREDIT) normaliza os dois casos.

Movimentações bancárias `PENDING` do Open Finance são mantidas com esse estado e não entram na conciliação de saldo até a origem confirmá-las como `POSTED`. No cartão, `PENDING` é compra da fatura ainda aberta: entra nos gastos a partir da data da compra (parcelas futuras só na data delas).

Se a Pluggy deixar de retornar ativos listados que já estavam registrados, a aplicação marca a sincronização como parcial e preserva as posições anteriores. Para encerrar uma posição manualmente, importe quantidade zero em data posterior ao último snapshot.

## Mercado: cotações, Ibovespa e CDI

**Atualizar mercado** (ou o agendador após 19h30) grava o histórico diário de fechamentos da [brapi](https://brapi.dev): 12 meses na primeira coleta, depois só o último mês. O Ibovespa também vem da brapi e exige token (o plano gratuito basta). O CDI vem da API pública do Banco Central (série SGS 12), sem chave. Sem token, a brapi libera poucos tickers; os demais podem usar o preço de fechamento da Posição B3 ou o CSV de cotações.

## Importar (Nubank, B3/NuInvest e modelos)

A página **Importar** aceita vários arquivos de uma vez e detecta o formato sozinha. Reimportar o mesmo arquivo não duplica nada.

| Arquivo | Onde baixar | O que entra |
|---|---|---|
| Extrato da conta, OFX | App Nubank › Extrato › exportar | Saldo e movimentações |
| Extrato da conta, CSV (`Data,Valor,Identificador,Descrição`) | App Nubank | Movimentações; o saldo é projetado a partir do último OFX |
| Fatura do cartão, CSV (`date,title,amount`) ou OFX | App Nubank › Fatura | Lançamentos, categoria e total da fatura |
| Posição B3, XLSX | Área do Investidor B3 › Extratos › Posição | Ações, FIIs, ETFs, BDRs, CDB/LCI/LCA e Tesouro |
| Negociação B3, XLSX | Área do Investidor B3 › Extratos › Negociação | Compras e vendas → preço médio e lucro realizado |
| Movimentação B3, XLSX | Área do Investidor B3 › Extratos › Movimentação | Dividendos, JCP, rendimentos, desdobros e bonificações |
| Modelo de renda fixa, CSV | Botão na página | Caixinhas/RDB e qualquer título fora da B3 |
| Modelos de operações, posições e cotações, CSV | Botões na página | Outras corretoras, preço médio inicial, preços manuais |

O Nubank não oferece um arquivo único com tudo. As Caixinhas/RDB não aparecem na B3 nem em exportação do app, então vêm do Open Finance (Meu Pluggy) ou do modelo CSV. A custódia da NuInvest aparece na B3 com o mesmo apelido do Open Finance (`Nubank / NuInvest`), e as duas origens são consolidadas sem contar em dobro.

Regras de consolidação: por conta e ativo vale o snapshot de posição mais recente, somado às operações posteriores a ele. As operações vêm de uma única origem por prioridade: Negociação B3, depois Movimentação B3, depois Open Finance, depois CSV. Na renda fixa e nos saldos vale, por conta, a origem mais recente. Gastos com categoria *Investimentos*, *Pagamento de fatura*, *Transferência própria* ou *Transferência entre titulares* ficam fora de receitas e despesas.

Conciliação entre contas: uma saída de conta casa 1 a 1 com uma entrada de mesmo valor em outra conta própria (até 3 dias, quando um dos lados é transferência própria — CPF igual de pagador e recebedor ou rótulo da origem) ou no cartão (até 5 dias, quando um dos lados é pagamento de fatura). Entre contas de titulares diferentes, o par vale quando um dos lados é transferência entre titulares (CPFs cadastrados) ou, sem CPF, quando os dois lados são *Pix e transferências* em até 1 dia. Os dois lados viram movimento interno; assim o salário que cai no Itaú conta como receita uma vez só, e a TED para o Nubank não vira despesa nem receita. A página **Pendências** (o sino da barra do topo) lista as divergências, as transferências próprias sem o outro lado (conta não conectada), os avisos dos ativos e, recolhidos, os pares conciliados.

Receitas são entradas em conta com categoria Salário, Proventos, Pix e transferências ou Outros; qualquer outra entrada (ex.: estorno no cartão) abate a despesa da categoria. Compra e venda de ações, aplicações, resgates e previdência são *Investimentos* mesmo quando a origem as rotula como compra.

Histórico do patrimônio: antes do primeiro saldo conhecido, o saldo de cada conta e cartão é reconstruído subtraindo as movimentações; a quantidade de cada ativo, desfazendo as operações; a renda fixa, em linha reta do valor aplicado (na data de aplicação) até a primeira fotografia. O patrimônio desconta a fatura do cartão em aberto e usa a renda fixa pelo valor bruto.

## Indicadores

- **Início:** patrimônio e variação em 30 dias, com a evolução do total (ou por classe); gastos do mês contra o orçamento; investimentos; saldo em conta e fatura; últimos lançamentos; o que pede atenção.
- **Investimentos › Resumo:** total investido, evolução, alocação por classe contra as metas, onde aportar e maiores variações do dia.
- **Investimentos › Ações e FIIs:** valor de mercado e variação do dia; resultado não realizado (R$ e %); lucro realizado; proventos em 12 meses, dividend yield e yield on cost; rentabilidade pelo método de cotas (TWR, com proventos) em 1M/3M/6M/ano/12M/início contra CDI e Ibovespa; volatilidade anualizada; queda máxima; concentração nos 5 maiores; rentabilidade mês a mês; valor de mercado contra capital aplicado. Por ativo: preço médio, peso, retorno em 1, 3 e 12 meses, distância da máxima de 52 semanas, gráfico de preço com linha do preço médio e histórico de eventos.
- **Renda fixa:** valor bruto e líquido de IR, rendimento sobre o aplicado, vencimentos e distribuição por tipo.

O preço médio segue o padrão da Receita (vendas não alteram o preço médio). Quando a quantidade operada difere da custódia, o preço médio é marcado como estimado.

## Metas de gastos (orçamento do mês)

Em **Gastos › Orçamento**, cada meta mostra em um card o que você gastou com as metas de cada grupo de categorias. Ele mostra:

- quanto ainda cabe por dia;
- a projeção do mês e a situação de cada meta (no ritmo, em risco, estourou);
- o histórico dos últimos 6 meses por meta;
- o que está sem meta.

Sem metas ainda, o app sugere limites pela média dos seus últimos 3 meses e cria todas com um clique. O agente de IA analisa gastos e metas juntos e grava recomendações (ajustar, criar ou remover meta, ou onde economizar) que você aplica com um botão em **Sugestões** ou na própria aba.

## Versões

A versão aparece no rodapé do menu e em `financas --version`. O que mudou em cada versão está no [CHANGELOG.md](CHANGELOG.md); as regras e o passo a passo de lançamento, em [docs/versionamento.md](docs/versionamento.md).

## Gastos por categoria e correções

Em **Gastos › Resumo** ficam o gasto do mês por categoria (com seletor de mês) e *O que mudou*; o botão **Mês a mês** abre a tabela que mostra os últimos 6 meses fechados e o mês corrente, com a variação do último mês contra a média dos 3 anteriores e dos últimos 3 meses contra os 3 anteriores. *O que mudou* lista as categorias que variaram mais de 15% (e R$ 50).

Em **Gastos › Lançamentos**, clicar num lançamento abre um painel para trocar a categoria; marcar *Usar sempre* cria ali mesmo a regra (*descrição contém X → categoria*). As regras e as categorias próprias (com ícone) ficam em **Configurações › Regras** e **› Categorias**. Ordem de prioridade: escolha manual > regra > categoria automática. Nenhuma das correções se perde numa nova sincronização.

## Fundamentos das ações

**Investimentos › Ações e FIIs › Fundamentos › Atualizar fundamentos** baixa da CVM (dados abertos, sem chave) as demonstrações trimestrais (ITR) e anuais (DFP) das empresas da carteira dos últimos 3 anos. Os arquivos ficam em cache em `%LOCALAPPDATA%\FinancasPessoais\cvm` e são conferidos semanalmente (também de forma automática, com o app aberto). Da brapi gratuita vêm valor de mercado, setor e descrição; o plano pago da brapi não é necessário.

Indicadores (12 meses, com o preço do dia): P/L, P/VP, EV/EBIT, EV/EBITDA, dividend yield e payout (dividendos/JCP efetivamente pagos), ROE, ROA, margens, dívida líquida/EBITDA e /PL, crescimento de receita e lucro e FCF yield. Bancos e seguradoras não têm os indicadores de dívida e EBITDA. Units (ex.: ALUP11) usam a composição informada à CVM para o valor de mercado. ETFs e FIIs ficam de fora.

Regras simples geram avisos: prejuízo, lucro ou receita caindo, ROE baixo ou caindo, margem caindo, dívida alta ou subindo, payout acima de 100%, P/L muito baixo com ROE alto (possivelmente barata) ou P/L acima de 25 (cara). "Visto" esconde o aviso até o próximo balanço.

## Metas e balanceamento

Em **Investimentos › Metas** (botão **Editar metas**), defina a reserva de emergência (R$), a divisão entre renda fixa e renda variável (% do que sobra além da reserva) e quanto da renda variável fica no exterior. A tela mostra onde você está contra cada meta, avisa desvios de 5 p.p. ou mais e calcula para onde vai o próximo aporte, sem vender nada: primeiro completa a reserva, depois reforça as classes abaixo da meta. O valor sugerido é a média de sobra dos últimos 3 meses.

- **Reserva:** caixa em conta menos a fatura em aberto. O excedente conta como renda fixa, e a previdência também, se você marcar.
- **Internacional:** BDRs e ETFs de índice externo (IVVB11, NASD11, QBTC11…) são internacionais por padrão; dá para corrigir ativo por ativo.

## Análises e recomendações trimestrais

- **Página de cada ativo:** mostra a análise mais recente do agente completa (Markdown com tabelas e checklist) e o histórico dos trimestres anteriores. **Análises** lista todos os relatórios, inclusive de renda fixa, previdência e da carteira.
- **Sugestões:** traz as recomendações do orçamento, prontas para aplicar, e, por trimestre, as mudanças sugeridas na carteira atual (ação, peso sugerido, convicção, preço justo, justificativa) e carteiras-modelo com o seu perfil, indicando quanto de cada uma você já tem. As versões anteriores ficam no histórico.

## Agentes de IA

O caminho recomendado é o servidor MCP ([Usar a IA](#usar-a-ia-servidor-mcp)): 36 ferramentas (leitura, escrita reversível e as sensíveis, que só rodam com pedido explícito), os roteiros passo a passo como prompts e pela ferramenta `roteiro`, e o contrato e os exemplos como resources. O código fica em `app/mcp_server/`; as operações, em `app/agente/operacoes.py`; os roteiros, em `app/agente/roteiros/`.

A linha de comando `financas.bat` (saída em JSON) chama as mesmas operações, para você e para agentes sem MCP. Exemplos: `financas gastos resumo`, `financas gastos regra --contem "UBER" --categoria Transporte`, `financas fundamentos contexto EGIE3`, `financas analise importar relatorio.json`, `financas mcp instalar --cliente claude-desktop`. O contrato está em `docs/agente-financeiro.md` e o modelo de relatório em `docs/agentes/`.

Rodando pelo código, **Configurações › Conectar à IA** aponta o agente para o Python do `.venv` (`python -m app.mcp_server`).

## Proventos e rendimento do CDI

A aba **Proventos e CDI** mostra a renda passiva: proventos creditados na conta (ligados ao ativo quando há um evento de mesmo valor em até 5 dias) e o rendimento do saldo parado. O Nubank não lança esse rendimento no extrato; ele só aparece no saldo. Por isso o app o calcula com o CDI diário oficial (Banco Central, série SGS 12, baixado junto com o mercado):

- **Estimado:** saldo do dia anterior × CDI do dia × % do CDI da conta (padrão: Nubank 100%, demais 0%; ajustável na aba).
- **Medido:** entre dois saldos reais do Open Finance, rendimento = saldo final − saldo inicial − movimentações. A estimativa do intervalo é ajustada para bater com ele (se o medido sair do esperado, fica a estimativa). Sincronizar todo dia deixa os meses medidos.

O rendimento entra como receita (*Rendimentos*) em receitas e despesas, um lançamento por conta e mês. O caixa já o inclui, pois vem do saldo real; na reconstrução do histórico o juro é descontado dia a dia, para não ser atribuído ao passado. Valores brutos: o IR regressivo é cobrado no resgate.

## Previdência (PGBL/VGBL)

Previdência privada é produto de seguradora (SUSEP) e fica no Open Insurance, não no Open Finance: a Pluggy não a devolve, e a contribuição descontada em folha também não passa pela conta. Na aba **Previdência**, registre o saldo do extrato do banco (saldo bruto, total contribuído e, se quiser, o líquido de IR) sempre que quiser atualizar. Lançar de novo na mesma data corrige o saldo.

O saldo entra no patrimônio e na alocação como *Previdência*, separado da renda fixa. Entre dois extratos o valor segue em linha reta; antes do primeiro, vai do contribuído (na data de início do plano) até o saldo. A rentabilidade no período encadeia os intervalos entre extratos descontando as contribuições de cada intervalo e é comparada ao CDI. Se um dia o Open Finance trouxer o plano, ele é gravado como *Previdência*; nesse caso, apague os lançamentos manuais do mesmo plano para não contar em dobro.

## Base local, backup e restauração

- Banco: `%LOCALAPPDATA%\FinancasPessoais\financas.sqlite3`
- Backups: `%LOCALAPPDATA%\FinancasPessoais\backups`
- Credenciais: Credential Manager do Windows ou Porta-chaves do Mac, separado do SQLite.
- No Mac, troque `%LOCALAPPDATA%\FinancasPessoais` por `~/Library/Application Support/Tabimoney`.

Em **Importações**, baixe um backup SQLite ou restaure um anterior. Antes de substituir a base, o aplicativo valida integridade/versão e salva uma cópia preventiva dos dados atuais. Guarde backups em local privado.

## Estrutura do projeto

- `app/`: interface local, importadores e adaptadores de provedores.
- `app/agente/`: operações e roteiros dos agentes de IA; `app/mcp_server/`: o servidor MCP e a conexão com cada agente.
- `migrations/`: esquema SQLite e views de conciliação/KPIs.
- `docs/superpowers/specs/2026-09-22-financas-pessoais-local-design.md`: especificação aprovada.
- `docs/superpowers/plans/2026-09-22-mvp-financas-locais.md`: plano de implementação.
- `docs/superpowers/specs/mcp-tabimoney.md`: especificação do servidor MCP.

## Licença

O código é distribuído sob a [Licença Apache 2.0](LICENSE). A fonte Inter segue a SIL Open Font License
(`app/static/fonts/LICENSE-Inter.txt`). O nome, o logo e o mascote Tabimoney (`app/static/brand/`)
não entram na licença do código: em um fork ou versão modificada, use outro nome e outra marca.
