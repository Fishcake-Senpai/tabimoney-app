# Investimentos

A área de **Investimentos** reúne a carteira, os fundamentos das empresas, as metas de alocação e as análises dos
ativos. Esta página explica o que cada tela mostra e como os números são calculados.

## Resumo

A aba **Resumo** traz:

- total investido e evolução no tempo;
- alocação por classe contra as metas;
- **Onde aportar**, com o valor sugerido para o próximo aporte;
- maiores variações do dia.

O total inclui ações, FIIs, ETFs, BDRs, renda fixa, previdência e caixinhas. O caixa em conta entra no
patrimônio, mas não no total investido.

## Ações e FIIs

A aba **Ações e FIIs** mostra:

- valor de mercado e variação do dia;
- resultado não realizado, em reais e em percentual;
- lucro realizado;
- proventos dos últimos 12 meses, dividend yield e yield on cost;
- rentabilidade pelo método de cotas (TWR, com proventos) em 1M, 3M, 6M, ano, 12M e desde o início, contra CDI e
  Ibovespa;
- volatilidade anualizada, queda máxima e concentração nos 5 maiores;
- rentabilidade mês a mês;
- valor de mercado contra o capital aplicado.

Ao abrir um ativo, você vê o preço médio, o peso na carteira, o retorno em 1, 3 e 12 meses, a distância da máxima de
52 semanas, o gráfico de preço com a linha do preço médio e o histórico de eventos (proventos, desdobros,
bonificações e operações).

O preço médio segue o padrão da Receita: vendas não alteram o preço médio. Quando a quantidade operada difere da
custódia, o preço médio é marcado como **estimado**.

## Fundamentos

Em **Investimentos › Ações e FIIs › Fundamentos › Atualizar fundamentos**, o app baixa da CVM — dados abertos, sem
chave — as demonstrações trimestrais (ITR) e anuais (DFP) das empresas da carteira dos últimos 3 anos. Os arquivos
ficam em cache na pasta de dados, em `cvm\`, e são conferidos semanalmente, inclusive de forma automática com o app
aberto.

Da brapi gratuita vêm valor de mercado, setor e descrição. O plano pago não é necessário.

Indicadores calculados com os últimos 12 meses e o preço do dia:

- P/L, P/VP, EV/EBIT e EV/EBITDA;
- dividend yield e payout (dividendos e JCP efetivamente pagos);
- ROE, ROA e margens;
- dívida líquida/EBITDA e dívida líquida/PL;
- crescimento de receita e lucro;
- FCF yield.

Bancos e seguradoras não têm os indicadores de dívida e EBITDA. Units (ex.: ALUP11) usam a composição informada à
CVM para o valor de mercado. ETFs e FIIs ficam de fora.

Regras simples geram avisos:

- prejuízo;
- lucro ou receita caindo;
- ROE baixo ou caindo;
- margem caindo;
- dívida alta ou subindo;
- payout acima de 100%;
- P/L muito baixo com ROE alto (possivelmente barata);
- P/L acima de 25 (cara).

**Visto** esconde o aviso até o próximo balanço.

## Renda fixa

A aba **Renda fixa** mostra valor bruto e líquido de IR, rendimento sobre o valor aplicado, vencimentos e
distribuição por tipo. Caixinhas e RDB entram pelo Open Finance ou pelo modelo CSV; CDB, LCI, LCA e Tesouro também
podem vir da Posição B3.

O patrimônio usa a renda fixa pelo **valor bruto**. O imposto regressivo é considerado na visão líquida e no resgate.

## Previdência (PGBL/VGBL)

Previdência privada é produto de seguradora (SUSEP) e fica no Open Insurance, não no Open Finance. A Pluggy não a
devolve, e a contribuição descontada em folha também não passa pela conta.

Na aba **Previdência**, registre o saldo do extrato do banco sempre que quiser atualizar:

- saldo bruto;
- total contribuído;
- saldo líquido de IR, se quiser.

Lançar de novo na mesma data corrige o saldo. O valor entra no patrimônio e na alocação como **Previdência**,
separado da renda fixa.

Entre dois extratos, o valor segue em linha reta. Antes do primeiro, vai do valor contribuído (na data de início do
plano) até o saldo. A rentabilidade no período encadeia os intervalos entre extratos, desconta as contribuições de
cada intervalo e é comparada ao CDI.

Se um dia o Open Finance trouxer o plano, ele é gravado como **Previdência**. Nesse caso, apague os lançamentos
manuais do mesmo plano para não contar em dobro.

## Proventos e CDI

A aba **Proventos e CDI** mostra a renda passiva:

- proventos creditados na conta, ligados ao ativo quando há um evento de mesmo valor em até 5 dias;
- rendimento do saldo parado.

O Nubank não lança o rendimento no extrato; ele só aparece no saldo. Por isso o app calcula com o CDI diário oficial
do Banco Central (série SGS 12, baixado junto com o mercado):

- **Estimado:** saldo do dia anterior × CDI do dia × % do CDI da conta. O padrão é Nubank 100% e demais 0%; você
  ajusta na aba.
- **Medido:** entre dois saldos reais do Open Finance, rendimento = saldo final − saldo inicial − movimentações. A
  estimativa do intervalo é ajustada para bater com o medido. Se o medido sair do esperado, fica a estimativa.
  Sincronizar todo dia deixa os meses medidos.

O rendimento entra como receita (*Rendimentos*) em receitas e despesas, um lançamento por conta e mês. O caixa já o
inclui, porque vem do saldo real; na reconstrução do histórico, o juro é descontado dia a dia para não ser atribuído
ao passado. Os valores são brutos: o IR regressivo é cobrado no resgate.

## Metas e balanceamento

Em **Investimentos › Metas** (botão **Editar metas**), defina:

- a reserva de emergência em reais;
- a divisão entre renda fixa e renda variável, em % do que sobra além da reserva;
- quanto da renda variável fica no exterior;
- se a previdência conta como renda fixa.

A tela mostra onde você está contra cada meta, avisa desvios de 5 pontos percentuais ou mais e calcula para onde vai
o próximo aporte, **sem vender nada**: primeiro completa a reserva, depois reforça as classes abaixo da meta. O valor
sugerido é a média de sobra dos últimos 3 meses.

- **Reserva:** caixa em conta menos a fatura em aberto. O excedente conta como renda fixa, e a previdência também,
  se você marcar.
- **Internacional:** BDRs e ETFs de índice externo (IVVB11, NASD11, QBTC11…) são internacionais por padrão; dá para
  corrigir ativo por ativo.

O **perfil do investidor** (horizonte e objetivo) fica na mesma tela. Ele vale por titular e é a primeira pergunta
das análises de longo prazo; sem perfil ou com mais de 12 meses, o agente pergunta antes de analisar.

## Análises e recomendações

- **Página de cada ativo:** mostra a análise mais recente do agente completa (Markdown com tabelas e checklist) e o
  histórico dos trimestres anteriores.
- **Análises:** lista todos os relatórios, inclusive de renda fixa, previdência e da carteira.
- **Sugestões:** traz as recomendações do orçamento e, por trimestre, as mudanças sugeridas na carteira atual
  (ação, peso sugerido, convicção, preço justo e justificativa) e carteiras-modelo com o seu perfil, indicando
  quanto de cada uma você já tem. As versões anteriores ficam no histórico.

Os roteiros e o formato dos relatórios estão em [IA e MCP](ia.md) e no
[contrato com agentes](../agente-financeiro.md).

## Como o histórico do patrimônio é reconstruído

Antes do primeiro saldo conhecido:

- o saldo de cada conta e cartão é reconstruído subtraindo as movimentações;
- a quantidade de cada ativo é reconstruída desfazendo as operações;
- a renda fixa segue em linha reta do valor aplicado (na data de aplicação) até a primeira fotografia.

O patrimônio desconta a fatura do cartão em aberto e usa a renda fixa pelo valor bruto. Quando falta um extrato
antigo, o app avisa que o histórico começa na data disponível.

## Relatório do período

O relatório em HTML do mês, trimestre ou ano também inclui investimentos, proventos e evolução do patrimônio.
Veja [Gastos e orçamento](gastos.md#relatório-do-período).
