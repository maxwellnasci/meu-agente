"""Integracao do script scripts/provision-client.sh (multi-tenant).

Executa o script de verdade num nome de cliente isolado por teste e valida
o ambiente gerado em deployments/<nome>/ (.env proprio, AGENTS.md
customizado, docker-compose.yml configurado, workflows copiados). Limpa o
diretorio ao final de cada teste para nao poluir o checkout.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "provision-client.sh"
DEPLOYMENTS = ROOT / "deployments"


def run_provision(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _unique_name(tag: str) -> str:
    return f"TCliente{tag}"


@pytest.fixture
def cleanup():
    created: list[str] = []
    yield created
    for name in created:
        shutil.rmtree(DEPLOYMENTS / name, ignore_errors=True)


def test_provision_clinica_end_to_end(cleanup):
    name = _unique_name("Clinica")
    cleanup.append(name)
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-name", "Dra. Ana",
        "--operator-to", "5541999999999",
        "--port", "8011",
    )
    assert proc.returncode == 0, proc.stderr

    dest = DEPLOYMENTS / name
    assert (dest / "AGENTS.md").is_file()
    assert (dest / ".env").is_file()
    assert (dest / "docker-compose.yml").is_file()

    agents = (dest / "AGENTS.md").read_text(encoding="utf-8")
    assert name in agents
    assert "[NOME_DA_CLINICA]" not in agents
    assert "Dra. Ana" in agents

    workflows = list((dest / "workflows").glob("workflow-*.json"))
    assert workflows, "workflow de exemplo do nicho nao foi copiado"
    for wf in workflows:
        payload = json.loads(wf.read_text(encoding="utf-8"))
        assert payload["nodes"], "workflow sem nodes"

    compose = yaml.safe_load((dest / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "meu-agente-net" in compose["networks"]
    service = next(iter(compose["services"].values()))
    assert service["ports"] == ["127.0.0.1:${ORCHESTRATOR_HOST_PORT:-8011}:8000"]


def test_provision_suporte_ti_niche(cleanup):
    name = _unique_name("Suporte")
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", "suporte-ti-pme", "--port", "8012")
    assert proc.returncode == 0, proc.stderr
    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert name in agents
    assert "[NOME_DA_EMPRESA]" not in agents


def test_provision_rejects_unknown_niche():
    proc = run_provision("--name", "TesteNichoRuim", "--niche", "nicho-inexistente")
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / "TesteNichoRuim").exists()


def test_provision_rejects_unsafe_name():
    proc = run_provision("--name", "../fora-do-deployments", "--niche", "clinica-saude")
    assert proc.returncode != 0
    assert not (ROOT / "fora-do-deployments").exists()


def test_provision_refuses_overwrite_without_force(cleanup):
    name = _unique_name("Duplo")
    cleanup.append(name)
    first = run_provision("--name", name, "--niche", "clinica-saude")
    assert first.returncode == 0, first.stderr
    second = run_provision("--name", name, "--niche", "clinica-saude")
    assert second.returncode != 0
    third = run_provision("--name", name, "--niche", "suporte-ti-pme", "--force")
    assert third.returncode == 0, third.stderr
    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert "suporte" in agents.lower()
