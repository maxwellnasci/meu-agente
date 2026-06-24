# Próximos Passos (Roadmap)

## FASE ATUAL: Segurança antes de expandir

O agente está vivo (`deepseek/deepseek-chat`, v2026.6.9) mas rodando **sem sandbox**.
Antes de qualquer nova feature, religar o isolamento é o passo zero.

### Prioridade 🔴 URGENTE

- [x] **Configurar docker.sock no compose:** (Feito)
- [x] **Religar sandbox:** (Feito)
- [x] **Validar isolamento:** (Em andamento)

### Prioridade 🟡 PRÓXIMA FASE

- [x] **Migrar para DeepSeek V4-flash:** (Aprendizado resolvido: não é necessário litellm, o V4-flash e V4-pro estão disponíveis nativamente na interface web após o `doctor --fix`)
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
