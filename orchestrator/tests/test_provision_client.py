"""Integracao do script scripts/provision-client.sh (multi-tenant).

Executa o script de verdade num nome de cliente isolado por teste e valida
o ambiente gerado em deployments/<nome>/ (.env proprio, AGENTS.md
customizado, docker-compose.yml configurado, workflows copiados). Limpa o
diretorio ao final de cada teste para nao poluir o checkout.
"""

import json
import shutil
import socket
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


def _get_free_port() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return str(s.getsockname()[1])


@pytest.fixture
def cleanup():
    created: list[str] = []
    yield created
    for name in created:
        shutil.rmtree(DEPLOYMENTS / name, ignore_errors=True)


def test_provision_clinica_end_to_end(cleanup):
    name = _unique_name("Clinica")
    cleanup.append(name)
    port = _get_free_port()
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-name", "Dra. Ana",
        "--operator-to", "5541999999999",
        "--port", port,
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
    assert service["ports"] == [f"127.0.0.1:${{ORCHESTRATOR_HOST_PORT:-{port}}}:8000"]


def test_provision_suporte_ti_niche(cleanup):
    name = _unique_name("Suporte")
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", "suporte-ti-pme", "--port", _get_free_port())
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


def test_provision_operator_name_with_ampersand(cleanup):
    """Valores com '&' devem ser interpolados literalmente (sem semantica do sed)."""
    name = _unique_name("Ampersand")
    cleanup.append(name)
    operator = "Max & Parceiros"
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-name", operator,
        "--operator-to", "5541999999999",
        "--channel", "whatsapp-cloud",
        "--port", _get_free_port(),
    )
    assert proc.returncode == 0, proc.stderr

    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert operator in agents
    assert "[OPERADOR_NOME]" not in agents
    assert "[NOME_DA_CLINICA]" not in agents
    # Se o '&' fosse interpretado pelo sed, o placeholder seria re-inserido
    # (ex: "Max [OPERADOR_NOME] Parceiros"); garante que isso nao ocorreu.
    assert agents.count(operator) >= 1

    env = (DEPLOYMENTS / name / ".env").read_text(encoding="utf-8")
    assert f"ORCHESTRATOR_ATTENDANT_OPERATOR_NAME='{operator}'" in env


def test_provision_channel_with_slash(cleanup):
    """Canais com '/' nao podem quebrar o delimitador nem corromper a saida."""
    name = _unique_name("Channel")
    cleanup.append(name)
    channel = "custom/channel"
    operator = "Silva & Filhos"
    proc = run_provision(
        "--name", name,
        "--niche", "suporte-ti-pme",
        "--operator-name", operator,
        "--operator-to", "5541888888888",
        "--channel", channel,
        "--port", _get_free_port(),
    )
    assert proc.returncode == 0, proc.stderr

    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert channel in agents
    assert operator in agents
    for placeholder in (
        "[NOME_DA_EMPRESA]",
        "[NOME_DA_CLINICA]",
        "[OPERADOR_NOME]",
        "[OPERADOR_NUMERO]",
        "[CANAL]",
    ):
        assert placeholder not in agents

    env = (DEPLOYMENTS / name / ".env").read_text(encoding="utf-8")
    assert f"ORCHESTRATOR_ATTENDANT_CHANNEL='{channel}'" in env
    assert f"ORCHESTRATOR_ATTENDANT_OPERATOR_NAME='{operator}'" in env


def test_provision_refuses_overwrite_without_force(cleanup):
    name = _unique_name("Duplo")
    cleanup.append(name)
    port = _get_free_port()
    first = run_provision("--name", name, "--niche", "clinica-saude", "--port", port)
    assert first.returncode == 0, first.stderr
    second = run_provision("--name", name, "--niche", "clinica-saude", "--port", port)
    assert second.returncode != 0
    third = run_provision("--name", name, "--niche", "suporte-ti-pme", "--port", port, "--force")
    assert third.returncode == 0, third.stderr
    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert "suporte" in agents.lower()


def _assert_no_tmp_leftovers():
    leftovers = [p for p in DEPLOYMENTS.glob(".*.tmp.*")]
    assert leftovers == [], f"diretorios temporarios orfaos: {leftovers}"


@pytest.mark.parametrize("field,value", [
    ("--name", "Bad\nName"),
    ("--niche", "clinica\nsaude"),
    ("--port", "8011\n"),
    ("--operator-name", "Dra.\nAna"),
])
def test_provision_rejects_newline_in_fields(field, value):
    """Quebra de linha em --name/--niche/--port/--operator-name deve falhar."""
    name = _unique_name("Newline")
    args = ["--name", name, "--niche", "clinica-saude"]
    if field == "--name":
        args = ["--name", value, "--niche", "clinica-saude"]
    elif field == "--niche":
        args = ["--name", name, "--niche", value]
    elif field == "--port":
        args = ["--name", name, "--niche", "clinica-saude", "--port", value]
    elif field == "--operator-name":
        args = ["--name", name, "--niche", "clinica-saude",
                "--operator-name", value]
    proc = run_provision(*args)
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / name).exists()
    assert not (DEPLOYMENTS / value).exists()
    _assert_no_tmp_leftovers()


@pytest.mark.parametrize("field", ["--operator-name", "--channel"])
@pytest.mark.parametrize("bad", ["Evil$VAR", "Bad\x01Name", "tab\there"])
def test_provision_rejects_dollar_and_control_chars(field, bad):
    """'$' e caracteres de controle em --operator-name/--channel devem falhar."""
    name = _unique_name("Unsafe")
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        field, bad,
    )
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / name).exists()
    _assert_no_tmp_leftovers()


@pytest.mark.parametrize("field", ["--operator-name", "--channel"])
@pytest.mark.parametrize("bad", ["it's", 'say "hi"', "back\\slash", "a`b", "a#b"])
def test_provision_rejects_shell_breaking_chars(field, bad):
    """Aspas, barra invertida, crase e '#' devem falhar (quebra Compose/shell)."""
    name = _unique_name("Unsafe")
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        field, bad,
    )
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / name).exists()
    _assert_no_tmp_leftovers()


@pytest.mark.parametrize("bad_phone", [
    "abc123",
    "5541999abc",
    "123",
    "1234567",
    "+1234567890123456",
    "55-11-99999",
    "55 11 99999",
])
def test_provision_rejects_invalid_operator_to(bad_phone):
    """--operator-to fora do padrao internacional deve falhar."""
    name = _unique_name("Fone")
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-to", bad_phone,
    )
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / name).exists()
    _assert_no_tmp_leftovers()


def test_provision_operator_to_accepts_empty_and_international(cleanup):
    """--operator-to vazio ou internacional valido deve passar."""
    for tag, phone in (("FoneVazio", ""), ("FonePlus", "+5541999999999")):
        name = _unique_name(tag)
        cleanup.append(name)
        args = ["--name", name, "--niche", "clinica-saude", "--port", _get_free_port()]
        if phone:
            args += ["--operator-to", phone]
        proc = run_provision(*args)
        assert proc.returncode == 0, proc.stderr
        env = (DEPLOYMENTS / name / ".env").read_text(encoding="utf-8")
        assert f"ORCHESTRATOR_ATTENDANT_OPERATOR_TO='{phone}'" in env
    _assert_no_tmp_leftovers()


def test_provision_single_pass_substitution(cleanup):
    """OPERATOR_NAME contendo '[CANAL]' nao deve ser re-substituido (passada unica)."""
    name = _unique_name("SinglePass")
    cleanup.append(name)
    operator = "[CANAL]"
    channel = "whatsapp-cloud"
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-name", operator,
        "--operator-to", "5541999999999",
        "--channel", channel,
        "--port", _get_free_port(),
    )
    assert proc.returncode == 0, proc.stderr
    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    # O valor literal do operador sobrevive; o placeholder real vira o canal.
    assert operator in agents
    assert channel in agents
    assert "[OPERADOR_NOME]" not in agents
    _assert_no_tmp_leftovers()


def test_provision_atomic_no_leftovers_on_error(cleanup):
    """Erro no meio do provisionamento nao deixa tmp orfao nem pasta inconsistente."""
    name = _unique_name("Atomico")
    cleanup.append(name)
    proc = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-to", "telefone-invalido",
    )
    assert proc.returncode != 0
    assert not (DEPLOYMENTS / name).exists()
    _assert_no_tmp_leftovers()

    # Overwrite recusado tambem nao deixa tmp orfao e preserva o destino.
    port = _get_free_port()
    first = run_provision("--name", name, "--niche", "clinica-saude", "--port", port)
    assert first.returncode == 0, first.stderr
    before = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    second = run_provision("--name", name, "--niche", "clinica-saude", "--port", port)
    assert second.returncode != 0
    after = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    assert before == after
    _assert_no_tmp_leftovers()


def test_provision_success_leaves_no_tmp_and_secure_env_perms(cleanup):
    """Sucesso move tudo de uma vez: sem tmp orfao, .env 600."""
    name = _unique_name("Perms")
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", "clinica-saude", "--port", _get_free_port())
    assert proc.returncode == 0, proc.stderr
    _assert_no_tmp_leftovers()
    import os
    import stat
    env_stat = os.stat(DEPLOYMENTS / name / ".env")
    assert stat.S_IMODE(env_stat.st_mode) == 0o600


def test_provision_force_preserves_data_and_env(cleanup):
    """--force regenera infra/template mas preserva ./data e .env com segredos."""
    name = _unique_name("Preserva")
    cleanup.append(name)
    port1 = _get_free_port()
    first = run_provision(
        "--name", name,
        "--niche", "clinica-saude",
        "--operator-to", "5541999999999",
        "--port", port1,
    )
    assert first.returncode == 0, first.stderr
    dest = DEPLOYMENTS / name

    (dest / "data").mkdir(exist_ok=True)
    (dest / "data" / "checkpoints.sqlite").write_text("memoria-cliente", encoding="utf-8")
    env = (dest / ".env").read_text(encoding="utf-8")
    assert "ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=''" in env
    (dest / ".env").write_text(
        env.replace(
            "ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN=''",
            "ORCHESTRATOR_OPENCLAW_GATEWAY_TOKEN='tok-real-123'",
        ),
        encoding="utf-8",
    )

    port2 = _get_free_port()
    second = run_provision(
        "--name", name,
        "--niche", "suporte-ti-pme",
        "--port", port2,
        "--force",
    )
    assert second.returncode == 0, second.stderr

    # Estado e segredos preservados, nao destruidos pelo --force.
    assert (dest / "data" / "checkpoints.sqlite").read_text(encoding="utf-8") == "memoria-cliente"
    env2 = (dest / ".env").read_text(encoding="utf-8")
    assert "tok-real-123" in env2
    assert f"ORCHESTRATOR_HOST_PORT='{port1}'" in env2

    # Infra/template regenerados a partir dos novos argumentos.
    agents = (dest / "AGENTS.md").read_text(encoding="utf-8")
    assert "suporte" in agents.lower()
    compose = yaml.safe_load((dest / "docker-compose.yml").read_text(encoding="utf-8"))
    service = next(iter(compose["services"].values()))
    assert service["ports"] == [f"127.0.0.1:${{ORCHESTRATOR_HOST_PORT:-{port2}}}:8000"]
    assert list((dest / "workflows").glob("workflow-*.json"))
    _assert_no_tmp_leftovers()


def test_provision_refuses_port_in_use():
    """Porta ocupada no host aborta com erro informativo, sem criar nada."""
    import socket

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        port = str(srv.getsockname()[1])
        name = _unique_name("PortBusy")
        proc = run_provision("--name", name, "--niche", "clinica-saude", "--port", port)
        assert proc.returncode != 0
        assert "em uso" in proc.stderr
        assert not (DEPLOYMENTS / name).exists()
        _assert_no_tmp_leftovers()
    finally:
        srv.close()


def test_provision_webhook_paths_namespaced_with_slug(cleanup):
    """Webhooks n8n ganham o slug do cliente para nao colidir na infra compartilhada."""
    name = "TCliente_HookNS"
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", "clinica-saude", "--port", _get_free_port())
    assert proc.returncode == 0, proc.stderr

    slug = "tcliente-hookns"
    workflows = list((DEPLOYMENTS / name / "workflows").glob("workflow-*.json"))
    assert workflows
    for wf in workflows:
        payload = json.loads(wf.read_text(encoding="utf-8"))
        hook_paths = [
            node.get("parameters", {}).get("path")
            for node in payload["nodes"]
            if node.get("type") == "n8n-nodes-base.webhook"
        ]
        assert hook_paths, "workflow sem webhook"
        for path in hook_paths:
            assert path == f"clinica-atendimento-{slug}", path


@pytest.mark.parametrize(("niche", "slots"), [
    ("clinica-saude", ["ESPECIALIDADES", "CONVENIOS", "ENDERECO_TELEFONE"]),
    ("suporte-ti-pme", ["SISTEMAS", "PLAYBOOKS"]),
])
def test_provision_marks_unfilled_placeholders(cleanup, niche, slots):
    """Slots sem argumento viram [A PREENCHER: ...] com aviso no stderr."""
    name = _unique_name("Mark" + niche.split("-")[0].capitalize())
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", niche, "--port", _get_free_port())
    assert proc.returncode == 0, proc.stderr

    agents = (DEPLOYMENTS / name / "AGENTS.md").read_text(encoding="utf-8")
    for slot in slots:
        assert f"[A PREENCHER: {slot}]" in agents
        assert f"[{slot}]" not in agents.replace(f"[A PREENCHER: {slot}]", "")
    assert "aviso" in proc.stderr
    assert "[A PREENCHER" in proc.stderr
    _assert_no_tmp_leftovers()


def test_provision_survives_other_env_without_host_port(cleanup):
    """Deployment vizinho sem ORCHESTRATOR_HOST_PORT nao mata o script (pipefail)."""
    other = _unique_name("SemPorta")
    cleanup.append(other)
    (DEPLOYMENTS / other).mkdir(parents=True, exist_ok=True)
    (DEPLOYMENTS / other / ".env").write_text("OUTRA_VAR=1\n", encoding="utf-8")

    name = _unique_name("DepoisSemPorta")
    cleanup.append(name)
    proc = run_provision("--name", name, "--niche", "clinica-saude", "--port", _get_free_port())
    assert proc.returncode == 0, proc.stderr
    assert (DEPLOYMENTS / name / ".env").is_file()
    _assert_no_tmp_leftovers()
