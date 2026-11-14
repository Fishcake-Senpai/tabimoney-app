# Privacidade

O Tabimoney foi desenhado para ser **local-first**: os seus dados ficam no seu computador, e a internet só é usada
para o que o app precisa buscar. Esta página explica exatamente o que fica onde e o que sai da máquina.

## O que fica no seu computador

| O quê | Onde |
|---|---|
| Contas, cartões, lançamentos, investimentos e metas | `financas.sqlite3`, criptografado, na pasta de dados |
| Backups | `backups\` na pasta de dados, criptografados; os antigos são convertidos na primeira abertura |
| Logs | `logs\` na pasta de dados |
| Cache das demonstrações da CVM | `cvm\` na pasta de dados |
| Demonstração | `demo.sqlite3`, separado da sua base |
| Chave da base, Client ID, Client Secret e token da brapi | Gerenciador de Credenciais (Windows) ou Porta-chaves (macOS) |

No Windows, a pasta padrão é `%LOCALAPPDATA%\FinancasPessoais`. No macOS, é
`~/Library/Application Support/Tabimoney`.

O servidor escuta apenas em `127.0.0.1` (o próprio computador). Ele não aceita conexões de outros aparelhos da
rede, e as rotas que mudam dados exigem um token CSRF da sessão.

## Criptografia em repouso

A base é criptografada com **SQLCipher 4** (AES-256, HMAC-SHA512). O arquivo no disco não começa com o cabeçalho
`SQLite format 3\0`; sem a chave, ele não abre em ferramentas comuns. Os backups criados pelo app a partir desta
versão também são criptografados.

- A chave é composta por **32 bytes aleatórios**, guardados no Gerenciador de Credenciais do Windows ou no
  Porta-chaves do macOS, separados do arquivo do banco.
- O app usa a chave em modo raw no dia a dia; o KDF de 256 mil iterações será usado no backup portátil com
  passphrase.
- A primeira abertura depois de uma atualização migra uma base antiga em texto claro automaticamente. O app guarda
  uma cópia de segurança, confere um fingerprint lógico do esquema e de todas as linhas e só então troca o arquivo.
- Backups antigos em texto claro são criptografados automaticamente na primeira abertura, com fingerprint e
  verificação. Se um arquivo não puder ser convertido, ele fica como está e o app registra o aviso no log.
- Backups antigos em texto claro também continuam restauráveis: o app os valida e os re-criptografa na restauração.
- Se a migração falhar, o app preserva a base original e avisa. Nada é apagado.

**Limites importantes:** SQLCipher protege o arquivo em repouso, não o app aberto. Malware rodando como o seu
usuário, capturas de tela, relatórios HTML exportados e arquivos CSV ainda podem expor os dados. A chave fica no
cofre do sistema; se ela for perdida, a base e os backups criptografados não poderão ser abertos. O backup portátil
com passphrase, que permite recuperar os dados em outro computador, está previsto para a próxima fase.

## O que sai da máquina

| Destino | Quando | O que é enviado | O que não é enviado |
|---|---|---|---|
| **Meu Pluggy / Pluggy** | Ao sincronizar o Open Finance | Consentimento, credenciais da aplicação e Item IDs; a resposta traz os dados bancários que você autorizou | Senha do banco, backups |
| **brapi** | Ao atualizar cotações e fundamentos | Tickers da carteira e o token, quando configurado | Saldos, lançamentos, posições |
| **Yahoo Finance** | Reserva da brapi para cotações | Tickers e intervalo de datas | Saldos, lançamentos, posições |
| **Banco Central (SGS 12)** | Ao atualizar o CDI | Nenhum dado pessoal; só a consulta da série | — |
| **CVM (dados abertos)** | Ao atualizar fundamentos | Nenhum dado pessoal; só o download das demonstrações | — |
| **GitHub** | Ao abrir e a cada 12 horas | Versão instalada no cabeçalho `User-Agent`, na consulta pública de Releases | Dados financeiros, identificadores, backups |
| **Provedor da sua IA** | Quando você conversa com o agente | O que você escreve e o que o agente decide consultar | Nada é enviado se você não usar IA |

Todas são chamadas HTTPS comuns. Fora o Meu Pluggy — que devolve os dados bancários que você autorizou —, nenhuma
delas carrega o seu extrato ou o seu saldo.

### O Meu Pluggy

O consentimento do Open Finance é dado por você no Meu Pluggy, não no Tabimoney. O app cria uma chave de API
temporária para sincronizar e guarda o Client ID e o Client Secret no cofre do sistema. A senha do Nubank, do Itaú
ou de qualquer outro banco nunca passa pelo Tabimoney.

A sincronização do Open Finance acontece quando você clica em **Sincronizar**. O Meu Pluggy mantém e atualiza as
conexões no ciclo diário do próprio serviço. Os dados que voltam são gravados no SQLite local.

### A IA

O servidor MCP roda dentro do Tabimoney, neste computador. Quando você pede uma análise, o agente consulta as
ferramentas locais e envia o resultado para o provedor do modelo que você escolheu — Claude, ChatGPT, Gemini ou
outro. É o mesmo contrato de qualquer conversa com IA: o que entra no contexto sai da máquina para o provedor.

Por isso:

- use a **demonstração** (`tabimoney-demo`) para testar prompts sem dados reais;
- não peça ao agente para enviar extratos, saldos, CPF ou números de conta a serviços externos;
- revise as permissões do agente e as configurações de retenção do provedor;
- para pesquisar informação pública de empresas, o agente pode usar a web normalmente.

## O que o app não faz

- Não cria conta, login ou perfil em servidor nenhum.
- Não envia telemetria, analytics, crashes ou métricas de uso.
- Não vende, compartilha ou usa seus dados para publicidade.
- Não sincroniza com a nuvem.
- Não acessa sites de bancos diretamente.
- Não apaga lançamentos. As correções são reversíveis.

Os pedidos automáticos são as atualizações agendadas de cotações, CDI e CVM enquanto o app está aberto, além da
consulta de versão nova no GitHub. A consulta de versão pode ser desligada em **Configurações › Atualizações**.
Sem internet, o aviso simplesmente não aparece.

## Backups

Os backups ficam na mesma pasta de dados, em `backups\`. Eles contêm seus saldos, lançamentos e posições; trate-os
como documentos privados.

- Baixe ou restaure um backup em **Importações**.
- Antes de restaurar, o app valida a integridade e a versão do arquivo e salva uma cópia preventiva.
- A restauração recusa uma base de versão mais nova do que o app instalado.
- Guarde cópias em um lugar privado, de preferência criptografado.
- Não versione a pasta de dados no Git. O `.gitignore` já protege os caminhos do projeto, mas backups copiados para
  fora dele são sua responsabilidade.

## Compartilhar o app

O `Tabimoney.exe` e o `Tabimoney.app` não contêm dados seus. Você pode enviar o executável para outra pessoa sem
levar sua base junto. A demonstração usa um arquivo separado e dados fictícios.

Se for mostrar o app em uma captura de tela ou vídeo, ative o ícone de olho para esconder os valores ou use a
demonstração.

## Recomendações

- Mantenha o sistema operacional e o app atualizados.
- Use a senha do computador e bloqueie a tela quando sair.
- Revise as conexões do Meu Pluggy e remova as que não usa mais.
- Se você usa IA, prefira a demonstração para experimentar e limite o que cola na conversa.
- Em um computador compartilhado, cada pessoa deve usar a própria conta do sistema; o cofre de senhas é por usuário.

## Licença e marca

O código é distribuído sob a [Licença Apache 2.0](../LICENSE). A fonte Inter segue a SIL Open Font License
(`app/static/fonts/LICENSE-Inter.txt`). O nome, o logo e o mascote Tabimoney (`app/static/brand/`) não entram na
licença do código: em um fork ou versão modificada, use outro nome e outra marca.
