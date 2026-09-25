# Tabimoney — finanças sérias (mais ou menos)

Aplicação local de finanças pessoais. A identidade visual (logo, mascote, paleta verde sobre fundo escuro e a fonte Inter) segue um manual de marca que não é distribuído com o código. Os ícones do app e do navegador ficam em `app/static/brand/`, e a fonte Inter em `app/static/fonts/`, servida localmente (licença OFL em `LICENSE-Inter.txt`).

Aplicativo pessoal para acompanhar saldos dos bancos (Nubank, Itaú…), posições de investimento e cotações diárias. A interface abre no navegador, mas o servidor aceita conexões somente em `127.0.0.1`. O banco SQLite fica no perfil local do Windows; não há GitHub, hospedagem ou cópia de dados na nuvem.

As chamadas autorizadas do Open Finance e da fonte de preços saem desta máquina para os provedores correspondentes. O banco e os dados normalizados permanecem locais.

## Iniciar

Há dois jeitos de usar: o **executável**, para quem só quer usar o app, e o **código**, para quem vai mexer
nele. Os dois guardam os dados no mesmo lugar e funcionam do mesmo jeito.

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
| Atualizar | Substitua o `Tabimoney.exe` pelo novo e abra. Os dados ficam; a base é atualizada sozinha. |
| Encerrar | No app, menu lateral › **Encerrar o Tabimoney**. Fechar a aba do navegador não encerra. |
| Apagar tudo | Encerre o app e apague a pasta `%LOCALAPPDATA%\FinancasPessoais`. |

Onde fica cada coisa:

- **Dados:** `%LOCALAPPDATA%\FinancasPessoais`. Lá ficam o banco, os backups e os registros de erro em `logs\`.
  Nada vai para a nuvem.
- **Senhas e chaves** (Pluggy, brapi): no Gerenciador de Credenciais do Windows.
- **Pasta da IA:** `%USERPROFILE%\Tabimoney`, que o app recria a cada abertura. Veja
  [Usar a IA com o executável](#usar-a-ia-com-o-executável).

Se algo der errado:

- *"A porta 8765 está ocupada"*: outra cópia do Tabimoney está aberta pelo `run.bat`, ou outro programa usa a
  porta. Feche a outra janela ou reinicie o computador.
- **O antivírus apagou o arquivo:** alguns antivírus desconfiam de programas feitos em Python e sem assinatura.
  Restaure o arquivo da quarentena e marque como confiável.
- **Investigar:** abra um terminal na pasta do exe e rode `Tabimoney.exe --primeiro-plano` para ver o log na
  tela.

### Com o código (para desenvolver)

1. Instale Python 3.11 ou mais recente para Windows e mantenha o launcher `py` habilitado.
2. Execute `run.bat` com duplo clique. Na primeira vez, ele cria o `.venv` e instala as dependências. Depois,
   abre o app como o executável: o servidor fica em segundo plano, e clicar de novo reinicia.
3. Para ver o log na tela (e encerrar com `Ctrl+C`), rode `.venv\Scripts\python.exe -m app.launch --primeiro-plano`.

### Gerar o executável

1. Rode `run.bat` uma vez, para criar o `.venv`.
2. Rode `build.bat`. Leva de 1 a 3 minutos e gera:
   - `dist\Tabimoney.exe` (cerca de 23 MB): pode mandar direto;
   - `dist\Tabimoney-<versão>.zip`: o exe mais o `LEIA-ME.txt`, para quando o WhatsApp ou o e-mail recusar o
     `.exe`.

O `packaging\tabimoney.spec` define o que vai dentro do exe: templates, arquivos estáticos, migrações, skills
e docs da IA. Arquivo novo que o app precise ler em tempo de execução tem que entrar na lista `datas` desse
arquivo. O mesmo exe tem três modos:

| Comando | O que faz |
|---|---|
| `Tabimoney.exe` | Abre o app (reinicia se já estiver aberto). |
| `Tabimoney.exe cli gastos resumo` | Linha de comando, igual ao `financas.bat`. |
| `Tabimoney.exe --primeiro-plano` | Servidor na janela atual, com log na tela. |

### Usar a IA com o executável

Quem clona o repositório usa a IA pela pasta do projeto. Quem só tem o exe usa a **pasta da IA**. Toda vez que
abre, o `Tabimoney.exe` grava em `%USERPROFILE%\Tabimoney`:

- `AGENTS.md` e `CLAUDE.md`: as instruções;
- `.claude\skills\`: os roteiros;
- `docs\`: o contrato e os exemplos;
- `financas.bat`: chama `Tabimoney.exe cli` no lugar onde o exe está.

Como tudo sai de dentro do exe, as skills estão sempre na mesma versão do app: atualizar o exe atualiza as
skills. Os arquivos dessa pasta são substituídos a cada abertura; a subpasta `trabalho\` é livre.

Para usar:

1. Abra o Tabimoney uma vez, para a pasta ser criada.
2. Abra o [Claude Code](https://claude.com/claude-code) (app de desktop ou terminal) na pasta
   `%USERPROFILE%\Tabimoney`. Outros agentes que leem `AGENTS.md`, como o Codex, também servem.
3. Peça, por exemplo: *"atualize minhas finanças"*, *"revise meus gastos do mês"* ou *"onde devo aportar?"*.

A IA lê e altera os dados só pelo `financas.bat`, com as mesmas proteções do app: correções reversíveis,
backup antes de mudanças em massa e nada de editar o banco direto.

O agendador diário de preços roda enquanto o aplicativo estiver aberto. Por padrão, ele tenta buscar os fechamentos depois de 19h30 (horário de Brasília). Também é possível atualizar manualmente no painel.

## Conectar os bancos pelo Meu Pluggy

1. Crie uma conta pessoal no [Meu Pluggy](https://meu.pluggy.ai) e conecte cada banco (ex.: Nubank e Itaú) pelo fluxo de consentimento do Open Finance.
2. Siga o [guia oficial de acesso via API](https://meu.pluggy.ai/api-guide): no Dashboard Pluggy, conecte o item do Meu Pluggy na aplicação demo e obtenha o `Client ID`, o `Client Secret` e o `Item ID` proxy de cada conexão.
3. Abra **Configurações** no aplicativo, informe esses valores (um Item ID por linha) e salve. A instituição de cada item é reconhecida pelo código do banco da conta.
4. No painel, escolha **Open Finance**. Cada item sincroniza separadamente: um item com falha não impede os demais.

Client ID, Client Secret e token da brapi são guardados no Credential Manager do Windows via Keyring. A aplicação cria uma chave de API Pluggy temporária para a sincronização e não pede senha do Nubank. O Meu Pluggy mantém seu consentimento e atualiza as conexões no ciclo diário do próprio serviço.

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

Regras de consolidação: por conta e ativo vale o snapshot de posição mais recente, somado às operações posteriores a ele. As operações vêm de uma única origem por prioridade: Negociação B3, depois Movimentação B3, depois Open Finance, depois CSV. Na renda fixa e nos saldos vale, por conta, a origem mais recente. Gastos com categoria *Investimentos*, *Pagamento de fatura* ou *Transferência própria* ficam fora de receitas e despesas.

Conciliação entre contas: uma saída de conta casa 1 a 1 com uma entrada de mesmo valor em outra conta própria (até 3 dias, quando um dos lados é transferência própria — CPF igual de pagador e recebedor ou rótulo da origem) ou no cartão (até 5 dias, quando um dos lados é pagamento de fatura). Os dois lados viram movimento interno; assim o salário que cai no Itaú conta como receita uma vez só, e a TED para o Nubank não vira despesa nem receita. A página **Conciliação** lista os pares e as transferências próprias sem o outro lado (conta não conectada).

Receitas são entradas em conta com categoria Salário, Proventos, Pix e transferências ou Outros; qualquer outra entrada (ex.: estorno no cartão) abate a despesa da categoria. Compra e venda de ações, aplicações, resgates e previdência são *Investimentos* mesmo quando a origem as rotula como compra.

Histórico do patrimônio: antes do primeiro saldo conhecido, o saldo de cada conta e cartão é reconstruído subtraindo as movimentações; a quantidade de cada ativo, desfazendo as operações; a renda fixa, em linha reta do valor aplicado (na data de aplicação) até a primeira fotografia. O patrimônio desconta a fatura do cartão em aberto e usa a renda fixa pelo valor bruto.

## Indicadores

- **Visão geral:** patrimônio e variação em 30 dias; evolução empilhada (renda variável, renda fixa, caixa); alocação; receitas e despesas; gastos por categoria; taxa de poupança; maiores variações do dia.
- **Ações e FIIs:** valor de mercado e variação do dia; resultado não realizado (R$ e %); lucro realizado; proventos em 12 meses, dividend yield e yield on cost; rentabilidade pelo método de cotas (TWR, com proventos) em 1M/3M/6M/ano/12M/início contra CDI e Ibovespa; volatilidade anualizada; queda máxima; concentração nos 5 maiores; rentabilidade mês a mês; valor de mercado contra capital aplicado. Por ativo: preço médio, peso, retorno em 1, 3 e 12 meses, distância da máxima de 52 semanas, gráfico de preço com linha do preço médio e histórico de eventos.
- **Renda fixa:** valor bruto e líquido de IR, rendimento sobre o aplicado, vencimentos e distribuição por tipo.

O preço médio segue o padrão da Receita (vendas não alteram o preço médio). Quando a quantidade operada difere da custódia, o preço médio é marcado como estimado.

## Metas de gastos (orçamento do mês)

No topo de **Conta e cartão**, o bloco *Orçamento do mês* compara o que você gastou com as metas de cada grupo de categorias. Ele mostra:

- quanto ainda cabe por dia;
- a projeção do mês e a situação de cada meta (no ritmo, em risco, estourou);
- o histórico dos últimos 6 meses por meta;
- o que está sem meta.

Sem metas ainda, o app sugere limites pela média dos seus últimos 3 meses e cria todas com um clique. O agente de IA analisa gastos e metas juntos e grava recomendações (ajustar, criar ou remover meta, ou onde economizar) que você aplica com um botão em **Recomendações** ou no próprio bloco.

## Versões

A versão aparece no rodapé do menu e em `financas --version`. O que mudou em cada versão está no [CHANGELOG.md](CHANGELOG.md); as regras e o passo a passo de lançamento, em [docs/versionamento.md](docs/versionamento.md).

## Gastos por categoria e correções

Em **Conta e cartão**, a tabela *Gasto por categoria, mês a mês* mostra os últimos 6 meses fechados e o mês corrente, com a variação do último mês contra a média dos 3 anteriores e dos últimos 3 meses contra os 3 anteriores. O card *O que mudou* lista as categorias que variaram mais de 15% (e R$ 50) e os lançamentos que puxaram a mudança.

A categoria de cada lançamento pode ser trocada na própria tabela de movimentações. Para erros que se repetem, crie uma regra (*descrição contém X → categoria*). Ordem de prioridade: escolha manual > regra > categoria automática. Nenhuma das correções se perde numa nova sincronização.

## Fundamentos das ações

**Ações e FIIs › Atualizar fundamentos** baixa da CVM (dados abertos, sem chave) as demonstrações trimestrais (ITR) e anuais (DFP) das empresas da carteira dos últimos 3 anos. Os arquivos ficam em cache em `%LOCALAPPDATA%\FinancasPessoais\cvm` e são conferidos semanalmente (também de forma automática, com o app aberto). Da brapi gratuita vêm valor de mercado, setor e descrição; o plano pago da brapi não é necessário.

Indicadores (12 meses, com o preço do dia): P/L, P/VP, EV/EBIT, EV/EBITDA, dividend yield e payout (dividendos/JCP efetivamente pagos), ROE, ROA, margens, dívida líquida/EBITDA e /PL, crescimento de receita e lucro e FCF yield. Bancos e seguradoras não têm os indicadores de dívida e EBITDA. Units (ex.: ALUP11) usam a composição informada à CVM para o valor de mercado. ETFs e FIIs ficam de fora.

Regras simples geram avisos: prejuízo, lucro ou receita caindo, ROE baixo ou caindo, margem caindo, dívida alta ou subindo, payout acima de 100%, P/L muito baixo com ROE alto (possivelmente barata) ou P/L acima de 25 (cara). "Visto" esconde o aviso até o próximo balanço.

## Metas e balanceamento

Em **Metas**, defina a reserva de emergência (R$), a divisão entre renda fixa e renda variável (% do que sobra além da reserva) e quanto da renda variável fica no exterior. A tela mostra onde você está contra cada meta, avisa desvios de 5 p.p. ou mais e calcula para onde vai o próximo aporte, sem vender nada: primeiro completa a reserva, depois reforça as classes abaixo da meta. O valor sugerido é a média de sobra dos últimos 3 meses.

- **Reserva:** caixa em conta menos a fatura em aberto. O excedente conta como renda fixa, e a previdência também, se você marcar.
- **Internacional:** BDRs e ETFs de índice externo (IVVB11, NASD11, QBTC11…) são internacionais por padrão; dá para corrigir ativo por ativo.

## Análises e recomendações trimestrais

- **Página de cada ativo:** mostra a análise mais recente do agente completa (Markdown com tabelas e checklist) e o histórico dos trimestres anteriores. **Análises** lista todos os relatórios, inclusive de renda fixa, previdência e da carteira.
- **Recomendações:** traz, por trimestre, as mudanças sugeridas na carteira atual (ação, peso sugerido, convicção, preço justo, justificativa) e carteiras-modelo com o seu perfil, indicando quanto de cada uma você já tem. As versões anteriores ficam no histórico.

## Agentes de IA

A linha de comando `financas.bat` (saída em JSON) permite que você ou um agente (Claude Code, Codex) revise gastos, recategorize, consulte a carteira e grave análises trimestrais, métricas e avisos, que aparecem nas telas. Exemplos: `financas gastos resumo`, `financas gastos regra --contem "UBER" --categoria Transporte`, `financas fundamentos contexto EGIE3`, `financas analise importar relatorio.json`. O contrato está em `docs/agente-financeiro.md`, o modelo de relatório em `docs/agentes/`, e os roteiros passo a passo nas skills `.claude/skills/financas*` (gastos, metas, análise trimestral, recomendações), referenciados no `AGENTS.md` para outros agentes.

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
- Credenciais: Credential Manager do Windows, separado do SQLite.

Em **Importações**, baixe um backup SQLite ou restaure um anterior. Antes de substituir a base, o aplicativo valida integridade/versão e salva uma cópia preventiva dos dados atuais. Guarde backups em local privado.

## Estrutura do projeto

- `app/`: interface local, importadores e adaptadores de provedores.
- `migrations/`: esquema SQLite e views de conciliação/KPIs.
- `docs/superpowers/specs/2026-09-22-financas-pessoais-local-design.md`: especificação aprovada.
- `docs/superpowers/plans/2026-09-22-mvp-financas-locais.md`: plano de implementação.

## Licença

O código é distribuído sob a [Licença Apache 2.0](LICENSE). A fonte Inter segue a SIL Open Font License
(`app/static/fonts/LICENSE-Inter.txt`). O nome, o logo e o mascote Tabimoney (`app/static/brand/`)
não entram na licença do código: em um fork ou versão modificada, use outro nome e outra marca.
