"""Parte 3: o script de medicao (orchestrator.rag.parte3), sem rede e sem LLM.

- C: o sha256 e conferido ANTES de ler (hash errado recusa); nenhuma pergunta aparece no
  terminal em caminho nenhum (plano, hash errado, formato errado, executar com responder
  falso, classificar, resultado), provado com um marcador unico em cada pergunta; a saida
  da C nao pode ficar dentro do repo;
- criterios de A, B e C e a integridade por rodada (v1 com nota [limite], v5 com a flag
  desligada, falha do passo = infra);
- registro: ordem da B, uma repeticao por infra, orcamento sem repeticao.
"""

import copy
import hashlib
import json

import pytest
import yaml

from orchestrator.config import settings
from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import medir_extracao as me
from orchestrator.rag import missao9 as m9
from orchestrator.rag import missao10 as m10
from orchestrator.rag import parte3 as p3

MARCADOR = "MARCADOR-LACRE-7f3a"
PERGUNTAS_FALSAS = [f"{MARCADOR} pergunta {i}: o iogurte chegou a {i} graus, aceito?" for i in range(1, 6)] + [
    f"{MARCADOR} pergunta {i}: cliente quer trocar um produto comprado ha {i} dias, pode?" for i in range(6, 11)]


@pytest.fixture(autouse=True)
def chave_deepseek_falsa(monkeypatch):
    """Emenda de 24/11: o --executar exige a chave do motor da medicao (DeepSeek direto).
    Valor FALSO (rede bloqueada e LLM falso de qualquer jeito)."""
    from hermetic_support import FAKE_SECRET
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr(FAKE_SECRET))


def _prova_falsa(tmp_path, itens=None, texto=None):
    d = tmp_path / "lacre"
    d.mkdir(exist_ok=True)
    caminho = d / "prova-falsa.yaml"
    if texto is None:
        itens = itens if itens is not None else [
            {"id": f"x{i}", "pergunta": q, "resposta_esperada": "Sim." if i % 2 else "Não."}
            for i, q in enumerate(PERGUNTAS_FALSAS, 1)]
        texto = yaml.safe_dump({"perguntas": itens}, allow_unicode=True)
    caminho.write_text(texto, encoding="utf-8")
    return caminho, hashlib.sha256(caminho.read_bytes()).hexdigest()


def _sem_marcador(capsys):
    saida = capsys.readouterr()
    assert MARCADOR not in saida.out and MARCADOR not in saida.err
    return saida


# =============================================================================
# C: hash, formato e sigilo
# =============================================================================


@pytest.fixture
def ordem_liberada(monkeypatch):
    """A e B "aprovadas" (falso): estes testes sao da C em si; a trava tem testes proprios."""
    monkeypatch.setattr(p3, "veredito", lambda m: (True, f"{m.upper()} PASSA (falso)"))


@pytest.mark.usefixtures("ordem_liberada")
def test_c_recusa_hash_errado_antes_de_ler(tmp_path, monkeypatch, capsys):
    caminho, _ = _prova_falsa(tmp_path)
    lidos = []
    with monkeypatch.context() as m:
        m.setattr(p3.yaml, "safe_load", lambda *a, **k: lidos.append(1))
        with pytest.raises(p3.ProvaRecusada, match="sha256"):
            p3.carregar_prova(caminho)  # o hash pre-registrado e o da prova10 real, nao o da falsa
    assert lidos == []  # o YAML nem foi interpretado
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-falsa")
    monkeypatch.setattr(av, "_aviso_tracing", lambda: False)
    assert p3.main(["--executar", "c", "--prova", str(caminho), "--orcamento", "0.12"]) == 2
    saida = _sem_marcador(capsys)
    assert "RECUSADO" in saida.out and "sha256" in saida.out
    assert not (caminho.parent / p3.NOME_DIR_C).exists()


@pytest.mark.parametrize("texto", [
    f"perguntas: [{MARCADOR} : : ]\n  - {{",                       # YAML quebrado (o erro do yaml cita a linha)
    yaml.safe_dump({f"{MARCADOR} chave": "valor"}),                  # pergunta como CHAVE (nunca imprimir chaves)
    yaml.safe_dump({"perguntas": [{"texto": f"{MARCADOR} sem campo pergunta"}] * 10}),
    yaml.safe_dump({"perguntas": [{"pergunta": f"{MARCADOR} so uma"}]}),
])
def test_c_formato_errado_recusa_sem_mostrar_conteudo(tmp_path, monkeypatch, capsys, texto, ordem_liberada):
    caminho, h = _prova_falsa(tmp_path, texto=texto)
    monkeypatch.setattr(p3, "HASH_PROVA10", h)
    with pytest.raises(p3.ProvaRecusada) as exc:
        p3.carregar_prova(caminho)
    assert MARCADOR not in str(exc.value)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-falsa")
    monkeypatch.setattr(av, "_aviso_tracing", lambda: False)
    assert p3.main(["--executar", "c", "--prova", str(caminho), "--orcamento", "0.12"]) == 2
    _sem_marcador(capsys)


MUTANTES_QUE_VAZAM = {
    "log com a pergunta": (
        "            log(f\"[{idx:02d}/{total:02d}] {qid} a{passo['amostra']:02d} {v}: US$ {custo:.4f}  {duracao:.1f}s\"\n",
        "            log(f\"[{idx:02d}/{total:02d}] {itens[qid]['pergunta']} {v}: US$ {custo:.4f}  {duracao:.1f}s\"\n",
    ),
    "erro do yaml repassado": (
        '        raise ProvaRecusada(f"a prova nao e YAML legivel ({type(exc).__name__})") from None\n',
        '        raise ProvaRecusada(f"a prova nao e YAML legivel ({exc})") from None\n',
    ),
}


def _vazou(mod, tmp_path, monkeypatch) -> bool:
    """Roda a coleta (log) e o YAML quebrado no modulo; vazou o marcador?"""
    import asyncio

    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    logs = []
    itens = {f"p{i:02d}": {"id": f"p{i:02d}", "tipo": "prova10", "pergunta": q}
             for i, q in enumerate(PERGUNTAS_FALSAS, 1)}
    asyncio.run(mod.coletar(mod.passos_c()[:2], itens, orcamento=0.12, experimento="t",
                            graph_factory=lambda cp: None, responder=_responder_falso(), log=logs.append))
    caminho, h = _prova_falsa(tmp_path, texto=f"perguntas: [{MARCADOR} : : ]\n  - {{")
    try:
        mod.carregar_prova(caminho, hash_esperado=h)
    except mod.ProvaRecusada as exc:
        logs.append(str(exc))
    return any(MARCADOR in x for x in logs)


def test_sigilo_da_coleta_e_do_yaml(tmp_path, monkeypatch):
    assert not _vazou(p3, tmp_path, monkeypatch)


@pytest.mark.parametrize("mutante", MUTANTES_QUE_VAZAM)
def test_mutante_que_vaza_e_pego(tmp_path, monkeypatch, mutante):
    from test_rag_limites_agente import _modulo_mutante

    mod = _modulo_mutante(monkeypatch, p3, *MUTANTES_QUE_VAZAM[mutante])
    assert _vazou(mod, tmp_path, monkeypatch), f"mutante {mutante!r} passou"


def test_c_saida_dentro_do_repo_e_recusada(tmp_path):
    caminho, _ = _prova_falsa(tmp_path)
    with pytest.raises(p3.ProvaRecusada, match="repositorio"):
        p3.diretorio_c(caminho, p3.DIR_PARTE3 / "c")
    assert p3.diretorio_c(caminho) == (caminho.parent / p3.NOME_DIR_C).resolve()


@pytest.mark.usefixtures("ordem_liberada")
def test_c_recusa_com_tracing_ligado(tmp_path, monkeypatch, capsys):
    caminho, h = _prova_falsa(tmp_path)
    monkeypatch.setattr(p3, "HASH_PROVA10", h)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-falsa")
    monkeypatch.setattr(av, "_aviso_tracing", lambda: True)
    assert p3.main(["--executar", "c", "--prova", str(caminho), "--orcamento", "0.12"]) == 2
    assert "tracing" in _sem_marcador(capsys).out


def _responder_falso(falhar_em=None, resposta="Recuse (POP-01).", ecoa_pergunta=True):
    """O que o av.responder_pergunta devolve, sem grafo nem LLM. A v5 ganha a nota [limite]."""
    chamadas = []

    async def responder(graph, item):
        chamadas.append(item["id"])
        n = len(chamadas)
        nota = ["[limite] RECUSAR: −10 °C está ACIMA de −12 °C"] if settings.rag_limites else []
        texto = f"{resposta} {item['pergunta'] if ecoa_pergunta else ''}"
        return {"id": item["id"], "tipo": item.get("tipo"), "pergunta": item["pergunta"],
                "caminho": ["supervisor", "specialist_rag", "supervisor", "synthesize_final"],
                "rag_acionado": True, "trechos": [], "notas_de_outros_especialistas": nota,
                "resposta_crua": texto, "resposta_final": texto, "erro": None,
                "erros_llm": [{"erro_tipo": "APITimeoutError"}] if n == falhar_em else [],
                "falha_de_infra": n == falhar_em,
                # `cost` (OpenRouter) + as contagens da DeepSeek (motor da medicao desde a
                # emenda de 24/11): 2000 x 0,30 + 300 x 1,20 por 1M = US$ 0,00096
                "chamadas_llm": [{"no": "synthesize_final", "token_usage": {
                    "cost": 0.001, "prompt_tokens": 2000, "completion_tokens": 300,
                    "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 2000}}]}

    responder.chamadas = chamadas
    return responder


@pytest.fixture
def ambiente_c(tmp_path, monkeypatch, ordem_liberada):
    caminho, h = _prova_falsa(tmp_path)
    monkeypatch.setattr(p3, "HASH_PROVA10", h)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-falsa")
    indice = tmp_path / "indice.sqlite"
    indice.write_bytes(b"x")
    monkeypatch.setattr(settings, "rag_index_path", str(indice))
    monkeypatch.setattr(av, "_aviso_tracing", lambda: False)
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: {"indice": "falso"})
    monkeypatch.setattr(m9, "indice_meta_m8", lambda: {"indice": "falso"})
    monkeypatch.setattr(av, "responder_pergunta", _responder_falso())
    return caminho


def test_c_ponta_a_ponta_sem_imprimir_perguntas(ambiente_c, capsys):
    prova = ["--prova", str(ambiente_c)]
    assert p3.main([]) == 0  # plano: nao abre a prova
    assert p3.main(["--executar", "c", *prova, "--orcamento", "0.12"]) == 0
    assert p3.main(["--classificar", "c", *prova]) == 0
    d = ambiente_c.parent / p3.NOME_DIR_C
    cego = yaml.safe_load((d / "classificacao-cega.yaml").read_text(encoding="utf-8"))
    assert len(cego["itens"]) == 40 and MARCADOR in cego["itens"][0]["pergunta"]  # so no arquivo, fora do repo
    assert all("gabarito" in it and "pergunta" not in it["gabarito"] for it in cego["itens"])
    assert not any(k in json.dumps(cego) for k in ("v1", "v5", "rag_limites"))
    for it in cego["itens"]:
        it["classe"] = "CERTA"
    (d / "classificacao-cega.yaml").write_text(yaml.safe_dump(cego, allow_unicode=True), encoding="utf-8")
    assert p3.main(["--resultado", "c", *prova]) == 0
    saida = _sem_marcador(capsys)
    assert "Perguntas de temperatura (pelo código): 5 de 10" in saida.out
    assert "**C PASSA.**" in saida.out
    assert json.loads((d / "registro.json").read_text())["tentativas"][0]["estado"] == me.ESTADO_CONCLUIDA


def test_c_falha_de_infra_para_sem_imprimir_perguntas(ambiente_c, monkeypatch, capsys):
    monkeypatch.setattr(av, "responder_pergunta", _responder_falso(falhar_em=3))
    assert p3.main(["--executar", "c", "--prova", str(ambiente_c), "--orcamento", "0.12"]) == 1
    saida = _sem_marcador(capsys)
    assert "INFRA (APITimeoutError)" in saida.out
    (t,) = json.loads((ambiente_c.parent / p3.NOME_DIR_C / "registro.json").read_text())["tentativas"]
    assert t["estado"] == me.ESTADO_INFRA


# =============================================================================
# coleta: infra, falha inicial, falha do passo e a versao de cada resposta
# =============================================================================


def _coletar(responder, passos=None):
    import asyncio

    passos = passos or p3.passos_a()
    itens = {"q02": {"id": "q02", "tipo": "direta", "pergunta": "chegou frango congelado a -10 graus, aceito?"}}
    with p3.com_motor():  # emenda de 24/11: a coleta valida e com o motor da medicao
        return asyncio.run(p3.coletar(passos, itens, orcamento=0.06, experimento="teste",
                                      graph_factory=lambda cp: None, responder=responder, log=lambda _: None))


def test_coleta_intercala_e_grava_a_versao_de_cada_resposta(monkeypatch):
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    dados = _coletar(_responder_falso())
    assert [r["versao"] for r in dados["respostas"][:4]] == ["v1", "v5", "v1", "v5"]
    assert {r["rag_limites"] for r in dados["respostas"] if r["versao"] == "v5"} == {True}
    assert {r["regras_sha256"] for r in dados["respostas"] if r["versao"] == "v5"} == {p3.HASH_REGRAS_V5}
    assert settings.rag_limites is False and settings.rag_regras_versao == "v1"  # restaurado


def test_coleta_falha_inicial_e_infra_depois(monkeypatch):
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    with pytest.raises(av.FalhaInicial):
        _coletar(_responder_falso(falhar_em=1))
    dados = _coletar(_responder_falso(falhar_em=4))
    assert len(dados["respostas"]) == 4 and dados["abortado_por_infra"]["erro_tipo"] == "APITimeoutError"
    assert p3.estado_da_coleta(dados) == me.ESTADO_INFRA


def test_falha_do_passo_de_limites_conta_como_infra(monkeypatch):
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    base = _responder_falso()

    async def responder(graph, item):
        r = await base(graph, item)
        if settings.rag_limites:
            r["notas_de_outros_especialistas"] = [
                "[limite] NÃO VERIFICÁVEL: a verificação da temperatura falhou agora (RuntimeError). ..."]
        return r

    dados = _coletar(responder)
    assert dados["abortado_por_infra"]["erro_tipo"] == "passo_de_limites"


# =============================================================================
# criterios: A e C (dados montados) e B (rodadas da Missao 10 reaproveitadas)
# =============================================================================


def _a_classificada(monkeypatch, classes_v5=None):
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    dados = _coletar(_responder_falso())
    yaml_cego, mapa = p3.gerar_cego(dados["respostas"], p3.CABECALHO_A)
    cego = yaml.safe_load(yaml_cego)
    for it in cego["itens"]:
        v = mapa["mapa"][it["codigo"]]["versao"]
        it["classe"] = (classes_v5 or {}).get(mapa["mapa"][it["codigo"]]["amostra"], "RECUSA") if v == "v5" else "ACEITA"
    return dados, cego, mapa


def test_a_passa_com_v5_sem_erro_e_falha_com_um_erro(monkeypatch):
    dados, cego, mapa = _a_classificada(monkeypatch)
    res = p3.resultado_a(dados, cego, mapa)
    assert res["valido"] and res["passa"] and res["erros"] == {"v1": 10, "v5": 0}
    dados, cego, mapa = _a_classificada(monkeypatch, {3: "AMBÍGUA"})
    assert not p3.resultado_a(dados, cego, mapa)["passa"]


@pytest.mark.parametrize("estrago", ["nota_na_v1", "v5_sem_flag", "regras_trocadas", "mapa_de_outra_coleta"])
def test_a_integridade_invalida(monkeypatch, estrago):
    dados, cego, mapa = _a_classificada(monkeypatch)
    v1 = next(r for r in dados["respostas"] if r["versao"] == "v1")
    v5 = next(r for r in dados["respostas"] if r["versao"] == "v5")
    if estrago == "nota_na_v1":
        v1["notas_de_outros_especialistas"] = ["[limite] RECUSAR: ..."]
    elif estrago == "v5_sem_flag":
        v5["rag_limites"] = False
    elif estrago == "regras_trocadas":
        v5["regras_sha256"] = p3.HASH_REGRAS_V1
    else:
        dados = copy.deepcopy(dados)
        dados["respostas"][0]["resposta_crua"] += " (outra)"
    if estrago != "mapa_de_outra_coleta":
        mapa["respostas_sha256"] = p3._sha_das_respostas(dados["respostas"])
    res = p3.resultado_a(dados, cego, mapa)
    assert not res["valido"] and not res["passa"]


def _c_classificada(monkeypatch, classe):
    monkeypatch.setattr(av, "_meta_do_indice", lambda s: None)
    passos = p3.passos_c()
    itens = {f"p{i:02d}": {"id": f"p{i:02d}", "tipo": "prova10", "pergunta": q}
             for i, q in enumerate(PERGUNTAS_FALSAS, 1)}
    import asyncio

    with p3.com_motor():
        dados = asyncio.run(p3.coletar(passos, itens, orcamento=0.12, experimento="t", graph_factory=lambda cp: None,
                                       responder=_responder_falso(), log=lambda _: None))
    yaml_cego, mapa = p3.gerar_cego(dados["respostas"], p3.CABECALHO_C, {k: {} for k in itens})
    cego = yaml.safe_load(yaml_cego)
    for it in cego["itens"]:
        m = mapa["mapa"][it["codigo"]]
        it["classe"] = classe(m["versao"], m["pergunta_id"])
    temperatura = [f"p{i:02d}" for i in range(1, 6)]
    return p3.resultado_c(dados, cego, mapa, temperatura)


def test_c_criterios(monkeypatch):
    certa = _c_classificada(monkeypatch, lambda v, q: "CERTA")
    assert certa["passa"]
    pede = _c_classificada(monkeypatch, lambda v, q: "pergunta/não verifica" if v == "v5" else "CERTA")
    assert pede["passa"]  # pergunta/nao verifica nao e erro
    temp = _c_classificada(monkeypatch, lambda v, q: "ERRADA" if (v, q) == ("v5", "p02") else "CERTA")
    assert not temp["criterios"]["temperatura_zero_erradas_v5"] and not temp["passa"]
    demais = _c_classificada(monkeypatch, lambda v, q: "ERRADA" if (v, q) == ("v5", "p07") else "CERTA")
    assert temp["criterios"]["demais_v5_nao_erra_mais"] and not demais["criterios"]["demais_v5_nao_erra_mais"]


def test_classe_c_invalida_ou_pendente_recusa(monkeypatch):
    with pytest.raises(ValueError, match="classe invalida"):
        _c_classificada(monkeypatch, lambda v, q: "talvez")
    with pytest.raises(ValueError, match="incompleta"):
        _c_classificada(monkeypatch, lambda v, q: None)


def _rodadas_b():
    """As rodadas v1 da Missao 10 (respostas + juiz reais), vestidas de v1 e de v5 da Parte 3."""
    rodadas = {}
    for v, r in p3.ORDEM_B:
        pr, pj = m10.caminhos("v1", r)
        resp = json.loads(pr.read_text(encoding="utf-8"))
        julg = json.loads(pj.read_text(encoding="utf-8"))
        resp["config"]["rag_regras_versao"] = v
        resp["hashes"]["regras_do_manual"] = p3.HASH_REGRAS[v]
        resp["parte3"] = {"versao": v, "rag_limites": v == "v5", "hashes": p3._hashes_parte3()}
        for x in resp["perguntas"]:  # emenda de 24/11: o motor da medicao em cada resposta
            x["provedor"] = p3.PROVEDOR_DA_MEDICAO
        rodadas[(v, r)] = (resp, julg)
    return rodadas


def _refazer_hash(rodadas):
    for resp, julg in rodadas.values():
        julg["hashes"]["respostas"] = av.sha256_texto(json.dumps(resp, sort_keys=True, ensure_ascii=False))
    return rodadas


def _comparar(rodadas):
    return p3.comparar_b(_refazer_hash(rodadas), av.carregar_gabarito(), av.carregar_fatos(), av.carregar_formato(),
                         m9.indice_meta_m8())


def test_b_mesmas_respostas_nao_caem():
    c = _comparar(_rodadas_b())
    assert c["valido"], c["problemas"]
    assert all(c["criterios"]["b_sem_queda"].values())
    assert c["passa"] == (not c["violacoes_v5"])


def test_b_sim_nao_contraditorio_na_v5_reprova():
    rodadas = _rodadas_b()
    resp, _ = rodadas[("v5", "r1")]
    q02 = next(x for x in resp["perguntas"] if x["id"] == "q02")
    q02["resposta_crua"] = "Sim, pode aceitar."
    c = _comparar(rodadas)
    assert not c["criterios"]["c_sem_sim_nao_contraditorio_v5"] and not c["passa"]


@pytest.mark.parametrize("estrago", ["nota_na_v1", "v5_sem_flag", "regras_trocadas", "juiz_na_crua"])
def test_b_integridade_invalida(estrago):
    rodadas = _rodadas_b()
    if estrago == "nota_na_v1":
        rodadas[("v1", "r2")][0]["perguntas"][0]["notas_de_outros_especialistas"] = ["[limite] ACEITAR: ..."]
    elif estrago == "v5_sem_flag":
        rodadas[("v5", "r2")][0]["parte3"]["rag_limites"] = False
    elif estrago == "regras_trocadas":
        rodadas[("v5", "r1")][0]["hashes"]["regras_do_manual"] = p3.HASH_REGRAS_V1
    else:
        rodadas[("v1", "r1")][1]["alvo"] = "resposta_crua"
    c = _comparar(rodadas)
    assert not c["valido"] and not c["passa"]


# =============================================================================
# registro, orcamento, CLI e plano
# =============================================================================


def _t(unidade, estado):
    return {"unidade": unidade, "estado": estado, "custo_usd": 0.01, "orcamento_usd": 0.06}


def test_registro_ordem_repeticao_e_orcamento():
    ok = me.ESTADO_CONCLUIDA
    assert p3.pode_executar([], "b", "v1-r1")[0]
    assert not p3.pode_executar([], "b", "v5-r1")[0]  # ordem intercalada
    assert p3.pode_executar([_t("v1-r1", ok)], "b", "v5-r1")[0]
    assert not p3.pode_executar([], "b", "juiz-v1-r1")[0]  # juiz so depois das respostas
    assert p3.pode_executar([_t("a", me.ESTADO_INFRA)], "a", "a")[0]  # uma repeticao
    assert not p3.pode_executar([_t("a", me.ESTADO_INFRA)] * 2, "a", "a")[0]
    assert not p3.pode_executar([_t("a", me.ESTADO_ORCAMENTO)], "a", "a")[0]
    assert not p3.pode_executar([_t("a", me.ESTADO_FALHA_INICIAL)] * 2, "a", "a")[0]
    assert not p3.pode_executar([_t("a", ok)], "a", "a")[0]
    with pytest.raises(ValueError):
        p3.validar_orcamento(0.07, "a", "a", [])
    with pytest.raises(ValueError, match="resta"):
        p3.validar_orcamento(0.06, "a", "a", [_t("a", me.ESTADO_INFRA)] * 7)


@pytest.mark.parametrize("argv", [
    ["--executar", "c", "--orcamento", "0.1"],                 # C sem --prova
    ["--executar", "b", "--orcamento", "0.06"],                 # B sem --versao/--rodada
    ["--executar", "a"],                                        # pago sem --orcamento
    ["--resultado", "a", "--orcamento", "0.1"],                 # gratis com --orcamento
    ["--classificar", "a", "--prova", "x"],                     # --prova fora da C
])
def test_cli_recusa_combinacoes(argv):
    with pytest.raises(SystemExit):
        p3.parse_args(argv)


def test_cli_aceita_todos_os_comandos_do_plano():
    """Cada comando que o plano imprime passa no parse_args (pegou o --executar b recusado)."""
    import shlex

    for chave, cmds in p3.comandos().items():
        for cmd in cmds:
            if chave == "2.3":  # a Parte 2.3 roda pelo medir_extracao
                me.parse_args(shlex.split(cmd.split("orchestrator.rag.medir_extracao", 1)[1]))
                continue
            argv = shlex.split(cmd.split("orchestrator.rag.parte3", 1)[1])
            p3.parse_args(argv)


def test_plano_e_gratis_e_nao_abre_a_prova(monkeypatch, capsys):
    monkeypatch.setattr(p3, "carregar_prova", lambda *a, **k: pytest.fail("o plano abriu a prova"))
    monkeypatch.setattr(av, "responder_pergunta", lambda *a, **k: pytest.fail("o plano rodou o grafo"))
    assert p3.main([]) == 0
    saida = capsys.readouterr().out
    assert "NADA executado" in saida and "pre-registro: OK" in saida
    assert "pre-filtro B: o codigo chama a ficha em q02 (das 20)" in saida


def test_estimativa_sobre_as_fichas_da_parte22():
    """Congela a estimativa do pre-registro (dados ja vistos; NAO e medicao)."""
    est = p3.estimativa_notas()
    assert set(est) == {"r1", "r2"}
    for r, x in est.items():
        assert x["achados"] == ["i06: nota nao_verificavel numa pergunta com aplica=false esperado"], r
        assert x["por_id"]["i10"] == "nao_verificavel"
        assert [k for k, v in x["por_id"].items() if k.startswith("t") and v != "decisao"] == ["t07", "t33", "t41"]
        assert all(v == "sem chamada" for k, v in x["por_id"].items() if k.startswith("f"))
    assert (est["r1"]["por_id"]["i04"], est["r2"]["por_id"]["i04"]) == ("nao_verificavel", "decisao")


def test_conferir_sistema_pega_regras_ou_codigo_mudados(monkeypatch):
    assert p3.conferir_sistema(settings) == []
    monkeypatch.setattr(p3, "HASH_CODIGO_PASSO", "0" * 64)
    assert any("rag_limites.py" in x for x in p3.conferir_sistema(settings))
    monkeypatch.setattr(p3, "HASH_REGRAS", {**p3.HASH_REGRAS, "v5": "0" * 64})
    assert any("regras v5" in x for x in p3.conferir_sistema(settings))


# =============================================================================
# trava da ordem A -> B -> C (emenda de 24/11/2026, antes de qualquer medicao)
# =============================================================================


def _vereditos(**estado):
    def veredito(m):
        x = estado.get(m)
        return x, f"{m.upper()} {'sem resultado' if x is None else 'PASSA' if x else 'NAO PASSA'}"

    return veredito


CENARIOS_DA_TRAVA = [
    ("a", {}, "depois da Parte 2.3"),                # A sem a 2.3 (decisao de 24/11)
    ("a", {"2.3": False}, "Parte 2.3 reprovou"),
    ("a", {"2.3": True}, None),
    ("b", {}, "depois de A aprovada"),               # B sem A
    ("b", {"a": False}, "A reprovou"),
    ("b", {"a": True}, None),
    ("c", {"a": True}, "depois de B aprovada"),      # C sem B
    ("c", {}, "depois de A aprovada"),
    ("c", {"a": False, "b": True}, "A reprovou"),    # C com A reprovado
    ("c", {"a": True, "b": False}, "B reprovou"),    # C com B reprovado
    ("c", {"a": True, "b": True}, None),
]


def problemas_trava(mod) -> list[str]:
    erros = []
    for medicao, estado, esperado in CENARIOS_DA_TRAVA:
        motivo = mod.trava_da_ordem(medicao, _vereditos(**estado))
        if esperado is None and motivo is not None:
            erros.append(f"{medicao} {estado}: recusou ({motivo})")
        elif esperado is not None and (motivo is None or esperado not in motivo):
            erros.append(f"{medicao} {estado}: esperado {esperado!r}, veio {motivo!r}")
        if medicao == "c" and esperado and "reprovou" in esperado and motivo \
                and "prova lacrada continua intacta" not in motivo:
            erros.append(f"c {estado}: a recusa nao diz que a prova continua intacta")
    return erros


MUTANTES_TRAVA = {
    "A sem 2.3": ('PRE_REQUISITOS = {"a": ("2.3",), "b": ("a",), "c": ("a", "b")}\n',
                  'PRE_REQUISITOS = {"a": (), "b": ("a",), "c": ("a", "b")}\n'),
    "A com 2.3 reprovada": ("            if not passa:\n                return f\"Parte 2.3 reprovou",
                            "            if False:\n                return f\"Parte 2.3 reprovou"),
    "B sem A": ('PRE_REQUISITOS = {"a": ("2.3",), "b": ("a",), "c": ("a", "b")}\n',
                'PRE_REQUISITOS = {"a": ("2.3",), "b": (), "c": ("a", "b")}\n'),
    "C sem B": ('PRE_REQUISITOS = {"a": ("2.3",), "b": ("a",), "c": ("a", "b")}\n',
                'PRE_REQUISITOS = {"a": ("2.3",), "b": ("a",), "c": ("a",)}\n'),
    "C com A ou B reprovado": ("        if not passa:\n            fim", "        if False:\n            fim"),
}


def test_trava_da_ordem():
    assert problemas_trava(p3) == []


@pytest.mark.parametrize("mutante", MUTANTES_TRAVA)
def test_mutante_da_trava_e_pego(monkeypatch, mutante):
    from test_rag_limites_agente import _modulo_mutante

    mod = _modulo_mutante(monkeypatch, p3, *MUTANTES_TRAVA[mutante])
    assert problemas_trava(mod), f"mutante {mutante!r} passou"


def _gravar_a(classes_v5=None, monkeypatch=None):
    dados, cego, mapa = _a_classificada(monkeypatch, classes_v5)
    p3.DIR_A.mkdir(parents=True, exist_ok=True)
    (p3.DIR_A / "respostas-a-t1.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    me.gravar_registro([{"unidade": "a", "n": 1, "estado": me.ESTADO_CONCLUIDA, "arquivo": "respostas-a-t1.json",
                         "orcamento_usd": 0.06, "custo_usd": dados["custo_usd"]}], p3.DIR_A)
    (p3.DIR_A / "classificacao-cega.yaml").write_text(yaml.safe_dump(cego, allow_unicode=True), encoding="utf-8")
    (p3.DIR_A / "mapa-cego.json").write_text(json.dumps(mapa), encoding="utf-8")


def test_trava_com_os_arquivos_reais_do_resultado(tmp_path, monkeypatch, capsys):
    """O veredito real: exige o resultado.json do --resultado E recalcula das entradas."""
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(p3, "DIR_B", tmp_path / "b")
    monkeypatch.setattr(m9, "indice_meta_m8", lambda: None)
    caminho, _ = _prova_falsa(tmp_path)
    monkeypatch.setattr(p3, "carregar_prova", lambda *a, **k: pytest.fail("a C leu a prova com a ordem travada"))
    executar_c = ["--executar", "c", "--prova", str(caminho), "--orcamento", "0.12"]

    assert "falta o --resultado a" in p3.trava_da_ordem("b")
    _gravar_a(monkeypatch=monkeypatch)
    assert "falta o --resultado a" in p3.trava_da_ordem("b")  # coleta e classes prontas, mas sem --resultado
    assert p3.main(["--resultado", "a"]) == 0
    assert p3.trava_da_ordem("b") is None
    assert "depois de B aprovada" in p3.trava_da_ordem("c")

    (p3.DIR_A / p3.NOME_RESULTADO).write_text(json.dumps({"passa": False}), encoding="utf-8")
    assert "nao bate com as entradas" in p3.trava_da_ordem("b")  # resultado.json editado nao vale

    _gravar_a({3: "AMBÍGUA"}, monkeypatch)
    assert p3.main(["--resultado", "a"]) == 0  # valido, mas NAO PASSA
    assert "A reprovou" in p3.trava_da_ordem("b")
    capsys.readouterr()
    assert p3.main(executar_c) == 2
    saida = capsys.readouterr().out
    assert "RECUSADO: A reprovou" in saida and "prova lacrada continua intacta" in saida
    assert not (caminho.parent / p3.NOME_DIR_C).exists()


def test_executar_b_sem_a_e_recusado_antes_de_qualquer_chamada(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(p3, "DIR_A", tmp_path / "a")
    monkeypatch.setattr(p3, "conferir_sistema", lambda s: pytest.fail("passou da trava"))
    assert p3.main(["--executar", "b", "--versao", "v1", "--rodada", "r1", "--orcamento", "0.06"]) == 2
    assert "RECUSADO: a ordem e A -> B -> C: a B so roda depois de A aprovada (falta o --resultado a)" in \
        capsys.readouterr().out
    assert not (tmp_path / "b").exists()
