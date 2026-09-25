---
name: financas-gastos
description: Revisar os gastos do usuário, explicar o que mudou por categoria e corrigir categorias erradas vindas do Open Finance (lançamento a lançamento ou com regras permanentes). Use quando o usuário pedir para olhar gastos, entender despesas ou recategorizar.
---

# Revisar gastos e recategorizar

1. **Panorama:** rode `.\financas.bat gastos resumo`. Olhe `o_que_mudou`, que traz o último mês fechado contra
   a média dos 3 anteriores, com os lançamentos que puxaram a mudança.
2. **Procure erros:** rode `.\financas.bat gastos listar --mes AAAA-MM --so-gastos`, depois
   `--categoria Outros` e `--categoria "Pix e transferências"`. Os erros típicos são:
   - salário ou reembolso da empresa como despesa ou em categoria de consumo;
   - compra ou venda de ações, CDB ou previdência classificada como "Compras" (o certo é `Investimentos`);
   - PIX para a própria pessoa como gasto (o certo é `Transferência própria`);
   - estabelecimento classificado errado pela Pluggy (ex.: "Google One" como Lazer).
3. **Corrija:**
   - erro que se repete (mesmo estabelecimento ou pagador): `.\financas.bat gastos regra --contem "TEXTO" --categoria "Categoria" --nota "motivo"`;
   - caso isolado: `.\financas.bat gastos recategorizar --id 123 456 --categoria "Categoria"`;
   - para desfazer: `gastos recategorizar --id 123 --automatica` ou `gastos remover-regra ID`.
   Use as categorias de `.\financas.bat gastos categorias`; crie uma nova só quando nenhuma servir, com
   `gastos criar-categoria "Nome"` (idempotente). Excluir: `gastos excluir-categoria "Nome" --destino Outros`
   (sem `--destino` a exclusão é bloqueada se houver lançamentos, regras ou metas nela; `--destino automatica`
   devolve cada lançamento à categoria automática). Nunca exclua sem o usuário pedir;
   `gastos restaurar-categoria "Nome"` desfaz.
4. **Confirme:** rode `gastos resumo` de novo.

Regras de conduta:

- Antes de criar mais de 3 regras ou mexer em mais de 20 lançamentos, mostre a lista ao usuário e peça confirmação.
- Categorias internas (`Investimentos`, `Pagamento de fatura`, `Transferência própria`) tiram o valor de receitas e despesas. Use-as só quando o dinheiro de fato não saiu do patrimônio.
- Ao final, diga o que mudou (quantos lançamentos, efeito em reais por categoria) e que o resultado aparece em **Conta e cartão**.
