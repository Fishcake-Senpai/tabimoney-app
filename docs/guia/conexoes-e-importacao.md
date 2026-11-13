# Conexões e importação

Esta página explica de onde vêm os dados do Tabimoney: Open Finance, arquivos importados e APIs públicas. Também
cobre a gestão a dois e as regras de conciliação entre contas.

## Open Finance pelo Meu Pluggy

O Tabimoney não pede a senha do seu banco. Ele usa o **Meu Pluggy**, um serviço de Open Finance autorizado, e
guarda as credenciais no cofre do sistema.

### 1. Conecte os bancos no Meu Pluggy

1. Crie uma conta pessoal em [meu.pluggy.ai](https://meu.pluggy.ai).
2. Conecte cada banco (Nubank, Itaú, etc.) pelo fluxo de consentimento do Open Finance.
3. Renove o consentimento quando o próprio Meu Pluggy pedir. O serviço atualiza as conexões no ciclo diário dele.

### 2. Crie a aplicação no Dashboard Pluggy

1. Abra [dashboard.pluggy.ai](https://dashboard.pluggy.ai) e entre com a mesma conta.
2. Em **Aplicações › Novo**, crie uma aplicação sua (por exemplo, *Tabimoney*). Não use a *Pluggy Demo App*.
3. Na linha da sua aplicação, copie o **Client ID** e o **Client Secret**.
4. Clique em ▷, use **Conectar Conta › MeuPluggy** para cada banco e copie o **Item ID** de cada item conectado.

O `Manual-de-conexoes.html`, que vem dentro do zip de distribuição, mostra cada tela desse processo com capturas.

### 3. Configure no Tabimoney

1. Abra **Configurações**.
2. Na conexão **Principal**, informe o Client ID, o Client Secret e os Item IDs separados por vírgula.
3. Salve. O Client ID, o Client Secret e os Item IDs precisam ser da mesma aplicação.
4. No painel, clique em **Sincronizar** e escolha **Open Finance**.

Cada Item ID sincroniza separadamente: um item com falha não impede os demais. A instituição de cada item é
reconhecida pelo código do banco da conta.

## Gestão a dois

Cada pessoa conecta os próprios bancos no Meu Pluggy, porque o consentimento do Open Finance é dado pelo titular
da conta.

1. Em **Configurações › Titulares**, cadastre a outra pessoa. O CPF é opcional, mas ajuda a conciliar Pix.
2. Adicione os Item IDs dela escolhendo o titular.
3. Se ela tem o próprio app no Dashboard Pluggy, crie uma **Nova conexão** com o Client ID e o Secret dela. Se usa
   o mesmo app, basta colar os Item IDs na conexão Principal.

O que muda:

- As contas de quem não é o titular principal ganham o sufixo “ · Nome” (ex.: “Nubank Cartão · Ana”), então dois
  Nubank não se misturam.
- O seletor **Casa / cada pessoa** na barra do topo filtra todas as telas.
- Cada titular pode ter metas de alocação próprias. As metas de gastos são sempre da casa.
- O Pix entre titulares vira *Transferência entre titulares* e fica fora de receitas e despesas: pelo CPF dos dois
  lados ou, sem CPF, quando a saída de um e a entrada do outro têm o mesmo valor em até um dia.
- Arquivos importados (OFX, CSV, B3) entram como do titular principal.

## Como a sincronização trata os dados

- **Sinais:** toda saída é negativa e toda entrada é positiva, em conta e cartão. No cartão, a Pluggy manda compra
  positiva e pagamento/estorno negativo; o campo `type` (DEBIT/CREDIT) normaliza os dois casos.
- **Pendências:** movimentações bancárias `PENDING` são mantidas com esse estado e não entram na conciliação de
  saldo até a origem confirmá-las como `POSTED`. No cartão, `PENDING` é compra da fatura ainda aberta: entra nos
  gastos a partir da data da compra, e as parcelas futuras só na data delas.
- **Posições:** a sincronização consulta contas, movimentações, posições e operações de investimento que a conexão
  disponibilizar. A API da B3 para a Área do Investidor não tem acesso direto para pessoa física; a custódia usa o
  Open Finance ou a importação manual de posição.
- **Sincronização parcial:** se a Pluggy deixar de retornar ativos que já estavam registrados, o app marca a
  sincronização como parcial e preserva as posições anteriores.
- **Encerrar uma posição manual:** importe quantidade zero em uma data posterior ao último snapshot.

## Importar arquivos

A página **Importar** aceita vários arquivos de uma vez e detecta o formato sozinha. Reimportar o mesmo arquivo não
duplica nada.

| Arquivo | Onde baixar | O que entra |
|---|---|---|
| Extrato da conta, OFX | App Nubank › Extrato › exportar | Saldo e movimentações |
| Extrato da conta, CSV (`Data,Valor,Identificador,Descrição`) | App Nubank | Movimentações; o saldo é projetado a partir do último OFX |
| Fatura do cartão, CSV (`date,title,amount`) ou OFX | App Nubank › Fatura | Lançamentos, categoria e total da fatura |
| Posição B3, XLSX | Área do Investidor B3 › Extratos › Posição | Ações, FIIs, ETFs, BDRs, CDB/LCI/LCA e Tesouro |
| Negociação B3, XLSX | Área do Investidor B3 › Extratos › Negociação | Compras e vendas → preço médio e lucro realizado |
| Movimentação B3, XLSX | Área do Investidor B3 › Extratos › Movimentação | Dividendos, JCP, rendimentos, desdobros e bonificações |
| Modelo de renda fixa, CSV | Botão na página | Caixinhas/RDB e qualquer título fora da B3 |
| Modelos de operações, posições e cotações, CSV | Botões na página | Outras corretoras, preço médio inicial e preços manuais |

O Nubank não oferece um arquivo único com tudo. As Caixinhas/RDB não aparecem na B3 nem na exportação do app, então
vêm do Open Finance (Meu Pluggy) ou do modelo CSV. A custódia da NuInvest aparece na B3 com o mesmo apelido do Open
Finance (`Nubank / NuInvest`), e as duas origens são consolidadas sem contar em dobro.

## Regras de consolidação

- Por conta e ativo vale o snapshot de posição mais recente, somado às operações posteriores a ele.
- As operações vêm de uma única origem por prioridade: **Negociação B3**, depois **Movimentação B3**, depois **Open
  Finance**, depois **CSV**.
- Na renda fixa e nos saldos vale, por conta, a origem mais recente.
- Gastos com categoria *Investimentos*, *Pagamento de fatura*, *Transferência própria* ou *Transferência entre
  titulares* ficam fora de receitas e despesas.

## Conciliação entre contas

Uma saída de conta casa 1 a 1 com uma entrada de mesmo valor:

- em outra conta própria, em até 3 dias, quando um dos lados é transferência própria (CPF igual de pagador e
  recebedor ou rótulo da origem);
- no cartão, em até 5 dias, quando um dos lados é pagamento de fatura;
- entre contas de titulares diferentes, quando um dos lados é transferência entre titulares (CPFs cadastrados) ou,
  sem CPF, quando os dois lados são *Pix e transferências* em até 1 dia.

Os dois lados viram movimento interno. Assim o salário que cai no Itaú conta como receita uma vez só, e a TED para o
Nubank não vira despesa nem receita.

A página **Pendências** (o sino da barra do topo) lista as divergências, as transferências próprias sem o outro lado
(conta não conectada), os avisos dos ativos e, recolhidos, os pares conciliados.

## Mercado: cotações, Ibovespa e CDI

**Atualizar mercado** (ou o agendador depois das 19h30) grava o histórico diário de fechamentos da
[brapi](https://brapi.dev): 12 meses na primeira coleta e, depois, só o último mês. O Ibovespa também vem da brapi
e exige token; o plano gratuito basta.

O CDI vem da API pública do Banco Central (série SGS 12), sem chave. Sem token da brapi, poucos tickers são
liberados; os demais podem usar o preço de fechamento da Posição B3 ou o CSV de cotações.

## Credenciais e segurança

Client ID, Client Secret e token da brapi ficam no cofre de senhas do sistema via Keyring (Gerenciador de
Credenciais no Windows, Porta-chaves no Mac), separados do SQLite. O app cria uma chave de API Pluggy temporária
para sincronizar e não pede a senha do Nubank.

Para entender o que sai da máquina e quando, veja [Privacidade](../privacidade.md).
