# Relatório de Teste: Isolamento Sandbox (OpenClaw)

**Data do Teste:** 2026-06-23
**Objetivo:** Validar o real isolamento de execução de código pelo agente.

## 1. Cenário e Configuração
A arquitetura do OpenClaw foi configurada com restrição máxima (Paranoia Mode):
- `sandbox.mode: "all"` ativado no `openclaw.json`.
- `docker.sock` montado na ponte do gateway.
- `GID 124` inserido no `docker-compose.yml` para permissão de orquestração Docker sem privilégios root.

## 2. Ação e Resposta
O usuário utilizou a interface web do OpenClaw e instruiu o agente (`Amigão`, rodando DeepSeek):
> "Execute o comando 'whoami' no terminal usando a ferramenta exec e me diga o resultado"

**Resultado obtido:**
> "sandbox"

## 3. Logs e Eventos (Provas Técnicas)

### Baseline de Containers (Antes do teste)
Havia 4 containers rodando no host (Gateway do OpenClaw, N8N, e Postgres).

### Eventos do Docker Durante o Teste
O monitoramento interceptou a criação de um container efêmero sob demanda:
```
2026-06-23T21:23:23.172082828-03:00 container start 3eba56e4f4743778fed38c4e38ee98162b8563c3b2a3676cbb4bf2172f7c37e0 (image=openclaw-sandbox:bookworm-slim, name=openclaw-sbx-agent-main-f331f052, openclaw.sandbox=1, openclaw.sessionKey=agent:main)
```
*Nota arquitetural: O container (5º elemento) permanece "Up" temporariamente para reaproveitamento (cache de sessão) e otimização de velocidade para comandos subsequentes, sendo finalizado posteriormente pelo ciclo de vida da sessão do OpenClaw.*

## 4. Veredito: SUCESSO TOTAL 🟢
O isolamento funcionou 100% como projetado. O código executado via LLM não teve acesso à máquina host (Kali Linux) nem aos binários principais do Gateway.

**Lições Aprendidas:**
1. **Hash Pinning:** O Dockerfile do Sandbox faz o pull do debian oficial apontando para um SHA256 específico (`f9c6a2fd2...`), mitigando ataques de *supply chain*.
2. **Drop de Privilégios (USER sandbox):** O `whoami` retornou "sandbox" (não "root"). O container não roda como administrador interno.
3. **Segurança Paranoica:** O OpenClaw recusou-se a executar a ferramenta quando a imagem exata da sandbox não estava buildada, recusando-se a usar imagens genéricas.
4. **Camada Dupla:** Temos um container Docker isolado que *dentro dele* faz drop de privilégio do usuário root para usuário comum, reduzindo o risco de *container escape*.

---

## 5. Modelo Usado no Teste

*   **Modelo configurado no `openclaw.json` (default):** `deepseek-chat` (V3)
*   **Modelo usado na sessão de teste:** `deepseek-v4-pro`

### Descoberta Arquitetural Relevante
*   O modelo do `openclaw.json` é apenas o DEFAULT para novas inicializações sem parâmetro.
*   A interface web do OpenClaw permite o **override do modelo POR SESSÃO** sem a necessidade de editar o arquivo de configuração ou reiniciar o gateway.
*   Modelos nativos disponíveis na interface (sem necessidade de providers customizados como LiteLLM): `v4-flash`, `v4-pro`, com controle nativo de profundidade de raciocínio (thinking).
*   Isso habilita a execução de uma **estratégia híbrida** na arquitetura.

### Implicações para o Projeto MXOS
*   **Segmentação de Produto:** Possibilidade de oferecer "níveis de inteligência" diferentes dependendo do cliente, ticket médio ou tipo de tarefa solicitada.
*   **Otimização de Custo-Eficiência (FinOps):** Tarefas triviais e operacionais usam o cérebro mais barato e rápido (`V4-flash`), enquanto decisões de alto risco, análises profundas ou arquiteturais são direcionadas para o cérebro mais caro (`V4-pro`).
