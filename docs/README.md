# Documentação do Tabimoney

O Tabimoney é um aplicativo local de finanças pessoais para Windows e macOS. Ele reúne contas, cartões,
investimentos, orçamento, imposto de renda e agentes de IA — com os dados no seu computador.

Esta documentação está separada por objetivo. Se você está começando, leia na ordem de **Usar o app**.

## Usar o app

| Guia | O que tem |
|---|---|
| [Instalação e atualização](guia/instalacao.md) | Baixar, abrir, atualizar, encerrar, backup, restauração e onde ficam os dados |
| [Primeiros passos](guia/primeiros-passos.md) | Demonstração, conexão com os bancos, importação e a rotina do dia a dia |
| [Conexões e importação](guia/conexoes-e-importacao.md) | Meu Pluggy, Open Finance, gestão a dois, formatos de arquivo e conciliação |
| [Gastos e orçamento](guia/gastos.md) | Visão inicial, resumo por categoria, regras, metas de gastos e pendências |
| [Investimentos](guia/investimentos.md) | Carteira, fundamentos, metas, renda fixa, previdência, proventos e análises |
| [Imposto de renda](guia/imposto-de-renda.md) | Estimativa, PGBL, apuração da bolsa, deduções e declaração |
| [IA e MCP](guia/ia.md) | Conectar Claude, Codex, Cursor, VS Code e Gemini CLI |
| [Privacidade](privacidade.md) | O que fica local, o que sai, como proteger seus dados e seus backups |

## Desenvolver e manter

| Guia | O que tem |
|---|---|
| [Desenvolvimento](desenvolvimento.md) | Rodar pelo código, arquitetura, testes, demo, build e convenções |
| [Versionamento](versionamento.md) | Branches, changelog, migrações, releases e o contrato da atualização |
| [Contrato com agentes](agente-financeiro.md) | Ferramentas MCP, comandos da CLI, formatos JSON e regras de cálculo |
| [Modelo da tese de longo prazo](agentes/modelo-relatorio-tese.md) | Seções obrigatórias da análise completa de um ativo |
| [Modelo do acompanhamento trimestral](agentes/modelo-relatorio-trimestral.md) | Seções do relatório de revisão de tese |
| [Exemplos JSON](agentes/exemplos/) | Relatórios e recomendações válidos para importar |

## Recursos usados pelo app

Estes arquivos são lidos pelo servidor MCP e pelo executável em tempo de execução. Eles ficam nesta pasta de
propósito e são entregues dentro do app:

| Arquivo | Para quê |
|---|---|
| [Contrato com agentes](agente-financeiro.md) | Recurso `tabimoney://docs/contrato` e referência da CLI |
| [Modelos de relatório](agentes/) | Recursos `tabimoney://docs/modelo-relatorio-*` |
| [Exemplos](agentes/exemplos/) | Recursos `tabimoney://exemplos/*` |
| [Instruções da pasta da IA](agentes/pasta-ia/AGENTS.md) | Texto que o app grava na antiga pasta de trabalho da IA |

## Como esta documentação é organizada

- **Guia do usuário:** explica o que a tela faz e por que ela faz daquele jeito, sem exigir conhecimento técnico.
- **Referência:** contrato, modelos e exemplos usados por quem integra agentes ou importa JSON.
- **Manutenção:** como rodar, testar, versionar e publicar o projeto.
- **Privacidade:** a página mais importante para quem vai confiar dados financeiros ao app.

Os documentos usam links relativos. Se você moveu um arquivo, atualize o link aqui e no README para não deixar a
documentação órfã.
