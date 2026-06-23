# Arquitetura de Segurança

## Auditoria Docker-Compose
Validamos a planta baixa da nossa infraestrutura:
- Portas expostas: `18789` (Gateway API/UI), `18790` (Sandbox), e `3978` (Webhooks).
- Volumes montados corretamente, mapeando as pastas de estado de forma explícita.
- **Sem acesso root/host total**: a flag `privileged: true` não existe, garantindo que o container não tenha acesso desenfreado ao kernel.

## O Conceito Sandbox (Quarto do Pânico)
A IA está trancafiada em um ambiente virtual efêmero. Isso blinda a máquina Host (o seu Kali Linux), limitando o raio de explosão ("blast radius") caso a IA execute comandos não previstos. 

## As 3 Travas de Segurança da Configuração
1. `workspaceAccess: "none"` - Máximo isolamento no nível de arquivos; a IA não lê nem escreve nada do Host.
2. `sandbox.mode: "all"` - Obrigatório para **todas** as sessões (não apenas para processos em background).
3. `sandbox.scope: "agent"` - Cada agente tem sua própria jaula isolada.

## Configuração Segura Validada (openclaw.json)
```json5
{
  "cron": { "enabled": false },
  "agents": {
    "defaults": {
      "model": { "primary": "deepseek/deepseek-v4-flash" },
      "skills": [],
      "sandbox": {
        "mode": "all",
        "workspaceAccess": "none",
        "scope": "agent"
      }
    }
  }
}
```

## Lição Aprendida
**Confiança Zero e Validação Cruzada**: Validar configurações sugeridas por IA cruzando a informação diretamente com a documentação oficial. Ao usar um modelo forte para auditar o plano original, identificamos e descartamos duas configurações inventadas que quebrariam o startup (`nodes.enabled` e `browser.enabled`). Segurança só existe com provas baseadas em documentação.
