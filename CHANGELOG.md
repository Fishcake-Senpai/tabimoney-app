# Changelog

Todas as mudanças relevantes do Tabimoney ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/). As regras de numeração e o passo a passo de
lançamento estão em [docs/versionamento.md](docs/versionamento.md).

Enquanto a versão for `0.x`, o projeto está em desenvolvimento inicial: versões novas podem mudar o esquema da
base (sempre por migração automática) e o contrato da CLI.

## [Não lançado]

### Alterado
- Gráficos históricos com períodos de 24 e 36 meses e todo o histórico disponível, incluindo fluxo de caixa,
  gastos por categoria, proventos e rentabilidade mensal. Navegação de Gastos aceita meses anteriores a 12 meses.
- Demonstração com mais de três anos de cotações, gastos e rendimentos para exercitar os períodos longos.

### Corrigido
- Histórico dos investimentos independente da cobertura dos extratos bancários: contas recentes não escondem
  cotações antigas. O patrimônio total começa onde há extrato das contas e informa quando começa esse trecho.
- Rentabilidade acumulada: num período maior que o histórico da carteira (ex.: 24M com um ano de carteira),
  CDI e Ibovespa partem do zero junto com a carteira, em vez de acumular os meses anteriores a ela.
- Primeiro ponto de “Tudo” incluído na rentabilidade acumulada, com base zero. Períodos de meses respeitam
  o calendário, incluindo fins de mês e anos bissextos, em qualquer fuso horário.
- Volatilidade calculada por pregões, sem influência de Pix e compras em fins de semana, preservando proventos
  entre pregões.

## [0.15.0] - 2026-10-01

### Alterado
- Interface nova, com cara de aplicativo: um número grande por tela (o patrimônio, o gasto do mês, o total
  investido), três números de apoio e o detalhe a um clique. Cards sem borda, ícones em toda parte, o verde só para
  o que subiu e para a ação principal, e as explicações longas no **?** ao lado de cada título. Guia de design em
  `docs/superpowers/specs/2026-09-30-revamp-ui.md`.
- Menu com quatro destinos: **Início**, **Gastos**, **Investimentos** e **Sugestões**, mais Configurações no
  rodapé. O menu recolhe para só ícones e lembra a escolha.
- Barra do topo em todas as telas: seletor de titular (Casa ou uma pessoa), o olho que esconde os valores, um botão
  **Sincronizar** só (Open Finance e mercado, com o tempo desde a última vez), o sino com o que pede atenção e
  **Importar**. O aviso de versão nova foi para o sino.
- **Início**: patrimônio com a evolução do total (ou por classe), gastos do mês contra o orçamento, investimentos,
  saldo em conta, os últimos lançamentos e o que pede atenção. Na base vazia, boas-vindas com os primeiros passos.
- **Gastos** (antes Conta e cartão) em três abas: **Resumo** (gasto do mês com seletor de mês, por categoria, o que
  mudou, contas e cartões; a tabela mês a mês abre num botão), **Lançamentos** (lista por dia; clicar abre um painel
  para trocar a categoria e, marcando *Usar sempre*, criar a regra ali mesmo) e **Orçamento** (metas em cards,
  criação e edição em janela, sugestões da IA prontas para aplicar).
- **Investimentos** reúne Ações e FIIs, Renda fixa, Previdência, Proventos (antes Proventos e CDI) e Metas em abas,
  com um **Resumo** novo: total investido, evolução, alocação contra as metas, onde aportar e as maiores variações.
- Ações e FIIs mostra 6 colunas nas posições (**Mais colunas** traz o resto e lembra a escolha) e alterna entre
  Posições e Fundamentos. A página de cada ativo ganhou abas (Visão geral, Fundamentos, Resultados, Análises e
  Eventos). Risco, capital aplicado e rentabilidade mês a mês ficam em **Mais números**.
- **Sugestões** (antes Recomendações) virou um feed de cards: as do orçamento com **Aplicar**, as da carteira com o
  peso de hoje e o sugerido; a tese completa abre num painel e as carteiras-modelo ficam recolhidas.
- **Pendências** (antes Conciliação, pelo sino) junta divergências, transferências sem par e os avisos dos ativos.
- Categorias e regras saíram de Gastos para **Configurações › Categorias** e **› Regras**; backup e restauração, de
  Importar para **Configurações › Dados e backup**. **Ver demonstração** fica em Configurações › Geral e nas
  boas-vindas.
- Avisos depois de salvar viram toasts no canto, que somem sozinhos (os de erro ficam até o clique).
- No celular, barra de abas embaixo, com **Mais** para Importar, Pendências e Configurações.
- Manual de conexões atualizado para a barra do topo e as Configurações novas.
- As análises de investimento passam a ser de **longo prazo** (5, 10, 20 anos) e começam perguntando o horizonte e o
  objetivo do investidor; com menos de 5 anos, não fazem análise de compra de ações e FIIs.
- O roteiro `analise-trimestral` virou o **acompanhamento das teses**: a cada balanço, confere os gatilhos que
  quebrariam a tese, atualiza nota e preço e chama a análise completa quando falta tese.
- As **recomendações** distribuem o aporte pelo método de notas (peso-alvo proporcional à nota de qualidade, aporte
  nos ativos mais abaixo do peso, ativo caro espera o próximo aporte) e só sugerem venda com a tese quebrada. Preço
  alto sozinho não é mais motivo de venda.
- O ciclo completo não reanalisa mais por oscilação de preço, só por balanço, aviso ou fato novo.

### Adicionado
- **Configurações › Aparência**: tema escuro (padrão), claro ou o do sistema, e abrir com os valores escondidos.
- Modo discreto: o olho da barra do topo borra todo valor em reais, até nos gráficos.
- Ícone por categoria nas listas; categoria criada por você ganha um ícone escolhido numa grade.
- Ícones Lucide embutidos (`app/static/icons.svg`, gerado por `packaging/icones.py`), sem depender de internet.
- **Análise completa de um ativo para o longo prazo** (roteiro `analise-ativo`, prompt `analise_ativo`), inspirada no
  método de Raul Sena (Investidor Sardinha): pesquisa profunda (RI, Formulário de Referência, CVM, B3, notícias,
  concorrentes e setor), filtro de entrada, checklist de qualidade com 11 perguntas e nota (sim − não), dez anos de
  números, leitura de Philip Fisher, preço por margem de segurança e o que quebraria a tese. Grava a tese no app
  (`kind: "tese"`), que vale 12 meses. Modelo em `docs/agentes/modelo-relatorio-tese.md`.
- **Dez anos de balanço anual** da CVM (DFP) para a análise de longo prazo: `fundamentos contexto` traz `anos`, com
  a série por exercício e o resumo (CAGR de 5 e 10 anos, ROE médio, anos com lucro ou prejuízo). A primeira
  atualização depois de instalar baixa os anos antigos e demora mais; depois, o cache segura.
- **Página do ativo** mostra a tese de longo prazo em destaque, com o papel na carteira (núcleo, complementar ou
  evitar novos aportes), o acompanhamento mais recente logo acima e o aviso de tese vencida (mais de um ano).
- **Horizonte e objetivo do investidor** em **Investimentos › Metas** (5 a 10, 10 a 20 ou mais de 20 anos; renda,
  crescimento ou os dois). As análises da IA perguntam antes de começar e guardam a resposta, por titular. Para
  agentes: `perfil_investidor` e `perfil_definir` no MCP, `financas perfil mostrar|definir` na CLI e `perfil` em
  `carteira contexto`.

### Corrigido
- `fundamentos contexto` não quebra mais para empresa cadastrada que ainda não tem balanço trimestral.

## [0.13.0] - 2026-09-30

### Corrigido
- Mac Intel: o executável não abria o servidor MCP (biblioteca de criptografia compilada contra outro OpenSSL).
  O build agora usa o pacote pronto, com o OpenSSL embutido.

### Adicionado
- Servidor MCP: conecte o seu agente de IA (Claude Desktop, Claude Code, Codex, Cursor, VS Code, Gemini CLI) ao
  Tabimoney e use a IA em qualquer conversa e em qualquer pasta, sem terminal e sem chave de API. O agente lê
  gastos, orçamento, carteira e metas e grava análises, recomendações e correções de categoria, com as mesmas
  proteções do app. O servidor vem dentro do executável (`Tabimoney.exe mcp`).
- **Configurações › Conectar à IA**: para cada agente, a situação (conectado, caminho antigo, último uso), o botão
  **Conectar**, que grava a configuração do agente (com cópia do arquivo antes), e a conexão à mão (ícone `</>`),
  com o comando ou o trecho da configuração. Se nada funcionar, **Configurar pela própria IA** traz um texto para
  colar na conversa, e a própria IA configura a conexão.
- Os roteiros (ciclo completo, gastos, orçamento, metas, análise trimestral e recomendações) chegam a qualquer
  agente pelo servidor: como comandos (no Claude Code, `/mcp__tabimoney__ciclo`) e pela ferramenta `roteiro`.
- Pela IA, o app faz backup sozinho antes da primeira mudança de cada conversa, e cada análise, regra ou
  recomendação guarda o nome do agente que a gravou.
- A entrada `tabimoney-demo` liga a IA à demonstração, para testar um pedido sem tocar nos seus dados.
- Ao abrir, se o executável mudou de pasta, o app corrige o caminho nas conexões que ele mesmo gravou.
- CLI: `financas mcp` (sobe o servidor), `financas mcp clientes`, `financas mcp config --cliente X` e
  `financas mcp instalar --cliente X [--demo]`. `financas gastos listar --deslocamento N` para paginar, e a
  resposta traz `proximo_deslocamento` quando há mais lançamentos.

### Alterado
- Configurações de cara nova, no padrão de app de configuração: as seções (Geral, Open Finance, Titulares,
  Mercado, Conectar à IA e Atualizações) ficam num menu à esquerda e abrem uma de cada vez; cada ajuste é uma linha
  com o valor e a ação; editar abre uma janela; e as explicações saíram da tela e ficaram no **?** ao lado de cada
  título. Os interruptores (cotações diárias, aviso de versão nova) salvam na hora, sem botão.
- A pasta da IA (`%USERPROFILE%\Tabimoney`, `~/Tabimoney` no Mac) entrou em transição para o MCP: o `AGENTS.md`
  indica **Conectar à IA**, os roteiros ficam em `roteiros/` com uma tabela ferramenta → comando, e as skills
  antigas (`.claude/skills/financas*`) são apagadas. O `financas.bat` da pasta continua funcionando.

### Descontinuado
- A pasta da IA sai numa versão futura; use o servidor MCP.

### Removido
- As skills `.claude/skills/financas*` do repositório. Os roteiros passaram para `app/agente/roteiros/`, a fonte
  única que o servidor MCP e a pasta da IA usam.

### Interno
- As operações dos agentes saíram de `app/cli.py` para `app/agente/operacoes.py`; a CLI e o servidor MCP
  (`app/mcp_server/`) chamam as mesmas funções. Dependência nova: `mcp` (SDK oficial, 2.x).
- Testes do servidor: catálogo e anotações das ferramentas, mesma resposta da CLI, importação dos exemplos,
  backup automático, autoria, tarefas longas, roteiros, prompts, resources, tamanho das respostas, nenhum segredo
  nas respostas e o servidor por stdio num processo à parte. Testes da conexão com cada agente, da tela (também
  no navegador) e de `financas mcp`. Nos testes, as configurações dos agentes ficam no home falso, e `claude` e
  `codex` nunca rodam de verdade.

## [0.12.0] - 2026-09-29

### Adicionado
- Demonstração: o botão **Ver demonstração** na visão geral abre o app com dados fictícios de um casal (Lucas e
  Marina), com todas as telas preenchidas. A demo fica numa base separada e usa um cofre de senhas próprio: seus
  dados não aparecem nela e nada do que você fizer na demo chega a eles. Uma faixa no topo lembra que é a demo e
  tem **Recomeçar** e **Sair da demo**. Sincronizar, atualizar mercado, backup e restauração ficam desligados na
  demo. A demo se refaz sozinha a cada dia e a cada versão, então as datas estão sempre atuais.
- CLI: `financas --demo <comando>` roda qualquer comando na demonstração, para testar roteiros de agentes sem
  dados reais.
- Gestão a dois (ou mais): em **Configurações › Titulares**, cadastre quem mais tem contas conectadas. Cada Item
  ID tem um titular, e as contas de quem não é o titular principal ganham o sufixo " · Nome" (ex.:
  "Nubank Cartão · Ana"). Com mais de um titular, o menu lateral mostra o seletor **Casa / cada pessoa**, que
  filtra todas as telas. Metas de gastos continuam sendo da casa.
- Metas de alocação por titular: na visão de uma pessoa, salvar as metas cria metas só dela, e **Usar as metas
  da casa** desfaz.
- Várias conexões Pluggy: cada conexão tem Client ID e Secret próprios (quando cada pessoa tem o próprio app no
  Dashboard Pluggy). Uma conexão com falha não impede as outras. A conexão que já existia vira a "Principal",
  com as mesmas credenciais.
- Pix entre titulares: com o CPF de cada titular (opcional, guardado só como código), o Pix de um para o outro
  vira "Transferência entre titulares", que fica fora de receitas e despesas. Sem CPF, um Pix que sai da conta de
  um titular e entra na do outro com o mesmo valor em até 1 dia também é conciliado. Quando a Pluggy informa o
  CPF do dono do item, ele é preenchido sozinho.
- CLI: `financas titulares` lista titulares, conexões e as contas de cada um. `financas --titular Ana <comando>`
  restringe carteira, metas e gastos a uma pessoa. Os lançamentos passam a trazer o campo `titular`.

### Corrigido
- Dois titulares no mesmo banco apagavam dados um do outro: as contas ganhavam o mesmo nome ("Nubank /
  NuInvest", "Nubank Cartão"), a posição de um ativo que os dois tinham ficava só com a de um, e o saldo de um
  dos cartões sumia.
- Com o Nubank de outro titular conectado, o extrato importado por arquivo deixava de ser vinculado ao Nubank do
  titular principal e podia ser contado em dobro.
- Na Conciliação, no celular, o caminho da base estourava a largura da tela.

### Alterado
- Configurações: o Open Finance ganhou formulários próprios por conexão. Os Item IDs saíram da configuração
  `pluggy_item_ids` e foram para a tabela `pluggy_item` (migração 009, automática).

### Interno
- Testes automatizados (pytest, `tests/`), sem mudança para quem usa o app:
  - abrem todas as páginas com a base vazia e com dados de exemplo;
  - cobrem os formulários principais, as categorias, o aviso de versão, a linha de comando e o comportamento em
    Windows e Mac;
  - cobrem os bugs já corrigidos: compras da fatura aberta, compras em dólar e página com variável faltando.
  Rodam isolados (base temporária, cofre falso, sem rede). No GitHub Actions, rodam em Windows e Mac antes do
  build, e nenhum executável é gerado se algum falhar.
- Testes de navegador (Playwright, `tests/e2e`): sobem o app de verdade com dados de exemplo e conferem menus,
  gráficos, erros de JavaScript, formulários de titulares, conexões, metas e categorias, e a largura no celular.
- Fluxo de branches: o trabalho vai para a `dev`, e o workflow **Testes** (pytest em Windows e Mac e navegador no
  Linux) roda a cada push e em todo PR. A `main` só recebe merge com o check **Testes ok** passando.
- Lançamento automático: o merge na `main` gera os executáveis e, se a versão de `app/__init__.py` ainda não
  tiver tag, cria a tag `vX.Y.Z` e publica o Release. Sem seção `## [X.Y.Z]` no CHANGELOG, o lançamento para com
  erro.

## [0.11.0] - 2026-09-24

### Adicionado
- Aviso de versão nova: ao abrir e a cada 12 horas, o app consulta o último Release no GitHub e, se houver versão
  mais nova, mostra uma faixa no topo com **Baixar** (o zip do sistema do usuário), **Ver novidades** e
  **Dispensar**. Em Configurações › Atualizações dá para desligar o aviso, ver a última verificação e
  **Verificar agora**. Nenhum dado do usuário é enviado.

## [0.10.0] - 2026-09-24

### Adicionado
- Página de cada categoria de gasto (`/contas/gastos/<categoria>`), aberta ao clicar na categoria em "Gasto por
  categoria, mês a mês" ou em "O que mudou":
  - gasto por mês com a média de 12 meses e projeção do mês corrente;
  - ritmo do mês (acumulado dia a dia contra o mês passado e a média de 3 meses);
  - gasto por dia da semana, estabelecimentos (compras, meses, ticket médio) e maiores compras;
  - observações automáticas (ritmo, tendência, concentração, frequência e ticket);
  - metas que incluem a categoria e todos os lançamentos, com troca de categoria ali mesmo.

- Categorias próprias: criar, excluir e restaurar em Conta e cartão (cartão "Categorias") e na CLI
  (`gastos criar-categoria | excluir-categoria | restaurar-categoria`).
  - Criar é idempotente: o nome é comparado sem acento e sem caixa, então "delivery" e "Delivery" são a mesma.
  - Excluir uma categoria com lançamentos, regras ou metas exige escolher o destino: Outros (padrão), outra
    categoria ou a categoria automática de cada lançamento. Tudo muda numa transação só. Uma meta que fica vazia
    é removida.
  - A exclusão guarda o que foi movido, e "Restaurar" devolve.
  - As categorias padrão não podem ser excluídas.
  - Migração `008_categories`.

- `Tabimoney.exe`: executável de arquivo único, com Python dentro, gerado por `build.bat` (PyInstaller).
  Serve para quem não vai mexer no código.
  - Dois cliques abrem o app; clicar de novo reinicia. O app aberto recebe um pedido de encerramento
    autenticado por token e, se não responder, o processo é finalizado.
  - O servidor roda em segundo plano, sem janela, com log em `%LOCALAPPDATA%\FinancasPessoais\logs`.
  - `Tabimoney.exe cli …` é a mesma linha de comando do `financas.bat`.
  - Pasta da IA em `%USERPROFILE%\Tabimoney` (AGENTS.md, skills, contrato e um `financas.bat` que chama o exe),
    recriada a cada abertura, para usar o Claude Code sem clonar o repositório.
- Versão para Mac (Apple Silicon e Intel): `Tabimoney.app`, com o mesmo comportamento do exe.
  - Chaves no Porta-chaves (Keychain) do macOS e dados em `~/Library/Application Support/Tabimoney`.
  - Reinício ao abrir de novo e erros mostrados numa caixa de diálogo, já que o app abre sem terminal.
  - Pasta da IA em `~/Tabimoney`, com `financas.sh`.
  - `run.command` e `financas.sh` para rodar pelo código.
- GitHub Actions (`executaveis.yml`): gera e testa as versões Windows, Mac Apple Silicon e Mac Intel a cada push
  que mexe no app. Numa tag `vX.Y.Z`, publica o Release com os três zips (app, LEIA-ME e manual).
- Manual de conexões (`Manual-de-conexoes.html`, dentro do zip de distribuição): passo a passo ilustrado para
  criar as chaves do Meu Pluggy e da brapi, colar no app e resolver os erros mais comuns. É um arquivo HTML só,
  com a marca do Tabimoney, que abre offline e pode ser salvo em PDF pelo navegador. As capturas têm os dados
  pessoais cobertos (`packaging/manual/redigir.py`).
- Botão "Encerrar o Tabimoney" no menu lateral, quando o app foi aberto pelo exe ou pelo `run.bat`.

### Alterado
- `run.bat` abre o app como o exe: servidor em segundo plano, e clicar de novo reinicia. O modo antigo, com o
  log na janela, é `python -m app.launch --primeiro-plano`.
- Depois de salvar ou excluir algo (metas, regras, categoria de um lançamento), a página volta na mesma posição
  de rolagem, e o aviso aparece fixo no canto da tela.

### Corrigido
- Cartões lado a lado ficavam desalinhados em todas as páginas: o segundo terminava 16px acima do primeiro,
  por uma margem que só devia valer para cartões empilhados.
- Compras no cartão em moeda estrangeira (ex.: assinaturas em dólar) entravam com o valor em dólar como se fosse
  real. Agora entram pelo valor em reais convertido na data da compra (`amountInAccountCurrency` da Pluggy). O
  valor original aparece embaixo, nas tabelas de lançamentos, e na CLI (`moeda_original`, `valor_original`).
  Migração `007_foreign_currency`. A próxima sincronização corrige os lançamentos antigos.
- Compras no cartão da fatura ainda aberta (`PENDING` no Open Finance) passam a entrar nos gastos, no orçamento
  e no fluxo de caixa. Antes só apareciam depois que a fatura fechava, e o mês corrente ficava subestimado.
  Parcelas futuras continuam de fora até a data delas.

## [0.9.0] - 2026-09-23

### Adicionado
- Metas de gastos por grupo de categorias, com limite mensal e aviso (80% do limite ou ritmo de estouro).
  Inclui meta opcional de gasto total do mês.
- Bloco "Orçamento do mês" no topo de Conta e cartão:
  - quanto já foi gasto e quanto ainda cabe por dia;
  - projeção do mês e situação de cada meta (no ritmo, em risco, estourou);
  - histórico dos últimos 6 meses por meta;
  - categorias ainda sem meta.
- Metas sugeridas pela média dos últimos 3 meses, criadas com um clique quando o usuário ainda não tem metas.
- Recomendações orçamentárias do agente de IA: criar, ajustar ou remover metas e ações de economia, com economia
  estimada. Aparecem em Recomendações e em Conta e cartão, e cada sugestão se aplica com um clique.
- CLI `financas orcamento mostrar | contexto | definir | remover | importar-recomendacoes`.
- Skill `financas-orcamento`; a análise orçamentária entrou no ciclo completo (`financas-ciclo`).
- Versionamento: `app.__version__`, versão no rodapé do menu, `financas --version`, este changelog e
  `docs/versionamento.md`.

### Alterado
- A página Recomendações agora reúne o orçamento do mês e a carteira do trimestre.
- A visão geral mostra o uso do orçamento no card de receitas e despesas.

### Segurança
- Exemplos do código e da documentação deixam de citar empresa e estabelecimentos reais do autor.

## [0.8.0] - 2026-09-23

### Alterado
- Nova identidade visual Tabimoney — finanças sérias (mais ou menos):
  - paleta verde sobre fundo escuro, fonte Inter servida localmente;
  - mascote no menu, ícones do app e do navegador (favicon, ícone da Apple, manifesto);
  - saudação na visão geral.

## [0.7.0] - 2026-09-23

### Adicionado
- `financas atualizar`: backup, Open Finance, cotações, CDI e balanços da CVM em um comando.
- Skill `financas-ciclo`: atualiza os dados, analisa, recomenda e resume a partir de uma frase ("atualize minhas finanças").

## [0.6.0] - 2026-09-23

### Adicionado
- Metas de alocação: reserva de emergência, renda fixa × variável, exposição internacional e plano de aporte
  sem vender.
- Relatórios completos do agente em Markdown, com histórico por trimestre na página de cada ativo e a tela
  Análises. Também para renda fixa, previdência e a carteira toda.
- Recomendações trimestrais: mudanças na carteira atual e carteiras-modelo.
- Skills por tarefa e guias para agentes (`AGENTS.md`, `docs/agente-financeiro.md`, `docs/agentes/`).

## [0.5.0] - 2026-09-23

### Adicionado
- Gasto por categoria mês a mês e "o que mudou", com os lançamentos que puxaram cada variação.
- Recategorização por lançamento e regras "descrição contém X → categoria", mantidas entre sincronizações.
- Fundamentos a partir das demonstrações oficiais da CVM (ITR/DFP): P/L, P/VP, EV/EBITDA, ROE, margens, dívida,
  dividend yield e outros indicadores, com avisos por regras.
- CLI `financas` com saída em JSON para uso por agentes de IA.

## [0.4.0] - 2026-09-23

### Adicionado
- Tela Proventos e CDI: proventos creditados, identificados pelo ativo, e rendimento do saldo em conta pelo CDI
  diário do Banco Central (estimado ou medido entre saldos reais).
- O rendimento do CDI entra como receita no fluxo de caixa.

## [0.3.0] - 2026-09-23

### Adicionado
- Previdência privada (PGBL/VGBL) lançada a partir do extrato, com rentabilidade no período contra o CDI.

## [0.2.0] - 2026-09-23

### Adicionado
- Vários bancos no Meu Pluggy (ex.: Nubank e Itaú), com a instituição detectada pelo código do banco.
- Conciliação de transferências entre contas próprias e de pagamento de fatura.

### Corrigido
- Sinal dos lançamentos de cartão: estornos e pagamentos contavam como despesa.
- Compra de ações classificada como gasto e proventos classificados como "Outros".
- Histórico do patrimônio sem saldo de caixa antes do primeiro saldo conhecido.
- Renda fixa exibida pelo valor líquido de IR no lugar do bruto.

## [0.1.0] - 2026-09-22

### Adicionado
- Primeira versão local: importação de OFX/CSV do Nubank e planilhas da B3.
- Meu Pluggy (Open Finance) e cotações diárias pela brapi.
- Carteira com preço médio e rentabilidade pelo método de cotas.
- Base SQLite local com backup e restauração.

[Não lançado]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.15.0...HEAD
[0.15.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.13.0...v0.15.0
[0.13.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Fishcake-Senpai/tabimoney-app/releases/tag/v0.10.0
[0.9.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Fishcake-Senpai/tabimoney-app/releases/tag/v0.1.0
