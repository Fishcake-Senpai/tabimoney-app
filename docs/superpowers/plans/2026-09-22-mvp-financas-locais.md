# Plano de implementação — MVP de finanças pessoais local

**Objetivo:** entregar um aplicativo pessoal que rode no Windows, conecte os dados autorizados do Meu Pluggy, importe arquivos do Nubank, registre posições e fechamentos diários no SQLite e mostre conciliações e valorização em uma interface local.

**Arquitetura:** aplicação Python com páginas HTML renderizadas no servidor, acessível apenas em `127.0.0.1`; SQLite e consultas SQL são a fonte dos dados e KPIs. Adaptadores separam Pluggy, brapi e arquivos locais do modelo financeiro.

**Stack:** Python 3.11+, FastAPI, Uvicorn, Jinja2, HTTPX, Keyring no Windows, `ofxparse`, SQLite da biblioteca padrão e CSS local.

**Especificação:** `docs/superpowers/specs/2026-09-22-financas-pessoais-local-design.md`.

## Restrições globais

- Sem GitHub, nuvem, sincronização externa da base ou porta acessível pela rede; o servidor sempre inicia em `127.0.0.1`.
- O banco e os backups ficam em `%LOCALAPPDATA%\FinancasPessoais`, fora do repositório.
- Credenciais Pluggy e token brapi ficam no Windows Credential Manager via Keyring. Não gravar segredos em SQLite, arquivos de configuração, logs ou HTML enviado ao navegador.
- O usuário conclui consentimento no Meu Pluggy e informa à aplicação local o `itemId` proxy; não coletar senha do Nubank nem automatizar login bancário.
- Dinheiro é armazenado em centavos inteiros e quantidades em milionésimos de unidade.
- Importações são idempotentes, preservam proveniência e não removem dados prévios em caso de falha parcial.
- Fechamentos usam preço `close` sem ajuste; preço ajustado não será apresentado como fechamento nem como retorno total.
- Posição, conciliação e KPIs são calculados em views SQLite. A interface não recalcula esses valores.
- Não criar nem executar testes automatizados nesta entrega.
- Manter commits locais por etapa concluída; não configurar remote.

## Decisões de implementação

- Aplicação FastAPI/Jinja2 para manter o fluxo simples, sem dependência de frontend remoto e preparada para novas páginas.
- Integração Meu Pluggy pela API pessoal documentada. O usuário fornece Client ID, Client Secret e Item ID localmente; credenciais são guardadas com Keyring.
- API brapi como fonte inicial de preço diário, usando o histórico diário e o campo `close`; token opcional e guardado no Keyring. A cobertura/limite depende da conta e do plano brapi. Importação manual de cotações continua disponível.
- B3 não terá integração direta no MVP. A custódia vem do recurso de investimentos disponibilizado pelo conector Open Finance ou de importação manual.
- OFX será usado para extrato bancário; CSVs documentados serão usados para abertura manual de posições e contingência de cotações.
- A API B3 está descrita como B2B e não é presumida acessível à pessoa física.

## Limite explícito desta entrega

O painel entrega saldo, valor de mercado e variação diária de preço. Custo médio e lucro/prejuízo não realizado ficam adiados: antes de exibi-los, será preciso fechar a importação de custo de abertura e definir como validar o histórico de compras, vendas e eventos corporativos. A aplicação os mostra como indisponíveis em vez de estimar custos incompletos. O desenho aprovado continua sendo a visão futura para esses KPIs.

O vínculo automático entre a mesma conta bancária de OFX e Open Finance usa o nome/sufixo apresentado pelo provedor. Se esses rótulos diferirem, a aplicação pode contar a conta duas vezes; um mapeamento explícito entre contas fica para uma próxima etapa, pois unir contas sem identificador compartilhado confiável também pode esconder contas diferentes.

## Organização de arquivos prevista

```text
app/
  main.py
  db.py
  security.py
  providers/pluggy.py
  providers/brapi.py
  services/importers.py
  services/sync.py
  templates/base.html
  templates/dashboard.html
  templates/settings.html
  templates/imports.html
  static/style.css
migrations/001_initial.sql
docs/superpowers/specs/2026-09-22-financas-pessoais-local-design.md
docs/superpowers/plans/2026-09-22-mvp-financas-locais.md
requirements.txt
run.bat
README.md
```

## Etapas

### Etapa 1 — Núcleo local e esquema

- Criar a aplicação, carregamento de configuração segura e inicialização do banco em LocalAppData.
- Criar migração inicial com `sync_run`, contas, snapshots de saldo, movimentações, instrumentos, eventos de investimento, snapshots de posição, cotações e decisões de conciliação.
- Ativar chaves estrangeiras, migrações versionadas e criação segura da pasta de dados.
- Adicionar esqueleto da interface e mensagens locais de estado.

### Etapa 2 — Importação manual e conciliações SQL

- Importar extrato OFX de conta bancária sem persistir número integral da conta.
- Importar CSVs-modelo de posições iniciais e preços diários, deduplicando por hash/origem.
- Criar views SQL para posição mais recente, valorização, variação diária de preço, alertas de cotação e divergência entre posição reportada e posição reconstruída quando existir abertura/histórico suficiente.
- Adiar custo médio/P&L até definir como importar uma base de custo confiável e validar compras, vendas e eventos corporativos.

### Etapa 3 — Open Finance via Meu Pluggy

- Guardar Client ID/Secret no Credential Manager e o `itemId` no banco.
- Obter uma API Key temporária no servidor local e consultar contas, transações, investimentos e movimentações de investimento pelos endpoints documentados.
- Normalizar os dados sem armazenar payloads pessoais completos; transações e investimentos usam IDs de origem para deduplicação.
- Tratar a coleta como completa somente quando todas as páginas/endpoints relevantes retornarem; manter último snapshot em falha/parcialidade.
- Documentar o fluxo manual no Meu Pluggy/Dashboard para obter o proxy Item ID.

### Etapa 4 — Fechamento diário automático

- Implementar adaptador brapi que solicita histórico diário dos tickers da carteira e persiste o último pregão disponível usando o campo `close` e sua data.
- Tornar os erros de autenticação, limite, ticker não coberto e ausência de cotação visíveis na interface sem apagar fechamentos já armazenados.
- Incluir ação manual de atualização diária e tentativa automática depois de 19h30 enquanto o aplicativo estiver aberto; integração com o Agendador de Tarefas do Windows pode ser acrescentada depois.

### Etapa 5 — Painel e operação local

- Exibir saldo bancário, valor de mercado, posição por ativo, última cotação/data, variação diária, pendências de conciliação e estado de sincronização.
- Adicionar telas de configuração, importação, backup e restauração com validação da base enviada e cópia preventiva antes de restaurar.
- Criar `run.bat` e README com instalação inicial, consentimento, exportação OFX, formatos CSV, local dos dados, atualização de preços e backup/restauração.
- Fazer revisão manual do diff, da SQL e dos textos de operação; sem testes automatizados conforme restrição global.

## Foco da revisão final

- Segredos nunca aparecem no SQLite, logs ou HTML nem em query strings.
- Nenhuma rota permite acesso fora de loopback; formulários de escrita mitigam requisições cross-site.
- Importações/sincronizações são idempotentes e uma falha parcial não troca posições por snapshot incompleto.
- A cotação de fechamento usa data do pregão e preço não ajustado; não confundir variação de preço com rentabilidade total.
- A interface distingue falta de histórico de um saldo/posição efetivamente divergente.
- Restaurar uma base inválida ou incompatível não substitui a base atual.

## Referências técnicas consultadas

- Guia de acesso pessoal Meu Pluggy: https://meu.pluggy.ai/api-guide
- Documentação Pluggy de autenticação, contas e investimentos: https://docs.pluggy.ai/en/docs/quickstart e https://docs.pluggy.ai/en/reference
- Documentação brapi de histórico e autenticação: https://web-next.brapi.dev/docs/acoes e https://web-next.brapi.dev/docs
- Especificação aprovada: `docs/superpowers/specs/2026-09-22-financas-pessoais-local-design.md`
