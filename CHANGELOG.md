# Changelog

Todas as mudanças relevantes do Tabimoney ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e as versões seguem o
[Versionamento Semântico](https://semver.org/lang/pt-BR/). As regras de numeração e o passo a passo de
lançamento estão em [docs/versionamento.md](docs/versionamento.md).

Enquanto a versão for `0.x`, o projeto está em desenvolvimento inicial: versões novas podem mudar o esquema da
base (sempre por migração automática) e o contrato da CLI.

## [Não lançado]

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

[Não lançado]: https://github.com/Fishcake-Senpai/tabimoney-app/compare/v0.11.0...HEAD
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
