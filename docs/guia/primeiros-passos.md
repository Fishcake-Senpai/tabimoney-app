# Primeiros passos

Este guia cobre a primeira sessão: ver a demonstração, conectar os bancos (ou importar arquivos) e entender onde
cada coisa fica.

## Antes de tudo: veja a demonstração

A demonstração é a melhor forma de conhecer o app sem conectar nada. Ela usa uma base separada, com um casal
fictício — Lucas e Marina — e todas as telas preenchidas: contas, cartões, carteira, renda fixa, previdência,
metas, análises e recomendações.

Na primeira abertura, o Início mostra o botão **Ver demonstração**. Você também encontra a opção em
**Configurações › Geral**.

- **Seus dados não aparecem na demonstração** e nada do que você fizer nela chega aos seus dados.
- **Recomeçar** volta a demonstração ao original.
- **Sair da demo** volta aos seus dados.
- Pela linha de comando: `financas --demo carteira contexto`.

Enquanto estiver na demo, uma faixa no topo lembra que os dados são fictícios.

## Conecte seus bancos

O caminho recomendado é o **Open Finance pelo Meu Pluggy**. É o mesmo consentimento que você daria a um app de
banco, mas os dados são gravados apenas neste computador.

1. Crie uma conta pessoal no [Meu Pluggy](https://meu.pluggy.ai) e conecte cada banco (Nubank, Itaú, etc.).
2. No [Dashboard Pluggy](https://dashboard.pluggy.ai), crie uma aplicação sua e copie o **Client ID** e o
   **Client Secret**.
3. Conecte cada conta em **Conectar Conta › MeuPluggy** e copie o **Item ID** de cada item.
4. No Tabimoney, abra **Configurações**, preencha a conexão **Principal** com o Client ID, o Client Secret e os
   Item IDs separados por vírgula, e salve.
5. No painel, clique em **Sincronizar**.

O passo a passo ilustrado, com capturas de tela, é o `Manual-de-conexoes.html` que vem dentro do zip de
distribuição. Os detalhes de cada campo e a gestão a dois estão em
[Conexões e importação](conexoes-e-importacao.md).

## Não quer conectar o banco agora?

A página **Importar** aceita vários arquivos de uma vez e reconhece o formato sozinha. É possível começar com:

- extrato da conta em OFX ou CSV;
- fatura do cartão em CSV ou OFX;
- posição, negociação e movimentação da B3 em XLSX;
- modelos CSV de renda fixa, operações, posições e cotações.

Reimportar o mesmo arquivo não duplica nada. A tabela completa está em
[Conexões e importação](conexoes-e-importacao.md#importar-arquivos).

## Sua rotina

| Quando | O que fazer |
|---|---|
| Todo dia (ou quando abrir) | Clique em **Sincronizar** no topo. O agendador também busca cotações depois das 19h30 enquanto o app estiver aberto. |
| Uma vez por mês | Veja **Gastos › Resumo**, ajuste categorias e confira o **Orçamento**. |
| A cada aporte | Consulte **Investimentos › Metas** para ver onde o próximo aporte faz diferença. |
| A cada balanço | Rode a análise trimestral dos ativos que você acompanha. |
| Em março e abril | Abra **Imposto de renda** e confira a estimativa e a declaração. |

## Onde fica cada coisa

| Menu | Para quê |
|---|---|
| **Início** | Patrimônio, variação, gastos do mês, investimentos, saldo em conta, últimos lançamentos e o que pede atenção. |
| **Gastos** | Resumo por categoria, lançamentos, orçamento e relatório do período. |
| **Investimentos** | Carteira, ações e FIIs, renda fixa, previdência, proventos e metas. |
| **Sugestões** | Recomendações do orçamento e da carteira, prontas para aplicar. |
| **Imposto de renda** | Estimativa, ações e fundos, deduções e declaração. |
| **Configurações** | Conexões, titulares, categorias, regras, atualizações, tema e conexão com a IA. |
| **Importar** | Arquivos, backup e restauração. |

O sino no topo abre **Pendências**: divergências de conciliação, transferências próprias sem o outro lado, avisos
dos ativos e atualizações.

## Dicas para começar bem

- **Esconda os valores** com o ícone de olho quando estiver em um lugar público. O app lembra a preferência.
- **Cadastre a outra pessoa da casa** em **Configurações › Titulares** antes de conectar as contas dela. O seletor
  **Casa / pessoa** no topo filtra todas as telas.
- **Corrija categorias uma vez:** ao trocar a categoria de um lançamento, marque **Usar sempre** para criar uma
  regra. Sincronizações futuras não desfazem a correção.
- **Defina as metas de gastos** em **Gastos › Orçamento**. Sem metas, o app sugere limites pela média dos últimos
  três meses.
- **Conecte a IA** em **Configurações › Conectar à IA** se quiser pedir análises e correções em linguagem natural.

## Próximos passos

- [Conexões e importação](conexoes-e-importacao.md) — como os dados entram e como as contas são conciliadas.
- [Gastos e orçamento](gastos.md) — como ler o resumo e criar metas.
- [Investimentos](investimentos.md) — carteira, fundamentos e metas de alocação.
- [Imposto de renda](imposto-de-renda.md) — estimativa e declaração.
- [IA e MCP](ia.md) — conecte seu agente.
