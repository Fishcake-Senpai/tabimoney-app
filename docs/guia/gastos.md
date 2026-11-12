# Gastos e orçamento

O Tabimoney foi feito para responder três perguntas: **para onde foi o dinheiro**, **quanto ainda posso gastar** e
**o que mudou**. Esta página mostra onde cada resposta aparece.

## Início

A página inicial reúne o retrato do mês:

- patrimônio total e variação em 30 dias, com a evolução por total ou por classe;
- gastos do mês contra o orçamento e quanto ainda cabe por dia;
- total investido e a variação do dia;
- saldo em conta e fatura do cartão;
- últimos lançamentos;
- o que pede atenção no sino de **Pendências**.

Use o seletor **Casa / pessoa** no topo para ver só as contas de um titular. O ícone de olho esconde os valores.

## Gastos › Resumo

O resumo mostra o gasto do mês por categoria, com seletor de mês. Ao lado, **O que mudou** lista as categorias que
variaram mais de 15% e R$ 50 em relação à média recente.

O botão **Mês a mês** abre uma tabela com os últimos 6 meses fechados e o mês corrente, com:

- a variação do último mês contra a média dos 3 anteriores;
- a variação dos últimos 3 meses contra os 3 anteriores;
- o total de receitas, despesas e o que sobrou.

Em **Entrou e saiu** dá para comparar receitas e despesas em 6M, 12M, 24M, 36M ou todo o histórico.

## Lançamentos e categorias

Em **Gastos › Lançamentos**, clique em um lançamento para abrir o painel e trocar a categoria. A ordem de
prioridade é:

1. **escolha manual** — o que você definiu naquele lançamento;
2. **regra** — texto que contém algo (ex.: “UBER” → Transporte);
3. **categoria automática** — a sugestão do app.

Marcar **Usar sempre** cria a regra ali mesmo. As regras e as categorias próprias (com ícone) ficam em
**Configurações › Regras** e **Configurações › Categorias**. Nenhuma correção se perde em uma nova sincronização.

Categorias internas — *Investimentos*, *Pagamento de fatura*, *Transferência própria* e *Transferência entre
titulares* — não contam como receita nem como despesa.

## O que entra como receita

Receitas são entradas em conta com categoria **Salário**, **Proventos**, **Pix e transferências** ou **Outros**.
Qualquer outra entrada, como estorno no cartão, abate a despesa da categoria.

Compra e venda de ações, aplicações, resgates e previdência são *Investimentos* mesmo quando a origem as rotula como
compra. O dinheiro que apenas mudou de conta não vira receita nem despesa.

## Orçamento do mês

Em **Gastos › Orçamento**, cada meta mostra em um card:

- o que você gastou e o que ainda cabe por dia;
- a projeção do mês e a situação da meta: **no ritmo**, **em risco** ou **estourou**;
- o histórico dos últimos 6 meses;
- o que está sem meta.

Sem metas ainda, o app sugere limites pela média dos seus últimos 3 meses e cria todas com um clique. As metas de
gastos são da casa, mesmo com mais de um titular.

As recomendações do orçamento aparecem em **Sugestões**: ajustar, criar ou remover meta, ou onde economizar. Você
aplica com um botão; nada muda sozinho.

## Pendências e conciliação

O sino no topo abre **Pendências**:

- divergências entre saldo e movimentações;
- transferências próprias sem o outro lado (conta não conectada);
- avisos de fundamentos dos ativos;
- pares conciliados, recolhidos.

O app casa saídas e entradas de mesmo valor entre contas próprias e cartões. O que não fecha fica listado para você
resolver. As regras completas estão em [Conexões e importação](conexoes-e-importacao.md#conciliação-entre-contas).

## Relatório do período

O botão **Relatório** em Gastos gera um HTML do mês, trimestre ou ano, que abre sozinho e funciona offline. O
relatório mascara contas e nomes em Pix; use `--sem-mascara` na linha de comando se quiser mostrar tudo. Também é
possível tirar o extrato com `--sem-extrato`.

```bash
financas.bat relatorio exportar --periodo mes
financas.bat relatorio exportar --periodo trimestre --referencia 2026-07
```

## Dicas

- **Corrija na origem:** uma regra bem-feita evita dezenas de correções futuras.
- **Compare com a média, não com o mês passado:** um mês atípico distorce a leitura; o app usa 3 meses como base.
- **Use o orçamento como limite, não como culpa:** a projeção serve para você decidir antes do fim do mês.
- **Feche o mês:** confira as pendências antes de comparar os meses.

Para conectar os bancos e importar arquivos, veja [Conexões e importação](conexoes-e-importacao.md). Para as metas de
investimento, veja [Investimentos](investimentos.md).
