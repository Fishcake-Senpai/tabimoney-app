---
titulo: Análise completa de um ativo (longo prazo)
descricao: Faz a análise fundamentalista completa de um ativo para quem investe por 5, 10 ou 20 anos, no método de Raul Sena (Investidor Sardinha): pesquisa profunda, checklist de qualidade, dez anos de números, preço e o que quebraria a tese. Grava a tese no app.
---

# Análise completa de um ativo (longo prazo)

Saída esperada: **uma tese por ativo** (`kind: "tese"`), no modelo `tabimoney://docs/modelo-relatorio-tese`, gravada
no app. A tese vale por 12 meses; a cada balanço, o roteiro `analise-trimestral` só confere se ela continua de pé.

A ótica é a de um sócio que vai ficar no negócio por **10 a 20 anos, nunca menos de 5**. A pergunta não é "vai subir
no trimestre?", e sim "esta empresa vai estar maior, mais lucrativa e pagando mais daqui a 10 anos?". O método se
inspira em Raul Sena (Investidor Sardinha, AUVP), no Diagrama do Cerrado e na principal influência dele, Philip
Fisher: **qualidade primeiro, preço depois; comprar com aportes e segurar; vender só quando a tese quebra**. A
redação das perguntas é deste roteiro. Diga ao usuário que a análise é da IA, inspirada no método, e não um
conselho da AUVP.

## 0. Perfil antes de tudo

Chame `perfil_investidor` (com `titular`, se a análise for de uma pessoa).

- Se `configurado` for `false` ou `vencido` for `true`, **pergunte ao usuário e espere a resposta**:
  1. "Por quanto tempo você pretende deixar esse dinheiro investido sem precisar dele?" (menos de 5 anos, 5 a 10,
     10 a 20, mais de 20)
  2. "Na renda variável, você busca renda passiva (dividendos), crescimento do patrimônio ou os dois?"

  Grave com `perfil_definir`. Nunca escolha pelo usuário.
- **Menos de 5 anos** (`menos-de-5`): explique que ações e FIIs não cabem nesse prazo (o método pede no mínimo 5
  anos), sugira o roteiro `metas` (reserva e renda fixa) e **pare aqui**. Só siga se o usuário insistir; nesse caso,
  escreva na primeira linha do relatório que o prazo é menor que o recomendado.
- O horizonte e o objetivo mudam a ênfase, não o checklist: em 20+ anos, pesam mais perenidade, P&D e reinvestimento;
  com objetivo `renda`, pesam mais proventos consistentes e o método de Bazin.

## 1. Dados do app

1. `carteira_contexto`: peso do ativo na carteira, preço médio, metas e a `ultima_analise`.
2. `fundamentos_contexto` com o ticker: indicadores, `quarters`, a série anual `anos` (até 10 anos, com CAGR), os
   `filings` da CVM, os avisos e os relatórios anteriores. Se a série vier curta, complete com as DFPs da CVM e o
   histórico do RI, e cite as fontes.
3. Se houver tese anterior (`analise_listar` com o ticker), `analise_mostrar` para comparar.

## 2. Pesquisa profunda (obrigatória)

Ações (Brasil). Leia, no mínimo, **5 fontes distintas**, e coloque cada uma em `sources`:

1. **Relações com investidores**: release e apresentação do último resultado; carta da administração.
2. **Formulário de Referência** (CVM): controle e acordo de acionistas, tag along, remuneração da diretoria,
   fatores de risco, histórico (ano de fundação), transações com partes relacionadas, maiores clientes.
3. **DFP** (CVM) para o que o app não traz: P&D, segmentos, dívida por vencimento, contingências.
4. **Segmento de listagem na B3** (Novo Mercado, N1, N2, tradicional) e free float.
5. **Notícias dos últimos 24 meses**: escândalos, investigações, processos relevantes, troca de CEO, mudança de
   controle, regulação, recuperação judicial de clientes ou fornecedores.
6. **Dois ou três concorrentes**: margens, ROE e múltiplos, para comparar.
7. **O setor**: regulação, tendência para os próximos 10 anos, risco de disrupção.

Exterior (BDR, stock): 10-K/20-F e o relatório anual no lugar do Formulário de Referência; proxy statement para
governança. FIIs, ETFs e renda fixa: seção 8.

**Privacidade:** pesquise só com o ticker e o nome da empresa. Nada do usuário (quantidade, valor, preço médio,
titular) vai para busca ou serviço externo.

## 3. Entender o negócio

Escreva, em linguagem simples: o que a empresa vende, para quem, como ganha dinheiro, de onde vem a receita
(segmentos e regiões) e quem manda nela. Se não dá para explicar o negócio em cinco linhas, diga isso na conclusão:
não entender o negócio é motivo para não aportar.

## 4. Filtro de entrada

Para ações, todos estes precisam passar para o ativo **receber aportes novos** (inspirado no índice do ETF AUVP11):

| Filtro | Corte |
|---|---|
| Lucro líquido | positivo em **cada um** dos últimos 5 anos |
| ROE | acima de 10% (12 meses) |
| Margem líquida | acima de 8% (não vale para bancos e seguradoras) |
| Dívida líquida / EBITDA | abaixo de 3x (não vale para bancos e seguradoras) |
| Tempo de bolsa | 5 anos ou mais |
| Controle | não estatal |
| Setor | fora de varejo, proteína animal e aviação |

Valor de mercado (R$ 3 bi), free float (15%) e liquidez são observação, não eliminam. Reprovado: a análise continua,
mas a conclusão é "evitar novos aportes" e diz qual filtro falhou. Posição que já existe **não é vendida** por isso;
grave um aviso (`filtro_reprovado`) e diga na tese se ainda vale manter.

## 5. Checklist de qualidade (11 perguntas)

Responda cada uma com **sim ou não e a evidência** (número, ano ou fonte). Na dúvida, **não**.

| # | Pergunta | "Sim" quando |
|---|---|---|
| 1 | A rentabilidade é alta e constante? | ROE médio de 5 anos ≥ 10% e nenhum ano abaixo de 5% |
| 2 | Deu lucro em todos os últimos 5 anos? | lucro líquido anual positivo em cada exercício |
| 3 | Cresceu acima da inflação? | CAGR de 5 anos da receita **ou** do lucro acima do IPCA do período |
| 4 | A dívida está sob controle? | dívida líquida/EBITDA < 3x ou dívida líquida < lucro de 12 meses. Bancos: Basileia com folga sobre o mínimo e inadimplência estável |
| 5 | Paga proventos de forma consistente? | pagou em todos os últimos 5 anos, sem cortes grandes fora de crise |
| 6 | Investe em pesquisa, inovação ou expansão, num negócio que não está ficando obsoleto? | P&D, capex de expansão ou lançamentos relevantes; setor em declínio é sempre "não" |
| 7 | Tem mais de 30 anos de história? | fundada há 30 anos ou mais |
| 8 | É líder ou tem vantagem clara sobre os concorrentes? | liderança, marca, escala, custo, rede, patente ou concessão |
| 9 | O setor é perene? | atende uma necessidade que vai existir daqui a 20 anos |
| 10 | A gestão e a governança são boas? | sem histórico de corrupção ou fraude; Novo Mercado ou tag along ≥ 80%; partes relacionadas comuns. Exterior: sem ações de voto desigual que calem o minoritário |
| 11 | É livre de controle estatal e de cliente único? | controle privado e nenhum cliente com mais de ~30% da receita |

- **Nota** = respostas sim − respostas não (de −11 a +11).
- **`score`** = 10 × sim ÷ 11, com uma casa.
- **Papel na carteira**: **núcleo** com score ≥ 8 (9 ou mais "sim"); **complementar** de 5 a 7,9 (6 a 8 "sim");
  **evitar novos aportes** abaixo de 5 (nota ≤ 0: no método, não recebe aporte).
- Objetivo `crescimento`: a pergunta 5 pode ser "não" sem pesar na conclusão (empresa que reinveste com ROE alto);
  explique no texto. A nota continua a mesma, para comparar ativos.
- Se uma resposta mudou desde a tese anterior, diga por quê.

## 6. Leitura de longo prazo (Philip Fisher)

Em texto, com as fontes: o mercado permite crescer as vendas por vários anos? A gestão cria produtos novos quando os
atuais param de crescer? As margens são boas e estão melhorando? A vantagem é difícil de copiar? A gestão pensa no
longo prazo ou no trimestre? O crescimento vai exigir emitir ações e diluir o acionista? A gestão fala com franqueza
quando as coisas vão mal? É íntegra?

## 7. Preço e margem de segurança

O preço **não muda a nota**; ele decide a prioridade do aporte. Use dois métodos, conforme o tipo:

| Empresa | Métodos |
|---|---|
| Lucrativa e estável | Graham, √(22,5 × LPA × VPA), e P/L médio de 5 a 10 anos × LPA normalizado |
| Boa pagadora (ou objetivo `renda`) | Bazin, dividendo por ação ÷ 6%, e P/L médio |
| Crescimento ou PL pequeno | P/L médio e fluxo de caixa descontado simples (crescimento até o CAGR de 5 anos; na perpetuidade, no máximo 10% ao ano) |
| Banco ou seguradora | P/VP justo pelo ROE sustentável e P/L médio |

- `fair_price` = o **menor** dos dois. Escreva as premissas.
- Margem de segurança = (justo − preço) ÷ justo. `verdict`: `barata` com margem ≥ 20%; `justa` entre −10% e 20%;
  `cara` com o preço mais de 10% acima do justo.
- Núcleo e cara: manter e pausar aportes. Evitar e barata: continua evitar.

## 8. Outros tipos de ativo

**FIIs.** Leia o relatório gerencial e o informe mensal (FNET/B3), o regulamento e as notícias. Seis perguntas, nota =
sim − não, `score` = 10 × sim ÷ 6 (núcleo ≥ 8; evitar < 5):

| # | Tijolo | Papel (recebíveis) |
|---|---|---|
| 1 | Imóveis de qualidade e bem localizados? | Carteira majoritariamente high grade, com garantias reais? |
| 2 | Vacância física abaixo de 10% e estável? | Inadimplência baixa e LTV médio abaixo de 70%? |
| 3 | 5 ou mais imóveis e nenhum inquilino com mais de ~25% da receita? | Nenhum devedor com mais de ~10% do patrimônio? |
| 4 | Gestora com 5+ anos de histórico e política de investimento clara? | idem |
| 5 | Taxa de administração + gestão até ~1% ao ano, sem performance abusiva? | idem |
| 6 | Pagou todo mês nos últimos 3 anos, sem cortes grandes? | idem, com o rendimento vindo do resultado e não de reserva |

Preço do FII: P/VP (acima de 1,5 é `cara`; abaixo de 1 favorece) e o dividend yield contra a NTN-B longa. Fundos de
fundos e híbridos usam as perguntas da maior parte da carteira.

**ETFs.** Índice e metodologia, taxa total, tamanho, liquidez, diferença para o índice, domicílio e imposto. Sem
checklist de empresa: a conclusão diz se o ETF cumpre o papel na meta (por exemplo, a fatia internacional).

**Renda fixa e previdência.** `subject` = nome do produto, `subject_type` = `renda_fixa` (ou `previdencia`). Taxa
contratada × taxa de hoje, crédito do emissor e FGC, liquidez, imposto e o **casamento com o horizonte**: para 10 a
20 anos, títulos IPCA+ longos travam juro real; resgatar antes do vencimento realiza a marcação a mercado. A reserva
de emergência não entra nessa conta.

## 9. O que quebra a tese

De três a cinco **gatilhos objetivos**, que dá para conferir a cada balanço ("dívida líquida/EBITDA acima de 3x",
"prejuízo no ano", "perda da concessão X", "troca de controle"). O `analise-trimestral` confere esses gatilhos.

## 10. Conclusão e gravação

- Conclusão: papel (núcleo, complementar, evitar), nota, veredito de preço e o que fazer **com aportes**, respeitando
  as metas de alocação. Diga quando reavaliar. Não recomende vender aqui; isso é do roteiro `recomendacoes`, pelos
  critérios dele.
- Grave com `analise_importar` (exemplo em `tabimoney://exemplos/analise-ativo`):
  - `report.kind` = `"tese"`; `period` = trimestre do último balanço (`2T26`); `verdict`, `score`, `fair_price` e
    `sources` (todas as fontes lidas).
  - `metrics` (`period_type` `"SNAPSHOT"`): `nota_qualidade`, `checklist_sim`, `filtro_entrada` (1 passa, 0
    reprova), `margem_seguranca` e as que você calculou, como `roe_medio_5a`, `cagr_receita_5a`, `cagr_lucro_5a`,
    `cagr_lucro_10a`, `cagr_proventos_5a` e `anos_com_lucro_10a`. FIIs: `nota_qualidade`, `vacancia_fisica`, `pvp`
    e `dy_12m`.
  - `alerts` só para o que muda decisão (`filtro_reprovado`, `tese_quebrada`, `governanca`).
- Resposta ao usuário: o papel e a nota, as três razões principais, o preço, o que fazer com o próximo aporte e
  onde está a tese completa (página do ativo).

## Padrões

- Muitos ativos: no máximo **3 teses por sessão**, começando pelos de maior peso na carteira; liste os que ficaram
  para a próxima.
- Seja explícito sobre incerteza e dados faltando. Número sem fonte não entra.
- Nada de previsão de preço de curto prazo, análise gráfica ou "momento de entrada".
