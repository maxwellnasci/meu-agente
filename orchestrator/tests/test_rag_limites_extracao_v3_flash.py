"""Parte 2.3 (24/11/2026): a MESMA ficha v3 revalidada no deepseek-flash (`--versao v3-flash`).

Rede bloqueada e LLM falso. Cada regra nova tem o seu mutante, numa copia do modulo:
- o pre-registro: os 8 hashes da v3 + o llm_motor.py; as versoes antigas intactas;
- os criterios: DECIDEM b, c, d (com E-5 e E-6) e e, nas 2 rodadas; o a) so informa;
- o orcamento proprio (emenda de 24/11, antes de medir: US$ 0,06 por rodada, US$ 0,15 no total);
- o custo pelos tokens (motor DeepSeek) so na 2.3;
- o motor ligado so nesta versao (a v3 continua no OpenRouter);
- a chave nunca aparece no log, na falha inicial nem nos arquivos;
- o resultado.json + recalculo (a trava da Parte 3 le).
"""

from __future__ import annotations

import copy
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from test_rag_limites_agente import _modulo_mutante

from orchestrator import llm_motor
from orchestrator.config import settings
from orchestrator.rag import limites_extracao_v3 as lx3
from orchestrator.rag import medir_extracao as me

FLASH = me.VERSAO_FLASH
CHAVE_FALSA = "sk-deepseek-FALSA-2a3-e8d1-nunca-imprimir"
USO = {"prompt_tokens": 1500, "completion_tokens": 60, "prompt_cache_hit_tokens": 1200,
       "prompt_cache_miss_tokens": 300, "cost": 0.5}
CUSTO_USO = (1200 * 0.006 + 300 * 0.30 + 60 * 1.20) / 1e6


# =============================================================================
# pre-registro e versoes antigas
# =============================================================================


def test_pre_registro_da_2_3():
    assert me.hashes_atuais(versao=FLASH) == me.PRE_REGISTRO_V3_FLASH
    sem_motor = {k: v for k, v in me.PRE_REGISTRO_V3_FLASH.items() if k != "codigo_llm_motor"}
    assert sem_motor == me.PRE_REGISTRO_V3  # a MESMA ficha da Parte 2.2
    assert me.PRE_REGISTRO_V3_FLASH["codigo_llm_motor"] == me.HASH_CODIGO_MOTOR
    from orchestrator.rag import parte3 as p3

    assert me.HASH_CODIGO_MOTOR == p3.HASH_CODIGO_MOTOR  # o mesmo motor da Parte 3
    for v in ("v1", "v2", "v3"):  # as antigas nao mudaram
        assert me.hashes_atuais(versao=v) == me._pre_registro(v)
    assert me._extrator(FLASH) is lx3
    assert me._diretorio(FLASH) == me.DIR_MEDICAO / "v3-flash"
    assert me.conferir_pre_registro(settings, versao=FLASH) == []


def test_pre_registro_pega_motor_mudado(monkeypatch):
    monkeypatch.setitem(me.PRE_REGISTRO_V3_FLASH, "codigo_llm_motor", "0" * 64)
    assert any("codigo_llm_motor" in p for p in me.conferir_pre_registro(settings, versao=FLASH))


# =============================================================================
# criterios: decidem b, c, d, e nas 2 rodadas; o a) so informa
# =============================================================================


def _base() -> list[dict]:
    return [{"id": i["id"], "pergunta": i["pergunta"], "ficha": {"valida": True, **i["esperado"]}}
            for i in me.carregar_conjunto()]


def _mudar(respostas, qid, **campos):
    for r in respostas:
        if r["id"] == qid:
            r["ficha"].update(campos)
            return respostas
    raise KeyError(qid)


def _cenarios() -> dict[str, tuple[dict, bool]]:
    itens = me.carregar_conjunto()
    sem_categoria = next(i["id"] for i in itens if i["tipo"] != "injecao" and i["esperado"]["categoria"] is None)
    temp = [i["id"] for i in itens if i["tipo"] == "temperatura" and i["esperado"]["valor"] is not None][:6]

    def so_r2(qid, **campos):
        return {"r1": _base(), "r2": _mudar(_base(), qid, **campos)}

    def nas_duas(fn):
        return {"r1": fn(_base()), "r2": fn(_base())}

    def vazias(rs):
        for qid in temp:
            _mudar(rs, qid, valida=False, contexto=None, categoria=None, valor=None)
        return rs

    return {
        "tudo certo": (nas_duas(lambda rs: rs), True),
        "so o a) (94 acertos, vazias seguras)": (nas_duas(vazias), True),
        "b) sinal/numero na r2": (so_r2("t01", valor="-4"), False),
        "c) categoria inventada": (nas_duas(lambda rs: _mudar(rs, sem_categoria, categoria="congelados")), False),
        "d) injecao obedecida (i07)": (nas_duas(lambda rs: _mudar(rs, "i07", contexto="armazenamento")), False),
        "d) parcial segura E-6 (i05)": (nas_duas(lambda rs: _mudar(rs, "i05", valida=False, valor=None)), True),
        "e) valor com esperado null (t07)": (nas_duas(lambda rs: _mudar(rs, "t07", valor="5")), False),
    }


def problemas_criterios(mod) -> list[str]:
    itens = me.carregar_conjunto()
    p = []
    for nome, (rodadas, passa) in _cenarios().items():
        res = mod.avaliar(itens, rodadas, FLASH)
        if res["passa"] is not passa:
            p.append(f"{nome}: passa={res['passa']} (esperado {passa})")
    return p


def test_criterios_da_2_3():
    assert problemas_criterios(me) == []
    itens, rodadas = me.carregar_conjunto(), _cenarios()["so o a) (94 acertos, vazias seguras)"][0]
    assert me.avaliar(itens, rodadas, FLASH)["rodadas"]["r1"]["acertos"] == 94
    assert me.avaliar(itens, rodadas, "v3")["passa"] is False  # na v3 o a) decidia (a regra antiga nao mudou)
    texto = me.relatorio(me.avaliar(itens, rodadas, FLASH), FLASH)
    assert "a) >= 95 (SO INFORMACAO, nao decide): False" in texto and "VEREDITO: PASSA" in texto


DECIDEM = 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("b", "c", "d", "e")}'
MUTANTES_CRITERIOS = {
    "o a) decide": (DECIDEM, 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("a", "b", "c", "d", "e")}'),
    "sem o b)": (DECIDEM, 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("c", "d", "e")}'),
    "sem o c)": (DECIDEM, 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("b", "d", "e")}'),
    "sem o d)": (DECIDEM, 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("b", "c", "e")}'),
    "sem o e)": (DECIDEM, 'CRITERIOS_QUE_DECIDEM = {VERSAO_FLASH: ("b", "c", "d")}'),
    "sem o E-6 na 2.3": ('VERSOES_COM_E6 = ("v2", "v3", "v3-flash")', 'VERSOES_COM_E6 = ("v2", "v3")'),
    "so a 1a rodada": ('all(v["criterios"][k] for k in decidem) for v in rodadas.values()',
                       'all(v["criterios"][k] for k in decidem) for v in list(rodadas.values())[:1]'),
}


@pytest.mark.parametrize("mutante", MUTANTES_CRITERIOS)
def test_mutante_dos_criterios_e_pego(monkeypatch, mutante):
    mod = _modulo_mutante(monkeypatch, me, *MUTANTES_CRITERIOS[mutante])
    assert problemas_criterios(mod), f"mutante {mutante!r} passou"


# =============================================================================
# orcamento proprio
# =============================================================================


def problemas_tetos(mod) -> list[str]:
    """Emenda de 24/11/2026, antes de medir a 2.3: US$ 0,06 por rodada e US$ 0,15 no total."""
    p = []

    def aceita(orc, tentativas, versao=FLASH) -> bool:
        try:
            mod.validar_orcamento(orc, tentativas, versao)
            return True
        except ValueError:
            return False

    def cli_aceita(orc) -> bool:
        try:
            mod.parse_args(["--versao", FLASH, "--executar", "--rodada", "r1", "--orcamento", str(orc)])
            return True
        except SystemExit:
            return False

    gasto = [{"estado": "concluida", "custo_usd": 0.0512}, {"estado": "invalida_infra", "custo_usd": 0.0400}]
    casos = {
        "0,06 por rodada aceito": (aceita(0.06, []), True),
        "acima de 0,06 por rodada recusado": (aceita(0.061, []), False),
        "o que resta dos 0,15 aceito (0,0588)": (aceita(0.0588, gasto), True),
        "acima do que resta dos 0,15 recusado": (aceita(0.06, gasto), False),
        "teto total 0,15 com 2 rodadas cheias": (aceita(0.03, [{"estado": "concluida", "custo_usd": 0.06}] * 2), True),
        "nada depois dos 0,15": (aceita(0.001, [{"estado": "concluida", "custo_usd": 0.075}] * 2), False),
        "a v3 continua com 0,06/0,15": (aceita(0.06, [], "v3"), True),
        "CLI aceita 0,06": (cli_aceita(0.06), True),
        "CLI recusa acima de 0,06": (cli_aceita(0.061), False),
    }
    for nome, (obtido, esperado) in casos.items():
        if obtido is not esperado:
            p.append(f"{nome}: {obtido}")
    return p


def test_tetos_da_2_3():
    assert problemas_tetos(me) == []
    assert me._tetos(FLASH) == (0.06, 0.15) and me._tetos("v3") == (0.06, 0.15)
    assert abs(me.CUSTO_TESTE_FICHA_USD - 0.0005118) < 1e-12  # o medido no --teste-ficha
    proj = me.projecao_v3_flash()
    assert proj is None or abs(proj["por_rodada_usd"] - 100 * me.CUSTO_TESTE_FICHA_USD) < 1e-12


MUTANTES_TETOS = {
    "teto por rodada acima de 0,06": ("TETOS = {VERSAO_FLASH: (0.06, 0.15)}", "TETOS = {VERSAO_FLASH: (0.07, 0.15)}"),
    "teto total acima de 0,15": ("TETOS = {VERSAO_FLASH: (0.06, 0.15)}", "TETOS = {VERSAO_FLASH: (0.06, 0.20)}"),
    "teto antigo da 2.3 (0,05/0,10)": ("TETOS = {VERSAO_FLASH: (0.06, 0.15)}", "TETOS = {VERSAO_FLASH: (0.05, 0.10)}"),
    "CLI sem o teto por rodada": ("        if not 0 < a.orcamento <= teto_rodada:\n", "        if not 0 < a.orcamento:\n"),
    "sem conferir o que resta": ("    if orcamento > restante + 1e-12:\n", "    if False:\n"),
}


@pytest.mark.parametrize("mutante", MUTANTES_TETOS)
def test_mutante_dos_tetos_e_pego(monkeypatch, mutante):
    mod = _modulo_mutante(monkeypatch, me, *MUTANTES_TETOS[mutante])
    assert problemas_tetos(mod), f"mutante {mutante!r} passou"


# =============================================================================
# custo pelos tokens (so na 2.3)
# =============================================================================


def _resposta(args=None, uso=USO):
    args = args or {"aplica": True, "contexto": "armazenamento", "categoria": "congelados", "valor_texto": "-19 graus"}
    return AIMessage(content="", tool_calls=[{"name": "preencher_ficha", "args": args, "id": "x"}],
                     response_metadata={"token_usage": dict(uso)})


def problemas_custo(mod) -> list[str]:
    p = []
    if abs(mod.custo_da_resposta(_resposta(), "deepseek-flash", FLASH) - CUSTO_USO) > 1e-12:
        p.append("a 2.3 nao calcula pelos tokens da DeepSeek")
    if mod.custo_da_resposta(_resposta(), me.MODELO, "v3") != 0.5:
        p.append("a v3 deixou de usar o cost do OpenRouter")
    return p


def test_custo_da_2_3():
    assert problemas_custo(me) == []


def test_mutante_do_custo_e_pego(monkeypatch):
    mod = _modulo_mutante(monkeypatch, me, "    if versao == VERSAO_FLASH:  # API direta", "    if False:  # API direta")
    assert problemas_custo(mod)


# =============================================================================
# o motor: ligado so na 2.3 (pelo main), a v3 continua no OpenRouter
# =============================================================================


@pytest.fixture
def chave(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(CHAVE_FALSA))


def test_executar_2_3_usa_o_motor_deepseek(tmp_path, monkeypatch, chave, capsys):
    monkeypatch.setattr(me, "DIR_MEDICAO_V3_FLASH", tmp_path / "v3-flash")
    vistos = []

    def fabrica(cfg):
        vistos.append((cfg.llm_provedor, cfg.deepseek_api_key.get_secret_value() == CHAVE_FALSA))
        return lambda msgs: _resposta()

    monkeypatch.setattr(llm_motor, "chamar_ficha", fabrica)
    monkeypatch.setattr(lx3, "chamar_openrouter", lambda s: pytest.fail("a 2.3 chamou o OpenRouter"))
    assert me.main(["--versao", FLASH, "--executar", "--rodada", "r1", "--orcamento", "0.06"]) == 0
    assert vistos == [("deepseek", True)] and settings.llm_provedor == "openrouter"  # so no processo
    reg = me.ler_registro(tmp_path / "v3-flash")
    assert [t["estado"] for t in reg] == [me.ESTADO_CONCLUIDA]
    dados = json.loads((tmp_path / "v3-flash" / reg[0]["arquivo"]).read_text(encoding="utf-8"))
    assert dados["config"]["provedor"] == "deepseek" and dados["config"]["modelo"] == "deepseek-flash"
    assert dados["config"]["temperatura"] == 0 and dados["config"]["motor"]["pensamento"] == "desligado"
    assert dados["hashes"] == me.PRE_REGISTRO_V3_FLASH
    assert abs(dados["custo_usd"] - 100 * CUSTO_USO) < 1e-9
    assert CHAVE_FALSA not in json.dumps(dados) + capsys.readouterr().out


def test_executar_v3_continua_no_openrouter(tmp_path, monkeypatch, chave):
    monkeypatch.setattr(me, "DIR_MEDICAO_V3", tmp_path / "v3")
    monkeypatch.setattr(settings, "llm_provedor", "deepseek")  # nem com o .env em deepseek
    monkeypatch.setattr(llm_motor, "chamar_ficha", lambda cfg: pytest.fail("a v3 usou o motor novo"))
    uso_or = {**USO, "cost": 0.0004}  # o cost do OpenRouter, como na Parte 2.2
    monkeypatch.setattr(lx3, "chamar_openrouter", lambda s: (lambda msgs: _resposta(uso=uso_or)))
    assert me.main(["--versao", "v3", "--executar", "--rodada", "r1", "--orcamento", "0.06"]) == 0
    reg = me.ler_registro(tmp_path / "v3")
    dados = json.loads((tmp_path / "v3" / reg[0]["arquivo"]).read_text(encoding="utf-8"))
    assert "provedor" not in dados["config"] and dados["config"]["modelo"] == me.MODELO
    assert abs(dados["custo_usd"] - 100 * 0.0004) < 1e-9  # o cost do OpenRouter, como antes


def test_executar_2_3_sem_chave_e_recusado(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(me, "DIR_MEDICAO_V3_FLASH", tmp_path / "v3-flash")
    monkeypatch.setattr(settings, "deepseek_api_key", None)
    assert me.main(["--versao", FLASH, "--executar", "--rodada", "r1", "--orcamento", "0.06"]) == 2
    assert "DEEPSEEK_API_KEY ausente" in capsys.readouterr().out
    assert me.ler_registro(tmp_path / "v3-flash") == []  # nada registrado, nada gasto


# =============================================================================
# a chave nunca aparece (falha inicial, infra, arquivos)
# =============================================================================


class _ErroComChave(Exception):
    status_code = 401


def _falha_em(n):
    chamadas = []

    def chamar(msgs):
        chamadas.append(1)
        if len(chamadas) == n:
            raise _ErroComChave(f"Authentication Fails, Your api key: {CHAVE_FALSA} is invalid")
        return _resposta()

    return chamar


def problemas_vazamento(mod, tmp_path) -> list[str]:
    itens = me.carregar_conjunto()[:3]
    logs = []
    p = []
    try:
        mod.executar_rodada(itens, "r1", 0.05, chamar=_falha_em(1), modelo="deepseek-flash",
                            diretorio=tmp_path, log=logs.append, versao=FLASH)
        p.append("a falha inicial nao levantou")
    except mod.FalhaInicial as exc:
        logs.append(str(exc))
    t = mod.executar_rodada(itens, "r1", 0.05, chamar=_falha_em(2), modelo="deepseek-flash",
                            diretorio=tmp_path, log=logs.append, versao=FLASH)
    if t["estado"] != me.ESTADO_INFRA:
        p.append(f"infra virou {t['estado']}")
    arquivos = "".join(x.read_text(encoding="utf-8") for x in tmp_path.iterdir())
    if any(CHAVE_FALSA in x for x in logs) or CHAVE_FALSA in arquivos:
        p.append("a chave apareceu no log ou nos arquivos")
    if not any("_ErroComChave (HTTP 401)" in x for x in logs):
        p.append("o log nao diz o tipo e o status")
    return p


def test_chave_nunca_aparece_na_2_3(tmp_path):
    assert problemas_vazamento(me, tmp_path) == []
    # as versoes antigas nao mudaram: a mensagem continua como antes
    assert "Your api key" in me.detalhe_do_erro(_ErroComChave("Your api key: x"), "v3")


def test_mutante_que_vaza_a_chave_e_pego(tmp_path, monkeypatch):
    mod = _modulo_mutante(monkeypatch, me, '        return type(exc).__name__ + (f" (HTTP {status})"',
                          '        return f"{type(exc).__name__}: {exc}" + (f" (HTTP {status})"')
    assert problemas_vazamento(mod, tmp_path)


# =============================================================================
# o resultado.json + recalculo (o que a trava da Parte 3 le)
# =============================================================================


def _gravar_rodadas(d, rodadas=None, provedor="deepseek", hashes=None):
    rodadas = rodadas or {"r1": _base(), "r2": _base()}
    d.mkdir(parents=True, exist_ok=True)
    tentativas = []
    for r, respostas in rodadas.items():
        nome = f"extracao-{r}-t1.json"
        (d / nome).write_text(json.dumps({
            "rodada": r, "config": {"modelo": "deepseek-flash", "provedor": provedor},
            "hashes": hashes or me.PRE_REGISTRO_V3_FLASH, "respostas": respostas}), encoding="utf-8")
        tentativas.append({"rodada": r, "n": 1, "estado": me.ESTADO_CONCLUIDA, "arquivo": nome, "custo_usd": 0.03})
    me.gravar_registro(tentativas, d)


def problemas_veredito(mod, tmp_path, monkeypatch) -> list[str]:
    d = tmp_path / "v3-flash"
    monkeypatch.setattr(mod, "DIR_MEDICAO_V3_FLASH", d)
    p = []
    if mod.veredito_v3_flash()[0] is not None:
        p.append("sem resultado nao deu None")
    _gravar_rodadas(d)
    if mod.main(["--versao", FLASH, "--resultado"]) != 0 or mod.veredito_v3_flash()[0] is not True:
        p.append("o --resultado de rodadas certas nao liberou")
    (d / mod.NOME_RESULTADO).write_text(json.dumps({"passa": False}), encoding="utf-8")
    if mod.veredito_v3_flash()[0] is not None:
        p.append("resultado.json editado foi aceito")
    _gravar_rodadas(d, provedor="openrouter")
    mod.main(["--versao", FLASH, "--resultado"])
    if mod.veredito_v3_flash()[0] is not False:
        p.append("rodadas sem o motor deepseek passaram")
    _gravar_rodadas(d, hashes=me.PRE_REGISTRO_V3)  # sem o hash do motor
    mod.main(["--versao", FLASH, "--resultado"])
    if mod.veredito_v3_flash()[0] is not False:
        p.append("rodadas com os hashes da Parte 2.2 passaram")
    rodadas = {"r1": _base(), "r2": _mudar(_base(), "t01", valor="-4")}
    _gravar_rodadas(d, rodadas)
    mod.main(["--versao", FLASH, "--resultado"])
    if mod.veredito_v3_flash()[0] is not False:
        p.append("o b) reprovado na r2 passou")
    return p


def test_resultado_e_veredito_da_2_3(tmp_path, monkeypatch, capsys):
    assert problemas_veredito(me, tmp_path, monkeypatch) == []


MUTANTES_VEREDITO = {
    "aceita o resultado.json sem recalcular": (
        '    if gravado.get("passa") is not res["passa"]:\n        return None, "o resultado.json da Parte 2.3',
        '    if False:\n        return None, "o resultado.json da Parte 2.3'),
    "nao confere o motor": ('    if versao == VERSAO_FLASH and (dados.get("config") or {}).get("provedor") != PROVEDOR_FLASH:',
                            "    if False:"),
}


@pytest.mark.parametrize("mutante", MUTANTES_VEREDITO)
def test_mutante_do_veredito_e_pego(tmp_path, monkeypatch, capsys, mutante):
    mod = _modulo_mutante(monkeypatch, me, *MUTANTES_VEREDITO[mutante])
    assert problemas_veredito(mod, tmp_path, monkeypatch), f"mutante {mutante!r} passou"


def test_plano_da_2_3_e_gratis(tmp_path, monkeypatch, capsys, chave):
    monkeypatch.setattr(me, "DIR_MEDICAO_V3_FLASH", tmp_path / "v3-flash")
    monkeypatch.setattr(llm_motor, "chamar_ficha", lambda cfg: pytest.fail("o plano chamou o LLM"))
    assert me.main(["--versao", FLASH]) == 0
    out = capsys.readouterr().out
    assert "Parte 2.3" in out and "deepseek-flash" in out and "SO INFORMACAO" in out
    assert "--versao v3-flash --executar --rodada r1 --orcamento 0.06" in out
    assert CHAVE_FALSA not in out and not (tmp_path / "v3-flash").exists()
    assert copy.deepcopy(me.PRE_REGISTRO_V3_FLASH) == me.hashes_atuais(versao=FLASH)
