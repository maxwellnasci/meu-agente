# Arquitetura de Segurança - 8 Camadas Defensivas

## Auditoria Docker-Compose
Validamos a planta baixa da nossa infraestrutura:
- Portas expostas: `18789` (Gateway API/UI), `18790` (Sandbox), e `3978` (Webhooks).
- Volumes montados corretamente, mapeando as pastas de estado de forma explícita.
- **Sem acesso root/host total**: a flag `privileged: true` não existe, garantindo que o container não tenha acesso desenfreado ao kernel.

## O Conceito Sandbox (Quarto do Pânico)
A IA está trancafiada em um ambiente virtual efêmero. Isso blinda a máquina Host (o seu Kali Linux), limitando o raio de explosão ("blast radius") caso a IA execute comandos não previstos. 

## 8 Camadas de Defense in Depth (Atualizado após Teste Nível 1)

1. **Container Docker isolado**: Sub-container efêmero por agente para execução de comandos isolados.
2. **Drop de privilégio**: Roda como usuário `sandbox` (`1000:1000`), nunca root.
3. **Hash pinning**: Imagens com SHA256 fixo (anti supply-chain).
4. **Tool policy com deny + allow**: O OpenClaw usa uma *tool policy* agressiva bloqueando nativamente `cron`, `gateway`, `nodes` no sandbox e permitindo APENAS as skills explicitamente descritas no `openclaw.json` (ex: `exec`), filtrando todas as outras (como pesquisa web e requisições externas).
5. **Cache de sessão (scope: agent)**: O sandbox é otimizado para reaproveitar containers (`sleep infinity`) de forma segura por agente (cofres individuais), aumentando a eficiência sem comprometer o isolamento.
6. **workspaceAccess: "none"**: Isolamento no nível de arquivos host. A IA não acessa os arquivos do sistema hospedeiro de forma alguma.
7. **NetworkMode: "none"**: Placa de rede desabilitada no sandbox. Impede exfiltração de dados, download de malware e comunicação com servidores C2 externos.
8. **Workspace read-only**: O `/workspace` dentro do container é montado com flag `ro` (read-only), impedindo qualquer tipo de alteração persistente nos arquivos injetados no contexto.

## Configuração Segura Validada (openclaw.json)
```json5
{
  "cron": { "enabled": false },
  "agents": {
    "defaults": {
      "model": { "primary": "deepseek/deepseek-v4-flash" },
      "skills": ["exec"],
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
