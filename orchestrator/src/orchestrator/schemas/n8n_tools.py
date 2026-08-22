from pydantic import BaseModel, Field

# Tools expostas ao LLM do especialista n8n via bind_tools (graph/nodes.py,
# specialist_n8n_node). Cada uma mapeia 1:1 para um metodo de
# clients/n8n_client.py - a lista aqui e o contrato de tool-calling real
# contra a API publica de uma instancia de n8n externa em producao.


class N8nListWorkflows(BaseModel):
    """Lista workflows existentes na instancia de n8n, com filtros opcionais."""

    active: bool | None = Field(default=None, description="Filtra so workflows ativos (true) ou inativos (false).")
    name: str | None = Field(default=None, description="Filtra por nome do workflow.")


class N8nGetWorkflow(BaseModel):
    """Busca o detalhe completo (nodes, connections, settings) de um workflow especifico."""

    workflow_id: str = Field(description="ID do workflow no n8n.")


class N8nCreateWorkflow(BaseModel):
    """Cria um novo workflow na instancia de n8n. O workflow nasce inativo -
    use N8nActivateWorkflow depois se ele precisar rodar automaticamente."""

    name: str = Field(description="Nome do workflow.")
    nodes: list[dict] = Field(
        description=(
            "Lista de nodes no formato nativo do n8n - cada item precisa ter "
            "id, name, type (ex.: 'n8n-nodes-base.noOp', 'n8n-nodes-base.webhook'), "
            "typeVersion, position ([x, y]) e parameters."
        )
    )
    connections: dict = Field(
        default_factory=dict,
        description="Mapa de conexoes entre nodes, no formato nativo do n8n ({'<nome do node origem>': {'main': [[{'node': ..., 'type': 'main', 'index': 0}]]}}).",
    )


class N8nUpdateWorkflow(BaseModel):
    """Substitui nodes/connections/nome de um workflow ja existente (update completo, nao incremental)."""

    workflow_id: str = Field(description="ID do workflow a atualizar.")
    name: str = Field(description="Novo nome do workflow (repita o atual se nao for para mudar).")
    nodes: list[dict] = Field(description="Lista completa de nodes apos a atualizacao (substitui a lista anterior inteira).")
    connections: dict = Field(default_factory=dict, description="Mapa completo de conexoes apos a atualizacao.")


class N8nDeleteWorkflow(BaseModel):
    """Deleta permanentemente um workflow da instancia de n8n."""

    workflow_id: str = Field(description="ID do workflow a deletar.")


class N8nActivateWorkflow(BaseModel):
    """Ativa (publica) um workflow - triggers automaticos (webhook, cron etc.) passam a valer."""

    workflow_id: str = Field(description="ID do workflow a ativar.")


class N8nDeactivateWorkflow(BaseModel):
    """Desativa um workflow - triggers automaticos deixam de valer."""

    workflow_id: str = Field(description="ID do workflow a desativar.")


class N8nTriggerWebhook(BaseModel):
    """Dispara uma execucao chamando a URL de webhook de um node Webhook do
    proprio workflow (a API publica do n8n nao tem endpoint generico de
    'executar workflow X' - so webhook e possivel via HTTP)."""

    path: str = Field(description="Path do node Webhook (o mesmo configurado no node, sem o prefixo /webhook/).")
    method: str = Field(default="POST", description="Metodo HTTP configurado no node Webhook (GET, POST, etc.).")
    body: dict | None = Field(default=None, description="Corpo JSON a enviar (para methods que aceitam body).")
    test: bool = Field(
        default=False,
        description="True usa /webhook-test (execucao unica, exige o editor do workflow aberto/'escutando'); false usa /webhook (producao, exige o workflow ativo).",
    )
