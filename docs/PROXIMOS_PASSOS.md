# Próximos Passos (Roadmap)

## FASE ATUAL: Segurança antes de expandir

O agente está vivo (`deepseek/deepseek-chat`, v2026.6.9) mas rodando **sem sandbox**.
Antes de qualquer nova feature, religar o isolamento é o passo zero.

### Prioridade 🔴 URGENTE

- [ ] **Configurar docker.sock no compose:** adicionar volume `- /var/run/docker.sock:/var/run/docker.sock` no serviço `openclaw-gateway` do `docker-compose.yml`
- [ ] **Religar sandbox:** alterar `sandbox.mode` de `"off"` para `"all"` no `~/.openclaw/openclaw.json`
- [ ] **Validar isolamento:** testar que o agente consegue criar contêineres de sandbox (checar logs de `[sandbox]` ao disparar uma tarefa)

### Prioridade 🟡 PRÓXIMA FASE

- [ ] **Migrar para DeepSeek V4-flash:** o V4 tem 1M de contexto e raciocínio mais poderoso. O `doctor --fix` instalou V3 automaticamente; V4 requer configuração manual via litellm ou atualização do provider `@openclaw/deepseek-provider`
- [ ] **Corrigir allowedOrigins permanentemente:** o gateway está fazendo seed automático a cada restart. Adicionar `gateway.controlUi.allowedOrigins: ["http://localhost:18789", "http://127.0.0.1:18789"]` no openclaw.json para tornar permanente
- [ ] **Silenciar aviso de memória semântica:** desabilitar `agents.defaults.memorySearch.enabled` ou configurar uma chave OpenAI

### Prioridade 🟢 EXPLORAÇÃO

- [ ] Conceder acesso de **leitura** a uma pasta segura e validar que o agente lê sem ultrapassar o limite
- [ ] Conceder acesso de **escrita** a uma pasta designada e validar que o agente não sai do escopo
- [ ] Habilitar skills básicas (pesquisa web, leitura de arquivos) e observar comportamento
- [ ] Documentar padrões de uso seguro para o projeto **MXOS**

## VISÃO FINAL

Aplicar esse aprendizado e arcabouço tecnológico sólido no projeto **MXOS**, focando no desenvolvimento e oferta de funcionários digitais (agentes autônomos de IA) voltados para clientes e PMEs com governança, segurança e alta qualidade técnica.

---

*Atualizado em 2026-06-23. O passo de segurança é a porta de entrada para tudo que vem depois.*
