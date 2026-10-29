# Imposto de renda: apuração de ações e estimador anual

Data: 2026-10-19 · Estado: **implementada** (as cinco fases juntas), em `[Não lançado]`. Decisões na §C.4. Junta dois itens do `backlog.md`: "Conciliação de venda de
ações para o IR" (Parte A) e "Estimador de imposto de renda anual" (Parte B). Os dois dividem a mesma base: o
perfil fiscal do titular, a tabela de parâmetros por ano e a tela **Imposto de renda**.

Ano de referência: **ano-calendário 2026, declaração de 2027**. É o primeiro ano com as regras da Lei 15.270/2025.
O ano-calendário 2025 também precisa funcionar, com os parâmetros dele, para a declaração que já foi entregue e para
quem quiser conferir ou retificar.

> Tudo aqui é cálculo de apoio. O app não entrega declaração nem emite DARF oficial. Toda tela de resultado diz
> "estimativa; confira no programa da Receita" e mostra a regra e a fonte de cada número.

## 0. Resumo

| | Parte A: ações e fundos na bolsa | Parte B: estimador do ano |
|---|---|---|
| Pergunta do usuário | "Quanto devo de imposto nas vendas, e o que ponho em cada ficha da declaração?" | "Quanto vou pagar ou restituir? Quanto ainda posso deduzir? Quanto falta aportar no PGBL?" |
| Entrada | Operações e eventos que o app já importa (B3, Pluggy, CSV) e posição inicial com preço médio | Perfil fiscal (CLT, PJ ou os dois), salário bruto ou pró-labore, dependentes, despesas marcadas como dedutíveis e aportes de previdência |
| Saída | Apuração mês a mês, DARF de cada mês, prejuízo a compensar, e o roteiro de preenchimento (Renda Variável, Isentos, Exclusivos, Bens e Direitos) | Imposto do ano nos modelos completo e simplificado, o melhor modelo, restituição ou saldo a pagar, limite do PGBL e quanto falta aportar, lista de documentos para cada dedução |
| Regra central | Preço médio ponderado **por CPF** (todas as corretoras juntas), apuração mensal por grupo (comum, day trade, FII) | Tabela anual com o redutor da Lei 15.270, deduções legais e PGBL até 12% da renda tributável |

Decisões do usuário e as que tomei na implementação estão na §C.4.

## 1. Fontes e vigência

As regras abaixo foram conferidas na fonte oficial sempre que deu. Onde só há fonte secundária, o texto diz
"a confirmar", e o valor fica marcado assim na tabela de parâmetros (§1.2).

### 1.1 Normas

| Assunto | Norma | Onde conferi |
|---|---|---|
| Renda variável (ganho líquido, custo médio, day trade, isenção, compensação, DARF) | Lei 11.033/2004 art. 2º e 3º; Lei 8.383/1991 art. 27; IN RFB 1.585/2015 arts. 56 a 65; RIR/2018 art. 841 | Perguntas e Respostas IRPF 2026, perguntas 704 a 745 (PDF oficial, v1.0 de 23/04/2026) |
| Tabela mensal desde maio de 2025 | Lei 15.191/2025 | P&R IRPF 2026 (perguntas 339 e 7474 do texto) |
| Isenção até R$ 5 mil, redutor mensal e anual, retenção de 10% nos dividendos, tributação mínima (IRPFM) | Lei 15.270/2025 (arts. 3º-A, 6º-A, 11-A, 16-A, 16-B da Lei 9.250) | Texto da lei (Câmara dos Deputados); P&R "Tributação de Altas Rendas" da Receita (19/12/2025) |
| Deduções (dependente, educação, saúde, previdência, simplificado) | Lei 9.250/1995 arts. 4º, 8º, 10; Lei 9.532/1997 art. 11 | P&R IRPF 2026, perguntas 012, 331, 335, 367, 368, 387, 392, 400, 401 |
| INSS 2026 | Portaria Interministerial MPS/MF nº 13/2026 | Fontes secundárias concordantes (a confirmar no texto da portaria) |
| Obrigatoriedade de declarar | IN RFB 2.312/2026 | P&R IRPF 2026, pergunta 001 |
| MP 1.303/2025 (unificava alíquotas em 17,5%) | **Caducou** em 08/10/2025 | Congresso Nacional; regras antigas seguem valendo |

### 1.2 Parâmetros por ano

Ficam num só lugar no código (`app/services/ir/parametros.py`), indexados pelo ano-calendário. Cada valor guarda a
fonte e se já foi confirmado no texto oficial. **Nenhum número da Receita fica espalhado pelo código.** Quando a
Receita publicar o programa e o Perguntas e Respostas do IRPF 2027 (normalmente em março), o trabalho é revisar
este arquivo e os testes dele.

| Parâmetro | AC 2025 (DIRPF 2026) | AC 2026 (DIRPF 2027) | Estado |
|---|---|---|---|
| Tabela mensal: faixa isenta | até 2.259,20 (jan–abr) e 2.428,80 (mai–dez) | até 2.428,80 | oficial |
| Tabela mensal 2026 | — | 0% até 2.428,80 · 7,5% até 2.826,65 · 15% até 3.751,05 · 22,5% até 4.664,68 · 27,5% acima | oficial (P&R 2026) |
| Parcelas a deduzir (mensal) | — | 182,16 · 394,16 · 675,49 · 908,73 | oficial |
| Desconto simplificado mensal (retenção) | 607,20 | 607,20 (25% da faixa isenta) | oficial |
| Redutor mensal | — | até 5.000,00: até 312,89; 5.000,01 a 7.350,00: 978,62 − 0,133145 × rendimento | lei |
| Tabela anual | mista (jan–abr e mai–dez) | 0% até 29.145,60 · 7,5% até 33.919,80 · 15% até 45.012,60 · 22,5% até 55.976,16 · 27,5% acima | **a confirmar** (12 × mensal) |
| Parcelas a deduzir (anual) | 2.135,04 · 4.679,03 · 8.054,97 · 10.853,78 | 2.185,92 · 4.729,91 · 8.105,85 · 10.904,66 | AC 2025 oficial; AC 2026 **a confirmar** (pela continuidade da tabela; ver §B.2.3) |
| Redutor anual | não há | até 60.000,00: até 2.694,15; 60.000,01 a 88.200,00: 8.429,73 − 0,095575 × rendimento | lei |
| Desconto simplificado anual | 20%, limite 16.754,34 | 20%, limite **17.640,00** | AC 2025 oficial; AC 2026 pela lei (art. 10, X), a confirmar |
| Dependente | 2.275,08 / ano (189,59 / mês) | 2.275,08 | oficial em 2025; 2026 sem mudança na lei |
| Educação (por pessoa) | 3.561,50 | 3.561,50 | idem |
| PGBL | 12% da renda tributável | 12% | lei |
| Doações incentivadas | até 6% do imposto devido (modelo completo) | 6% | oficial |
| INSS empregado 2026 | — | 7,5% até 1.621,00 · 9% até 2.902,84 · 12% até 4.354,27 · 14% até 8.475,55; máximo 988,09 | a confirmar |
| INSS contribuinte individual (pró-labore) | — | 11% até o teto: máximo 932,31 | a confirmar |
| Retenção de dividendos | não há | 10% sobre o total, quando uma mesma empresa paga mais de 50.000,00 no mês | lei |
| IRPFM | não há | renda total acima de 600.000,00; alíquota (renda ÷ 60.000) − 10, até 10% | lei |
| Obrigatoriedade | tributáveis > 35.584,00; isentos > 200.000; vendas em bolsa > 40.000 ou com imposto; bens > 800.000 | a publicar | oficial em 2025 |
| Renda variável | 15% comum · 20% day trade · 20% FII · IRRF 0,005% e 1% · isenção de ações 20.000,00 / mês · DARF 6015 · mínimo R$ 10 | sem mudança | oficial |

## 2. O que o app tem hoje

| Peça | Onde | Serve para o IR? |
|---|---|---|
| Compras, vendas, desdobros, bonificações e proventos | `investment_event` (fontes `b3`, `b3_mov`, `pluggy`, `manual_ops`, `manual`) | Sim, é a matéria-prima da Parte A |
| Data do negócio (pregão) e instituição | Planilha "Negociação" da B3 (`smart_import._import_b3_trades`) | Sim. A Receita usa a data do pregão para o limite de isenção (pergunta 745) |
| Taxas | Só no CSV manual (coluna `fees`, já somada ao custo da compra e tirada da venda) | Parcial. A planilha da B3 não traz corretagem e emolumentos |
| Preço médio e lucro realizado | `analytics.py`, chaveado por **conta** `(account_name, instrument_id)` | **Não serve como está**: a Receita exige a média ponderada **por CPF**, juntando todas as corretoras (pergunta 720) |
| Bonificação | `BONUS` soma quantidade, sem custo | **Errado para o IR**: a ação bonificada tem custo, o valor capitalizado informado pela empresa (pergunta 721) |
| Grupamento | Vira `SPLIT` com quantidade negativa | Certo: só a quantidade muda, o custo total fica |
| Classe do ativo | `instrument.asset_class`; o sufixo 11 vira "FII/ETF/Unit" | **Ambíguo**: FII (20%, sem isenção), ETF (15%, sem isenção) e unit de ações (15%, com isenção) têm regras diferentes |
| Posição inicial | `OPENING` com custo opcional | Sim, é a "posição inicial" que o ReVar também pede |
| Titular de cada conta | `financial_account.member_id` | Sim: cada titular é uma declaração e uma apuração. Cônjuges apuram separado (pergunta 737) |
| Previdência | `pension.py`: fotografias de saldo e total contribuído em `fixed_income_snapshot` | **Não basta**: não há aportes datados nem a divisão entre participante e empresa |
| Salário recebido | Categoria "Salário" em `cash_transaction` | Só o **líquido**. O bruto precisa vir do usuário (ou do informe de rendimentos) |
| Despesas | Categorias (Saúde, Educação…) e regras | Ponto de partida para marcar dedutíveis, mas falta o beneficiário e o CNPJ/CPF do prestador |

## 3. Concorrentes: o que aprender

| Produto | O que faz | O que levar para o Tabimoney |
|---|---|---|
| **ReVar** (Receita + B3, grátis, no e-CAC) | Recebe as operações da B3 com autorização do investidor. Abas: Início, **Posição Inicial**, **Resolução de Pendências**, Eventos, Estoque, Extrato de Operações. Pede custo de aquisição e prejuízo a compensar no começo. Imposto abaixo de R$ 10 vai acumulando até chegar ao mínimo. Gera DARF com Pix. Desde a declaração 2026, pré-preenche a renda variável de quem autorizou. | A estrutura de abas e a ideia de **pendências** antes do resultado. Conferir com o ReVar é um passo do roteiro: os dois devem dar o mesmo imposto do mês. |
| **Grana** | Importa da B3, cobre ações, FII, BDR, ETF, opções e futuros. Relatório anual e preenchimento automático no programa IRPF. "Otimizador de IR". | O "otimizador" vira dois avisos simples: **quanto ainda dá para vender de ações neste mês sem imposto** e **quanto de prejuízo ainda há para compensar**. |
| **Velotax** | Grátis, integrado à B3, calcula e emite DARF. | Mostra que o cálculo mensal já é commodity. O diferencial do app é juntar com o resto (estimador, previdência, despesas). |
| **myProfit** | Apuração mensal, compensação, informe anual por ativo para Bens e Direitos. Separa o "Relatório Anual" (para preencher) dos relatórios de conferência. Usuários relatam lançar valores à mão e copiar e colar. | Um relatório **para preencher** (ficha por ficha, na ordem do programa) separado dos detalhes de conferência. Botão de copiar em cada valor. |
| **Mycapital** | DARF retroativo com multa e juros. | DARF atrasado entra numa fase posterior, com o link para o Sicalc da Receita em vez de cálculo próprio de multa (§A.6). |
| **Sencon** | Lê notas de corretagem em PDF (padrão SINACOR). | Fase posterior: ler a nota resolve as taxas e o IRRF, que a planilha da B3 não traz. |
| **Simulador da Receita** e calculadoras online | Comparam completo e simplificado. | O estimador precisa comparar os dois e **medir o ganho do PGBL contra o melhor modelo**, não contra o completo (§B.4.3). Nenhuma calculadora encontrada faz isso. |

## Parte A. Apuração de ações, fundos e ETFs na bolsa

### A.1 Escopo

Dentro: mercado à vista em bolsa de **ações, units, BDRs, ETFs de ações, FIIs e Fiagros**; operações comuns e day
trade; desdobramento, grupamento, bonificação, subscrição e frações; proventos (dividendos, JCP, rendimentos de
FII); posição em 31/12 para Bens e Direitos.

Fora, com aviso na tela: opções, termo e futuros; ações fora de bolsa (ganho de capital, GCAP); fundos abertos de
ações (o banco retém o imposto); ETF de renda fixa (tributado na fonte como renda fixa); ativos no exterior
(Lei 14.754/2023, apuração anual); criptoativos. Se o titular tiver evento de um desses, a apuração mostra uma
pendência: "operação fora do cálculo".

### A.2 Regras (memorial)

#### A.2.1 Classe fiscal do ativo

| Classe | Exemplos | Alíquota comum | Isenção de R$ 20 mil | Grupo de compensação | Bens e Direitos |
|---|---|---|---|---|---|
| Ação | PETR4, ITSA4 | 15% | **Sim** | comum | 03 – 01 |
| Unit de ações | TAEE11, KLBN11 | 15% | Sim (a confirmar, §C.4) | comum | 03 – 01 |
| BDR | AAPL34 | 15% | Não | comum | 04 – 04 |
| ETF de ações | BOVA11, IVVB11 | 15% | Não (pergunta 707) | comum | 07 – 06 (a confirmar: há guias com 07 – 09) |
| FII | HGLG11 | 20% | Não | **FII**, separado | 07 – 03 |
| Fiagro | — | 20% | Não | FII | 07 – 02 |
| Day trade (qualquer classe) | — | 20% | Não | **day trade**, separado | — |

A classe fica numa coluna nova, `instrument.tax_class`. Ordem para preencher:

1. o que o usuário ou o agente informou;
2. a aba da planilha de Posição da B3 (Ações, BDR, ETF, Fundos de Investimento), quando houver;
3. o sufixo do ticker: 3, 4, 5, 6 e 8 → ação; 32 a 39 → BDR;
4. sufixo 11 sem outra pista → **pendência** "diga se é FII, ETF ou unit". O app não chuta, porque o erro muda a
   alíquota e a isenção.

#### A.2.2 Custo de aquisição

- **Preço médio ponderado**, recalculado a cada compra, **juntando todas as corretoras do mesmo titular**
  (perguntas 719 e 720).
- **Taxas** (corretagem, emolumentos, liquidação) somam no custo da compra e saem do valor da venda (pergunta 708).
  Sem a taxa, o app usa zero e mostra o aviso "sem taxas: o imposto pode sair alguns centavos maior". O usuário
  pode informar a taxa total do mês por corretora (`rv_fee`) e o app rateia pelo valor de cada operação do mês.
- **Venda** não muda o preço médio. Ela tira `quantidade vendida × preço médio` do custo total.
- **Desdobramento**: custo zero; a quantidade aumenta e o custo total não muda (pergunta 722).
- **Grupamento**: a quantidade diminui e o custo total não muda. A fração que sobra e é vendida em leilão é venda
  comum, com custo pelo preço médio.
- **Bonificação**: as ações recebidas custam o valor capitalizado por ação que a empresa informa (fato relevante ou
  aviso aos acionistas), vezes a quantidade recebida (pergunta 721). O custo entra no total e muda o preço médio. O
  app usa `unit_price_cents` do evento quando a planilha da B3 traz; sem ele, **pendência** "informe o custo por
  ação da bonificação de X em DD/MM".
- **Subscrição**: o custo é o valor pago na subscrição. O direito de subscrição vendido é venda com custo zero
  (a confirmar no tratamento do direito recebido de graça; ver §C.4).
- **Posição inicial**: se a história do ativo não começa na primeira compra, o usuário informa quantidade e preço
  médio numa data (`OPENING`, como hoje). Sem custo, a venda vira pendência.
- **Herança e doação**: custo é o valor declarado pelo doador ou espólio. Entra como posição inicial.

#### A.2.3 Day trade

- Compra e venda do **mesmo ativo, no mesmo dia, na mesma corretora**, com a quantidade liquidada total ou
  parcialmente (pergunta 705).
- A quantidade de day trade é `mín(comprado no dia, vendido no dia)` naquela corretora e ativo.
- O resultado casa as primeiras compras com as primeiras vendas do dia, na ordem. Como a planilha da B3 não traz a
  hora, o app usa o **preço médio das compras do dia e o preço médio das vendas do dia** para a parte de day trade.
  Com a quantidade casada e preços médios, o resultado é o mesmo do casamento em ordem.
- O que sobra do dia vira operação comum: compra que sobra entra no preço médio; venda que sobra sai do estoque pelo
  preço médio da posição anterior ao dia.
- Perdas de day trade do mesmo dia se compensam entre si. Day trade só compensa com day trade.

#### A.2.4 Apuração mensal

Para cada titular, mês e grupo:

```
resultado_operação = valor_venda − taxas_venda − quantidade × preço_médio
```

| Passo | Comum (ações, units, BDR, ETF) | Day trade | FII e Fiagro |
|---|---|---|---|
| 1. Total vendido de ações no mês (só ações e units, operações comuns, pela data do pregão) | `vendas_acoes` | — | — |
| 2. Isenção | se `vendas_acoes ≤ 20.000,00` **e** o resultado das ações no mês for positivo, esse lucro é isento e sai da base | não há | não há |
| 3. Resultado tributável do mês | ações (se não isentas) + units (idem) + BDR + ETF | soma do mês | soma do mês |
| 4. Compensação | prejuízo comum acumulado (de qualquer mês ou ano anterior) | prejuízo de day trade acumulado | prejuízo de FII acumulado |
| 5. Base | `max(0, resultado + prejuízo)`; o que sobra de prejuízo segue para o mês seguinte | idem | idem |
| 6. Imposto | 15% × base | 20% × base | 20% × base |
| 7. IRRF a descontar | 0,005% das vendas (dedo-duro) | 1% do resultado positivo do dia, por corretora | 0,005% das vendas |

Regras de borda:

- **Prejuízo das ações em mês isento compensa**: se `vendas_acoes ≤ 20.000` e o resultado das ações for negativo, o
  prejuízo entra no acumulado comum (pergunta 729: o demonstrativo é dispensado "exceto no caso de pretender
  compensar as perdas").
- **Isenção olha só ações e units**, e só a soma das **vendas** (não o lucro). Venda de ETF, BDR e FII não conta
  para os R$ 20 mil, e o lucro deles nunca é isento.
- Venda de ações em **day trade**: o app soma no limite de R$ 20 mil (escolha conservadora; ver §C.4).
- **Prejuízo não volta**: não se compensa prejuízo com lucro de meses anteriores (pergunta 710).
- **Prejuízo não vence**: passa de ano sem limite (pergunta 711). O prejuízo de anos anteriores à história do app
  é informado pelo usuário em `rv_carryover` (como no ReVar).
- **IRRF de 0,005%** só é retido quando passa de R$ 1,00 (pergunta 706). Sem o valor da nota, o app **estima** e
  marca como estimado. O IRRF de day trade só se compensa até dezembro do mesmo ano (perguntas 714 e 715). O que
  sobrar de IRRF no fim do ano é informado na declaração (ficha Renda Variável, linha do imposto retido) e pode ser
  restituído.
- **Cônjuges**: cada um apura o seu e tem o seu limite de R$ 20 mil (pergunta 737). O app já separa por titular.

#### A.2.5 DARF

| Campo | Valor |
|---|---|
| Código | 6015 (pessoa física, ganhos líquidos em bolsa) |
| Período de apuração | último dia do mês da venda |
| Vencimento | último dia útil do mês seguinte (pergunta 730). Venda no último pregão do mês com liquidação no mês seguinte: o vencimento conta da liquidação (pergunta 745) |
| Valor | `imposto comum + day trade + FII − IRRF compensável` do mês |
| Mínimo | abaixo de R$ 10,00 não se paga: o valor soma no mês seguinte até chegar a R$ 10 (como no ReVar) |
| Pago em atraso | multa de 0,33% ao dia (até 20%) e juros Selic. O app **não calcula**: mostra o atraso e manda para o Sicalc da Receita |

O app marca o DARF como pago (`rv_darf`) quando o usuário confirma, ou quando encontra um lançamento de débito com
"DARF" ou "Receita Federal" no valor certo, entre o vencimento e 60 dias depois (sugestão, nunca automático).

#### A.2.6 Declaração anual (o que vai em cada ficha)

| Ficha | O que o app entrega |
|---|---|
| Renda Variável › Operações Comuns / Day Trade | Para cada mês: resultado de "Mercado à vista – ações", de "Mercado à vista – outros" (onde a Receita põe BDR e ETF; a confirmar no programa), prejuízo a compensar, IRRF e imposto pago. Prejuízo de anos anteriores no primeiro mês. |
| Renda Variável › Fundos de Investimento Imobiliário | Resultado mensal de FII e Fiagro, prejuízo acumulado e imposto pago |
| Rendimentos Isentos › 20 | Soma dos lucros de ações isentos (meses com vendas ≤ 20 mil) |
| Rendimentos Isentos › 09 | Dividendos recebidos, por empresa (CNPJ e nome) |
| Rendimentos Isentos › 99 (ou o código que o programa trouxer) | Rendimentos de FII e Fiagro, por fundo (a confirmar: há guias com 26 e 99) |
| Rendimentos Sujeitos à Tributação Exclusiva › 10 | JCP **líquido**, por empresa |
| Rendimentos Sujeitos à Tributação Exclusiva › 06 | Rendimentos de ETF tributados na fonte, se houver |
| Bens e Direitos | Um item por ativo com o grupo e código da §A.2.1, situação em 31/12 do ano anterior e do ano (**sempre pelo custo**, nunca pelo valor de mercado), e a discriminação pronta (texto abaixo) |

Dispensa de Bens e Direitos: conjunto de ações de uma mesma empresa com custo abaixo de R$ 1.000,00 (pergunta 007).
O app lista o item mesmo assim, marcado "dispensado; declarar é opcional". Obrigatoriedade de declarar por causa da
bolsa: vendas acima de R$ 40.000 no ano ou qualquer ganho tributável (pergunta 001).

Discriminação sugerida (Bens e Direitos):

```
1.200 ações ITSA4 - ITAÚSA S.A., CNPJ 61.532.644/0001-15. Custódia: XP Investimentos (800) e BTG Pactual (400).
Custo médio de R$ 11,00 por ação.
```

O CNPJ da empresa vem de `company_profile.cnpj`. O da corretora é opcional (o usuário pode cadastrar).

### A.3 Algoritmo

```
para cada titular T e ano A:
    eventos = eventos escolhidos por conta (mesma prioridade de fonte de analytics.py),
              juntados de todas as contas de T, ordenados por (data, ordem do dia)
    estoque[ativo] = (quantidade, custo_total), partindo da posição em 31/12/(A−1)
    prejuízo[comum | day_trade | fii] = acumulado até 31/12/(A−1) + rv_carryover informado
    para cada dia:
        separar day trade por (corretora, ativo): q = mín(compras, vendas)
        resultado_dt += q × (preço_médio_venda_dia − preço_médio_compra_dia) − taxas proporcionais
        aplicar sobras: compras → estoque; vendas → resultado comum pelo preço médio do estoque
        aplicar eventos corporativos do dia (desdobro, grupamento, bonificação, subscrição)
    para cada mês: passos 1 a 7 da §A.2.4; DARF; acúmulo abaixo de R$ 10
    posição em 31/12/A por ativo → Bens e Direitos
    proventos do ano por empresa → Isentos / Exclusivos
```

Pontos de implementação:

- O código de escolha de eventos por fonte (`best_source` em `analytics.py`) sai para uma função comum. A apuração
  usa o mesmo filtro, para não contar em dobro a mesma venda vinda da B3 e da Pluggy.
- Ordem dentro do dia: eventos corporativos antes das operações (a data "com" já passou), compras antes das vendas
  na parte comum.
- Centavos em inteiro; quantidades em milionésimos. Preço médio guardado como custo total e quantidade (sem
  arredondar no meio). Imposto arredondado meio para cima no centavo, como na §B.2.3.
- `analytics.py` continua com o preço médio por conta para a tela da carteira; a apuração do IR fica num serviço
  próprio (`app/services/ir/renda_variavel.py`).

### A.4 Pendências

O resultado do mês só sai como "conferido" sem pendências. Cada uma diz o que fazer.

| Pendência | Quando | Como resolver |
|---|---|---|
| Venda sem custo | Venda sem posição inicial com preço médio | Informar quantidade e preço médio na data, ou importar o histórico |
| Estoque negativo | Venda maior que a posição | Falta compra, evento ou posição inicial; mostrar as fontes do ativo |
| Classe desconhecida | Ticker 11 sem classe | Escolher FII, ETF ou unit |
| Bonificação sem custo | `BONUS` sem custo por ação | Informar o valor do aviso da empresa |
| Evento não suportado | Opção, termo, futuro, OPA, incorporação, troca de ticker | Fora do cálculo; lançar à mão no programa |
| IRRF estimado | Sem valor da nota | Informar o IRRF do mês (nota ou informe da corretora), ou aceitar a estimativa |
| Taxas ausentes | Planilha B3 sem taxas | Informar taxa do mês, ou aceitar (aviso, não bloqueia) |
| Prejuízo anterior | Primeiro ano com dados e não houve resposta | Informar o prejuízo a compensar de anos anteriores, ou "não tenho" |

### A.5 Exemplo completo (vira teste)

Titular Ana, ano-calendário 2026, sem prejuízo anterior. Taxas já embutidas nos valores.

| Mês | Operação | Conta |
|---|---|---|
| jan | Compra 100 ITSA4 a R$ 10,00 na XP; custo 1.000,30 · Compra 100 ITSA4 a R$ 12,00 no BTG; custo 1.200,30 | Preço médio **consolidado** = 2.200,60 ÷ 200 = **11,003**. Por conta seria 10,003 e 12,003: dá outro lucro, e é o erro que a regra de CPF evita |
| fev | Venda 150 ITSA4 a 13,00 (100 XP + 50 BTG); líquido 1.949,60 | Custo 1.100,30 + 550,15 = 1.650,45 · lucro **299,15** · vendas de ações 1.950 ≤ 20.000 → **isento** (Isentos › 20) |
| mar | Venda 50 ITSA4 a 9,00; líquido 449,90 · Venda 10 HGLG11 (FII), líquido 1.600,00, custo 1.700,00 | Ações: custo 550,15, **prejuízo 100,25** (mês isento, mas o prejuízo fica para compensar) · FII: **prejuízo 100,00** |
| abr | Venda 2.000 PETR4 a 30,00; líquido 59.997,00; preço médio 27,00 (custo 54.000,00) | Lucro 5.997,00 · vendas > 20 mil → tributável · compensa 100,25 → base **5.896,75** · imposto 15% = **884,51** · IRRF 0,005% × 60.000 = 3,00 · **DARF de abr: 881,51**, vence 29/05/2026 |
| mai | Venda 100 BOVA11 (ETF), lucro 50,00; vendas 12.000 (IRRF 0,60, abaixo de R$ 1, não retido) | ETF não tem isenção · imposto 15% = **7,50** · abaixo de R$ 10 → não paga, acumula |
| jun | Venda de HGLG11 com lucro 300,00 | Compensa 100,00 do prejuízo de FII → base 200,00 · 20% = 40,00 · **DARF de jun: 40,00 + 7,50 = 47,50** |
| jul | Day trade na XP: compra 100 WEGE3 a 40,00 e venda 100 a 41,00 no mesmo dia; taxas 0,50 | Resultado 99,50 · 20% = 19,90 · IRRF 1% = 1,00 (0,995 arredondado) · **DARF de jul: 18,90** |

Declaração 2027 dessa Ana: Isentos › 20 = 299,15; Renda Variável com mar (−100,25 comum; −100,00 FII), abr
(5.997,00; compensação; IRRF 3,00; pago 881,51), mai, jun e jul; Bens e Direitos com a posição em 31/12 pelo custo.

### A.6 Telas

**Imposto de renda › Ações e fundos** (seletor de titular e de ano):

1. Faixa de cima: "Imposto do ano: R$ X em N DARFs · Prejuízo a compensar: comum R$ A, day trade R$ B, FII R$ C".
2. **Este mês**: "Você vendeu R$ 12.300 em ações. Ainda pode vender **R$ 7.700** sem imposto sobre o lucro das
   ações." Some no ano fechado.
3. **Pendências** (quando houver), no topo e antes dos números (modelo ReVar).
4. Tabela mensal: vendas de ações, resultado por grupo, isento, compensado, base, imposto, IRRF, DARF, vencimento,
   pago. Cada linha abre as operações com o cálculo do preço médio.
5. DARF do mês: código, período, vencimento e valor, com botão de copiar e o link do Sicalc (a Receita gera o
   documento oficial; o app não gera código de barras).

**Imposto de renda › Declaração**: o passo a passo do programa, ficha por ficha, na ordem do programa, com cada
valor e um botão de copiar. Aviso no topo: "Autorizou o ReVar? Confira se a declaração pré-preenchida bate com
estes números."

## Parte B. Estimador de imposto do ano

### B.1 Perfil fiscal

Por titular e por ano (`tax_profile`), na tela **Imposto de renda › Estimativa**:

| Campo | CLT | PJ (sócio) | Observação |
|---|---|---|---|
| Fontes de renda | salário bruto mensal, por empregador | pró-labore mensal e faturamento mensal da empresa | Pode ter as duas (CLT e PJ); cada uma é uma fonte (`tax_income_source`) |
| 13º e férias | 13º: sim / não; 1/3 de férias: mês | — | 13º é tributado só na fonte e fica fora do ajuste e da base do PGBL |
| INSS | calculado pela tabela; pode ser substituído pelo valor do holerite | 11% do pró-labore, até 932,31 | |
| IRRF já retido | calculado; pode ser substituído pelo informe | idem | |
| Lucros distribuídos | — | valor por mês e empresa | Isentos até R$ 50 mil por mês de cada empresa (§B.2.7) |
| Regime da empresa | — | Simples Anexo III, Anexo V, ou "outro, informo o lucro" | Só para estimar o lucro disponível (§B.2.8) |
| Dependentes | lista (nome, parentesco, ano de nascimento) | idem | Quem é titular da casa pode ser dependente; o app avisa que a renda dele entra junto |
| Outros rendimentos tributáveis | aluguel, autônomo | idem | Fase posterior (carnê-leão) |
| Regime próprio (servidor) | sim / não, com alíquota do patrocinador | — | Caso Funpresp (§B.3.4) |

**Conciliação com o extrato.** O app compara o líquido esperado (bruto − INSS − IRRF − descontos informados) com a
soma da categoria "Salário" no mês. Diferença acima de 5% vira aviso: "o holerite de março não bate com o
recebido; confira o bruto ou os descontos". É o mesmo espírito da conciliação de transferências.

### B.2 Regras (memorial)

#### B.2.1 INSS

- **Empregado (CLT)**, progressivo por faixa: 7,5% até 1.621,00; 9% de 1.621,01 a 2.902,84; 12% até 4.354,27;
  14% até 8.475,55. Máximo **988,09** por mês. Ex.: salário de 5.000,00 → 501,51.
- **Pró-labore**: 11% sobre o pró-labore, até o teto (**932,31**). A parte da empresa (20% no Simples Anexo IV,
  Presumido e Real) não é do sócio e não entra no IR dele.
- Mais de uma fonte: a soma não passa do teto. O usuário informa se uma fonte já desconta até o teto.

#### B.2.2 Retenção mensal (IRRF)

Ordem do cálculo, conforme a orientação da Receita para 2026:

1. `base = rendimento bruto − deduções do mês`, onde deduções são `max(INSS + 189,59 × dependentes + pensão +
   previdência complementar descontada em folha, 607,20)`. O 607,20 é o desconto simplificado mensal.
2. `imposto = tabela mensal(base)`.
3. `redução = 312,89` até 5.000,00 de **rendimento bruto**; `978,62 − 0,133145 × rendimento bruto` entre 5.000,01 e
   7.350,00; zero acima. A redução não passa do imposto.
4. `IRRF = imposto − redução`.

Exemplos da Receita: bruto 4.500,00 → imposto 200,39, redução 200,39, IRRF zero. Bruto 6.000,00 → base 5.392,80,
imposto 574,29, redução 179,75, IRRF 394,54.

Duas fontes de R$ 4.000: nenhuma retém, mas no ajuste anual a renda soma 96 mil e haverá imposto a pagar. O
estimador mostra isso cedo, e pode sugerir o recolhimento complementar mensal (DARF 0246) para não juntar tudo em
abril.

#### B.2.3 Ajuste anual

```
rendimentos_tributáveis = salários + pró-labore + 1/3 de férias + outros (sem 13º, sem PLR, sem lucros)
deduções_completo = INSS + dependentes × 2.275,08 + saúde + mín(educação, 3.561,50 por pessoa)
                    + pensão judicial + mín(PGBL do participante, 12% × rendimentos_tributáveis)
                    + Funpresp até a alíquota do patrocinador
desconto_simplificado = mín(20% × rendimentos_tributáveis, 17.640,00)
para cada modelo:
    base = max(0, rendimentos_tributáveis − deduções)
    imposto = tabela anual(base)
    redução = mín(imposto, redutor anual(rendimentos_tributáveis))
    devido = imposto − redução − doações incentivadas (só completo, até 6% do imposto)
saldo = devido − IRRF do ano − carnê-leão e complementar pagos
melhor modelo = o de menor devido
```

- A **redução anual** usa os rendimentos tributáveis brutos, não a base depois das deduções. Por isso, deduzir
  mais não aumenta nem diminui a redução: só muda o imposto de onde ela é tirada.
- Na faixa de 60 mil, a fórmula dá 2.695,23 e o teto fixo é 2.694,15 (R$ 1,08 de diferença). O app aplica a lei
  como está escrita: até 60.000,00 vale o teto fixo; acima, a fórmula.
- Imposto como a Receita calcula: base × alíquota da faixa − parcela a deduzir, arredondado no centavo. Por fatias
  dá até 1 centavo de diferença (a Receita mostra 574,29 no exemplo de R$ 6.000; por fatias sai 574,30), por isso a
  implementação usa a parcela. As parcelas anuais oficiais sempre saíram pela continuidade da tabela (ex.: AC 2024,
  26.963,20 × 7,5% = 2.022,24), e é assim que as do AC 2026 foram calculadas até a publicação. O INSS do
  empregado segue por fatias.
- Educação: o limite é por pessoa e o que um dependente passa não cobre o outro (pergunta 401).
- Saúde: sem limite. Remédio de farmácia **não** entra (pergunta 392). Reembolso do plano sai do valor. Plano de
  saúde pago pela empresa só entra na parte descontada do salário.

#### B.2.4 Previdência complementar (PGBL)

- Dedutível só no modelo **completo**, até **12% dos rendimentos tributáveis** do ajuste (pergunta 335).
- Exige contribuir para o INSS ou regime próprio (ou ser aposentado por eles). O pró-labore cumpre a exigência.
- Só conta o que o **participante pagou** ("cujo ônus tenha sido do participante"). **O aporte da empresa não entra
  no limite e não é dedutível**; também não é renda do participante no aporte.
- Aporte no nome de dependente entra no limite do titular. Dependente com mais de 16 anos precisa contribuir para o
  INSS em nome próprio.
- **VGBL não deduz.** Vai em Bens e Direitos (99 – 06) pelo valor aportado.
- Aporte descontado em folha já reduz o IRRF do mês; no ajuste, entra com o resto.
- Para servidor com Funpresp (código 37), a contribuição até a alíquota do patrocinador não entra no limite de 12%;
  o que passar disso soma com o PGBL no limite (pergunta 335, exemplos 4 e 5).
- No resgate ou benefício, o PGBL é tributado sobre **tudo** (aportes e rendimentos), pela tabela progressiva ou
  regressiva (35% a 10%). O benefício é adiar o imposto, não isentar. A tela diz isso perto do botão "aportar".

#### B.2.5 Outras deduções

| Dedução | Limite | Documento | Ficha na declaração |
|---|---|---|---|
| Dependente | 2.275,08 cada | CPF do dependente | Dependentes |
| Saúde (médico, dentista, psicólogo, fisioterapeuta, fonoaudiólogo, terapeuta ocupacional, hospital, exames, plano) | sem limite | Nota ou recibo com nome, CPF/CNPJ e endereço do prestador, quem pagou e o paciente; Receita Saúde vale | Pagamentos Efetuados |
| Educação (creche a pós, técnico) | 3.561,50 por pessoa | Nota da escola com CNPJ | Pagamentos Efetuados |
| Pensão alimentícia judicial ou por escritura | sem limite | Decisão ou escritura | Pagamentos Efetuados |
| PGBL / FAPI | 12% | Informe da seguradora | Pagamentos Efetuados, código 36 |
| Funpresp | §B.2.4 | Informe do órgão | Pagamentos Efetuados, código 37 |
| Doações (ECA, Idoso, cultura, esporte…) | 6% do imposto, no total | Recibo do fundo | Doações Efetuadas |
| Doação no próprio programa (ECA e Idoso) | 3% cada, dentro dos 6% | DARF gerado pelo programa, pago até o prazo | Doações Diretamente na Declaração |

Não dedutíveis, para a tela evitar engano: remédio de farmácia, academia, curso livre (idiomas, cursinho), material
escolar, plano de saúde de quem não é dependente, gasto com acompanhante, empregada doméstica (acabou em 2019).

#### B.2.6 Quem precisa declarar

A tela avisa, com a regra do ano (pergunta 001 do ano corrente). Para o AC 2025: tributáveis acima de 35.584,00;
isentos e exclusivos acima de 200 mil; vendas em bolsa acima de 40 mil ou com ganho tributável; bens acima de
800 mil, entre outros. Os valores do AC 2026 entram na tabela de parâmetros quando a Receita publicar.

#### B.2.7 Dividendos (a partir de 2026)

- Dividendo de uma mesma empresa abaixo ou igual a R$ 50 mil no mês: isento e sem retenção.
- Acima de R$ 50 mil no mês, da mesma empresa: retenção de **10% sobre o total**, sem dedução (art. 6º-A). Ex.: R$
  70 mil num mês → R$ 7 mil retidos.
- Lucros de 2025 aprovados até 31/12/2025 e pagos como aprovados (até 2028) ficam fora da retenção e do IRPFM.
- Se a renda total do ano ficar **até R$ 600 mil**, a retenção volta na declaração (restituição). Acima, ela
  desconta do IRPFM (§B.2.9).
- Simples Nacional também retém (P&R Altas Rendas, pergunta 10).

O estimador soma a retenção por empresa e por mês e mostra quanto volta na declaração.

#### B.2.8 PJ: do faturamento ao que sobra para o sócio

O imposto da pessoa física do sócio depende só do pró-labore (tributável) e dos lucros (isentos dentro das regras
acima). O faturamento serve para duas coisas: estimar o lucro que dá para distribuir e conferir o fator R.

Simples Nacional, com faturamento dos últimos 12 meses `RBT12`:

```
alíquota_efetiva = (RBT12 × alíquota_nominal − parcela_a_deduzir) ÷ RBT12
fator_R = folha dos 12 meses (pró-labore + salários + encargos) ÷ RBT12
fator_R ≥ 28% → Anexo III; abaixo → Anexo V (para as atividades sujeitas ao fator R)
```

| Faixa do RBT12 | Anexo III | Anexo V |
|---|---|---|
| até 180.000 | 6,00% · 0 | 15,50% · 0 |
| até 360.000 | 11,20% · 9.360 | 18,00% · 4.500 |
| até 720.000 | 13,50% · 17.640 | 19,50% · 9.900 |
| até 1.800.000 | 16,00% · 35.640 | 20,50% · 17.100 |
| até 3.600.000 | 21,00% · 125.640 | 23,00% · 62.100 |
| até 4.800.000 | 33,00% · 648.000 | 30,50% · 540.000 |

(LC 123/2006, anexos III e V. A confirmar na fonte antes de implementar.) Lucro Presumido e Real ficam como "informo
o lucro": o usuário digita o lucro distribuível. Calcular o imposto da empresa nesses regimes é trabalho do
contador e do futuro "Tabim PJ Money".

O que a tela de PJ mostra: pró-labore mínimo para o fator R de 28%, o DAS estimado nos dois anexos e o IR e INSS
do sócio em cada caso.

#### B.2.9 Tributação mínima (IRPFM), só acima de R$ 600 mil

```
renda_total = todos os rendimentos do ano (tributáveis, isentos, exclusivos, dividendos)
              − exclusões: poupança, LCI, LCA, CRI, CRA, LIG, debêntures incentivadas, FII e Fiagro (bolsa),
                ganho de capital fora de bolsa, herança e doação, indenizações, lucros de 2025 da transição …
se renda_total ≤ 600.000: IRPFM = 0
alíquota = mín(10%, renda_total ÷ 60.000 − 10)
IRPFM_bruto = alíquota × renda_total
IRPFM = max(0, IRPFM_bruto − IR do ajuste − IR exclusivo na fonte da base − IR definitivo − redutor do art. 16-B)
        − retenção de 10% dos dividendos
```

Ex.: R$ 900 mil → alíquota 5% → IRPFM bruto R$ 45 mil, menos o que já foi pago. O redutor do art. 16-B (quando a
empresa e o sócio juntos passam de 34%) depende da alíquota efetiva da empresa, que o app não sabe. O estimador
calcula o IRPFM **sem o redutor**, diz que o valor é um teto, e para por aí. Ganho em bolsa **entra** na base.

### B.3 Previdência: aportes do participante e da empresa

#### B.3.1 Dados

Tabela nova `pension_contribution`: plano (`product_key`), data, valor, **quem pagou** (`participante` ou
`empresa`), se foi descontado em folha, e a origem (manual, extrato, informe). As fotografias de saldo de hoje
continuam como estão.

O formulário da tela Previdência ganha um bloco "Aportes do ano": valor, data e quem pagou, e um atalho "aporte
mensal fixo" (gera 12 lançamentos previstos que o usuário confirma). Um débito no extrato com o nome da seguradora
(ex.: "ITAU VIDA PREV") vira sugestão de aporte do participante.

#### B.3.2 Limite e quanto falta

```
limite = 12% × rendimentos_tributáveis do ano (estimados até dezembro)
aportado = soma dos aportes do participante em PGBL no ano (inclui os dependentes)
falta = max(0, limite − aportado)
```

A empresa aparece ao lado ("a empresa aportou R$ X; isso não conta para o limite") e soma no saldo do plano.

#### B.3.3 Quanto o aporte rende de imposto

O ganho do aporte é medido **contra o melhor modelo sem ele**, não contra o modelo completo:

```
economia(P) = mín(devido_completo(aporte atual), devido_simplificado) − devido_completo(aporte atual + P)
```

A tela mostra a economia de completar o limite e a economia por real aportado. Se `economia ≤ 0` (o simplificado
continua melhor, ou não há imposto), o texto diz que **o PGBL não ajuda o IR este ano**, e o VGBL ou outro
investimento pode fazer mais sentido. Prazo: o aporte precisa ser pago até 31/12 (conferir o prazo da seguradora).

#### B.3.4 Exemplos (viram testes)

Parâmetros do AC 2026 da §1.2.

**CLT, 12 mil por mês.** 12 salários de 12.000,00 = 144.000,00 (13º fora). INSS 988,09 × 12 = 11.857,08. Um
dependente (2.275,08), saúde 6.000,00, educação do dependente 5.000,00 → 3.561,50. Limite do PGBL 12% = 17.280,00.
Já aportou 6.000,00.

| | Completo (PGBL 6.000) | Completo (PGBL 17.280) | Simplificado |
|---|---|---|---|
| Deduções | 29.693,66 | 40.973,66 | 17.640,00 |
| Base | 114.306,34 | 103.026,34 | 126.360,00 |
| Imposto | 20.529,58 | 17.427,58 | 23.844,34 |
| Redução | 0 | 0 | 0 |

Melhor modelo: completo. Faltam 11.280,00 de PGBL; completar o limite economiza **3.102,00** (27,5% do aporte).

**CLT, 6.500 por mês.** 78.000,00 por ano, INSS 711,51 × 12 = 8.538,12, sem outras deduções. Redução anual
8.429,73 − 0,095575 × 78.000 = **974,88**. Simplificado: base 62.400,00, imposto 6.255,34, devido **5.280,46**.
Completo sem PGBL: 7.222,48. Completo com o PGBL máximo (9.360,00): **4.648,48**. Economia real do aporte: 631,98
(6,8% do aporte), e não os 27,5% da faixa em que a base cai. É esse o caso que as calculadoras online não mostram.

**PJ, pró-labore de 8.400 por mês.** 100.800,00 por ano; INSS 11% = 924,00 por mês (11.088,00 no ano); IRRF
1.147,17 por mês. Limite do PGBL: 12.096,00 (12% do pró-labore; lucros e faturamento não contam). Simplificado:
devido **11.964,34**; completo sem PGBL: 13.766,14; completo com 12.096,00 de PGBL: **10.439,74**. Economia
**1.524,60** (12,6% do aporte). Com o IRRF do ano (13.766,04), o simplificado sem PGBL já restitui 1.801,70; com o
PGBL máximo no completo, restitui 3.326,30.

**Alta renda.** Renda total de R$ 900 mil com R$ 600 mil de dividendos: IRPFM bruto 45.000,00, menos o IR do
ajuste e as retenções.

### B.4 Despesas dedutíveis

#### B.4.1 Marcar

- **Por categoria**: cada categoria pode ter um tipo de dedução (`category_tax`): saúde, educação, previdência
  (PGBL), pensão, doação ou nenhum. As categorias "Saúde" e "Educação" já vêm com o tipo, desligado até o usuário
  confirmar, porque nelas há farmácia e academia.
- **Por lançamento** (`transaction_tax`): tipo, beneficiário (titular ou dependente), prestador (nome e CPF/CNPJ),
  reembolso e "não dedutível". O lançamento manda na categoria.
- **Regras**: as regras de categorização ganham o tipo de dedução (ex.: "UNIMED" → saúde, beneficiário titular).
- **Fora do extrato**: despesa paga em dinheiro ou por outra pessoa entra à mão (`tax_deduction`), com os mesmos
  campos.

O CPF/CNPJ do prestador fica na base local, em texto. É dado de quem prestou o serviço, necessário para a ficha
Pagamentos Efetuados, e nunca sai da máquina (regra de privacidade do `AGENTS.md`).

#### B.4.2 Consolidado do ano

Tela **Imposto de renda › Deduções**: por tipo e por pessoa, total, total aproveitado (depois dos limites), quanto
vale em imposto (a diferença no devido) e uma linha por prestador, que é como a ficha Pagamentos Efetuados pede.

Ao lado de cada linha, o que falta para ela valer:

- "Falta o CNPJ do prestador";
- "Guarde a nota fiscal (ou o recibo do Receita Saúde)";
- "Farmácia não é dedutível; desmarque";
- "Plano de saúde: informe o reembolso, se houve".

E o **checklist do ano**: informe de rendimentos de cada empregador, informe da corretora, informe do PGBL, notas de
saúde e educação, recibo de doações, DARFs pagos.

#### B.4.3 Sugestões de economia

Só com números do próprio usuário, cada uma com o valor em reais:

1. completar o PGBL (§B.3.3);
2. doar até 6% do imposto (ou 3% no próprio programa, para ECA e Idoso): "isso não reduz o que você gasta, só
   escolhe para onde vai parte do imposto";
3. dependente que vale a pena ou não (a renda dele entra junto);
4. declaração em separado ou em conjunto, para casais com dois titulares no app (fase posterior);
5. venda de ações: quanto ainda cabe na isenção do mês (Parte A).

## C. Comum às duas partes

### C.1 Dados (migração `011_imposto_renda.sql`)

| Tabela ou coluna | Campos principais |
|---|---|
| `instrument.tax_class` | `acao`, `unit`, `bdr`, `etf`, `etf_rf`, `fii`, `fiagro`, `outro` |
| `rv_carryover` | titular, ano, grupo (`comum`, `day_trade`, `fii`), prejuízo em centavos |
| `rv_fee` | titular, conta, mês, taxas em centavos |
| `rv_irrf` | titular, mês, grupo, IRRF em centavos |
| `rv_darf` | titular, mês, valor pago, data do pagamento, lançamento ligado (opcional) |
| `tax_profile` | titular, ano, servidor (sim/não, alíquota do patrocinador), observações |
| `tax_income_source` | titular, ano, tipo (`salario`, `pro_labore`, `outro`), pagador, bruto mensal, meses, 13º, mês das férias, INSS e IRRF informados (opcionais), regime e faturamento da PJ |
| `tax_dependent` | titular, ano, nome, parentesco, ano de nascimento |
| `tax_profit` | titular, mês, empresa (nome e CNPJ), lucro distribuído, retido |
| `category_tax` | categoria, tipo de dedução |
| `transaction_tax` | lançamento, tipo, beneficiário, prestador, documento do prestador, reembolso, excluído |
| `tax_deduction` | titular, data, tipo, beneficiário, prestador, documento, valor, reembolso, observação, autor |
| `pension_contribution` | plano, data, valor, pagador (`participante`, `empresa`), em folha, origem |

Toda escrita registra o autor (usuário ou agente), como as categorias, para poder desfazer. Nada apaga lançamento.

### C.2 Agentes (MCP e CLI)

Operações novas em `app/agente/operacoes.py`, com ferramenta no MCP e comando na CLI:

| Ferramenta MCP | CLI | Tipo |
|---|---|---|
| `ir_contexto` (perfil, fontes, deduções, previdência e apuração do ano num JSON só) | `financas ir contexto` | leitura |
| `ir_acoes_apuracao` | `financas ir acoes` | leitura |
| `ir_declaracao` (o passo a passo por ficha) | `financas ir declaracao` | leitura |
| `ir_estimativa` | `financas ir estimativa` | leitura |
| `ir_fonte_salvar` (salário, pró-labore, outro; corrige e remove) | `financas ir fonte` | escrita |
| `ir_dependente_salvar` | `financas ir dependente` | escrita |
| `ir_previdencia_oficial` (condição do PGBL) | `financas ir previdencia-oficial` | escrita |
| `ir_deducao_marcar` (lançamentos ou categoria) | `financas ir deducao` | escrita |
| `ir_deducao_adicionar` (despesa fora do extrato) | `financas ir deducao-manual` | escrita |
| `ir_pendencia_resolver` (classe, bonificação, prejuízo anterior, IRRF, taxas, DARF pago) | `financas ir pendencia` | escrita |
| `previdencia_aporte_registrar` | `financas previdencia aporte` | escrita |

Roteiro novo `app/agente/roteiros/imposto-renda.md`: `ir_contexto` → resolver pendências com o usuário → revisar
despesas de saúde e educação do ano e marcar as dedutíveis (perguntar na dúvida, nunca marcar farmácia) → mostrar a
estimativa e o PGBL que falta → em março e abril, entregar o passo a passo da declaração. Entra no `ciclo.md` em
dezembro (PGBL e doações) e em março (declaração).

### C.3 Telas e demo

- Menu: **Imposto de renda**, com as abas Estimativa, Ações e fundos, Deduções e Declaração. Seletor de ano e de
  titular.
- Previdência: bloco de aportes (§B.3.1) e o cartão "PGBL: faltam R$ X para o limite; economia estimada R$ Y".
- Início: em novembro e dezembro, "faltam R$ X de PGBL"; em março, "a declaração abriu: veja o passo a passo";
  todo mês com venda, "DARF de R$ X vence dia D".
- Demo (`app/demo.py`): titular fictício CLT com dependente, uma segunda titular PJ, aportes de participante e
  empresa, despesas de saúde e educação marcadas, e as operações do exemplo da §A.5.

### C.4 Decisões

Do usuário (2026-10-19):

| # | Pergunta | Decisão |
|---|---|---|
| 1 | Units (TAEE11) têm a isenção de R$ 20 mil? | Sim, com aviso (classe `unit`, tratada como ação) |
| 2 | Venda de ações em day trade conta no limite de R$ 20 mil? | Conta (conservador) |
| 3 | Gerar o arquivo da declaração (.DEC) | Não: passo a passo ficha por ficha com botão de copiar |
| 4 | Ativos no exterior, cripto e imposto da empresa no Presumido e no Real | Fora desta entrega |
| 5 | Fases | Todas juntas |
| 6 | Regras desatualizadas | Aviso automático passado março (§C.7) |

Tomadas na implementação (o usuário delegou):

| # | Ponto | Decisão |
|---|---|---|
| 7 | Direito de subscrição | Fora: a planilha da B3 não traz o evento; a venda vira pendência "venda sem custo" |
| 8 | Ordem das operações sem horário | Eventos corporativos, depois compras, depois vendas, no mesmo dia |
| 9 | Vencimento do DARF | Pelo mês do pregão; feriados não entram no "último dia útil" (dito na tela) |
| 10 | IRRF sem nota | Estimado (0,005% por dia e conta, só acima de R$ 1; 1% do lucro do day trade) e marcado "est." |
| 11 | Bonificação sem custo | Custo zero (conservador) e pendência até o usuário informar |
| 12 | Prejuízo em mês isento | Compensável (pergunta 729) |
| 13 | IRRF que sobra | Desconta de qualquer grupo no mesmo ano; o saldo do fim do ano vai para a declaração |
| 14 | Categorias Saúde e Educação | Só contam depois que o usuário confirma; farmácia, academia, curso livre e material escolar saem sozinhos |
| 15 | 13º | À parte (tributação exclusiva), sem o desconto simplificado mensal (conservador) |
| 16 | Conciliação do salário | Só CLT: o pró-labore costuma cair na conta da empresa |
| 17 | Funpresp (servidor público) | Fora desta entrega |
| 18 | Menu | "Imposto de renda" é o quinto item do menu lateral; no celular, fica em "Mais" |
| 19 | IR na visão da casa | É por pessoa: na visão da casa, as telas mostram o titular principal e avisam |
| 20 | Lista de deduções | Agrupada por prestador e beneficiário, como a ficha Pagamentos Efetuados |

### C.5 Fases

| Fase | Entrega |
|---|---|
| 1 | Parâmetros por ano; `tax_class`; apuração mensal com preço médio por CPF; pendências; DARF do mês; tela Ações e fundos; MCP/CLI de leitura; exemplo da §A.5 como teste |
| 2 | Perfil fiscal, INSS, IRRF, ajuste anual com os dois modelos; aportes de previdência com o pagador; limite do PGBL e quanto falta |
| 3 | Despesas dedutíveis (categoria, lançamento, manual), consolidado e checklist; dividendos acima de 50 mil e IRPFM sem redutor |
| 4 | Passo a passo da declaração (renda variável, isentos, exclusivos, bens e direitos, pagamentos efetuados); roteiro do agente; lembretes no Início |
| 5 | PJ no Simples (fator R, DAS), DARF pago ligado ao extrato, notas de corretagem |

### C.6 Testes

Arquivos: `tests/test_ir_parametros.py`, `tests/test_ir_renda_variavel.py`, `tests/test_ir_estimador.py`,
`tests/test_ir_telas.py`, a paridade MCP/CLI em `tests/test_mcp.py` e os testes de navegador em
`tests/e2e/test_navegador.py`.

Regra do `AGENTS.md`: cada regra acima vira teste, e os exemplos das §A.5 e §B.3.4 entram com os valores exatos.

- **Parâmetros**: tabela anual por fatias igual à tabela com parcela; redutor mensal (4.500 → IRRF 0; 6.000 →
  394,54); redutor anual (78.000 → 974,88; 60.000 → 2.694,15 de teto; 88.200 → 0); INSS (5.000 → 501,51; teto →
  988,09); simplificado limitado a 17.640,00.
- **Renda variável**: preço médio por CPF com duas corretoras; isenção exatamente em 20.000,00 (isento) e em
  20.000,01 (tributável); prejuízo em mês isento compensado depois; FII separado; ETF sem isenção; day trade com
  sobra que vai para o comum; desdobro, grupamento e bonificação com custo; DARF abaixo de R$ 10 acumulado; mesma
  venda vinda da B3 e da Pluggy contada uma vez; cônjuges com limites separados; pendências bloqueando o
  "conferido".
- **Estimador**: os quatro exemplos da §B.3.4; empresa não conta no limite do PGBL; VGBL não deduz; educação
  limitada por pessoa; farmácia fora; 13º fora da base; dividendo de 50.000,00 (sem retenção) e 50.000,01 (10% do
  total); IRPFM em 600 mil (zero), 900 mil (5%) e 1,2 milhão (10%).
- **E2E**: cadastrar perfil, marcar uma despesa, registrar um aporte da empresa e do participante, ver o "falta
  aportar" mudar.
- `tests/test_mcp.py`: ferramentas novas no catálogo, com `EQUIVALENTE_CLI`, e o roteiro citando só ferramentas que
  existem.


### C.7 Aviso de regras desatualizadas

`EXERCICIO_CONFIRMADO` em `parametros.py` guarda o último exercício (ano da declaração) cujos números foram
conferidos na publicação da Receita (hoje, 2026: o Perguntas e Respostas IRPF 2026). A partir de 1º de abril do
ano Y, se `EXERCICIO_CONFIRMADO < Y`, o app avisa no sino, nas telas do IR e em `ir_contexto` (`aviso_regras`) que
as regras da declaração Y podem estar desatualizadas e pede para atualizar o Tabimoney. Quem revisa os parâmetros
sobe a constante na mesma versão, e o aviso some com a atualização. Ano sem tabela usa a do ano mais próximo, com
aviso de projeção.

## Fontes

- Receita Federal, [Perguntas e Respostas IRPF 2026](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/dirpf/p-r-irpf-2026-v1-00-2026-04-23.pdf/view), v1.0 (23/04/2026): perguntas 001, 007, 012, 331, 335 a 339, 367, 368, 387, 392, 400, 401, 704 a 745.
- Receita Federal, [Perguntas e Respostas: Tributação de Altas Rendas, lucros e dividendos](https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/dirf/manual_padrao_rfb_per_tributacao_cotin_v-19-12-2025.pdf/view) (19/12/2025).
- [Lei 15.270/2025](https://www2.camara.leg.br/legin/fed/lei/2025/lei-15270-26-novembro-2025-798354-publicacaooriginal-177117-pl.html) (texto na Câmara; [Planalto](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15270.htm)).
- [Orientação da Receita sobre a redução mensal](https://coad.com.br/home/noticias-detalhe/135095/receita-federal-orienta-fontes-pagadoras-e-contribuintes-a-calcular-a-reducao-do-imposto-de-renda-a-partir-de-1-de-janeiro-de-2026) (exemplos de 4.500 e 6.000).
- Tabela anual do AC 2026: [contabilidade.com](https://contabilidade.com/tabela-irpf/), [Jettax](https://www.jettax.com.br/blog/nova-tabela-do-ir-2026-veja-faixas-e-aliquotas/) (a confirmar na Receita).
- INSS 2026: [Convenia](https://blog.convenia.com.br/nova-tabela-inss/), [Contabilizei (pró-labore)](https://www.contabilizei.com.br/contabilidade-online/inss-pro-labore/) (a confirmar na portaria).
- MP 1.303: [Congresso Nacional](https://www.congressonacional.leg.br/materias/medidas-provisorias/-/mpv/169059), [InfoMoney](https://www.infomoney.com.br/minhas-financas/mp-1-303-cai-no-congresso-veja-como-fica-a-tributacao-dos-investimentos-agora/).
- Códigos de Bens e Direitos: [Bora Investir (B3), BDRs](https://borainvestir.b3.com.br/noticias/imposto-de-renda/renda-variavel-imposto-de-renda/como-declarar-bdrs-no-imposto-de-renda-2026-veja-guia-completo-para-nao-cometer-erros/), [Seu Dinheiro, ETFs](https://www.seudinheiro.com/2026/financas-pessoais/como-declarar-etf-no-imposto-de-renda-2026-julw/), [Suno, FIIs](https://www.suno.com.br/guias/como-declarar-fundos-de-investimento-imobiliarios-2026/).
- Compensação por grupo (FII separado): [Planejar](https://www.planejar.org.br/e-possivel-compensar-prejuizo-em-fundo-imobiliario-com-acao), [NSC Total](https://www.nsctotal.com.br/noticias/compensacao-prejuizo-bolsa-regras-calculo-imposto-de-renda-2026).
- Concorrentes: [ReVar (B3)](https://www.b3.com.br/pt_br/noticias/revar.htm), [Econet sobre o ReVar](https://blog.econeteditora.com.br/revar-regras-sobre-a-calculadora-de-renda-variavel-ferramenta-da-rfb/), [Grana](https://grana.capital/), [Mycapital](https://www.mycapital.com.br/), [Sencon](https://sencon.com.br/), [Avenue e myProfit](https://avenue.us/duvidas/quais-relatorios-auxiliares-de-imposto-de-renda-a-avenue-disponibiliza/), [Bora Investir: apps de IR 2026](https://borainvestir.b3.com.br/noticias/imposto-de-renda/imposto-de-renda-2026-8-aplicativos-que-podem-salvar-sua-declaracao-na-reta-final/).
