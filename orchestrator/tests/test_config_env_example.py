"""Os `.env.example` versionados precisam carregar no `Settings` quando
copiados como `.env` (bug anterior a Missao 5: as chaves do compose e do
gateway, que moram no mesmo arquivo, derrubavam o import com extra_forbidden).
A protecao contra chave desconhecida (typo) continua valendo."""

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.config import COMPOSE_E_GATEWAY_KEYS, Settings

# So o `orchestrator/.env.example` vira o `.env` do orquestrador. O da raiz e
# o de `deployments/servidor-dedicado/` sao do compose/stack inteira (ASKMAX_*,
# N8N_*, POSTGRES_*, OPENCLAW_*) e nao foram feitos para o `Settings`.
EXEMPLO = Path(__file__).resolve().parents[1] / ".env.example"


def test_env_example_do_orquestrador_copiado_como_dotenv_carrega(tmp_path, monkeypatch):
    shutil.copy(EXEMPLO, tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.rag_enabled is False  # padrao do exemplo: desligado


def test_chave_desconhecida_continua_derrubando(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ORCHESTRATOR_RAG_ENABLD=true\n")  # typo de RAG_ENABLED
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError, match="rag_enabld"):
        Settings()


def test_chaves_de_compose_e_gateway_sao_ignoradas_nao_campos(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("".join(f"ORCHESTRATOR_{k.upper()}=x\n" for k in sorted(COMPOSE_E_GATEWAY_KEYS)))
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert not COMPOSE_E_GATEWAY_KEYS & set(Settings.model_fields)
    assert s.port == 8000  # nada vazou para campo nenhum


# --- M-05 (2a revisao adversaria): o cabecalho do .env.example da raiz ----------------

RAIZ = Path(__file__).resolve().parents[2] / ".env.example"


def _cabecalho(arquivo: Path) -> str:
    linhas = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if not linha.startswith("#"):
            break
        linhas.append(linha.lstrip("# "))
    return " ".join(linhas)


def test_env_example_da_raiz_nao_manda_copiar_para_o_orquestrador():
    """O cabecalho mandava copiar o arquivo da raiz TAMBEM para
    `orchestrator/.env`; as chaves ASKMAX_*/N8N_* dele derrubam o Settings."""
    cabecalho = _cabecalho(RAIZ)
    assert "orchestrator/.env.example" in cabecalho  # a fonte certa do orchestrator/.env
    assert "e para `orchestrator/.env`" not in cabecalho
    assert "valem pros dois" not in cabecalho


def test_env_example_da_raiz_realmente_nao_serve_para_o_settings():
    """Fato que o cabecalho precisa avisar (se um dia passar a carregar, o aviso
    pode sair): ASKMAX_* / N8N_* sao extra_forbidden no Settings."""
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        Settings(_env_file=RAIZ)
