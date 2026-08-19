from contextlib import asynccontextmanager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from orchestrator.config import settings


@asynccontextmanager
async def checkpointer_context():
    """Abre o checkpointer usado pelo grafo (pilar Memoria/Checkpointing).

    AsyncSqliteSaver.from_conn_string mantem uma conexao aberta durante toda
    a vida da aplicacao - por isso essa abertura/fechamento nao acontece por
    request, e sim uma unica vez no lifespan do FastAPI (main.py), que guarda
    a instancia resultante em app.state.

    Caminho de evolucao: trocar por AsyncPostgresSaver sem mudar a interface
    consumida pelo builder do grafo (build_graph so espera um
    BaseCheckpointSaver).
    """
    async with AsyncSqliteSaver.from_conn_string(settings.checkpointer_sqlite_path) as saver:
        yield saver
