# CURSOR_INTEGRATION.md — Integração Orquestra ↔ Cursor

**Data:** 31/08/2026  
**Status:** Produção ✅  
**Autores:** Max + Antigravity

---

## Objetivo

Fazer o Orquestra ser o **piloto** do Cursor (o carro), controlando o que é exibido
na tela do editor sem o usuário precisar clicar em nada. O usuário só conversa com
o Orquestra; o Cursor vira uma janela viva que reage às ações dos agentes.

---

## Arquitetura Final (O que foi construído)

```
┌──────────────────────────────────────────────────┐
│  Terminal do Cursor (onde você digita no Orquestra)│
│                                                    │
│  orquestra.py                                      │
│  ├── _start_bridge_server()  ← sobe na porta 49152 │
│  ├── _auto_open_in_cursor_at(file, line) ← GPS     │
│  ├── _get_cursor_context()   ← Retrovisor          │
│  └── Câmbio Automático (injeção no prompt)         │
│                     │ HTTP POST                    │
│                     ▼                              │
│  BridgeHandler (thread daemon)                     │
│  ├── action='open'  → cursor -g file:line          │
│  └── action='diff'  → gera .diff e abre no Cursor  │
└──────────────────────────────────────────────────┘
```

---

## Funcionalidades Implementadas

### 1. Bridge HTTP Interna (porta 49152)

**Problema resolvido:** A CLI do Cursor (`cursor -d file1 file2`) trava quando chamada
de dentro do próprio terminal embutido do Cursor. Tentamos instalar uma extensão local
(`~/.cursor/extensions/orquestra-bridge-1.0.0/`), mas o Cursor bloqueia extensões sem
assinatura da loja oficial.

**Solução:** O Orquestra sobe o próprio servidor HTTP em background ao iniciar
(`_start_bridge_server()`). Os comandos são enviados via HTTP POST para `127.0.0.1:49152`
e o servidor executa o binário `cursor` de fora do terminal embutido, onde funciona.

**Código:** `_start_bridge_server()` → classe `BridgeHandler` → `do_POST()`

---

### 2. Auto-Open de Arquivos (Fase 1)

**O que faz:** Quando um agente termina uma tarefa e modifica arquivos, o Orquestra
detecta os arquivos alterados via `git diff` e os abre automaticamente no Cursor.

**Como funciona:**
1. Antes de executar a tarefa, salva o snapshot dos arquivos modificados (`pre_snapshot`).
2. Após a execução, compara com `_git_status_paths()` para descobrir o que mudou.
3. Chama `_auto_open_in_cursor_at(filepath, first_line)` para cada arquivo.

**Código:** `_worker_lifecycle()` → bloco `post_snapshot_set` (~linha 3275)

---

### 3. GPS — Navegação até a Linha Exata (Fase 2)

**O que faz:** Ao invés de abrir o arquivo no topo, o Cursor vai direto para a primeira
linha que o agente modificou.

**Como funciona:**
1. Após detectar os arquivos modificados, roda `git diff HEAD -- <arquivo>`.
2. Faz parse das linhas de hunk (`@@ -a,b +c,d @@`) para extrair a linha `+c`.
3. Chama `cursor -g {arquivo}:{linha}` via bridge.

**Código:** `_auto_open_in_cursor_at(filepath, line)` + bloco de detecção de linha no
`_worker_lifecycle()`

---

### 4. /diff — Revisor de Mudanças (Fase 2)

**O que faz:** O usuário digita `/diff 22` e o Cursor abre um arquivo `.diff` mostrando
exatamente o que o agente fez na Tarefa #22 (linhas verdes = adicionadas, vermelhas = removidas).

**Como funciona:**
1. Busca o snapshot pré-tarefa no banco de dados.
2. Compara com o estado atual via `diff -u arquivo_antigo arquivo_novo`.
3. Salva o resultado em `/tmp/orquestra_review.diff` e abre no Cursor via bridge.

**Erros que encontramos:**
- `cursor -d` dentro do terminal embutido trava silenciosamente → resolvido pelo bridge HTTP
- A extensão local não carregava por falta de assinatura → resolvido movendo o servidor para dentro do Orquestra

**Código:** Bloco `elif low.startswith("/diff"):` no loop REPL (~linha 2940)

---

### 5. Retrovisor — Consciência de Contexto

**O que faz:** Sempre que o Orquestra abre um arquivo no Cursor (GPS ou Auto-Open),
ele grava em `~/.orquestra_cursor_state.json` qual arquivo está na tela e em qual linha.

**Como funciona:**
1. `BridgeHandler.do_POST()` para `action='open'` grava o estado no JSON.
2. `_get_cursor_context()` lê esse JSON a qualquer momento.

**Arquivo de estado:** `~/.orquestra_cursor_state.json`
```json
{"file": "/caminho/absoluto/para/arquivo.py", "line": 42}
```

**Código:** `_get_cursor_context()` + bloco `action='open'` no `BridgeHandler`

---

### 6. Câmbio Automático — Injeção Silenciosa de Contexto

**O que faz:** Quando você faz uma pergunta ao Orquestra sem mencionar `@arquivo`,
ele detecta automaticamente o arquivo que está aberto no Cursor e inclui o conteúdo
como contexto invisible para o agente. Você pode perguntar "o que essa função faz?"
sem precisar especificar o arquivo — o agente já sabe.

**Como funciona:**
1. Após processar `@arquivo` (injeção manual), verifica se `file_matches` está vazio.
2. Se sim, chama `_get_cursor_context()` para saber o arquivo atual.
3. Inclui o conteúdo no final do prompt enviado ao agente.
4. Exibe `🔭 Contexto automático: nome_arquivo.py (cursor na linha 42)` no terminal.

**Código:** Bloco `# Câmbio Automático` no loop REPL após a injeção de `@files` (~linha 2728)

---

## Fluxo Completo do Dia a Dia

```
Você abre o Cursor (cursor .) →
Inicia o Orquestra (orquestra ou python3 orquestra.py) →
Bridge HTTP sobe automaticamente na porta 49152 →

Pede uma tarefa →
Agente trabalha →
Orquestra detecta o arquivo modificado via git →
GPS abre o arquivo na linha exata no Cursor →
Retrovisor salva o arquivo no estado →

Você olha o arquivo no Cursor →
Digita uma pergunta qualquer no Orquestra →
Câmbio Automático injeta o contexto do arquivo silenciosamente →
Agente responde com contexto completo sem você digitar @arquivo →

Digita /diff 22 →
orquestra_review.diff abre no Cursor mostrando o antes e depois →

Digita /aprovar 22 →
Commit automático no Git →
Tarefa arquivada ✅
```

---

## Comandos Disponíveis

| Comando | O que faz |
|---|---|
| `/tarefas` | Lista todas as tarefas com ID e status |
| `/diff [ID]` | Abre o diff da tarefa no Cursor |
| `/aprovar [ID]` | Aprova e faz commit das mudanças no Git |
| `/rejeitar [ID]` | Desfaz todas as mudanças da tarefa (git reset) |
| `/cursor` | Abre o projeto no Cursor (equivalente a `cursor .`) |

---

## Arquivos Relevantes

| Arquivo | Propósito |
|---|---|
| `orquestra.py` | Código principal do Orquestra |
| `~/.orquestra_cursor_state.json` | Estado atual: arquivo + linha aberta no Cursor |
| `/tmp/orquestra_review.diff` | Último diff gerado para revisão |
| `~/.cursor/extensions/orquestra-bridge-1.0.0/` | Extensão desativada (não usada) |

---

## Limitações Conhecidas

1. **Diff não é side-by-side:** O Cursor não expõe API para abrir o diff viewer nativo
   via CLI. O arquivo `.diff` é aberto com syntax highlighting, que é funcional mas
   não tão visual quanto a tela dividida.

2. **Câmbio Automático em arquivos grandes:** Arquivos muito grandes (>500KB) podem
   estourar o limite de tokens do agente. Uma melhoria futura pode truncar o contexto
   ou enviar apenas as linhas ao redor do cursor.

3. **Estado do Retrovisor é por abertura:** O estado só é atualizado quando o Orquestra
   abre um arquivo. Se o usuário mudar de aba manualmente no Cursor, o estado não é
   atualizado automaticamente (exigiria a extensão nativa).

---

## Histórico de Tentativas e Erros

### Tentativa 1: `cursor -d` direto
- **Resultado:** Trava silenciosamente dentro do terminal embutido do Cursor.
- **Por que falhou:** O Cursor bloqueia comandos que tentam modificar sua própria UI de dentro do processo filho.

### Tentativa 2: Extensão Local (`~/.cursor/extensions/`)
- **Resultado:** Cursor não carregou a extensão.
- **Por que falhou:** O Cursor valida extensões contra a loja oficial. Extensões locais sem
  assinatura são ignoradas silenciosamente mesmo quando registradas no `extensions.json`.

### Solução Final: Bridge HTTP interno ao Orquestra
- O Orquestra sobe o servidor HTTP como thread daemon no seu próprio processo.
- Os comandos são executados pelo servidor de fora do terminal embutido, onde funcionam.
- Sem dependências externas, sem extensões, sem permissões especiais.
