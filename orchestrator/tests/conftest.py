"""Configuracao hermetica da suite de testes.

`orchestrator.config.settings` e instanciado no import e le o `.env` do
diretorio corrente. Sem este arquivo, parte da suite so passava na maquina de
quem tinha um `orchestrator/.env` local com o n8n configurado (ex.:
`specialist_n8n_node` devolve cedo "integracao n8n nao configurada" quando
URL/API key estao ausentes - ver graph/nodes.py) e FALHAVA em qualquer
checkout limpo / CI.

Variaveis de ambiente tem precedencia sobre o `.env` no pydantic-settings,
entao fixar aqui os valores que os testes assumem torna o resultado
independente do ambiente de quem roda. Os valores sao FALSOS de proposito:
nenhum teste fala com rede real (o N8nClient e sempre mockado ou usa
httpx.MockTransport) e nenhum segredo de verdade deve ser necessario.

Precisa rodar ANTES de qualquer `import orchestrator...` - por isso fica no
nivel de modulo do conftest, que o pytest carrega antes de coletar os testes.
"""

import os

# Opt-in deliberado para o teste de integracao contra um n8n REAL
# (RUN_LIVE_N8N_TESTS=1): nesse caso nao sobrescreve as credenciais do ambiente.
if os.environ.get("RUN_LIVE_N8N_TESTS") != "1":
    os.environ["ORCHESTRATOR_N8N_URL"] = "https://n8n.test.invalid"
    os.environ["ORCHESTRATOR_N8N_API_KEY"] = "test-only-not-a-real-key"
