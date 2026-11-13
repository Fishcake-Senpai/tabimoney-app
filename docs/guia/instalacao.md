# Instalação e atualização

O Tabimoney existe em duas formas:

- **Executável:** um arquivo só, com o Python e as dependências dentro. É o jeito de quem só quer usar o app.
- **Código:** para quem vai desenvolver ou conferir o projeto. Veja [Desenvolvimento](../desenvolvimento.md).

As duas formas guardam os dados no mesmo lugar e têm as mesmas telas. O executável roda no **Windows 10/11** e no
**macOS 11 ou mais recente** (Apple Silicon ou Intel).

## Windows

1. Abra a página de [Releases](https://github.com/Fishcake-Senpai/tabimoney-app/releases/latest) e baixe o zip
   `Tabimoney-<versão>-windows.zip`.
2. Clique com o botão direito no zip e escolha **Extrair tudo**. Guarde a pasta em um lugar seu, como
   `Documentos\Tabimoney`. Não execute o app de dentro do zip.
3. Dê dois cliques em `Tabimoney.exe`. Uma janela mostra o progresso e fecha sozinha; o app abre no navegador em
   `http://127.0.0.1:8765`.
4. **Primeira vez:** o Windows pode mostrar *“O Windows protegeu o computador”*. Clique em **Mais informações** e
   depois em **Executar assim mesmo**. O aviso aparece porque o executável não tem assinatura digital paga; ele só
   é mostrado uma vez.
5. **Atalho opcional:** botão direito no `Tabimoney.exe` › **Enviar para** › **Área de trabalho (criar atalho)**.

| Quero… | Como |
|---|---|
| Abrir | Dois cliques no `Tabimoney.exe` ou no atalho. |
| Reiniciar | Abra de novo: a cópia que estiver aberta é encerrada com segurança e outra sobe. |
| Atualizar | Use o aviso **Atualizar agora** no sino. Se preferir, substitua o `Tabimoney.exe` pelo novo e abra. |
| Encerrar | No app, rodapé do menu lateral › **Encerrar**. Fechar a aba do navegador não encerra o servidor. |
| Apagar tudo | Encerre o app e apague a pasta `%LOCALAPPDATA%\FinancasPessoais`. |

## macOS

1. Na página de [Releases](https://github.com/Fishcake-Senpai/tabimoney-app/releases/latest), baixe o zip da sua
   máquina:
   - `…-mac-apple-silicon.zip` para chips M1, M2, M3 ou M4;
   - `…-mac-intel.zip` para Macs com processador Intel.

   O chip aparece no menu Apple › **Sobre este Mac**.
2. Extraia e arraste o `Tabimoney.app` para a pasta **Aplicativos**.
3. **Primeira vez:** o app não tem assinatura paga da Apple, então o macOS bloqueia a abertura.
   - No macOS 15 (Sequoia) ou mais novo: tente abrir, feche o aviso e vá em **Ajustes do Sistema › Privacidade e
     Segurança**; clique em **Abrir Mesmo Assim** e abra de novo.
   - No macOS 14 ou mais antigo: botão direito no app › **Abrir** › **Abrir**.
   - Se o sistema disser que o app “está danificado”, rode no Terminal:
     `xattr -dr com.apple.quarantine /Applications/Tabimoney.app`.
4. Dois cliques abrem o app no navegador. Clicar de novo reinicia. **Encerrar** fica no rodapé do menu lateral.

No Mac, os dados ficam em `~/Library/Application Support/Tabimoney` e as chaves no **Porta-chaves (Keychain)**. Na
primeira vez que o app salvar uma chave, o sistema pode pedir permissão: escolha **Sempre Permitir**.

A linha de comando é:

```bash
/Applications/Tabimoney.app/Contents/MacOS/Tabimoney cli gastos resumo
```

O servidor MCP usa o mesmo caminho com `mcp` no lugar de `cli`.

## Atualizar

O app consulta o último Release ao abrir e a cada 12 horas. Quando há versão nova, o sino da barra do topo mostra
**Atualizar agora** (Windows), **Baixar** (macOS) e **Novidades**. A consulta é um pedido comum à API pública do
GitHub e não envia dados financeiros.

- **Windows:** a atualização com um clique baixa o novo executável, faz backup dos dados, troca o arquivo e
  reinicia. Se o Release não tiver o pacote de atualização, o app volta ao botão **Baixar**.
- **macOS:** baixe o zip novo, substitua o `Tabimoney.app` e abra. Os dados ficam.
- **Pelo código:** o aviso pede `git pull` em vez de download.

Os dados nunca são apagados na atualização. A base é migrada automaticamente ao abrir. Você pode desligar a
verificação em **Configurações › Atualizações** ou verificar na hora.

## Onde ficam seus dados

| O quê | Windows | macOS |
|---|---|---|
| Banco, backups, logs e cache da CVM | `%LOCALAPPDATA%\FinancasPessoais` | `~/Library/Application Support/Tabimoney` |
| Senhas e chaves | Gerenciador de Credenciais | Porta-chaves (Keychain) |
| Demonstração | `demo.sqlite3` na mesma pasta | `demo.sqlite3` na mesma pasta |

Nada disso vai para a nuvem. A pasta de dados contém:

- `financas.sqlite3` — sua base;
- `backups\` — cópias automáticas e manuais;
- `logs\` — registro do app, útil para investigar erros;
- `cvm\` — cache das demonstrações financeiras baixadas da CVM;
- `demo.sqlite3` — dados fictícios da demonstração, separados dos seus.

## Backup e restauração

Em **Importações**, baixe um backup SQLite ou restaure um anterior. Antes de substituir a base, o app valida a
integridade e a versão do arquivo e salva uma cópia preventiva dos dados atuais. A restauração recusa uma base de
versão mais nova do que o app instalado.

Pela linha de comando:

```bash
financas.bat backup
```

Guarde os backups em um lugar privado. Eles contêm seus saldos, lançamentos e posições.

## Problemas comuns

**“A porta 8765 está ocupada.”** Outra cópia do Tabimoney está aberta pelo código, ou outro programa usa a porta.
Feche a outra janela ou reinicie o computador.

**O antivírus apagou o executável.** Alguns antivírus desconfiam de programas feitos em Python e sem assinatura.
Restaure o arquivo da quarentena e marque como confiável.

**O app não abre.** Abra um terminal na pasta do executável e rode:

```bash
Tabimoney.exe --primeiro-plano
```

O servidor sobe na janela atual e mostra o log. No Mac, o app aberto pelo Finder mostra uma caixa de diálogo quando
não consegue iniciar.

**Quero ver o log.** Os arquivos ficam em `logs\` dentro da pasta de dados. O principal é `tabimoney.log`.

## Rodar pelo código

Para quem vai mexer no projeto:

1. Instale Python 3.11 ou mais recente (no Windows, mantenha o launcher `py` habilitado).
2. **Windows:** execute `run.bat`. **macOS:** execute `run.command` (dois cliques no Finder abrem o Terminal).
   Na primeira vez, o script cria o `.venv` e instala as dependências. Depois, abre o app como o executável.
3. Para ver o log na tela e encerrar com `Ctrl+C`:
   `.venv\Scripts\python.exe -m app.launch --primeiro-plano` (Windows) ou
   `.venv/bin/python -m app.launch --primeiro-plano` (macOS).
4. A linha de comando é `financas.bat` no Windows e `./financas.sh` no Mac.

O resto — testes, arquitetura e build — está em [Desenvolvimento](../desenvolvimento.md).

## Desinstalar

1. Encerre o app pelo menu lateral.
2. Apague a pasta de dados (`%LOCALAPPDATA%\FinancasPessoais` ou `~/Library/Application Support/Tabimoney`).
3. Apague o executável e, se quiser, as chaves do Meu Pluggy e da brapi no cofre do sistema.
