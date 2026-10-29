---
titulo: Imposto de renda
descricao: Estima o IR do ano, organiza as deduções e o PGBL, resolve as pendências da bolsa e, na época da declaração, entrega o passo a passo ficha por ficha.
---

# Imposto de renda

O IR é **por pessoa**. Com mais de um titular, pergunte de quem é (parâmetro `titular`); sem ele, vale o titular
principal. Tudo é estimativa de apoio: diga sempre ao usuário para conferir no programa da Receita e nos informes de
rendimentos. As regras e as fontes estão na spec `docs/superpowers/specs/2026-10-19-imposto-de-renda.md`.

## Passos

1. **Contexto:** chame `ir_contexto` (com `ano`; padrão é o ano atual). Se vier `aviso_regras`, avise o usuário
   antes de tudo: os parâmetros do app podem estar desatualizados para a declaração nova, e ele precisa atualizar o
   Tabimoney. Os itens de `parametros.a_confirmar` ainda não foram conferidos no texto oficial.
2. **Perfil fiscal:** se `perfil.fontes` estiver vazio, pergunte ao usuário e grave com `ir_fonte_salvar`:
   - CLT: o salário **bruto** do holerite (não o líquido do extrato), mês das férias e se recebe 13º;
   - PJ: o **pró-labore** bruto, o faturamento médio da empresa, o regime (Simples com fator R, Anexo III, Anexo V
     ou outro) e o lucro distribuído por mês;
   - aluguel ou trabalho sem vínculo: tipo `outro` (paga carnê-leão).
   Dependentes com `ir_dependente_salvar`. Se o usuário tiver o informe de rendimentos, use o INSS e o IRRF dele
   (`inss_mensal`, `irrf_ano`). `estimativa.conciliacao` compara o líquido esperado com o salário que entrou no
   extrato: diferença grande sugere bruto ou descontos errados.
3. **Deduções:** em `deducoes.categorias_sugeridas_sem_tipo`, Saúde e Educação ainda não contam. Pergunte ao
   usuário e, com o sim, chame `ir_deducao_marcar` com `categoria`. Depois revise `deducoes.itens`:
   - farmácia, academia, curso livre e material escolar **não deduzem** (o app já tira os mais comuns; o campo
     `aviso` diz por quê). Lançamento dedutível que o app tirou: `ir_deducao_marcar` com `ids` e o `tipo`;
   - para cada prestador, peça o CPF/CNPJ (`documento`) e quem foi atendido (`beneficiario`: `titular` ou
     `dep:<id>`). Reembolso do plano de saúde sai do valor (`reembolso`);
   - gasto pago fora das contas do app: `ir_deducao_adicionar`.
4. **Previdência:** em `previdencia.sugestoes_de_aporte` estão débitos que parecem aporte. Registre com
   `previdencia_aporte_registrar`, perguntando **quem pagou**: o participante (deduz no PGBL até 12% da renda
   tributável) ou a empresa (não deduz). Aporte mensal fixo: `repetir_ate_dezembro`.
   - O PGBL só deduz no modelo completo e com contribuição ao INSS ou regime próprio (ou aposentadoria por eles);
     sem isso, `ir_previdencia_oficial`.
   - Use `estimativa.previdencia`: `falta` é quanto ainda cabe no ano e `economia_completar` é o que isso economiza
     **contra o melhor modelo**. Se `ajuda` for false, diga que o PGBL não reduz o IR este ano. Lembre que o PGBL
     adia o imposto (tributa tudo no resgate), não isenta. Para testar outro valor, `ir_estimativa` com `pgbl_extra`.
5. **Bolsa:** em `bolsa.pendencias`, resolva o que bloqueia com `ir_pendencia_resolver`, perguntando ao usuário:
   - `classe`: ticker 11 sem classe (FII, ETF ou unit muda alíquota e isenção);
   - `custo_bonificacao`: valor por ação do aviso aos acionistas (`ref_id` da pendência);
   - `prejuizo_anterior`: prejuízo de antes do histórico, por grupo e ano (`valor` 0 se não tem);
   - `posicao_sem_historico`: a corretora custodia mais do que o histórico de operações explica (a Pluggy manda só
     uns 12 meses), e Bens e Direitos sai incompleto. Não se resolve por ferramenta: peça ao usuário para informar a
     posição inicial com preço médio em **Importar › posições**, na mesma conta e com data anterior à primeira
     operação do histórico;
   - `irrf` e `taxa`: valores da nota ou do informe da corretora; `darf_pago` quando o usuário pagou.
   Mostre os DARFs com vencimento (`bolsa.darfs`) e quanto ainda cabe de vendas de ações no mês sem imposto
   (`bolsa.este_mes.isencao_restante`).
6. **Responda ao usuário** com:
   - o imposto do ano no melhor modelo e se vai restituir ou pagar (`estimativa.saldo`);
   - quanto falta de PGBL e a economia, com o prazo de 31/12;
   - deduções sem documento e o que juntar;
   - DARFs da bolsa a pagar e pendências.

## Na época da declaração (março a maio)

Chame `ir_declaracao` com o ano-calendário declarado (padrão: o ano passado). Ele traz, na ordem do programa, cada
ficha com os valores prontos e o `checklist` de documentos. Percorra as seções com o usuário. O app não gera o
arquivo da declaração: o usuário copia os valores no programa da Receita. Se ele autorizou o ReVar (calculadora da
Receita com a B3), peça para conferir a declaração pré-preenchida com a seção de renda variável.
