"""Missao 9: formato do Max (REGRAS_DO_MANUAL v2 x v1).

Rede bloqueada (conftest), LLM FALSO. O que se prova aqui: a v1 continua byte
a byte igual a da Missao 8 (hash gravado nas respostas de 19/11), a v2 contem
a v1 inteira, o seletor e o synth usam a versao configurada (padrao v1, B-01
mantido), a avaliacao grava a versao/hash efetivos e exige --regras, e a regra
de decisao pre-registrada (a, b, c) com dados SINTETICOS: meio ponto na
media, empate em a), queda de exatamente 1 e de 1,5, Sim/Nao contradizendo o
gabarito, resposta fixa sem LLM fora do c), juiz pendente e integridade.
O que NAO se prova: se o LLM real segue o formato (isso e a execucao paga).
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_rag_avaliar_respostas import (  # noqa: F401
    GABARITO,
    G,
    _citacao,
    _julgamento,
    _llms_falsos,
    _respostas_ideais,
    ambiente_grafo,
)
from test_specialist_rag import _sistema_do_synth

from orchestrator.config import settings
from orchestrator.graph import rag_specialist
from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import juiz
from orchestrator.rag import missao9 as m9

FATOS = av.carregar_fatos()
FMT = av.carregar_formato()
HASH_V1_MISSAO8 = "3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240"
META = {"model_name": "m", "n_chunks": "46", "bm25_stemming": "1", "contextos_sha256": "ctx"}


# --- regras v1 / v2 e seletor ----------------------------------------------------


def test_v1_intacta_igual_a_gravada_na_missao8():
    assert av.sha256_texto(rag_specialist.REGRAS_DO_MANUAL) == HASH_V1_MISSAO8
    gravado = json.loads(m9.RESPOSTAS_M8.read_text(encoding="utf-8"))["hashes"]["regras_do_manual"]
    assert gravado == HASH_V1_MISSAO8
    assert rag_specialist.regras_do_manual("v1") is rag_specialist.REGRAS_DO_MANUAL


def test_v2_contem_a_v1_inteira_e_so_acrescenta_o_formato():
    v2 = rag_specialist.regras_do_manual("v2")
    assert v2.startswith(rag_specialist.REGRAS_DO_MANUAL) and len(v2) > len(rag_specialist.REGRAS_DO_MANUAL)
    extra = v2[len(rag_specialist.REGRAS_DO_MANUAL):]
    for trecho in ('"Sim"', '"Não"', "3 linhas de no maximo 80 caracteres", "LINHA EM BRANCO",
                   "termina em \"?\"", "Quer mais detalhes?", "regra 4", "regra 5"):
        assert trecho in extra, trecho


def test_hashes_pre_registrados_batem_com_o_texto_atual():
    for v in m9.VERSOES:
        assert av.sha256_texto(rag_specialist.regras_do_manual(v)) == m9.HASH_REGRAS_PRE_REGISTRO[v], v
    assert m9.HASH_REGRAS_PRE_REGISTRO["v1"] == HASH_V1_MISSAO8


def test_regras_alteradas_depois_do_pre_registro_invalidam(monkeypatch):
    monkeypatch.setitem(m9.HASH_REGRAS_PRE_REGISTRO, "v2", "outro")
    c = m9.comparar(_base(), GABARITO, FATOS, FMT, META)
    assert not c["valido"] and c["v2_vira_padrao"] is False


def test_seletor_segue_o_settings_e_recusa_versao_desconhecida(monkeypatch):
    assert settings.rag_regras_versao == "v5"  # padrao desde 25/11/2026 (Parte 3)
    assert rag_specialist.regras_do_manual() == rag_specialist.REGRAS_DO_MANUAL_V5
    monkeypatch.setattr(settings, "rag_regras_versao", "v1")
    assert rag_specialist.regras_do_manual() == rag_specialist.REGRAS_DO_MANUAL
    monkeypatch.setattr(settings, "rag_regras_versao", "v2")
    assert rag_specialist.regras_do_manual() == rag_specialist.REGRAS_DO_MANUAL_V2
    with pytest.raises(ValueError):
        rag_specialist.regras_do_manual("v3")


@pytest.mark.parametrize("versao", ["v1", "v2"])
@pytest.mark.parametrize(
    "nota_rag",
    [rag_specialist.nota_trechos([], "bm25"), rag_specialist.nota_indisponivel(FileNotFoundError("x"))],
    ids=["zero-trechos", "erro"],
)
@pytest.mark.asyncio
async def test_synth_usa_a_versao_configurada_e_mantem_o_b01(monkeypatch, versao, nota_rag):
    monkeypatch.setattr(settings, "rag_regras_versao", versao)
    sistema = await _sistema_do_synth([nota_rag, "[n8n] Workflow listado."])
    assert sistema.endswith(rag_specialist.regras_do_manual(versao))
    assert ("6. FORMATO" in sistema) is (versao == "v2")
    assert rag_specialist.FRASE_NAO_COBRE in sistema and "a consulta ao manual falhou" in sistema


@pytest.mark.asyncio
async def test_sem_nota_do_rag_nem_a_v2_entra(monkeypatch):
    monkeypatch.setattr(settings, "rag_regras_versao", "v2")
    assert "REGRAS DO MANUAL" not in await _sistema_do_synth(["[n8n] Workflow listado."])


# --- avaliacao: versao e hash efetivos, --regras obrigatorio ---------------------


@pytest.mark.parametrize("versao", ["v1", "v2"])
@pytest.mark.asyncio
async def test_etapa_respostas_grava_versao_e_hash_das_regras_usadas(ambiente_grafo, monkeypatch, versao):  # noqa: F811
    monkeypatch.setattr(settings, "rag_regras_versao", "v2" if versao == "v1" else "v1")  # como se viesse do .env
    sistemas = []
    original = _llms_falsos(set(), set())

    def fabrica(*a, **k):
        llm = original(*a, **k)
        if k.get("temperature") != 0:
            antigo = llm.ainvoke.side_effect

            async def espiar(msgs, *aa, **kk):
                sistemas.append(msgs[0].content)
                return await antigo(msgs, *aa, **kk)

            llm.ainvoke = AsyncMock(side_effect=espiar)
        return llm

    with patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=fabrica):
        dados = await av.etapa_respostas([G["q12"]], log=lambda *_: None, regras=versao)
    assert dados["config"]["rag_regras_versao"] == versao
    assert dados["hashes"]["regras_versao"] == versao
    assert dados["hashes"]["regras_do_manual"] == av.sha256_texto(rag_specialist.regras_do_manual(versao))
    assert sistemas and all(s.endswith(rag_specialist.regras_do_manual(versao)) for s in sistemas)


@pytest.mark.asyncio
async def test_etapa_respostas_recusa_versao_desconhecida_antes_de_gastar(ambiente_grafo):  # noqa: F811
    with pytest.raises(ValueError):
        await av.etapa_respostas([G["q12"]], log=lambda *_: None, regras="v3",
                                 graph_factory=MagicMock(side_effect=AssertionError("montou o grafo")))


@pytest.mark.parametrize("argv", [
    ["--executar", "--etapa", "respostas"],                     # sem --regras
    ["--regras", "v2"],                                         # --regras sem executar
    ["--executar", "--etapa", "julgar", "--regras", "v2"],      # --regras no juiz
])
def test_cli_regras(argv):
    with pytest.raises(SystemExit):
        av.parse_args(argv)
    assert av.parse_args(["--executar", "--etapa", "respostas", "--regras", "v2"]).regras == "v2"


def test_custo_estimado_por_versao():
    v1 = av.estimar_custo(GABARITO, 5, "deepseek/deepseek-chat", "deepseek/deepseek-chat", regras="v1")
    v2 = av.estimar_custo(GABARITO, 5, "deepseek/deepseek-chat", "deepseek/deepseek-chat", regras="v2")
    assert v2["tokens_por_pergunta"]["synthesize"] > v1["tokens_por_pergunta"]["synthesize"]


def test_plano_nao_gasta_e_orcamento_cabe_no_teto(monkeypatch, capsys):
    monkeypatch.setattr(av, "etapa_respostas", MagicMock(side_effect=AssertionError("executou")))
    monkeypatch.setattr(av, "etapa_julgar", MagicMock(side_effect=AssertionError("julgou")))
    assert m9.main([]) == 0
    saida = capsys.readouterr().out
    assert saida.count("--executar") == 8 and saida.count("--regras v2") == 2
    assert len(m9.ORDEM) * (m9.ORCAMENTO_RESPOSTAS_USD + m9.ORCAMENTO_JUIZ_USD) <= m9.TETO_TOTAL_USD
    cmds = m9.comandos()
    assert [c.split("--regras ")[1][:2] for c in cmds if "--regras" in c] == ["v1", "v2", "v1", "v2"]  # intercalado
    assert all("--saida fixtures/rag/m9/" in c and "--orcamento" in c for c in cmds)
    assert all("--respostas fixtures/rag/m9/" in c for c in cmds if "julgar" in c)


# --- regra de decisao (sintetico) ------------------------------------------------

# Principal curta (60 caracteres), complemento com o texto completo + citacao
# (mantem os fatos-chave), oferta na ultima linha.
_V2_FORMATADA = {
    g["id"]: {"resposta_crua": f"{g['resposta_esperada'][:60]}\n\n{g['resposta_esperada']} {_citacao(g)}"
                               "\n\nQuer mais detalhes?"}
    for g in GABARITO if g["tipo"] in av.COM_FONTE
}


def _rodada(versao: str, sobrescreve: dict | None = None, julg: dict | None = None) -> tuple[dict, dict]:
    resp = _respostas_ideais(**(sobrescreve or {}))
    resp["config"] = {"rag_regras_versao": versao,
                      "indice_meta": dict(META)}
    resp["hashes"] = {"regras_do_manual": av.sha256_texto(rag_specialist.regras_do_manual(versao))}
    j = julg or _julgamento()
    j = {**j, "hashes": {"respostas": av.sha256_texto(json.dumps(resp, sort_keys=True, ensure_ascii=False)),
                         "prompt_fidelidade": juiz.HASH_PROMPT_FIDELIDADE, "prompt_correcao": juiz.HASH_PROMPT_CORRECAO}}
    return resp, j


def _base(**v2) -> dict:
    return {("v1", "r1"): _rodada("v1"), ("v1", "r2"): _rodada("v1"),
            ("v2", "r1"): v2.get("r1", _rodada("v2", _V2_FORMATADA)),
            ("v2", "r2"): v2.get("r2", _rodada("v2", _V2_FORMATADA))}


def test_primeira_palavra_e_gabarito():
    assert m9.primeira_palavra("**Não**, só com F-07.") == "nao"
    assert m9.primeira_palavra("\n- Sim, pode.") == "sim"
    assert m9.primeira_palavra("Simples: ...") is None and m9.primeira_palavra("Segundo o manual, não") is None
    assert m9.esperado_sim_nao(GABARITO, FMT["sim_nao"]) == {"q01": "nao", "q02": "nao", "q04": "nao",
                                                             "q05": "sim", "q10": "nao"}


def test_v2_formatada_vira_padrao():
    c = m9.comparar(_base(), GABARITO, FATOS, FMT, META)
    assert c["valido"], c["problemas"]
    assert c["medias"]["v2"]["g_total"] > c["medias"]["v1"]["g_total"]
    assert c["v2_vira_padrao"] is True
    assert "VIRA" in m9.relatorio(c)


def test_empate_no_formato_reprova_a():
    c = m9.comparar(_base(r1=_rodada("v2"), r2=_rodada("v2")), GABARITO, FATOS, FMT, META)
    assert c["medias"]["v2"]["g_total"] == c["medias"]["v1"]["g_total"]
    assert c["criterios"]["a_formato_v2_maior"] is False and c["v2_vira_padrao"] is False


def test_meio_ponto_de_formato_basta_para_a():
    """Uma rodada da v2 formatada so numa pergunta, a outra sem formato: media +0,5."""
    so_q03 = {"q03": _V2_FORMATADA["q03"]}
    c = m9.comparar(_base(r1=_rodada("v2", so_q03), r2=_rodada("v2")), GABARITO, FATOS, FMT, META)
    assert c["medias"]["v2"]["g_total"] - c["medias"]["v1"]["g_total"] == pytest.approx(0.5)
    assert c["criterios"]["a_formato_v2_maior"] is True


def _sem_grave(ids) -> dict:
    j = _julgamento()
    for q in ids:
        j["fidelidade"][q]["sem_grave"] = False
    return j


def test_queda_de_exatamente_1_passa_e_de_1_5_reprova():
    um = m9.comparar(_base(r1=_rodada("v2", _V2_FORMATADA, _sem_grave(["q03"])),
                           r2=_rodada("v2", _V2_FORMATADA, _sem_grave(["q04"]))), GABARITO, FATOS, FMT, META)
    assert um["medias"]["v1"]["d_sem_grave"] - um["medias"]["v2"]["d_sem_grave"] == pytest.approx(1.0)
    assert um["criterios"]["b_sem_queda"]["d_sem_grave"] is True and um["v2_vira_padrao"] is True
    um_e_meio = m9.comparar(_base(r1=_rodada("v2", _V2_FORMATADA, _sem_grave(["q03", "q06"])),
                                  r2=_rodada("v2", _V2_FORMATADA, _sem_grave(["q04"]))), GABARITO, FATOS, FMT, META)
    assert um_e_meio["criterios"]["b_sem_queda"]["d_sem_grave"] is False and um_e_meio["v2_vira_padrao"] is False


def test_juiz_pendente_conta_como_nao_acerto():
    j = _julgamento()
    j["correcao"]["q03"] = {"correta": None}
    j["correcao"]["q06"] = {"correta": None}
    c = m9.comparar(_base(r1=_rodada("v2", _V2_FORMATADA, j), r2=_rodada("v2", _V2_FORMATADA, j)),
                    GABARITO, FATOS, FMT, META)
    assert c["por_rodada"]["v2-r1"]["pendentes"]["f_correcao"] == 2
    assert c["criterios"]["b_sem_queda"]["f_correcao"] is False


def test_sim_nao_contradizendo_o_gabarito_reprova_c():
    errada = {**_V2_FORMATADA, "q05": {"resposta_crua": "Não, não precisa.\n\nQuer mais detalhes?"}}
    c = m9.comparar(_base(r2=_rodada("v2", errada)), GABARITO, FATOS, FMT, META)
    assert c["criterios"]["c_sem_sim_nao_errado"] is False and c["v2_vira_padrao"] is False
    assert c["violacoes_v2"] == [{"id": "q05", "esperado": "sim", "veio": "nao", "rodada": "r2"}]


def test_sem_sim_nao_nao_viola_c_e_resposta_fixa_fica_fora():
    sem_palavra = {**_V2_FORMATADA, "q01": {"resposta_crua": "O manual exige F-07.\n\nQuer mais detalhes?"}}
    fixa = {**_V2_FORMATADA, "q05": {"resposta_crua": rag_specialist.FRASE_INDISPONIVEL,
                                     "resposta_fixa_sem_llm": True}}
    c = m9.comparar(_base(r1=_rodada("v2", sem_palavra), r2=_rodada("v2", fixa)), GABARITO, FATOS, FMT, META)
    assert c["criterios"]["c_sem_sim_nao_errado"] is True
    assert c["por_rodada"]["v2-r2"]["fixas_fora_do_c"] == ["q05"]
    # a mesma frase "Nao consegui..." gerada pelo LLM conta
    llm = {**_V2_FORMATADA, "q05": {"resposta_crua": rag_specialist.FRASE_INDISPONIVEL}}
    assert m9.comparar(_base(r2=_rodada("v2", llm)), GABARITO, FATOS, FMT, META)["criterios"][
        "c_sem_sim_nao_errado"] is False


def test_v1_que_erra_sim_nao_nao_conta_no_c():
    base = _base()
    base[("v1", "r1")] = _rodada("v1", {"q05": {"resposta_crua": "Não."}})
    assert m9.comparar(base, GABARITO, FATOS, FMT, META)["criterios"]["c_sem_sim_nao_errado"] is True


@pytest.mark.parametrize("estraga", ["versao", "hash_regras", "julgamento_de_outra", "juiz", "indice"])
def test_integridade_invalida_a_comparacao(estraga):
    base = _base()
    resp, julg = copy.deepcopy(base[("v2", "r1")])
    if estraga == "versao":
        resp["config"]["rag_regras_versao"] = "v1"
    elif estraga == "hash_regras":
        resp["hashes"]["regras_do_manual"] = "x"
    elif estraga == "julgamento_de_outra":
        julg = base[("v1", "r1")][1]
    elif estraga == "juiz":
        julg["hashes"]["prompt_correcao"] = "x"
    else:
        resp["config"]["indice_meta"]["bm25_stemming"] = "0"  # mesmos contextos, outro indice
    if estraga in ("versao", "hash_regras", "indice"):  # recalcula o elo julgamento->respostas
        julg = {**julg, "hashes": {**julg["hashes"],
                                   "respostas": av.sha256_texto(json.dumps(resp, sort_keys=True, ensure_ascii=False))}}
    base[("v2", "r1")] = (resp, julg)
    c = m9.comparar(base, GABARITO, FATOS, FMT, META)
    assert not c["valido"] and c["problemas"] and c["v2_vira_padrao"] is False
    assert "INVÁLIDA" in m9.relatorio(c)


def test_indice_diferente_da_missao8_invalida():
    assert not m9.comparar(_base(), GABARITO, FATOS, FMT, {**META, "n_chunks": "47"})["valido"]


def test_rodada_faltando_recusa(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m9, "DIR_M9", tmp_path)
    assert m9.main(["--comparar"]) == 2
    assert "rodadas faltando" in capsys.readouterr().err


def test_comparar_le_os_arquivos_de_m9(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m9, "DIR_M9", tmp_path)
    m8 = tmp_path / "m8.json"
    m8.write_text(json.dumps({"config": {"indice_meta": dict(META)}}), encoding="utf-8")
    monkeypatch.setattr(m9, "RESPOSTAS_M8", m8)
    for (v, r), (resp, julg) in _base().items():
        pr, pj = m9.caminhos(v, r)
        pr.write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
        pj.write_text(json.dumps(julg, ensure_ascii=False), encoding="utf-8")
    assert m9.main(["--comparar"]) == 0
    assert "v2 VIRA padrão" in capsys.readouterr().out
