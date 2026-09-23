# Finanças Pessoais — aplicação local

Aplicativo pessoal para acompanhar saldos do Nubank, posições de investimento e cotações diárias. A interface abre no navegador, mas o servidor aceita conexões somente em `127.0.0.1`. O banco SQLite fica no perfil local do Windows; não há GitHub, hospedagem ou cópia de dados na nuvem.

As chamadas autorizadas do Open Finance e da fonte de preços saem desta máquina para os provedores correspondentes. O banco e os dados normalizados permanecem locais.

## Iniciar

1. Instale Python 3.11 ou mais recente para Windows e mantenha o launcher `py` habilitado.
2. Execute `run.bat` com duplo clique.
3. Na primeira execução, o script cria `.venv`, instala as dependências e abre `http://127.0.0.1:8765`.
4. Para encerrar, volte à janela do aplicativo e pressione `Ctrl+C`.

O agendador diário de preços roda enquanto o aplicativo estiver aberto. Por padrão, ele tenta buscar os fechamentos depois de 19h30 (horário de Brasília). Também é possível atualizar manualmente no painel.

## Conectar o Nubank pelo Meu Pluggy

1. Crie uma conta pessoal no [Meu Pluggy](https://meu.pluggy.ai) e conecte o Nubank pelo fluxo de consentimento do Open Finance.
2. Siga o [guia oficial de acesso via API](https://meu.pluggy.ai/api-guide): no Dashboard Pluggy, conecte o item do Meu Pluggy na aplicação demo e obtenha o `Client ID`, o `Client Secret` e o `Item ID` proxy.
3. Abra **Configurações** no aplicativo, informe esses valores e salve.
4. No painel, escolha **Sincronizar Open Finance**.

Client ID, Client Secret e token da brapi são guardados no Credential Manager do Windows via Keyring. A aplicação cria uma chave de API Pluggy temporária para a sincronização e não pede senha do Nubank. O Meu Pluggy mantém seu consentimento e atualiza as conexões no ciclo diário do próprio serviço.

A sincronização consulta contas, movimentações, posições e operações de investimento que a conexão disponibilizar. A API B3 para a Área do Investidor não tem acesso direto para pessoa física; a custódia do MVP usa o que vier pelo Open Finance ou a importação manual de posição. Consulte o [FAQ da B3 for Developers](https://developers.b3.com.br/faq).

Movimentações bancárias `PENDING` do Open Finance são mantidas com esse estado e não entram na conciliação de saldo até a origem confirmá-las como `POSTED`.

Se a Pluggy deixar de retornar ativos listados que já estavam registrados, a aplicação marca a sincronização como parcial e preserva as posições anteriores. Para encerrar uma posição manualmente, importe quantidade zero em data posterior ao último snapshot.

## Cotações

A integração inicial usa o histórico diário da [brapi](https://web-next.brapi.dev/docs/acoes), armazenando `close` sem ajuste e a data do pregão. Sem token, a documentação da brapi limita os tickers disponíveis; para sua carteira, configure o token no painel conforme a cobertura/limites da sua conta. O token nunca é enviado ao navegador.

O serviço busca uma cotação por ticker uma vez ao dia. Se um ativo não estiver coberto, se o token/limite impedir a consulta ou se a API estiver indisponível, o último preço local é mantido e o painel indica falha, cotação ausente ou preço antigo. Fechamentos também podem ser importados por CSV.

## Importações manuais

- **Extrato bancário:** no app Nubank, exporte o extrato em OFX e carregue em **Importações**. A aplicação guarda saldos e movimentações deduplicados por identificador; não persiste o número integral da conta. OFX e Open Finance são consolidados quando os nomes de conta exibidos coincidem; confira a lista do painel se o provedor omitir um dos sufixos da conta, pois a mesma conta pode aparecer duas vezes.
- **Posições iniciais:** use o modelo de posições para informar ticker, quantidade, data e, opcionalmente, nome da conta, classe e moeda. Se `account_name` ficar vazio, o padrão é `Nubank / NuInvest`, igual ao apelido usado pela integração Pluggy; as quantidades dessas duas origens são consolidadas para evitar contagem duplicada. Use nomes diferentes para posições em outra corretora. A importação é aditiva e não remove ativos que não vierem no arquivo: inclua `quantity=0` numa data mais recente para registrar a baixa. A primeira posição de cada ativo/conta vira a abertura da série de conciliação.
- **Fechamentos:** use o modelo de cotações para importar ticker, data do pregão e preço de fechamento.

Os CSVs aceitam vírgula ou ponto e vírgula como separador. Valores podem usar ponto decimal ou formato brasileiro (vírgula decimal). Datas devem estar no formato `AAAA-MM-DD`. Valores são gravados em centavos inteiros; quantidades, em milionésimos.

Este MVP ainda não calcula custo médio nem lucro/prejuízo não realizado; esses indicadores dependem de definir e validar uma base de custo histórica confiável. A variação diária exibida mede mudança de preço da posição atual e não é rentabilidade total ajustada por aportes e proventos.

Na área de conciliação, você pode registrar observações locais para uma pendência e marcá-las como resolvidas. As notas documentam sua decisão sem alterar os dados importados nem os cálculos das views.

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
