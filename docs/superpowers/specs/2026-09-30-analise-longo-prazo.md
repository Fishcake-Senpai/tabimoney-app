# Análise fundamentalista de longo prazo, no método do Investidor Sardinha

Data: 2026-09-30 · Estado: **implementada e lançada na 0.15.0** · Versão-alvo: **0.15.0**

## 1. Objetivo

Os roteiros de investimento do Tabimoney (`analise-trimestral` e `recomendacoes`) foram escritos com a cabeça no
**trimestre**: o veredito sai do preço (barata, justa, cara), o checklist tem cinco itens e as recomendações
declaram o "horizonte (trimestre)". O Tabimoney é uma ferramenta de **longo prazo**, e a análise precisa olhar
como um sócio que vai ficar 10 ou 20 anos no negócio, nunca menos de 5.

Esta mudança reescreve as skills de análise com base no método de **Raul Sena (Investidor Sardinha, AUVP)**:

1. **Antes de começar, a skill pergunta o horizonte** (e o objetivo) do investidor. Com menos de 5 anos, ela não
   segue para renda variável.
2. **Uma análise completa por ativo, com pesquisa profunda**: negócio, vantagem competitiva, gestão, 10 anos de
   números, o checklist de qualidade do método, o preço e o que quebraria a tese. Fontes obrigatórias e citadas.
3. **Qualidade primeiro, preço depois**: a nota mede a empresa; o preço só decide a prioridade do aporte.
4. **Comprar e segurar**: recomendações feitas com aportes; venda só quando a tese quebra.

### Critérios de sucesso

| Critério | Hoje | Meta |
|---|---|---|
| Horizonte do investidor | não é perguntado | perguntado antes da 1ª análise, guardado e citado em todo relatório |
| Profundidade por ativo | 1 documento da CVM + release | negócio, setor, gestão, governança, 10 anos de números, pares e notícias; mínimo de 5 fontes por ação |
| Checklist de qualidade | 5 itens, misturando preço | 11 perguntas de qualidade (sim/não, com a evidência) + filtro de entrada; preço à parte |
| Histórico de números | 3 anos (`YEARS_BACK = 3`) | 10 anos de balanço anual (DFP) |
| Venda | "quando o fundamento piorou ou o preço passou do justo" | só com a tese quebrada (critérios escritos, §4.9) |
| Distribuição do aporte entre ativos | livre | proporcional à nota de qualidade; nota ≤ 0 não recebe aporte |

## 2. O que a pesquisa mostrou

### 2.1 Quem é e como pensa

Raul Sena (Goiânia, 1993) criou o canal Investidor Sardinha em 2019 e fundou a AUVP ("A Única Verdade Possível"),
escola de investimentos, hoje em parceria com o BTG. Também é autor do livro *A Única Verdade Possível: Enriqueça
no longo prazo*. Os pontos que se repetem em todas as fontes:

- **Buy and hold.** Comprar para ficar, aumentando a participação nas empresas ao longo do tempo, sem tentar
  acertar o momento. Ganhar com o tempo, não com a operação.
- **A principal influência declarada é Philip Fisher**, o investidor de qualidade e longo prazo (*Ações comuns,
  lucros extraordinários*). Fisher defende que a boa ação não se vende. Benjamin Graham aparece como influência
  secundária (margem de segurança).
- **As perguntas da análise**: a empresa tem vantagem competitiva? Mostra bons resultados? Gera caixa? Tem dívida
  excessiva? Consegue crescer? Como é a governança? **O preço pago faz sentido?** O preço é a última pergunta,
  não a primeira.
- **O que ele olha com mais cuidado**: quanto tempo a empresa tem de mercado e quanto investe em pesquisa e
  desenvolvimento (quem investe em inovação tende a crescer o lucro ao longo dos anos).
- **O que ele evita**: estatais (incerteza política e troca frequente de gestão) e empresas com prejuízos
  recorrentes por longos períodos.
- **"Qualidade é infinitamente melhor que quantidade."** Poucos ativos bons em vez de muitos medianos.
- **Pré-requisitos do curso**: sem dívidas caras, reserva de emergência pronta e **horizonte mínimo de 5 anos**.
  O curso exclui day trade, análise gráfica e especulação.
- **Diversificação entre classes**: renda fixa, ações Brasil, FIIs, exterior e uma parcela pequena em reserva de
  valor (cripto), cada classe com meta em %.

### 2.2 O Diagrama do Cerrado (o método de notas)

É a ferramenta central da AUVP para decidir **o aporte do mês**:

1. O investidor define a meta de cada classe (ex.: 30% ações, 20% FIIs, 20% exterior, 15% renda fixa, 15% cripto).
2. Cada ativo responde a um questionário de **sim ou não** sobre a qualidade (11 perguntas para ações, nacionais e
   internacionais; 6 para FIIs).
3. **Nota = respostas sim − respostas não.** Ativo com nota ≤ 0 não recebe aporte.
4. O aporte vai **primeiro para as classes abaixo da meta**, proporcional ao que falta; **dentro da classe, para os
   ativos, proporcional à nota** e ao que falta para o peso-alvo.
5. **Nunca manda vender**: a carteira converge para o alvo só com aportes.

O passo 4 entre classes é exatamente o que o plano de aporte do Tabimoney já faz (`metas_mostrar`, "nunca vende").
O que falta é a nota por ativo e a distribuição dentro da classe.

As perguntas de ações, como aparecem nas transcrições públicas (comunidade AUVP e ferramentas abertas):

- ROE historicamente maior que 5%? (a comunidade costuma subir para 10% ou 15%)
- A dívida líquida é menor que o lucro líquido dos últimos 12 meses?
- Cresceu receita ou lucro acima de 5% ao ano (ou acima da inflação) nos últimos 5 anos?
- Tem histórico de pagamento de dividendos (acima de 4% a 5% nos últimos 5 anos)?
- Investe amplamente em pesquisa e inovação? (setor obsoleto é sempre "não")
- Tem mais de 30 anos de mercado (fundação)?
- É líder nacional ou mundial no setor (blue chip), tem monopólio ou vantagem clara sobre os concorrentes?
- O setor em que atua tem mais de 100 anos (perene)?
- Tem boa gestão? (histórico de corrupção é sempre "não")
- É livre de controle estatal e de concentração em um cliente único?
- Tem lucro em todos os últimos 5 anos (nunca deu prejuízo no exercício)?

Para FIIs, as 6 perguntas giram em torno de: P/VP abaixo de 1 (acima de 1,5 descarta), vacância física baixa
(abaixo de ~9–10%), localização e qualidade dos imóveis, não depender de um único inquilino ou imóvel, taxa de
administração razoável e gestão com histórico e política de investimento clara.

### 2.3 O filtro quantitativo público: o índice do AUVP11

Em 2026 a AUVP lançou com o BTG o ETF **AUVP11**, que replica o **Índice Teva Ações Fundamentos (IAFD)**, montado
pela AUVP Analítica a partir de cerca de 400 empresas da B3. É a versão objetiva e pública do método. Para
entrar, a empresa precisa de **todos** os filtros:

| Filtro | Corte |
|---|---|
| Lucro líquido | positivo em **cada um** dos últimos 5 anos |
| ROE | acima de 10% |
| Margem líquida | acima de 8% |
| Dívida líquida / EBITDA | abaixo de 3x |
| Tempo de bolsa | pelo menos 5 anos |
| Valor de mercado | a partir de R$ 3 bilhões |
| Free float | a partir de 15% |
| Liquidez | R$ 100 milhões negociados em cada um dos 2 meses anteriores |
| Setores excluídos | varejo, proteína animal e transporte aéreo ("sem histórico sustentável de criação de valor no longo prazo") |

### 2.4 Philip Fisher, a influência principal

Dos 15 pontos de Fisher, os que viram perguntas na análise qualitativa:

- O produto ou serviço tem mercado para crescer as vendas por **vários anos**?
- A gestão está decidida a criar produtos novos quando os atuais pararem de crescer? (P&D)
- As margens são boas e estão melhorando?
- A empresa tem **vantagem** difícil de copiar no seu ramo?
- A gestão olha o **longo prazo** ou o lucro do trimestre?
- O crescimento vai exigir emissão de ações que dilua o acionista?
- A gestão fala com franqueza com o acionista também quando as coisas vão mal?
- A gestão é íntegra?

E as **três razões para vender** de Fisher: (1) a análise original estava errada; (2) a empresa deixou de passar
nos critérios (a tese quebrou); (3) apareceu um uso muito melhor para o dinheiro. Preço alto sozinho não é razão.

### 2.5 Preço: margem de segurança, não timing

As referências de preço que circulam no ecossistema (inclusive nas ferramentas abertas do método) são:

- **Graham**: valor intrínseco = √(22,5 × LPA × VPA). Para empresas estáveis e lucrativas; não serve para
  crescimento alto nem para quem tem PL pequeno.
- **Bazin**: preço-teto = dividendo por ação ÷ 6%. Para boas pagadoras de dividendos.
- **P/L histórico**: P/L médio de 5 a 10 anos × lucro por ação normalizado.
- **Fluxo de caixa descontado simples**, com crescimento conservador.

No método, o preço **não decide se a empresa é boa**. Ele decide **quanto do aporte vai para ela agora**.

### 2.6 Limites da pesquisa

- A lista literal do Diagrama do Cerrado é material do curso pago e tem variações (a própria AUVP mudou os cortes
  e os alunos ajustam as perguntas). A comunidade bloqueia leitura automatizada, então as perguntas acima vêm de
  trechos públicos. **A spec usa redação própria**, inspirada no método, e diz isso no roteiro.
- Os cortes objetivos mais confiáveis são os do IAFD (AUVP11), públicos e da própria AUVP.
- O roteiro não vai se apresentar como "o método oficial da AUVP". Ele cita a inspiração (Raul Sena, Diagrama do
  Cerrado, Philip Fisher) e deixa claro que a análise é da IA.

## 3. Diagnóstico das skills atuais

| Onde | Problema |
|---|---|
| `analise-trimestral.md` | Não pergunta horizonte nem objetivo. Pesquisa = "leia o ITR e o release". Veredito e nota saem do preço. |
| `modelo-relatorio-trimestral.md` | Seções de trimestre (resultado contra o mesmo trimestre do ano anterior). Não tem negócio, vantagem competitiva, gestão, governança nem história longa. Checklist de 5 itens mistura qualidade e preço ("preço abaixo do justo"). |
| `recomendacoes.md` | "Deixe claro o horizonte (trimestre)". `reduzir`/`vender` quando "o preço passou do justo". Nada liga a nota ao peso do ativo. |
| `ciclo.md` | Refaz a análise se o preço andou mais de 15%: reação a preço, não a fundamento. |
| Dados | `YEARS_BACK = 3` em `app/services/fundamentals.py`: não dá para responder "lucro em todos os últimos 5 anos", "ROE histórico" nem CAGR de 5 anos com os dados do app. |
| FIIs e ETFs | "Modelo adaptado" de uma linha, sem critérios. |

## 4. A proposta

### 4.1 Pergunta de horizonte e objetivo (antes de tudo)

Antes da primeira análise, a skill confere se o perfil está guardado (`perfil_investidor`). Se não estiver, ou se
tiver mais de 12 meses, pergunta ao usuário e grava (`perfil_definir`):

1. **Horizonte**: "Por quanto tempo você pretende deixar esse dinheiro investido sem precisar dele?"
   Respostas: `5 a 10 anos`, `10 a 20 anos`, `mais de 20 anos`, `menos de 5 anos`.
2. **Objetivo da renda variável**: `renda passiva` (dividendos), `crescimento do patrimônio` ou `os dois`.

Regras:

- **Menos de 5 anos**: a skill explica que ações e FIIs não cabem nesse prazo (no método, 5 anos é o mínimo),
  sugere revisar reserva e renda fixa (roteiro `metas`) e **não faz análise de compra**. Só segue se o usuário
  insistir, e diz isso no relatório.
- O horizonte muda o peso das coisas: em 20+ anos pesam mais perenidade, P&D e reinvestimento; com objetivo de
  renda passiva pesam mais dividendos consistentes e Bazin. O checklist é o mesmo; o texto da tese e a escolha do
  método de preço mudam.
- Com mais de um titular, o perfil é **por titular** (como as metas). Sem titular, vale o da casa.
- No `ciclo`, essa é a única pergunta permitida, e só quando o perfil está faltando ou vencido. Com o perfil
  guardado, o ciclo segue sem perguntar.
- Todo relatório abre com a linha **"Horizonte: 10 a 20 anos · Objetivo: crescimento"**.

### 4.2 Organização das skills

| Roteiro | Papel | Quando |
|---|---|---|
| **`analise-ativo`** (novo) | A análise completa de **um** ativo: pesquisa profunda, tese de longo prazo, checklist, preço e o que quebra a tese. Relatório `kind: "tese"`. | Ativo sem tese; tese com mais de 12 meses; tese quebrada no acompanhamento; pedido do usuário ("analisa a fundo a WEGE3"); ativo novo antes de comprar. |
| **`analise-trimestral`** (reescrito) | O **acompanhamento** do trimestre: o balanço novo mantém a tese de pé? Atualiza o checklist com os números novos, a nota e o preço. Relatório `kind: "trimestral"`, curto. | A cada balanço. Para cada ativo sem tese válida, chama `analise-ativo` primeiro. |
| `recomendacoes` (ajustado) | Distribuição do aporte pelo método de notas (§4.8) e venda só com tese quebrada (§4.9). | Depois das análises. |
| `ciclo` (ajustado) | Pergunta o perfil se faltar; troca o gatilho "preço andou 15%" por "balanço novo, aviso novo ou tese vencida". | "Atualize tudo". |
| `visao-geral`, `metas` (ajustados) | Tabela de roteiros com o novo; `metas` mostra o horizonte. | — |

Por que separar: a análise completa é cara (pesquisa de várias fontes por ativo). Refazer tudo a cada trimestre
para uma carteira de 15 ativos não cabe numa sessão e não faz sentido para quem fica 20 anos. A tese é a peça
pesada e dura um ano; o trimestre só confere se ela continua de pé. É o que Fisher manda: acompanhar o negócio,
não o preço.

### 4.3 A análise completa (`analise-ativo`), passo a passo

0. **Perfil**: `perfil_investidor` (§4.1).
1. **Dados do app**: `fundamentos_contexto` (com a série anual de 10 anos, §5.1) e `carteira_contexto` (peso na
   carteira, preço médio, a tese anterior). Se houver tese anterior, `analise_mostrar`.
2. **Pesquisa profunda.** Fontes **obrigatórias** para ações (cada uma vai em `sources`):
   1. **Relações com investidores**: o release e a apresentação do último resultado; a carta da administração.
   2. **Formulário de Referência** (CVM): controle e acordo de acionistas, tag along, remuneração da diretoria,
      fatores de risco, histórico da companhia, transações com partes relacionadas.
   3. **DFP dos últimos anos** (CVM) para conferir o que o app não traz (P&D, segmentos, dívida por vencimento).
   4. **Segmento de listagem na B3** (Novo Mercado, N1, N2, tradicional) e free float.
   5. **Notícias dos últimos 24 meses**: escândalos, processos relevantes, investigações, troca de CEO, mudança de
      controle, recuperação judicial de clientes ou fornecedores, mudança regulatória.
   6. **Dois ou três concorrentes**: margens, ROE e múltiplos para comparar.
   7. **O setor**: regulação, tendência de 10 anos, risco de disrupção.

   Mínimo de **5 fontes distintas** por ação. A pesquisa usa só o ticker e o nome da empresa; **nenhum dado do
   usuário** (quantidade, valor, preço médio) vai para busca externa.
3. **Entender o negócio** (seção "O negócio"): o que vende, para quem, como ganha dinheiro, de onde vem a receita
   (segmentos, regiões), quem manda na empresa.
4. **Filtro de entrada** (§4.5): passa ou não. Reprovado num filtro eliminatório, a análise continua, mas a
   conclusão já sai "evitar novos aportes" e diz qual filtro falhou.
5. **Checklist de qualidade** (§4.4): as 11 perguntas, cada uma com **sim/não e a evidência** (número ou fonte).
   Na dúvida, "não".
6. **Leitura qualitativa (Fisher)**: crescimento por vários anos, P&D, margens, vantagem, visão de longo prazo da
   gestão, diluição, franqueza com o acionista, integridade. Em texto, apoiado nas fontes.
7. **Dez anos de números**: tabela anual de receita, lucro, margem líquida, ROE, dívida líquida/EBITDA, proventos
   por ação e payout; CAGR de 5 e de 10 anos de receita, lucro e proventos; anos com prejuízo.
8. **Preço** (§4.6): margem de segurança por dois métodos adequados ao tipo de empresa, com as premissas.
9. **O que quebra a tese**: de três a cinco gatilhos objetivos e verificáveis no trimestre ("dívida líquida/EBITDA
   acima de 3x", "perder a concessão X em 2031", "prejuízo anual"). É o que o `analise-trimestral` confere depois.
10. **Conclusão**: nota, papel na carteira (núcleo, complementar, evitar), veredito de preço e o que fazer **com
    aportes**. Respeita as metas de alocação.
11. **Gravação**: `analise_importar` com `kind: "tese"`, as métricas do §4.7 e avisos só do que muda decisão.

### 4.4 Checklist de qualidade (ações, Brasil e exterior)

Redação própria, inspirada no Diagrama do Cerrado, com cortes objetivos onde dá (do IAFD quando existe):

| # | Pergunta | "Sim" quando | Onde verificar |
|---|---|---|---|
| 1 | A rentabilidade é alta e constante? | ROE médio de 5 anos ≥ 10% e nenhum ano abaixo de 5% | série anual (app) |
| 2 | Deu lucro em todos os últimos 5 anos? | lucro líquido anual > 0 em cada exercício | série anual |
| 3 | Cresceu acima da inflação? | CAGR de 5 anos da receita **ou** do lucro acima do IPCA do período | série anual + IPCA |
| 4 | A dívida está sob controle? | dívida líquida/EBITDA < 3x (ou dívida líquida < lucro 12M). Bancos: Basileia com folga sobre o mínimo e inadimplência estável | app; release |
| 5 | Paga proventos de forma consistente? | pagou em todos os últimos 5 anos, sem cortes grandes fora de crise | app; RI |
| 6 | Investe em pesquisa, inovação ou expansão, num negócio que não está ficando obsoleto? | P&D, capex de expansão ou lançamentos relevantes; setor em declínio é "não" | DFP, RI, notícias |
| 7 | Tem mais de 30 anos de história? | fundação há 30 anos ou mais | Formulário de Referência |
| 8 | É líder ou tem vantagem clara sobre os concorrentes? | liderança, marca, escala, custo, rede, patente ou concessão | RI, setor, pares |
| 9 | O setor é perene? | atende necessidade que vai existir em 20 anos (energia, saneamento, bancos, seguros, telecom, alimentos, saúde…) | setor |
| 10 | A gestão e a governança são boas? | sem histórico de corrupção ou fraude; Novo Mercado ou tag along ≥ 80%; transações com partes relacionadas comuns | Formulário de Referência, notícias |
| 11 | É livre de controle estatal e de cliente único? | controle privado e nenhum cliente com mais de ~30% da receita | Formulário de Referência |

- **Nota** = sim − não (de −11 a +11), o número do método. Vai em `metrics` como `nota_qualidade`.
- **`score` (0–10)** = 10 × sim ÷ 11, arredondado a uma casa. Mantém o campo que a tela já mostra.
- **Papel na carteira**:
  - **núcleo**: score ≥ 8 (9 ou mais "sim");
  - **complementar**: score de 5 a 7,9 (6 a 8 "sim"; nota positiva);
  - **evitar novos aportes**: score < 5 (5 "sim" ou menos; nota ≤ 0). No método, não recebe aporte.
- Objetivo **crescimento**: a pergunta 5 pode ser "não" sem pesar na conclusão; o texto explica (empresa que
  reinveste tudo com ROE alto). A nota continua sendo a nota, para comparar ativos.
- **Exterior** (BDR, stock, ETF de ação única): mesmas perguntas, com 10-K/20-F no lugar do Formulário de
  Referência; a pergunta 10 olha ações com voto desigual (dual class) no lugar do tag along; a 3 usa a inflação
  da moeda da empresa.

### 4.5 Filtro de entrada (eliminatório para comprar mais)

Inspirado no IAFD. Reprovar em qualquer um muda a conclusão para "evitar novos aportes" e gera aviso:

| Filtro | Corte |
|---|---|
| Lucro | positivo em cada um dos últimos 5 anos |
| ROE | > 10% (12M) |
| Margem líquida | > 8% (não se aplica a bancos e seguradoras) |
| Dívida líquida/EBITDA | < 3x (não se aplica a bancos e seguradoras) |
| Tempo de bolsa | ≥ 5 anos |
| Controle | não estatal |
| Setor | fora de varejo, proteína animal e aviação |

Valor de mercado (R$ 3 bi), free float (15%) e liquidez entram como **observação** e não eliminam: o índice
precisa deles por ser um ETF; a pessoa física, não. Posição que já existe e reprova **não é vendida** por isso: vira
aviso e a tese diz se ainda vale manter (§4.9).

### 4.6 Preço: margem de segurança

- Dois métodos por ativo, escolhidos pelo tipo:
  - lucrativa e estável: **Graham** + **P/L médio de 5–10 anos**;
  - boa pagadora (ou objetivo renda passiva): **Bazin** (6%) + P/L médio;
  - crescimento ou PL pequeno: **P/L médio** + **fluxo de caixa descontado simples**, com crescimento
    conservador (no máximo o CAGR de 5 anos e nunca acima de 10% a.a. na perpetuidade);
  - bancos: **P/VP × ROE sustentável** + P/L médio.
- `fair_price` = o **menor** dos dois (conservador). Premissas escritas no relatório.
- **Margem de segurança** = (justo − preço) ÷ justo. Veredito:
  - `barata`: margem ≥ 20%;
  - `justa`: margem entre −10% e 20%;
  - `cara`: preço mais de 10% acima do justo.
- O veredito **não muda a nota**. Ele muda a prioridade do aporte (§4.8). Empresa núcleo e cara: manter e pausar
  aportes. Empresa evitar e barata: continua evitar ("barato pode ficar mais barato").

### 4.7 Métricas gravadas (`metrics`, `period_type: "SNAPSHOT"` salvo indicação)

`nota_qualidade` (pontos), `checklist_sim` (0–11), `margem_seguranca` (fração), `roe_medio_5a`, `margem_liquida_media_5a`,
`cagr_receita_5a`, `cagr_lucro_5a`, `cagr_receita_10a`, `cagr_lucro_10a`, `cagr_proventos_5a`, `anos_com_lucro_10a`,
`filtro_entrada` (1 passa, 0 reprova). Para FIIs: `nota_qualidade`, `vacancia_fisica`, `pvp`, `dy_12m`.

### 4.8 Recomendações: o aporte pelo método de notas

1. **Entre classes**: o plano de aporte do app (metas), como hoje.
2. **Dentro da renda variável**, por classe (ações BR, FIIs, exterior):
   - só entram ativos com **nota > 0** e filtro de entrada aprovado;
   - **peso-alvo** de cada ativo = nota ÷ soma das notas da classe (o mesmo do método);
   - o aporte vai para os ativos **mais abaixo do peso-alvo**, proporcional ao que falta;
   - veredito `cara` → o ativo sai da fila deste aporte (fica para o próximo); `barata` → sobe na fila.
3. `target_weight` = peso-alvo; `conviction` = 1 a 5 a partir do score (≥ 9 → 5; 8 → 4; 6,5 → 3; 5 → 2; abaixo → 1).
4. Ativo novo só entra com análise completa (`analise-ativo`) gravada.
5. A tese (`body_md`) troca "horizonte (trimestre)" por **horizonte do investidor** e acrescenta a seção "Pesos-alvo
   pelo método de notas" (tabela ativo → nota → peso-alvo → peso hoje → falta).
6. Carteiras-modelo: o núcleo (score ≥ 8) do usuário completado por ativos núcleo que ele ainda não tem.

### 4.9 Quando sugerir venda (critérios escritos)

Só com um destes, e com `conviction` justificada:

1. **A tese quebrou**: um gatilho do §4.3-9 disparou, o checklist caiu para nota ≤ 0, prejuízo anual sem causa
   pontual, fraude ou investigação grave, estatização ou mudança de controle ruim, perda da vantagem competitiva.
2. **A análise original estava errada** (fato novo que já existia e não foi visto).
3. **Uso muito melhor para o dinheiro**: ativo complementar trocado por um núcleo da mesma classe, quando aportes
   sozinhos levariam anos para corrigir.

Preço alto sozinho **nunca** é motivo de venda; no máximo, `manter` com aportes pausados. Toda venda lembra que o
ganho de capital pode gerar imposto e pede para conferir a regra vigente (a IA não assume alíquota nem isenção).

### 4.10 Modelo do relatório completo (`kind: "tese"`)

```markdown
Horizonte: 10 a 20 anos · Objetivo: crescimento · Papel: núcleo (8,2/10)

## Resumo
Cinco linhas: o negócio, por que é (ou não) bom para ficar 10+ anos, a nota, o preço e o que fazer com aportes.

## O negócio
O que vende, para quem, como ganha dinheiro, segmentos e regiões, quem controla.

## Vantagem competitiva e setor
Por que os concorrentes não tomam esse lucro. O setor daqui a 10–20 anos: perenidade, regulação, disrupção.

## Gestão e governança
Controle, segmento de listagem, tag along, histórico da gestão, remuneração, partes relacionadas, polêmicas.

## Dez anos de números
| Ano | Receita | Lucro | Margem líq. | ROE | DL/EBITDA | Proventos/ação | Payout |
CAGR de 5 e 10 anos; anos com prejuízo e por quê.

## Filtro de entrada
Tabela filtro → valor → passa/reprova.

## Checklist de qualidade
- [x] 1. Rentabilidade alta e constante: ROE médio de 5 anos de 21%.
- [ ] 7. Mais de 30 anos de história: fundada em 2005.
...
Nota: +7 (9 sim, 2 não) · Score 8,2 · Papel: núcleo

## Leitura de longo prazo
Os pontos de Fisher que importam para este ativo, com as fontes.

## Preço e margem de segurança
Os dois métodos, premissas e o preço justo; margem de segurança e veredito.

## O que quebra a tese
- Gatilhos objetivos, verificáveis a cada balanço.

## Conclusão
O que fazer **com aportes**, respeitando as metas de alocação. Quando reavaliar.
```

O relatório **trimestral** (acompanhamento) fica curto: Resumo; Resultado do trimestre (como hoje); Os gatilhos da
tese (tabela gatilho → hoje → ok/disparou); Checklist atualizado (só o que mudou); Preço; Conclusão ("tese de pé" ou
"tese quebrada: refazer a análise completa").

### 4.11 FIIs, ETFs e renda fixa

**FIIs**: pesquisa no relatório gerencial e no informe mensal (FNET/B3), regulamento e notícias. Checklist de 6
perguntas, nota = sim − não, `score` = 10 × sim ÷ 6:

| # | Tijolo | Papel (recebíveis) |
|---|---|---|
| 1 | Imóveis de qualidade e bem localizados (classe A/AAA, regiões consolidadas)? | Carteira majoritariamente high grade, com garantias reais? |
| 2 | Vacância física abaixo de 10% e estável? | Inadimplência e atrasos baixos; LTV médio abaixo de 70%? |
| 3 | Diversificado: 5+ imóveis e nenhum inquilino com mais de ~25% da receita? | Nenhum devedor com mais de ~10% do patrimônio? |
| 4 | Gestão com histórico (5+ anos) e política de investimento clara? | idem |
| 5 | Taxa de administração + gestão até ~1% a.a., sem performance abusiva? | idem |
| 6 | Rendimento consistente: pagou todo mês nos últimos 3 anos, sem cortes grandes? | idem, e o rendimento vem de resultado, não de reserva |

Preço do FII: P/VP (acima de 1,5 descarta; abaixo de 1 favorece) e DY contra a NTN-B longa. Fundos de fundos e
híbridos usam as perguntas da maior parte da carteira.

**ETFs**: índice e metodologia, taxa total, tamanho e liquidez, diferença para o índice, onde está domiciliado e
o imposto. Sem nota de qualidade de empresa; a conclusão diz se o ETF cumpre o papel na meta (ex.: internacional).

**Renda fixa**: como hoje, mais o casamento com o horizonte: para 10–20 anos, Tesouro IPCA+ e títulos longos
travam juro real; resgatar antes do vencimento realiza a marcação a mercado. A reserva de emergência fica fora.

## 5. Mudanças no código

### 5.1 Dados: dez anos de balanço anual

- `YEARS_BACK` passa a valer só para o **ITR** (3 anos, como hoje); a **DFP** (anual) baixa **10 anos**. Os anos
  fechados há mais de 2 anos já ficam 60 dias no cache (`cvm.fetch_zip`), então o custo é na primeira vez (cada
  zip da DFP tem dezenas de MB; medir antes e avisar na tela de progresso).
- `fundamentos_contexto` ganha **`anos`**: série anual (receita, EBIT, lucro, margem líquida, ROE, dívida líquida,
  dívida líquida/EBITDA, proventos pagos, ações) e os CAGR de 5 e 10 anos, para a IA não montar ano a partir de
  trimestre. Bancos e seguradoras sem EBITDA, como hoje.
- Sem migração: os balanços já ficam na tabela de fundamentos por `period_end`.

### 5.2 Perfil do investidor

- Guardado em `app_setting` (chave `perfil_investidor` e `perfil_investidor:<titular>`), sem migração:
  `{"horizonte": "10-20", "objetivo": "crescimento", "atualizado_em": "2026-09-30"}`.
- Operação `perfil_investidor` (leitura) e `perfil_definir` (escrita reversível) em `app/agente/operacoes.py`,
  com ferramenta MCP, `EQUIVALENTE_CLI` e comando `financas perfil mostrar|definir`.
- `carteira_contexto` passa a trazer `perfil` (e `perfil_vencido: true` com mais de 12 meses).
- Na interface: uma linha em **Investimentos › Metas** ("Horizonte: 10 a 20 anos · Objetivo: crescimento", com
  editar). Mínimo; a análise continua sendo da IA.

### 5.3 Arquivos

| Arquivo | Mudança |
|---|---|
| `app/agente/roteiros/analise-ativo.md` | **novo** (§4.3–4.7, 4.10, 4.11) |
| `app/agente/roteiros/analise-trimestral.md` | reescrito como acompanhamento (§4.2) |
| `app/agente/roteiros/recomendacoes.md` | método de notas e venda (§4.8–4.9), horizonte |
| `app/agente/roteiros/ciclo.md` | perfil no início; gatilho de reanálise |
| `app/agente/roteiros/visao-geral.md`, `metas.md` | tabela de roteiros; horizonte |
| `app/agente/__init__.py` | `analise-ativo` em `ROTEIROS` |
| `app/mcp_server/servidor.py` | prompt `analise_ativo` (args: `ticker`, `titular`); resource do modelo novo |
| `docs/agentes/modelo-relatorio-tese.md` | **novo** (§4.10); o trimestral encolhe |
| `docs/agentes/exemplos/analise-ativo.json` | **novo**, exemplo válido com `kind: "tese"` |
| `docs/agente-financeiro.md` | roteiro novo, `kind` (`tese`, `trimestral`), perfil, métricas do §4.7, `anos` |
| `AGENTS.md`, `docs/agentes/pasta-ia/AGENTS.md` | tabela de roteiros |
| `app/services/fundamentals.py`, `app/providers/cvm.py` | DFP 10 anos; série `anos` |
| `app/agente/operacoes.py`, `app/mcp_server/ferramentas.py`, `app/cli.py` | perfil |
| Tela do ativo (aba Análises) | mostrar a tese mais recente acima dos trimestrais (hoje mostra a mais nova de qualquer tipo) |
| `app/demo.py` | uma tese completa fictícia (ex.: a ação principal do casal), perfil "10 a 20 anos", série anual de 10 anos |
| `CHANGELOG.md` | `[Não lançado]` |
| `packaging/tabimoney.spec` | nada: `app/agente/roteiros` e `docs/agentes` já entram inteiros |

### 5.4 Testes

- `tests/test_mcp.py`: já confere que os roteiros só citam ferramentas que existem, a paridade com a CLI e o
  catálogo; entram `perfil_investidor`, `perfil_definir` e o prompt `analise_ativo`.
- Novo: `perfil_definir` grava e `carteira_contexto` devolve; perfil vencido com mais de 12 meses; por titular.
- Novo: série `anos` (agregação anual a partir da DFP, CAGR, banco sem EBITDA), com dados da CVM falsos.
- Novo: `analise_importar` aceita o exemplo `analise-ativo.json`; a tela do ativo mostra a tese.
- `tests/test_demo.py` e `tests/e2e`: a tese da demo aparece na página do ativo; a linha do perfil em Metas.

## 6. Fora de escopo

- **Calculadora do Diagrama no app** (o usuário digita o aporte e o app diz quanto comprar de cada ativo, com cotas
  inteiras). Fica para depois: aqui a distribuição é feita pela IA nas Sugestões.
- Questionário editável pelo usuário (trocar cortes e perguntas).
- Cripto (o app não acompanha cripto hoje).
- Nota automática calculada pelo app sem a IA (as perguntas 6 a 11 exigem pesquisa).

## 7. Riscos

| Risco | Como tratar |
|---|---|
| Análise completa de 15 ativos não cabe numa sessão | tese dura 12 meses; o ciclo faz no máximo 3 teses por vez e lista as que ficaram para depois |
| Download de 10 anos de DFP demora na 1ª vez | só DFP (anual); progresso na tarefa; cache longo |
| Perguntas subjetivas (6, 8, 9, 10) variam entre execuções | exigir a evidência em cada resposta; "na dúvida, não"; comparar com a tese anterior e explicar qualquer mudança |
| Parecer conselho oficial da AUVP | redação própria; o roteiro cita a inspiração e diz que a análise é da IA |
| Dados do usuário em buscas | regra explícita: buscar só ticker e nome da empresa |

## 8. Fases

1. **Roteiros e modelos** (`analise-ativo`, trimestral, recomendações, ciclo, visão geral, contrato, exemplo).
   Já funciona com os dados atuais (a IA busca o histórico longo na CVM e no RI).
2. **Perfil do investidor** (operação, MCP, CLI, linha em Metas, demo).
3. **Dez anos de DFP e série `anos`** (CVM, `fundamentos_contexto`, demo).
4. **Tela do ativo** mostrando a tese acima dos trimestrais.

Cada fase é um commit na `dev` com testes e `CHANGELOG`.

## 9. Decisões em aberto

1. **Versão.** Hoje `__version__` é `0.13.0` e o revamp da interface está em `[Não lançado]` (vai sair como
   `0.14.0`). `0.14.5` não existe no SemVer que o projeto usa (`docs/versionamento.md`): depois de `0.14.0` vem
   `0.14.1` (correção) ou `0.15.0` (funcionalidade). Como esta mudança traz roteiro, ferramenta e comando novos,
   pela regra é **`0.15.0`**. Se ficar só a fase 1 (texto dos roteiros), dá para chamar de `0.14.1`.
   Recomendação: lançar a `0.14.0` (interface) antes e esta como `0.15.0`.
2. **Um roteiro ou dois?** Recomendo dois (`analise-ativo` pesado + `analise-trimestral` leve, §4.2). A
   alternativa é um só, sempre completo, mais simples porém caro a cada trimestre.
3. **Cortes do checklist.** ROE ≥ 10% (IAFD) ou ≥ 15% (o modelo atual e parte da comunidade)? Recomendo 10%, que é
   o corte da própria AUVP no AUVP11.
4. **Fases 2–4 nesta versão?** Recomendo as quatro; a fase 1 sozinha já entrega a análise nova, mas sem os 10
   anos no app a IA depende mais de busca externa.

### Decididas (2026-09-30)

- Versão **0.15.0**; ROE ≥ **10%**; dois roteiros; as **quatro fases** nesta versão.

## 10. Fontes da pesquisa

- [Raul Sena: conheça a história e quem é o Investidor Sardinha (Investidor10)](https://investidor10.com.br/conteudo/raul-sena-o-investidor-sardinha/)
- [Raul Sena – Investidor Sardinha (Dicionário de Favelas Marielle Franco)](https://wikifavelas.com.br/index.php/Raul_Sena_-_Investidor_Sardinha)
- [A Única Verdade Possível: Enriqueça no longo prazo (Google Books)](https://books.google.com/books/about/A_%C3%9Anica_Verdade_Poss%C3%ADvel.html?id=U5BFEAAAQBAJ)
- [AUVP vale a pena? Avaliação do curso (educacaofinanceira.pro.br)](https://educacaofinanceira.pro.br/investimentos/curso-do-raul-sena-e-bom-auvp-vale-a-pena-review-sincero-2026/)
- [AUVP11 – ETF AUVP (AUVP Analítica)](https://analitica.auvp.com.br/campanhas/auvp11)
- [AUVP11: como funciona o ETF de ações por fundamentos (Renova Invest)](https://renovainvest.com.br/blog/auvp11-etf-acoes-fundamentos/)
- [AUVP lança ETF AUVP11 (Funds Society)](https://www.fundssociety.com/br/news/auvp-lanca-etf-auvp11-com-foco-em-empresas-solidas-e-rentaveis-da-bolsa-brasileira/)
- [Diagrama Pantaneiro, reimaginação aberta do Diagrama do Cerrado (GitHub)](https://github.com/HigorJSilva/diagrama_pantaneiro)
- [finance-hubs: carteira com notas e sugestão de aporte (GitHub, issue #59)](https://github.com/LucianoAMagalhaes/finance-hubs/issues/59)
- [Sardinha.net: B3 pela metodologia de critérios objetivos](https://sardinha.net/)
- Comunidade AUVP, tópicos "Perguntas Diagrama do Cerrado – Ações", "Diagrama do Cerrado para Fundos
  Imobiliários", "É livre de controle estatal ou concentração em cliente único?" (comunidade.auvp.com.br; lidos
  pelos trechos públicos indexados, o acesso direto é bloqueado)
- [Preço justo das ações: Graham × Bazin (Investidor10)](https://investidor10.com.br/conteudo/preco-justo-das-acoes-metodo-bazin/)
- Philip Fisher, *Common Stocks and Uncommon Profits* (1958): os 15 pontos e as três razões para vender.

## 11. Progresso

Atualizado a cada passo. Para retomar numa sessão nova: ler este parágrafo e seguir do primeiro item sem `[x]`.

- [x] Fase 1: roteiros e modelos (`analise-ativo`, trimestral, recomendações, ciclo, visão geral, metas, modelo da
  tese, exemplo, contrato, AGENTS, prompt MCP, CHANGELOG)
- [x] Fase 2: perfil do investidor (operação, MCP, CLI, `carteira_contexto`, linha em Metas, demo, testes).
  Feita antes da 1 porque os roteiros citam as ferramentas. Serviço em `app/services/investor_profile.py`; testes em
  `tests/test_longo_prazo.py`.
- [x] Fase 3: dez anos de DFP e série `anos` (CVM, `fundamentos_contexto`, demo, testes)
- [x] Fase 4: tela do ativo mostra a tese acima dos trimestrais (demo, e2e)
- [x] Fechamento: suíte completa (unidade e navegador), CHANGELOG revisado. Lançada na 0.15.0, junto com o revamp da interface.
