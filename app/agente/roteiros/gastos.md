---
titulo: Revisar gastos e recategorizar
descricao: Revisa os gastos, explica o que mudou por categoria e corrige categorias erradas vindas do Open Finance (lançamento a lançamento ou com regras permanentes).
---

# Revisar gastos e recategorizar

1. **Panorama:** chame `gastos_resumo`. Olhe `o_que_mudou`, que traz o último mês fechado contra a média dos 3
   anteriores, com os lançamentos que puxaram a mudança.
2. **Procure erros:** chame `gastos_listar` com `mes` e `so_gastos: true`, depois com `categoria: "Outros"` e
   `categoria: "Pix e transferências"`. A lista vem paginada: se houver `proximo_deslocamento`, repita com
   `deslocamento` igual a ele. Use `campos` (ex.: `["data", "descricao", "valor", "categoria"]`) para respostas
   menores. Os erros típicos são:
   - salário ou reembolso da empresa como despesa ou em categoria de consumo;
   - compra ou venda de ações, CDB ou previdência classificada como "Compras" (o certo é `Investimentos`);
   - PIX para a própria pessoa como gasto (o certo é `Transferência própria`);
   - PIX entre titulares da casa (veja `titulares`) como gasto (o certo é `Transferência entre titulares`);
   - estabelecimento classificado errado pela Pluggy (ex.: "Google One" como Lazer).
3. **Corrija:**
   - erro que se repete (mesmo estabelecimento ou pagador): `gastos_criar_regra` com `contem`, `categoria` e `nota`;
   - caso isolado: `gastos_recategorizar` com `ids` e `categoria`;
   - para desfazer: `gastos_recategorizar` com `automatica: true`, ou `gastos_remover_regra`.
   Use as categorias de `gastos_categorias`; crie uma nova só quando nenhuma servir, com `gastos_criar_categoria`
   (idempotente). Para excluir, `gastos_excluir_categoria` com `destino` (ex.: `Outros`, ou `automatica` para
   devolver cada lançamento à categoria automática); sem destino, a exclusão é bloqueada se houver lançamentos,
   regras ou metas nela. Nunca exclua sem o usuário pedir; `gastos_restaurar_categoria` desfaz.
4. **Confirme:** chame `gastos_resumo` de novo.

Regras de conduta:

- Antes de criar mais de 3 regras ou mexer em mais de 20 lançamentos, mostre a lista ao usuário e peça confirmação.
- Categorias internas (`Investimentos`, `Pagamento de fatura`, `Transferência própria`, `Transferência entre
  titulares`) tiram o valor de receitas e despesas. Use-as só quando o dinheiro de fato não saiu do patrimônio.
- Ao final, diga o que mudou (quantos lançamentos, efeito em reais por categoria) e que o resultado aparece em
  **Gastos** (Resumo e Lançamentos).
