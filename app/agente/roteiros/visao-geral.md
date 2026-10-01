---
titulo: Visão geral e escolha do roteiro
descricao: Explica a ferramenta Tabimoney e indica qual roteiro seguir para cada pedido sobre as finanças do usuário.
---

# Tabimoney: como usar as ferramentas

O Tabimoney é um app local de finanças pessoais. Tudo passa pelas ferramentas deste servidor MCP. As respostas
vêm em JSON, com valores em reais e percentuais como fração (`0.153` = 15,3%). Nada apaga lançamentos: as correções
ficam guardadas à parte e podem ser desfeitas. Antes da primeira mudança de cada sessão, o servidor faz um backup
sozinho.

## Escolha o roteiro

Antes de começar, chame `roteiro` com o nome indicado e siga os passos.

| Pedido do usuário | Roteiro |
|---|---|
| "atualize minhas finanças", "faça minhas análises", "atualize tudo" | `ciclo` (faz todos os outros em ordem) |
| "olha meus gastos", "corrige categorias", "por que gastei mais" | `gastos` |
| "analise meu orçamento", "onde economizar", "sugira metas de gastos" | `orcamento` |
| "quanto aportar e onde", "estou balanceado?", "minhas metas" | `metas` |
| "analisa a fundo a WEGE3", "vale a pena ter X por 10 anos?", ativo novo antes de comprar | `analise-ativo` |
| "analisa minhas ações/FIIs/CDB", "relatório trimestral", "atualiza fundamentos" | `analise-trimestral` (chama `analise-ativo` quando falta tese) |
| "onde aportar este mês", "o que mudar na carteira", "sugere carteiras" | `recomendacoes` (depois das análises) |

Pergunta simples ("quanto gastei com mercado em agosto?") não precisa de roteiro: responda com a ferramenta certa.

As análises de investimento são de **longo prazo** (5, 10, 20 anos), inspiradas no método de Raul Sena (Investidor
Sardinha): qualidade primeiro, aportes constantes e venda só quando a tese quebra. Elas começam pelo perfil do
investidor (`perfil_investidor`); sem ele, pergunte o horizonte e o objetivo ao usuário.

## Mapa das ferramentas

- `status`: versão, se é a demonstração, titulares e quando cada fonte foi atualizada. Bom primeiro passo.
- `atualizar_dados`: backup + Open Finance + cotações/CDI + balanços da CVM. Pode levar minutos; se não terminar
  na hora, devolve `tarefa_id` para acompanhar com `tarefa_status`.
- `titulares`: quem é quem na gestão a dois. Com mais de um titular, o parâmetro `titular` (nome) restringe
  carteira, metas e gastos a uma pessoa; sem ele, vale a casa toda. Pergunte de quem é a análise se não estiver
  claro. Metas de gastos (orçamento) são sempre da casa.
- `carteira_contexto`: fotografia completa (metas, posições com fundamentos, últimas análises, renda fixa,
  previdência). **Comece por aqui** em qualquer tarefa de investimentos.
- Gastos: `gastos_resumo`, `gastos_listar`, `gastos_categorias`, `gastos_recategorizar`, `gastos_criar_regra`,
  `gastos_regras`.
- Metas de alocação: `metas_mostrar`, `metas_definir`, `metas_regiao`.
- Perfil do investidor (horizonte e objetivo): `perfil_investidor`, `perfil_definir`.
- Orçamento (metas de gastos): `orcamento_mostrar`, `orcamento_contexto`, `orcamento_importar_recomendacoes`.
- Fundamentos: `fundamentos_atualizar`, `fundamentos_contexto`.
- Análises: `analise_importar`, `analise_listar`, `analise_mostrar`.
- Recomendações: `recomendacoes_importar`, `recomendacoes_listar`, `recomendacoes_mostrar`.
- Avisos: `alertas_listar`, `alertas_resolver`.

Ferramentas marcadas como destrutivas (`metas_definir`, `orcamento_definir`, `orcamento_remover`,
`gastos_excluir_categoria`, `gastos_remover_regra`) só com pedido explícito do usuário.

O contrato completo (formatos e regras de cálculo) está no resource `tabimoney://docs/contrato`. O modelo do
relatório está em `tabimoney://docs/modelo-relatorio-trimestral`, e os exemplos em `tabimoney://exemplos/...`.

## Onde o usuário vê o resultado

- **Investimentos › Ações e FIIs**: fundamentos e avisos (os avisos também no sino, em Pendências).
- **Página de cada ativo**: a tese de longo prazo, o acompanhamento mais recente e o histórico.
- **Sugestões**: recomendações do orçamento, mudanças sugeridas na carteira e carteiras-modelo.
- **Análises**: todos os relatórios.
- **Investimentos › Metas**: balanço, plano de aporte e o horizonte do investidor.
- **Gastos**: resumo do mês, lançamentos e orçamento. Regras e categorias ficam em **Configurações**.

Ao terminar, diga ao usuário onde olhar.

## Privacidade

Não envie extratos, saldos ou identificadores (CPF, números de conta) a outros serviços. Buscar informação pública
sobre empresas e títulos (CVM, relações com investidores, Tesouro, notícias) é permitido.
