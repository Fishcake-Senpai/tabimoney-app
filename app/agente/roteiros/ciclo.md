---
titulo: Ciclo completo
descricao: Atualiza os dados, analisa todos os ativos, monta as recomendações de carteira e de orçamento, confere metas e gastos e entrega um resumo, de ponta a ponta.
---

# Ciclo completo

Execute as etapas em ordem, sem pedir confirmação entre elas. **Não altere metas nem crie regras de categoria
neste ciclo**: isso só acontece com pedido explícito.

## 1. Atualizar os dados

Chame `atualizar_dados`. Ele faz backup, sincroniza o Open Finance, as cotações e o CDI e baixa os balanços da
CVM. Se devolver `tarefa_id`, acompanhe com `tarefa_status` até `situacao` ser `concluida`. Se uma etapa falhar
(ex.: Open Finance sem credenciais), anote para o resumo e siga com os dados que existem.

## 2. Fotografia

Chame `carteira_contexto`. Para cada ativo, veja se `ultima_analise.period` já corresponde ao trimestre de
`ultimo_balanco` (`2026-06-30` → `2T26`).

- **Já analisado:** só refaça se o preço andou mais de 15% ou se há aviso novo em `avisos`.
- **Não analisado ou desatualizado:** entra na etapa 3.

## 3. Análises trimestrais

Siga o roteiro `analise-trimestral` para os ativos pendentes: ações, FIIs, ETFs, os títulos de renda fixa
relevantes e a previdência. Grave com `analise_importar`. Com mais de 8 ativos pendentes, grave em lotes de até 5.

## 4. Recomendações

Se foi gravada ao menos uma análise nova, ou se não existe recomendação para o trimestre atual, siga o roteiro
`recomendacoes` e grave com `recomendacoes_importar`.

## 5. Metas de alocação (só leitura)

Chame `metas_mostrar`. Se `configurado` for `false`, avise que o plano de aporte depende de definir as metas na
aba **Metas**.

## 6. Orçamento e gastos

Siga o roteiro `orcamento` para o mês corrente, ou para o mês anterior se estiver nos primeiros 5 dias. Grave com
`orcamento_importar_recomendacoes`. Se o usuário não tiver metas de gastos, recomende `criar` a partir de
`metas_sugeridas_pela_media`. Categorias claramente erradas entram só como sugestão; a correção é o roteiro
`gastos`, com o usuário.

## 7. Resumo ao usuário

Uma mensagem curta, nesta ordem:

1. **Dados:** o que foi atualizado e o que falhou.
2. **Carteira:** uma tabela ativo → veredito → nota → mudança desde o trimestre anterior.
3. **Avisos que pedem atenção:** no máximo 5.
4. **Recomendações do trimestre:** 3 a 5 bullets.
5. **Próximo aporte:** para onde vai, segundo as metas.
6. **Orçamento:** gasto × metas no mês, as 3 principais sugestões e a economia estimada.
7. **Onde ver:** Recomendações, página de cada ativo, Metas e Conta e cartão → Orçamento do mês.
