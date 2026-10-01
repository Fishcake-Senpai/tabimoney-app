---
titulo: Acompanhamento trimestral das teses
descricao: A cada balanço, confere se a tese de longo prazo de cada ativo (ações, FIIs, ETFs, renda fixa, previdência) continua de pé, atualiza checklist, nota e preço e grava um relatório curto por ativo, com histórico por trimestre.
---

# Acompanhamento trimestral das teses

Quem investe por 10 ou 20 anos não reavalia a empresa inteira a cada trimestre: confere se **a tese continua de
pé**. A peça pesada é a tese (`kind: "tese"`, roteiro `analise-ativo`), que vale 12 meses. Este roteiro grava **um
relatório curto por ativo e por trimestre** (`kind: "trimestral"`), no modelo
`tabimoney://docs/modelo-relatorio-trimestral`.

## Passos

1. **Perfil:** chame `perfil_investidor`. Sem perfil ou vencido, pergunte ao usuário e grave com `perfil_definir`
   (as perguntas estão no roteiro `analise-ativo`, passo 0). Com horizonte `menos-de-5`, avise e pare.
2. **Dados frescos:** `fundamentos_atualizar`. Se devolver `tarefa_id`, acompanhe com `tarefa_status`.
3. **Fotografia:** `carteira_contexto` (posições, metas, `ultima_analise` de cada ativo, renda fixa, previdência).
4. **Teses:** para cada ativo, `analise_listar` com o ticker e veja a tese mais recente (`kind` = `tese`).
   - **Sem tese, tese com mais de 12 meses ou tese quebrada no trimestre anterior:** siga o roteiro `analise-ativo`
     para esse ativo (no máximo 3 por sessão, pelos de maior peso; liste os que ficaram para depois).
   - **Com tese válida:** siga o passo 5.
5. **Acompanhamento de cada ativo com tese:**
   1. `analise_mostrar` da tese: os gatilhos de "O que quebra a tese", o checklist e o preço justo.
   2. `fundamentos_contexto` com o ticker: o trimestre novo, `quarters` e a série `anos`.
   3. Leia o release do trimestre e as notícias desde o último relatório (só ticker e nome da empresa na busca).
   4. Confira **cada gatilho** (hoje × limite → ok ou disparou) e as respostas do checklist que dependem de número
      (1 a 5). As qualitativas (6 a 11) só mudam com fato novo, que precisa estar em `sources`.
   5. Atualize nota, `score`, preço justo e `verdict` pelas regras do `analise-ativo` (passos 5 e 7).
   6. **Gatilho disparou ou a nota caiu para ≤ 0:** escreva "tese quebrada", grave o aviso `tese_quebrada` e refaça a
      tese pelo `analise-ativo` agora ou na próxima sessão.
6. **FIIs, ETFs, renda fixa e previdência:** o mesmo acompanhamento, com o relatório gerencial (FIIs), a taxa de
   hoje (renda fixa) e os critérios do `analise-ativo`, passo 8. Renda fixa e previdência usam `subject` e
   `subject_type`, sem `ticker`.
7. **Gravação:** `analise_importar` com a lista (exemplo em `tabimoney://exemplos/analise-trimestral`), `kind`
   `"trimestral"` e `metrics` atualizadas (`nota_qualidade`, `checklist_sim`, `margem_seguranca`). Se der erro,
   corrija o item indicado e grave de novo; nada é gravado pela metade.
8. **Resumo ao usuário:** uma tabela ativo → papel → nota → tese (de pé ou quebrada) → preço (barata, justa, cara),
   os avisos novos, as teses que ficaram pendentes e a sugestão de seguir com o roteiro `recomendacoes`.

## Padrões

- O período é o trimestre do último balanço: `2T26` = abril a junho de 2026. Regravar o mesmo período e o mesmo
  `kind` substitui a versão.
- Oscilação de preço não é motivo de reanálise; balanço novo, fato relevante e aviso novo são.
- Não repita o que as regras automáticas do app já dizem; interprete.
- Seja explícito sobre incerteza e dados faltando (ex.: "a CVM ainda não tem o 3T26").
- Não recomende compra ou venda aqui; isso é do roteiro `recomendacoes`, que considera as metas.
