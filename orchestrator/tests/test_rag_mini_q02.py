"""Testes do mini-teste q02 e q04 (v1 x v4, proposta Antigravity).

Rede bloqueada (conftest), LLM FALSO. Prova:
- v4 comeca exatamente pela v1 (v4 = v1 + acrescimo) e tem hashes congelados;
- o padrao de producao e REGRAS_POR_VERSAO continuam intactos em v1;
- a coleta pelo grafo inteiro intercala v1/v4, injeta o texto certo no synth,
  restaura o modulo apos o turno, respeita FalhaInicial e o teto de US$ 0,10;
- o arquivo cego nao vaza versao nem hash e a semente e deterministica;
- o --resultado aplica os criterios 1-3 com casos de borda, falhas e integridade.
"""

import inspect
import json
import random
import re
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from hermetic_support import FAKE_SECRET
from test_rag_avaliar_respostas import (  # noqa: F401
    GABARITO,
    G,
    _citacao,
    _llms_falsos,
    ambiente_grafo,
)

from orchestrator.config import Settings, settings
from orchestrator.graph import rag_specialist
from orchestrator.graph.rag_specialist import codigo_pop
from orchestrator.rag import avaliar_respostas as av
from orchestrator.rag import mini_q02

# Literais pre-registrados (nao derivados de mini_q02.*: mudar texto + constante
# juntos no modulo ainda falha aqui).
HASH_V1_LITERAL = "3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240"
HASH_ARQUIVO_V4_LITERAL = "4c23e9c03e040c9972d438fb58aa43f9c18f6990d13b9f8bb99a0fa16497070b"
HASH_REGRAS_V4_LITERAL = "646921f245b120a1faeac60df499054dc238a1f863f537e91d59147a3600e1a0"
META_M8 = {"model_name": "m", "n_chunks": "46", "bm25_stemming": "1", "contextos_sha256": "ctx-m8"}

_SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")


def _trechos_com_regra(qid: str) -> list[dict]:
    g = G[qid]
    return [
        {"n": i + 1, "pop": codigo_pop(arq), "secao": sec, "texto": g["resposta_esperada"]}
        for i, (arq, sec) in enumerate(zip(g["arquivo_fonte"], g["secao_fonte"], strict=True))
    ]


def _lote_respostas(sobrescreve: dict[tuple[str, str, int], dict] | None = None, *,
                    indice_meta: dict | None = None, abortado: bool = False) -> dict:
    """Constroi um respostas.json sintetico completo (40 respostas intercaladas)."""
    sobrescreve = sobrescreve or {}
    respostas = []
    for passo in mini_q02.sequencia_execucao():
        v, qid, amostra, idx = passo["versao"], passo["id"], passo["amostra"], passo["indice_execucao"]
        g = G[qid]
        crua = f"{g['resposta_esperada']} {_citacao(g)}"
        reg = {
            "indice_execucao": idx,
            "amostra": amostra,
            "versao": v,
            "regras_sha256": HASH_V1_LITERAL if v == "v1" else HASH_REGRAS_V4_LITERAL,
            "id": qid,
            "tipo": g["tipo"],
            "pergunta": g["pergunta"],
            "caminho": ["supervisor", "specialist_rag", "supervisor", "synthesize_final"],
            "rag_acionado": True,
            "trechos": _trechos_com_regra(qid),
            "resposta_crua": crua,
            "resposta_final": crua,
            "resposta_fixa_sem_llm": False,
            "anexo_de_citacao": False,
            "erro": None,
            "erros_llm": [],
            "falha_de_infra": False,
            "etapa2_aplicada": False,
            "tempo_synth_s": 1.2,
            "tempo_total_s": 2.4,
            "custo_usd": 0.0018,
        }
        reg.update(sobrescreve.get((v, qid, amostra), {}))
        respostas.append(reg)
    return {
        "versao": 1,
        "experimento": "mini-teste-q02-q04",
        "data": "2026-11-21T21:00:00-03:00",
        "config": {
            "indice_meta": dict(META_M8 if indice_meta is None else indice_meta),
            "perguntas_ids": ["q02", "q04"],
            "versoes": ["v1", "v4"],
            "n_amostras": 10,
        },
        "hashes": {
            "v1_regras_do_manual": HASH_V1_LITERAL,
            "v4_arquivo_proposta": HASH_ARQUIVO_V4_LITERAL,
            "v4_regras_do_manual": HASH_REGRAS_V4_LITERAL,
        },
        "custo_usd": sum(r["custo_usd"] for r in respostas),
        "custo_por_versao_usd": {
            "v1": sum(r["custo_usd"] for r in respostas if r["versao"] == "v1"),
            "v4": sum(r["custo_usd"] for r in respostas if r["versao"] == "v4"),
        },
        "orcamento_usd": 0.10,
        "abortado_por_orcamento": abortado,
        "respostas": respostas,
    }


def _classificar_tudo(respostas: dict, mapa_classes: dict[tuple[str, str, int], str] | None = None, *,
                      semente: int | None = None) -> tuple[dict, dict]:
    """Gera classificacao cega + mapa e preenche todas as 40 classes (padrao: todas certas)."""
    mapa_classes = mapa_classes or {}
    yaml_cego, mapa_dados = mini_q02.gerar_classificacao_cega(respostas, semente=semente)
    dados_cegos = yaml.safe_load(yaml_cego)
    for item in dados_cegos["itens"]:
        info = mapa_dados["mapa"][item["codigo"]]
        chave = (info["versao"], info["pergunta_id"], info["amostra"])
        item["classe"] = mapa_classes.get(chave, mini_q02.CLASSE_CERTA[info["pergunta_id"]])
    return dados_cegos, mapa_dados


# --- v4 comeca pela v1, hashes congelados e isolamento de producao -----------


def test_v4_comeca_exatamente_pela_v1_e_recusa_divergencia(tmp_path):
    v1 = rag_specialist.REGRAS_DO_MANUAL
    v4 = mini_q02.carregar_regras_v4()
    assert v4.startswith(v1)
    assert v4[len(v1):].startswith("\n6. Em perguntas de decisao")
    assert len(v4) > len(v1)

    quebrado = tmp_path / "proposta-quebrada.txt"
    quebrado.write_text("TEXTO ALTERADO\n" + v4.lstrip("\n"), encoding="utf-8")
    with pytest.raises(ValueError, match="NAO comeca exatamente"):
        mini_q02.carregar_regras_v4(quebrado, verificar_hash=False)


def test_hash_v4_congelado_e_recusa_adulteracao(tmp_path):
    assert av.sha256_texto(rag_specialist.REGRAS_DO_MANUAL) == HASH_V1_LITERAL == mini_q02.HASH_REGRAS_V1
    assert mini_q02.juiz.sha256_arquivo(mini_q02.CAMINHO_PROPOSTA_V4) == HASH_ARQUIVO_V4_LITERAL == mini_q02.HASH_ARQUIVO_V4
    v4 = mini_q02.carregar_regras_v4()
    assert av.sha256_texto(v4) == HASH_REGRAS_V4_LITERAL == mini_q02.HASH_REGRAS_V4
    assert mini_q02.HASH_REGRAS_PRE_REGISTRO == {"v1": HASH_V1_LITERAL, "v4": HASH_REGRAS_V4_LITERAL}

    adulterado = tmp_path / "proposta-adulterada.txt"
    adulterado.write_text(mini_q02.CAMINHO_PROPOSTA_V4.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        mini_q02.carregar_regras_v4(adulterado, verificar_hash=True)


def test_padrao_de_producao_e_regras_por_versao_continuam_v1(monkeypatch):
    assert Settings.model_fields["rag_regras_versao"].default == "v1"
    assert settings.rag_regras_versao == "v1"
    # A v5 (Parte 3 da ferramenta de limites, 24/11/2026) entrou como versao SELECIONAVEL;
    # o padrao continua v1 e a v4 continua so dentro do mini-teste.
    assert tuple(rag_specialist.REGRAS_POR_VERSAO) == ("v1", "v2", "v5")
    assert tuple(rag_specialist.REGRAS_DA_ETAPA1_POR_VERSAO) == ("v1", "v2", "v3", "v5")
    with pytest.raises(ValueError):
        rag_specialist.regras_do_manual("v4")
    with pytest.raises(ValueError):
        rag_specialist.regras_da_etapa1("v4")
    monkeypatch.setenv("ORCHESTRATOR_RAG_REGRAS_VERSAO", "v4")
    with pytest.raises(ValueError):
        Settings(_env_file=None)
    # Apenas o mini_q02 seleciona v4 por parametro e recusa outras versoes
    assert mini_q02.regras_do_mini_teste("v4").startswith(rag_specialist.REGRAS_DO_MANUAL)
    for invalida in ("v2", "v3", "v5"):
        with pytest.raises(ValueError):
            mini_q02.regras_do_mini_teste(invalida)


# --- coleta no grafo inteiro com LLM falso ----------------------------------


@pytest.mark.asyncio
async def test_coleta_intercala_v1_v4_injeta_regras_e_restaura(ambiente_grafo):  # noqa: F811
    seq_padrao = mini_q02.sequencia_execucao()
    assert len(seq_padrao) == 40
    assert [p["versao"] for p in seq_padrao] == ["v1", "v4"] * 20
    assert {(p["versao"], p["id"]) for p in seq_padrao} == {("v1", "q02"), ("v4", "q02"), ("v1", "q04"), ("v4", "q04")}

    base = _llms_falsos(set(), set())
    supervisor = base(temperature=0)
    synth_base = base(temperature=None)
    antigo = synth_base.ainvoke.side_effect
    sistemas_vistos: list[str] = []

    async def synth_espiado(msgs, *a, **k):
        sistemas_vistos.append(msgs[0].content)
        assert msgs[0].content != rag_specialist.PROMPT_FORMATADOR_V3  # etapa 2 nunca roda
        return await antigo(msgs, *a, **k)

    synth_base.ainvoke = AsyncMock(side_effect=synth_espiado)

    def fabrica(*a, **k):
        return supervisor if k.get("temperature") == 0 else synth_base

    original_fn = rag_specialist.regras_da_etapa1
    logs: list[str] = []
    with patch("orchestrator.graph.nodes.ChatOpenAI", side_effect=fabrica):
        dados = await mini_q02.etapa_coleta(GABARITO, n_amostras=2, orcamento=0.10, log=logs.append)

    # Restaura o modulo e mantem o padrao de producao v1
    assert rag_specialist.regras_da_etapa1 is original_fn
    assert settings.rag_regras_versao == "v1"
    with pytest.raises(ValueError):
        rag_specialist.regras_da_etapa1("v4")

    resps = dados["respostas"]
    assert len(resps) == 8
    assert [r["versao"] for r in resps] == ["v1", "v4"] * 4
    assert [r["id"] for r in resps] == ["q02", "q02", "q04", "q04"] * 2

    v1 = rag_specialist.REGRAS_DO_MANUAL
    v4 = mini_q02.carregar_regras_v4()
    assert len(sistemas_vistos) == 8
    for r, sys_msg in zip(resps, sistemas_vistos, strict=True):
        esperado = v1 if r["versao"] == "v1" else v4
        assert sys_msg.endswith(esperado)
        assert r["regras_sha256"] == (HASH_V1_LITERAL if r["versao"] == "v1" else HASH_REGRAS_V4_LITERAL)
        assert r["rag_acionado"] is True and len(r["trechos"]) == 5
        assert r["resposta_crua"] and r["tempo_total_s"] >= 0 and r["custo_usd"] >= 0
        assert r["etapa2_aplicada"] is False
    # Log preserva a cegueira (sem texto de resposta) e sem segredos
    texto_log = "\n".join(logs)
    assert G["q02"]["resposta_esperada"][:25] not in texto_log
    assert FAKE_SECRET not in json.dumps(dados, ensure_ascii=False)

    # Restauracao mesmo quando ocorre excecao dentro do contexto
    with pytest.raises(RuntimeError), mini_q02._com_regras_no_synth("v4", v4):
        assert rag_specialist.regras_da_etapa1() == v4
        raise RuntimeError("boom")
    assert rag_specialist.regras_da_etapa1 is original_fn


@pytest.mark.asyncio
async def test_coleta_falha_inicial_orcamento_e_nao_sobrescreve(ambiente_grafo, tmp_path, monkeypatch):  # noqa: F811
    async def falha_primeira(graph, item):
        return {"id": item["id"], "caminho": [], "falha_de_infra": True, "erro": "TimeoutError", "chamadas_llm": []}

    with pytest.raises(av.FalhaInicial):
        await mini_q02.etapa_coleta(GABARITO, n_amostras=1, graph_factory=lambda cp: object(),
                                    responder=falha_primeira, log=lambda *_: None)

    chamadas = []

    async def cara(graph, item):
        chamadas.append(item["id"])
        return {"id": item["id"], "caminho": ["supervisor", "specialist_rag", "supervisor", "synthesize_final"],
                "rag_acionado": True, "trechos": [], "resposta_crua": "Não.", "resposta_final": "Não.",
                "falha_de_infra": False, "chamadas_llm": [{"no": "synthesize_final", "token_usage": {"cost": 0.06}}]}

    dados = await mini_q02.etapa_coleta(GABARITO, n_amostras=2, orcamento=0.10, graph_factory=lambda cp: object(),
                                        responder=cara, log=lambda *_: None)
    assert len(chamadas) == 2 and dados["abortado_por_orcamento"] is True and dados["custo_usd"] == pytest.approx(0.12)

    # CLI nao sobrescreve arquivo de saida ja existente
    monkeypatch.setattr(mini_q02, "DIR_SAIDA", tmp_path / "ctrl")
    indice = tmp_path / "idx.sqlite"
    indice.write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "rag_index_path", str(indice))
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    saida = tmp_path / "respostas.json"
    saida.write_text("{}", encoding="utf-8")
    assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida)]) == 2


# --- CLI e plano gratis -----------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["--executar", "--orcamento", "0.11"],
    ["--executar", "--orcamento", "0.1001"],
    ["--executar", "--orcamento", "0"],
    ["--executar", "--orcamento", "-0.01"],
    ["--executar", "--orcamento", "nan"],
    ["--executar", "--orcamento", "inf"],
    ["--orcamento", "0.05"],
    ["--semente", "42"],
    ["--executar", "--classificar-arquivo"],
    ["--executar", "--resultado"],
    ["--classificar-arquivo", "--resultado"],
    ["--classificar-arquivo", "--orcamento", "0.05"],
    ["--resultado", "--semente", "1"],
])
def test_cli_recusa_orcamento_acima_de_0_10_e_flags_invalidas(argv):
    with pytest.raises(SystemExit):
        mini_q02.parse_args(argv)


def test_plano_gratis_nao_chama_llm_e_mostra_custo_e_comando_pago(monkeypatch, capsys):
    monkeypatch.setattr(mini_q02, "etapa_coleta", MagicMock(side_effect=AssertionError("executou coleta")))
    assert mini_q02.main([]) == 0
    out = capsys.readouterr().out
    assert "NADA executado" in out
    assert HASH_V1_LITERAL in out and HASH_ARQUIVO_V4_LITERAL in out and HASH_REGRAS_V4_LITERAL in out
    assert "comeca exatamente pela v1: sim" in out
    assert "US$ 0.10" in out
    assert mini_q02.comando_pago() in out
    assert FAKE_SECRET not in out
    # O proprio comando pago impresso e aceito pelo parser
    parsed = mini_q02.parse_args(mini_q02.comando_pago().split("mini_q02 ")[1].split())
    assert parsed.executar is True and parsed.orcamento == pytest.approx(0.10)


# --- arquivo cego e determinismo da semente ---------------------------------


def test_arquivo_cego_nao_contem_versao_nem_hash(tmp_path):
    lote = _lote_respostas()
    yaml_cego, mapa = mini_q02.gerar_classificacao_cega(lote)
    assert "v1" not in yaml_cego.lower()
    assert "v4" not in yaml_cego.lower()
    assert HASH_V1_LITERAL not in yaml_cego
    assert HASH_REGRAS_V4_LITERAL not in yaml_cego
    assert HASH_ARQUIVO_V4_LITERAL not in yaml_cego
    assert not _SHA256_RE.search(yaml_cego)
    for proibido in ("versao", "versão", "regras_sha256", "indice_execucao", "amostra", "custo_usd", "tempo_", "trechos",
                     "semente"):
        assert proibido not in yaml_cego, proibido
    assert str(mapa["semente"]) not in yaml_cego  # Emenda M-01: semente SO no mapa

    dados = yaml.safe_load(yaml_cego)
    assert set(dados) == {"elo", "itens"} and len(dados["itens"]) == 40
    assert dados["elo"] == mapa["elo"] and re.fullmatch(r"[0-9a-f]{32}", dados["elo"])
    codigos = [it["codigo"] for it in dados["itens"]]
    assert codigos == [f"r{i:02d}" for i in range(1, 41)]
    for it in dados["itens"]:
        assert set(it) == {"codigo", "pergunta_id", "pergunta", "resposta", "classe", "observacao"}
        assert it["classe"] is None

    assert len(mapa["mapa"]) == 40
    assert {m["versao"] for m in mapa["mapa"].values()} == {"v1", "v4"}

    # CLI grava os dois arquivos e recusa sobrescrever
    arq_resp = tmp_path / "respostas.json"
    arq_resp.write_text(json.dumps(lote), encoding="utf-8")
    cega, mapa_p = tmp_path / "cega.yaml", tmp_path / "mapa.json"
    assert mini_q02.main(["--classificar-arquivo", "--respostas", str(arq_resp),
                          "--saida-cega", str(cega), "--saida-mapa", str(mapa_p)]) == 0
    assert cega.is_file() and mapa_p.is_file()
    assert mini_q02.main(["--classificar-arquivo", "--respostas", str(arq_resp),
                          "--saida-cega", str(cega), "--saida-mapa", str(mapa_p)]) == 2


def test_mesma_semente_gera_o_mesmo_embaralhamento():
    lote = _lote_respostas()
    # Semente e elo fixos so no teste (no CLI os dois vem de `secrets`, Emenda M-01).
    y1, m1 = mini_q02.gerar_classificacao_cega(lote, semente=12345, elo="a" * 32)
    y2, m2 = mini_q02.gerar_classificacao_cega(lote, semente=12345, elo="a" * 32)
    y3, m3 = mini_q02.gerar_classificacao_cega(lote, semente=54321, elo="a" * 32)
    assert y1 == y2 and m1 == m2
    assert y1 != y3
    ordem_1 = [m1["mapa"][f"r{i:02d}"]["indice_execucao"] for i in range(1, 41)]
    ordem_3 = [m3["mapa"][f"r{i:02d}"]["indice_execucao"] for i in range(1, 41)]
    assert ordem_1 != ordem_3
    assert ordem_1 != list(range(1, 41))  # de fato embaralhou


# --- --resultado: validacao, criterios 1-3, falhas e integridade ------------


def test_resultado_recusa_classificacao_incompleta_ou_invalida():
    lote = _lote_respostas()
    cega, mapa = _classificar_tudo(lote)

    incompleta = yaml.safe_load(yaml.safe_dump(cega))
    incompleta["itens"][0]["classe"] = None
    with pytest.raises(ValueError, match="incompleta"):
        mini_q02.avaliar_resultado(lote, incompleta, mapa, GABARITO, indice_meta_m8=META_M8)

    # Classe de q04 usada numa q02
    trocada = yaml.safe_load(yaml.safe_dump(cega))
    item_q02 = next(it for it in trocada["itens"] if it["pergunta_id"] == "q02")
    item_q02["classe"] = "NÃO TROCA"
    with pytest.raises(ValueError, match="classe invalida"):
        mini_q02.avaliar_resultado(lote, trocada, mapa, GABARITO, indice_meta_m8=META_M8)

    # Classe de q02 usada numa q04
    trocada2 = yaml.safe_load(yaml.safe_dump(cega))
    item_q04 = next(it for it in trocada2["itens"] if it["pergunta_id"] == "q04")
    item_q04["classe"] = "RECUSA"
    with pytest.raises(ValueError, match="classe invalida"):
        mini_q02.avaliar_resultado(lote, trocada2, mapa, GABARITO, indice_meta_m8=META_M8)

    # Codigo faltando
    faltando = yaml.safe_load(yaml.safe_dump(cega))
    faltando["itens"].pop()
    with pytest.raises(ValueError, match="ausentes"):
        mini_q02.avaliar_resultado(lote, faltando, mapa, GABARITO, indice_meta_m8=META_M8)


@pytest.mark.parametrize(
    ("erros_v1_q02", "erros_v4_q02", "erros_v4_q04", "espera_c1", "espera_c2", "espera_sinal", "espera_sem_concl"),
    [
        (2, 0, 0, True, True, True, False),    # v4 zera erro da q02 e q04 -> passa
        (2, 1, 0, True, True, True, False),    # caso de borda: 1 erro exato na q02 (< v1=2) -> passa
        (3, 2, 0, False, True, False, False),  # 2 erros na q02 (mesmo < v1=3) -> reprova c1
        (1, 1, 0, False, True, False, False),  # caso de borda: empate com v1 (1 == 1) -> reprova c1
        (0, 0, 0, False, True, False, True),   # caso de borda: v1 com 0 erros na q02 -> sem conclusao
        (2, 0, 1, True, False, False, False),  # 1 erro na q04 na v4 -> reprova c2
    ],
    ids=["passa-zero", "borda-1-erro-q02", "2-erros-q02", "borda-empate-v1", "borda-v1-zero-erros", "erro-q04-v4"],
)
def test_resultado_criterios_1_e_2_com_casos_de_borda(
    erros_v1_q02, erros_v4_q02, erros_v4_q04, espera_c1, espera_c2, espera_sinal, espera_sem_concl
):
    lote = _lote_respostas()
    classes = {}
    for a in range(1, erros_v1_q02 + 1):
        classes[("v1", "q02", a)] = "ACEITA"
    for a in range(1, erros_v4_q02 + 1):
        classes[("v4", "q02", a)] = "AMBÍGUA" if a % 2 else "ACEITA"
    for a in range(1, erros_v4_q04 + 1):
        classes[("v4", "q04", a)] = "TROCA"
    cega, mapa = _classificar_tudo(lote, classes)

    res = mini_q02.avaliar_resultado(lote, cega, mapa, GABARITO, indice_meta_m8=META_M8)
    assert res["valido"] is True, res["problemas"]
    assert res["criterios"]["c1_q02"]["passa"] is espera_c1
    assert res["criterios"]["c2_q04"]["passa"] is espera_c2
    assert res["q02_sem_conclusao"] is espera_sem_concl
    assert res["passa_no_sinal"] is espera_sinal
    rel = mini_q02.relatorio(res)
    if espera_sem_concl:
        assert "o erro não apareceu nesta amostra" in rel and "sem conclusão sobre a q02" in rel
    if espera_sinal:
        assert "v4 PASSA NO SINAL" in rel
    else:
        assert "NÃO passa no sinal" in rel


def test_resultado_criterio_3_falso_nao_cobre_na_v4():
    # v1 erra 2 na q02 para c1 passar; v4 acerta q02/q04, mas diz "nao cobre" com a regra nos trechos
    sobrescreve = {
        ("v4", "q02", 1): {"resposta_crua": f"{rag_specialist.FRASE_NAO_COBRE} Recuse a -10 °C."},
    }
    lote = _lote_respostas(sobrescreve)
    cega, mapa = _classificar_tudo(lote, {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"})
    res = mini_q02.avaliar_resultado(lote, cega, mapa, GABARITO, indice_meta_m8=META_M8)
    assert res["criterios"]["c3_sem_falso_nao_cobre_v4"]["passa"] is False
    assert len(res["criterios"]["c3_sem_falso_nao_cobre_v4"]["ocorrencias"]) == 1
    assert res["passa_no_sinal"] is False

    # Se os trechos NAO trazem a secao-fonte, dizer "nao cobre" nao viola criterio 3
    sem_regra = {
        ("v4", "q02", 1): {
            "trechos": [{"n": 1, "pop": "POP-05", "secao": "Outra secao", "texto": "irrelevante"}],
            "resposta_crua": rag_specialist.FRASE_NAO_COBRE,
        },
    }
    lote2 = _lote_respostas(sem_regra)
    cega2, mapa2 = _classificar_tudo(lote2, {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"})
    res2 = mini_q02.avaliar_resultado(lote2, cega2, mapa2, GABARITO, indice_meta_m8=META_M8)
    assert res2["criterios"]["c3_sem_falso_nao_cobre_v4"]["passa"] is True

    # Negativa legitima ("o manual nao preve troca apos o prazo") NAO dispara falso positivo
    negativa_legitima = {
        ("v4", "q04", 1): {"resposta_crua": "Não. O manual não prevê troca de perecíveis após o prazo de 24 horas."},
    }
    lote3 = _lote_respostas(negativa_legitima)
    cega3, mapa3 = _classificar_tudo(lote3, {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"})
    res3 = mini_q02.avaliar_resultado(lote3, cega3, mapa3, GABARITO, indice_meta_m8=META_M8)
    assert res3["criterios"]["c3_sem_falso_nao_cobre_v4"]["passa"] is True and res3["passa_no_sinal"] is True


def test_resultado_fora_do_rag_conta_como_erro_e_falha_de_infra_invalida():
    # Fora do RAG (rag_acionado=False): conta como erro mesmo classificada como certa; o resultado segue valido.
    fora = {("v4", "q02", 2): {"rag_acionado": False, "caminho": ["supervisor", "synthesize_final"], "trechos": []}}
    lote = _lote_respostas(fora)
    cega, mapa = _classificar_tudo(lote, {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"})
    res = mini_q02.avaliar_resultado(lote, cega, mapa, GABARITO, indice_meta_m8=META_M8)
    assert res["valido"] is True and res["grupos"]["v4"]["q02"]["erros"] == 1
    assert len(res["fora_do_rag"]) == 1 and res["fora_do_rag"][0]["pergunta_id"] == "q02"
    assert "não foram ao RAG" in mini_q02.relatorio(res)

    # Emenda E-B03: falha de infra deixa de ser "erro da amostra" e SEMPRE invalida.
    infra = {("v4", "q04", 1): {"falha_de_infra": True, "erro": "TimeoutError"}}
    lote2 = _lote_respostas(infra)
    cega2, mapa2 = _classificar_tudo(lote2, {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"})
    res2 = mini_q02.avaliar_resultado(lote2, cega2, mapa2, GABARITO, indice_meta_m8=META_M8)
    assert res2["valido"] is False and res2["passa_no_sinal"] is False
    assert len(res2["problemas"]) == 1 and "falha de infra" in res2["problemas"][0]
    rel = mini_q02.relatorio(res2)
    assert "Falhas de infraestrutura (invalidam a coleta" in rel and "INVÁLIDO" in rel


def test_resultado_integridade_e_roundtrip_cli(tmp_path, monkeypatch, capsys):
    lote = _lote_respostas()
    arq_resp = tmp_path / "respostas.json"
    arq_resp.write_text(json.dumps(lote), encoding="utf-8")
    arq_cega = tmp_path / "classificacao-cega.yaml"
    arq_mapa = tmp_path / "mapa-cego.json"
    assert mini_q02.main(["--classificar-arquivo", "--respostas", str(arq_resp),
                          "--saida-cega", str(arq_cega), "--saida-mapa", str(arq_mapa)]) == 0
    saida_cli = capsys.readouterr().out
    assert yaml.safe_load(arq_cega.read_text(encoding="utf-8"))["elo"] not in saida_cli  # log colavel: sem elo
    assert str(json.loads(arq_mapa.read_text(encoding="utf-8"))["semente"]) not in saida_cli  # nem semente

    # Antes de classificar -> CLI recusa (codigo 2)
    monkeypatch.setattr(mini_q02.m10.m9, "indice_meta_m8", lambda: dict(META_M8))
    assert mini_q02.main(["--resultado", "--respostas", str(arq_resp),
                          "--classificacao", str(arq_cega), "--mapa", str(arq_mapa)]) == 2

    # Preenche todas as 40 (v1 erra 2 na q02, v4 acerta tudo) -> passa no sinal (codigo 0)
    cega = yaml.safe_load(arq_cega.read_text(encoding="utf-8"))
    mapa = json.loads(arq_mapa.read_text(encoding="utf-8"))
    for it in cega["itens"]:
        info = mapa["mapa"][it["codigo"]]
        if info["versao"] == "v1" and info["pergunta_id"] == "q02" and info["amostra"] in (1, 2):
            it["classe"] = "ACEITA"
        else:
            it["classe"] = mini_q02.CLASSE_CERTA[info["pergunta_id"]]
    arq_cega.write_text(yaml.safe_dump(cega, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert mini_q02.main(["--resultado", "--respostas", str(arq_resp),
                          "--classificacao", str(arq_cega), "--mapa", str(arq_mapa)]) == 0
    assert "v4 PASSA NO SINAL" in capsys.readouterr().out

    # Quebra elo mapa -> respostas: invalida (codigo 1)
    mapa["respostas_sha256"] = "0" * 64
    arq_mapa.write_text(json.dumps(mapa), encoding="utf-8")
    assert mini_q02.main(["--resultado", "--respostas", str(arq_resp),
                          "--classificacao", str(arq_cega), "--mapa", str(arq_mapa)]) == 1
    assert "INVÁLIDO" in capsys.readouterr().out


# --- Emenda M-01: o ataque da revisao (semente -> versoes) nao reconstroi mais -----


def _ataque_reconstrucao(yaml_cego: str, mapa: dict) -> int:
    """Ataque da revisao adversaria (demo.py, parte b2), agora como teste: com SO o
    YAML cego e o codigo publico, tenta reconstruir a versao de cada codigo. Testa
    como semente todo inteiro escrito no YAML, o elo (hex) e todo literal inteiro do
    codigo-fonte do mini_q02, refazendo `random.Random(semente).shuffle` sobre a
    ordem publica `sequencia_execucao()`. O `mapa` so CONTA os acertos. Devolve o
    melhor placar dos dois lados (acertar tudo ou errar tudo revela igual)."""
    plano = mini_q02.sequencia_execucao()
    candidatos = {int(x) for x in re.findall(r"\d+", yaml_cego)}
    candidatos |= {int(x) for x in re.findall(r"\d+", inspect.getsource(mini_q02))}
    elo = (yaml.safe_load(yaml_cego) or {}).get("elo")
    if elo:
        candidatos.add(int(elo, 16))
    real = {cod: info["versao"] for cod, info in mapa["mapa"].items()}
    melhor = 0
    for semente in candidatos:
        idx = list(range(len(plano)))
        random.Random(semente).shuffle(idx)
        derivado = {f"r{p:02d}": plano[i]["versao"] for p, i in enumerate(idx, 1)}
        acertos = sum(derivado[c] == v for c, v in real.items())
        melhor = max(melhor, acertos, len(real) - acertos)
    return melhor


def test_m01_ataque_da_semente_nao_reconstroi_as_versoes():
    lote = _lote_respostas()
    # Caminho real do --classificar-arquivo: semente e elo sorteados com `secrets`.
    yaml_cego, mapa = mini_q02.gerar_classificacao_cega(lote)
    # Placar de chance: 40 - 2j, j hipergeometrico (media 20). >= 38 por acaso: ~1e-6 no total.
    assert _ataque_reconstrucao(yaml_cego, mapa) < 38

    # Controle positivo (o ataque nao e vazio): com a semente vazada no YAML ele acerta 40/40.
    s = secrets.randbits(64)
    yaml_vazado, mapa_vazado = mini_q02.gerar_classificacao_cega(lote, semente=s)
    assert _ataque_reconstrucao(yaml_vazado + f"# semente: {s}\n", mapa_vazado) == 40

    # Cada geracao sorteia semente e elo novos.
    _, mapa2 = mini_q02.gerar_classificacao_cega(lote)
    assert mapa2["semente"] != mapa["semente"] and mapa2["elo"] != mapa["elo"]


# --- Emenda B-01: cada guarda de integridade, quebrada sozinha, invalida -------

_V1_ERRA_2_NA_Q02 = {("v1", "q02", 1): "ACEITA", ("v1", "q02", 2): "ACEITA"}


def _avaliar(lote: dict, *, mexe_cega=None, mexe_mapa=None) -> dict:
    cega, mapa = _classificar_tudo(lote, _V1_ERRA_2_NA_Q02)
    if mexe_cega:
        mexe_cega(cega)
    if mexe_mapa:
        mexe_mapa(mapa)
    return mini_q02.avaliar_resultado(lote, cega, mapa, GABARITO, indice_meta_m8=META_M8)


def _troca_ordem(lote: dict) -> None:
    r = lote["respostas"]
    r[0]["indice_execucao"], r[1]["indice_execucao"] = r[1]["indice_execucao"], r[0]["indice_execucao"]


def test_b01_controle_lote_integro_e_valido_e_passa():
    res = _avaliar(_lote_respostas())
    assert res["valido"] is True and res["problemas"] == [] and res["passa_no_sinal"] is True


@pytest.mark.parametrize(
    ("quebra", "esperado"),
    [
        (_troca_ordem, "ordem de execucao nao e intercalada"),
        (lambda lote: lote["config"].__setitem__("indice_meta", {**META_M8, "contextos_sha256": "outro"}),
         "indice diferente do da Missao 8"),
        (lambda lote: lote["respostas"][1].__setitem__("regras_sha256", HASH_V1_LITERAL),
         "hash das regras difere do pre-registro"),
        (lambda lote: lote["respostas"][0].__setitem__("etapa2_aplicada", True), "etapa 2 aplicada indevidamente"),
        (lambda lote: lote.__setitem__("abortado_por_orcamento", True), "coleta abortada por orcamento"),
        (lambda lote: lote.__setitem__("abortado_por_infra", {"indice_execucao": 7, "erro_tipo": "TimeoutError"}),
         "coleta abortada por falha de infra no meio"),
        (lambda lote: lote["respostas"][5].update({"falha_de_infra": True, "erro": "TimeoutError"}),
         "falha de infra (Emenda E-B03: invalida a coleta)"),
        (lambda lote: lote["respostas"][0].__setitem__("amostra", 2), "grade completa 2 x 2 x 10"),
    ],
    ids=["ordem-intercalada", "indice-meta-m8", "hash-por-resposta", "etapa2", "abortado-orcamento",
         "abortado-infra", "falha-infra-em-resposta", "grade-2x2x10"],
)
def test_b01_cada_guarda_de_integridade_recusa_sozinha(quebra, esperado):
    lote = _lote_respostas()
    quebra(lote)
    res = _avaliar(lote)
    assert res["valido"] is False and res["passa_no_sinal"] is False
    # So ESTA guarda dispara: se ela sumir, nenhuma outra segura o INVALIDO.
    assert len(res["problemas"]) == 1 and esperado in res["problemas"][0], res["problemas"]
    assert "INVÁLIDO" in mini_q02.relatorio(res)


@pytest.mark.parametrize(
    ("mexe_cega", "mexe_mapa"),
    [
        (lambda c: c.__setitem__("elo", "0" * 32), None),
        (lambda c: c.pop("elo"), None),
        (lambda c: c.pop("elo"), lambda m: m.pop("elo")),
    ],
    ids=["elo-diferente", "elo-ausente-no-cego", "elo-ausente-nos-dois"],
)
def test_b01_elo_ausente_ou_diferente_invalida(mexe_cega, mexe_mapa):
    res = _avaliar(_lote_respostas(), mexe_cega=mexe_cega, mexe_mapa=mexe_mapa)
    assert res["valido"] is False
    assert res["problemas"] == ["elo ausente ou diferente entre o arquivo cego e o mapa"]


def test_b01_criterio_3_conta_so_a_v4():
    # "nao cobre" na v1 (com a regra nos trechos) fica registrado, mas NAO decide o criterio 3.
    lote = _lote_respostas({("v1", "q02", 3): {"resposta_crua": rag_specialist.FRASE_NAO_COBRE}})
    res = _avaliar(lote)
    assert len(res["grupos"]["v1"]["q02"]["falsos_nao_cobre"]) == 1
    assert res["criterios"]["c3_sem_falso_nao_cobre_v4"]["passa"] is True and res["passa_no_sinal"] is True


# --- Emenda B-02: detector ampliado do criterio 3, nos dois lados ---------------

FRASES_NAO_COBRE_NOVAS = [
    "O manual não menciona o que fazer com essa carga.",
    "Não especifica o que fazer nesse caso.",
    "Não encontrei no manual uma regra para isso.",
    "Os trechos não cobrem esse caso.",
    "O POP não cobre essa situação.",
    "O POP-01 não cobre essa situação.",
    "Não há informação sobre isso nos trechos.",
    "Isso não consta no manual.",
]
FRASES_NAO_COBRE_ORIGINAIS = [
    "O manual de procedimentos não cobre isso.",
    "O manual não trata de frango congelado.",
    "O manual de procedimentos não aborda esse ponto.",
    "Infelizmente o texto não cobre o caso.",
]
NEGATIVAS_CORRETAS = [
    "Não. O manual não prevê troca após o prazo de 24 horas.",
    "Não. O manual não permite troca de perecível depois de 24 horas.",
    'Não. Recuse a carga: congelado só é aceito até −12 °C (POP-01, seção "4. Temperatura na chegada").',
    "Não é possível trocar: já passou o prazo de 24 horas.",
    "Não há troca para perecível depois de 24 horas.",
    "Não aceite: a −10 °C a carga está acima do limite.",
    "Se não encontrar o cupom, não faça a troca.",
]


@pytest.mark.parametrize("frase", FRASES_NAO_COBRE_NOVAS + FRASES_NAO_COBRE_ORIGINAIS)
def test_b02_detector_dispara_em_cada_frase_de_nao_cobre(frase):
    assert mini_q02.diz_que_manual_nao_cobre(frase) is True


@pytest.mark.parametrize("frase", NEGATIVAS_CORRETAS)
def test_b02_detector_nao_dispara_em_negativa_correta(frase):
    assert mini_q02.diz_que_manual_nao_cobre(frase) is False


def test_b02_respostas_reais_da_q02_e_q04_nas_missoes_8_a_10_nao_disparam():
    base = av.ORCHESTRATOR_DIR / "fixtures" / "rag"
    m10_r2 = json.loads((base / "m10" / "respostas-v1-r2.json").read_text(encoding="utf-8"))
    q04_m10 = next(p["resposta_crua"] for p in m10_r2["perguntas"] if p["id"] == "q04")
    assert "o manual não prevê troca após o prazo" in q04_m10  # a resposta certa citada na emenda
    assert mini_q02.diz_que_manual_nao_cobre(q04_m10) is False

    vistas = 0
    for arq in sorted(base.glob("m*/respostas*.json")):
        for p in json.loads(arq.read_text(encoding="utf-8")).get("perguntas", []):
            if p["id"] in mini_q02.PERGUNTAS_IDS:
                vistas += 1
                assert mini_q02.diz_que_manual_nao_cobre(p.get("resposta_crua")) is False, (arq.name, p["id"])
    assert vistas >= 18  # M8 + 2x M9 v1/v2 + 2x M10 v1/v3, q02 e q04


def test_b02_frase_nova_reprova_o_criterio_3_pelo_resultado():
    lote = _lote_respostas({("v4", "q04", 5): {"resposta_crua": "Não. Os trechos não cobrem esse caso."}})
    res = _avaliar(lote)
    assert res["criterios"]["c3_sem_falso_nao_cobre_v4"]["passa"] is False and res["passa_no_sinal"] is False


# --- Emenda B-03: coleta abortada e FalhaInicial com repeticao unica -----------


def _resposta_ok(item: dict, custo: float = 0.001) -> dict:
    return {"id": item["id"], "tipo": item["tipo"], "pergunta": item["pergunta"],
            "caminho": ["supervisor", "specialist_rag", "supervisor", "synthesize_final"], "rag_acionado": True,
            "trechos": [], "resposta_crua": "Não.", "resposta_final": "Não.", "falha_de_infra": False,
            "chamadas_llm": [{"no": "synthesize_final", "token_usage": {"cost": custo}}]}


@pytest.mark.asyncio
async def test_b03_excecao_no_meio_grava_parcial_abortado_e_restaura(ambiente_grafo):  # noqa: F811
    chamadas = []

    async def cai_no_terceiro(graph, item):
        chamadas.append(item["id"])
        if len(chamadas) == 3:
            raise ConnectionError("mensagem do provedor que nao deve ir para o disco")
        return _resposta_ok(item)

    original_fn = rag_specialist.regras_da_etapa1
    dados = await mini_q02.etapa_coleta(GABARITO, n_amostras=2, graph_factory=lambda cp: object(),
                                        responder=cai_no_terceiro, log=lambda *_: None)
    assert len(chamadas) == 3 and len(dados["respostas"]) == 2
    assert dados["abortado_por_infra"] == {"indice_execucao": 3, "id": "q04", "versao": "v1", "amostra": 1,
                                           "erro_tipo": "ConnectionError"}
    assert "mensagem do provedor" not in json.dumps(dados, ensure_ascii=False)
    assert rag_specialist.regras_da_etapa1 is original_fn and settings.rag_regras_versao == "v1"

    # Excecao logo na 1a chamada: FalhaInicial (nada gravado), so com o TIPO do erro.
    async def cai_no_primeiro(graph, item):
        raise ConnectionError("x")

    with pytest.raises(av.FalhaInicial) as exc_info:
        await mini_q02.etapa_coleta(GABARITO, n_amostras=1, graph_factory=lambda cp: object(),
                                    responder=cai_no_primeiro, log=lambda *_: None)
    assert exc_info.value.erro_tipo == "ConnectionError"
    assert rag_specialist.regras_da_etapa1 is original_fn


def _cli_executar_pronto(tmp_path, monkeypatch, etapa):
    """Controle (registro + marcador) em tmp_path/ctrl; a saida fica em OUTRA pasta,
    para provar que o controle nao depende de --saida."""
    indice = tmp_path / "idx.sqlite"
    indice.write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "rag_index_path", str(indice))
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(mini_q02, "etapa_coleta", etapa)
    monkeypatch.setattr(mini_q02, "DIR_SAIDA", tmp_path / "ctrl")
    return tmp_path / "saida" / "respostas.json"


def test_b03_falha_inicial_registra_e_permite_repetir_uma_vez(tmp_path, monkeypatch, capsys):
    tentativas = []

    async def sempre_falha_inicial(gabarito, **kw):
        tentativas.append(1)
        exc = av.FalhaInicial("a 1a chamada falhou: detalhe do provedor")
        exc.erro_tipo = "TimeoutError"
        raise exc

    saida = _cli_executar_pronto(tmp_path, monkeypatch, sempre_falha_inicial)
    registro = mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_FALHA_INICIAL
    argv = ["--executar", "--orcamento", "0.10", "--saida", str(saida)]

    assert mini_q02.main(argv) == 2 and "pode repetir 1 vez" in capsys.readouterr().err
    assert [f["tentativa"] for f in mini_q02.ler_falhas_iniciais(registro)] == [1]
    # A 2a tentativa usa OUTRA --saida: o registro fixo segura do mesmo jeito.
    outra = ["--executar", "--orcamento", "0.10", "--saida", str(tmp_path / "outra" / "respostas.json")]
    assert mini_q02.main(outra) == 2 and "repeticao esgotada" in capsys.readouterr().err
    falhas = mini_q02.ler_falhas_iniciais(registro)
    assert [f["tentativa"] for f in falhas] == [1, 2] and {f["erro_tipo"] for f in falhas} == {"TimeoutError"}
    assert "detalhe do provedor" not in registro.read_text(encoding="utf-8")  # so o tipo vai para o disco
    # 3a vez: recusa ANTES de coletar (nao ha nova coleta nesta exploracao)
    assert mini_q02.main(argv) == 2 and "nao ha nova coleta" in capsys.readouterr().err
    assert len(tentativas) == 2 and not saida.exists()
    assert mini_q02.ler_coletas(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_COLETAS) == []  # FalhaInicial nao e coleta
    assert {f["estado"] for f in falhas} == {"falha_inicial"}


def test_b03_repeticao_bem_sucedida_registra_tentativa_e_aborto_sai_invalido(tmp_path, monkeypatch, capsys):
    async def coleta_ok(gabarito, **kw):
        return {"custo_usd": 0.07, "abortado_por_orcamento": False, "abortado_por_infra": None, "respostas": []}

    saida = _cli_executar_pronto(tmp_path, monkeypatch, coleta_ok)
    registro = mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_FALHA_INICIAL
    registro.parent.mkdir(parents=True)
    registro.write_text(json.dumps({"falhas_iniciais": [{"tentativa": 1, "erro_tipo": "TimeoutError"}]}),
                        encoding="utf-8")
    assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida)]) == 0
    gravado = json.loads(saida.read_text(encoding="utf-8"))
    assert gravado["tentativa"] == 2 and len(gravado["falhas_iniciais_anteriores"]) == 1
    coletas = mini_q02.ler_coletas(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_COLETAS)
    assert [(c["coleta"], c["estado"], c["saida"]) for c in coletas] == [(1, "concluida", str(saida))]
    # Coleta concluida: nova coleta recusada mesmo com OUTRA --saida.
    outra = tmp_path / "outra" / "respostas.json"
    assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(outra)]) == 2
    assert "ja houve uma coleta concluida" in capsys.readouterr().err and not outra.exists()

    # Coleta abortada no meio: grava o parcial (o fato fica registrado) e sai INVALIDO (codigo 1).
    (tmp_path / "b").mkdir()
    saida2 = _cli_executar_pronto(tmp_path / "b", monkeypatch, _coletas_falsas(["infra"]))
    assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida2)]) == 1
    assert saida2.is_file() and "INVALIDO" in capsys.readouterr().out


@pytest.mark.parametrize("interrupcao", [KeyboardInterrupt, SystemExit])
def test_b03_interrupcao_no_meio_deixa_marcador_e_bloqueia_nova_coleta(tmp_path, monkeypatch, capsys, interrupcao):
    chamadas = []

    async def interrompida(gabarito, **kw):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise interrupcao()  # Ctrl+C / kill: BaseException, nada gravado pelo script
        # Se uma guarda quebrada liberar nova coleta, ela "funciona" e o teste reprova limpo.
        return {"custo_usd": 0.01, "respostas": [], "abortado_por_orcamento": False, "abortado_por_infra": None}

    saida = _cli_executar_pronto(tmp_path, monkeypatch, interrompida)
    with pytest.raises(interrupcao):
        mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida)])
    coletas = mini_q02.ler_coletas(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_COLETAS)
    assert [c["estado"] for c in coletas] == ["iniciada"]  # o fato fica registrado

    for destino in (saida, tmp_path / "outra" / "respostas.json"):
        assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(destino)]) == 2
        assert "interrompida sem registro" in capsys.readouterr().err
    assert len(chamadas) == 1 and not saida.exists()


def test_b03_erro_de_pre_checagem_nao_deixa_marcador(tmp_path, monkeypatch, capsys):
    async def hash_mudou(gabarito, **kw):
        raise ValueError("sha256 do arquivo v4 mudou")  # pre-checagem: antes de qualquer chamada paga

    saida = _cli_executar_pronto(tmp_path, monkeypatch, hash_mudou)
    assert mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida)]) == 2
    assert mini_q02.ler_coletas(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_COLETAS) == []


# --- Emenda E-B03 (decisao do Max): parada com K = 1 e UMA nova coleta por infra ---

_PARADA_INFRA = {"indice_execucao": 9, "id": "q02", "versao": "v1", "amostra": 3, "erro_tipo": "TimeoutError"}


def _coletas_falsas(roteiro: list[str]):
    """etapa_coleta falsa: cada chamada segue o roteiro ("ok", "infra", "orcamento" ou "fi")."""
    chamadas: list[str] = []

    async def etapa(gabarito, **kw):
        acao = roteiro[len(chamadas)]
        chamadas.append(acao)
        if acao == "fi":
            exc = av.FalhaInicial("a 1a chamada falhou")
            exc.erro_tipo = "TimeoutError"
            raise exc
        return {"custo_usd": 0.01, "respostas": [], "abortado_por_orcamento": acao == "orcamento",
                "abortado_por_infra": dict(_PARADA_INFRA) if acao == "infra" else None}

    etapa.chamadas = chamadas
    return etapa


def _executar(saida) -> int:
    return mini_q02.main(["--executar", "--orcamento", "0.10", "--saida", str(saida)])


def _estados() -> list[str]:
    return [c["estado"] for c in mini_q02.ler_coletas(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_COLETAS)]


@pytest.mark.asyncio
@pytest.mark.parametrize("idx_falha", [2, 40])
async def test_b03_falha_de_infra_na_amostra_para_a_coleta_na_hora(ambiente_grafo, idx_falha):  # noqa: F811
    chamadas = []

    async def falha_em(graph, item):
        chamadas.append(item["id"])
        r = _resposta_ok(item)
        if len(chamadas) == idx_falha:  # o responder real devolve isto quando captura erro do grafo/provedor
            r.update({"falha_de_infra": True, "erro": "APITimeoutError: mensagem do provedor", "erros_llm": []})
        return r

    original_fn = rag_specialist.regras_da_etapa1
    dados = await mini_q02.etapa_coleta(GABARITO, graph_factory=lambda cp: object(), responder=falha_em,
                                        log=lambda *_: None)
    passo = mini_q02.sequencia_execucao()[idx_falha - 1]
    assert len(chamadas) == idx_falha and len(dados["respostas"]) == idx_falha  # parou na hora; a que falhou fica
    assert dados["abortado_por_infra"] == {"indice_execucao": idx_falha, "id": passo["id"], "versao": passo["versao"],
                                           "amostra": passo["amostra"], "erro_tipo": "APITimeoutError"}
    assert "mensagem do provedor" not in json.dumps(dados["abortado_por_infra"])
    assert rag_specialist.regras_da_etapa1 is original_fn and settings.rag_regras_versao == "v1"
    # e o --resultado desse respostas.json e INVALIDO
    problemas = mini_q02._checar_integridade(dados, {"elo": "x"}, {"elo": "x"}, indice_meta_m8=None,
                                             caminho_v4=mini_q02.CAMINHO_PROPOSTA_V4)
    assert any("coleta abortada por falha de infra" in p for p in problemas)
    assert any("falha de infra (Emenda E-B03" in p for p in problemas)


def test_b03_nova_coleta_por_infra_liberada_uma_vez_e_a_2a_invalida_encerra(tmp_path, monkeypatch, capsys):
    etapa = _coletas_falsas(["infra", "infra"])
    s1 = _cli_executar_pronto(tmp_path, monkeypatch, etapa)
    assert _executar(s1) == 1 and _estados() == ["invalida_infra_1a"]
    out = capsys.readouterr().out
    assert "UMA nova coleta completa" in out and "REGISTRAR NO PRE-REGISTRO" in out and "amostra 3" in out
    assert _executar(s1) == 2 and "ja existe" in capsys.readouterr().err  # exige OUTRA --saida
    s2 = tmp_path / "coleta2" / "respostas.json"
    assert _executar(s2) == 1 and _estados() == ["invalida_infra_1a", "invalida_infra_2a_encerra"]
    assert "ENCERRADA sem resultado" in capsys.readouterr().out
    assert json.loads(s2.read_text(encoding="utf-8"))["coleta"] == 2
    assert _executar(tmp_path / "coleta3" / "respostas.json") == 2  # nao ha 3a
    assert "encerrada sem resultado" in capsys.readouterr().err
    assert etapa.chamadas == ["infra", "infra"]


def test_b03_nova_coleta_por_infra_bem_sucedida_e_depois_nada(tmp_path, monkeypatch, capsys):
    etapa = _coletas_falsas(["infra", "ok"])
    _cli_executar_pronto(tmp_path, monkeypatch, etapa)
    assert _executar(tmp_path / "c1" / "respostas.json") == 1
    s2 = tmp_path / "c2" / "respostas.json"
    assert _executar(s2) == 0 and _estados() == ["invalida_infra_1a", "concluida"]
    gravado = json.loads(s2.read_text(encoding="utf-8"))
    assert gravado["coleta"] == 2 and gravado["coletas_anteriores"][0]["parou_em"] == _PARADA_INFRA
    assert _executar(tmp_path / "c3" / "respostas.json") == 2 and etapa.chamadas == ["infra", "ok"]


def test_b03_aborto_por_orcamento_nao_libera_nova_coleta(tmp_path, monkeypatch, capsys):
    etapa = _coletas_falsas(["orcamento", "ok"])
    _cli_executar_pronto(tmp_path, monkeypatch, etapa)
    assert _executar(tmp_path / "c1" / "respostas.json") == 1 and _estados() == ["invalida_orcamento"]
    assert "orcamento: sem direito a nova coleta" in capsys.readouterr().out
    assert _executar(tmp_path / "c2" / "respostas.json") == 2
    assert "INVALIDA por orcamento" in capsys.readouterr().err and etapa.chamadas == ["orcamento"]


@pytest.mark.parametrize(
    ("roteiro", "estados_finais", "n_falhas_iniciais"),
    [
        (["fi", "infra", "ok"], ["invalida_infra_1a", "concluida"], 1),  # FalhaInicial nao consome a nova coleta
        (["infra", "fi", "ok"], ["invalida_infra_1a", "concluida"], 1),  # a nova coleta nao consome a FalhaInicial
    ],
    ids=["falha-inicial-depois-infra", "infra-depois-falha-inicial"],
)
def test_b03_falha_inicial_e_nova_coleta_por_infra_nao_se_somam(tmp_path, monkeypatch, capsys, roteiro,
                                                                estados_finais, n_falhas_iniciais):
    etapa = _coletas_falsas(roteiro)
    _cli_executar_pronto(tmp_path, monkeypatch, etapa)
    codigos = [_executar(tmp_path / f"c{i}" / "respostas.json") for i in range(1, len(roteiro) + 1)]
    assert codigos == [{"fi": 2, "infra": 1, "ok": 0}[a] for a in roteiro]
    assert etapa.chamadas == roteiro and _estados() == estados_finais
    falhas = mini_q02.ler_falhas_iniciais(mini_q02.DIR_SAIDA / mini_q02.NOME_REGISTRO_FALHA_INICIAL)
    assert len(falhas) == n_falhas_iniciais and falhas[0]["estado"] == "falha_inicial"


def test_b03_decidir_nova_coleta_distingue_os_estados():
    pode = mini_q02.decidir_nova_coleta
    assert pode([])[0] is True
    assert pode([{"estado": "invalida_infra_1a"}])[0] is True
    for historico in ([{"estado": "iniciada"}], [{"estado": "concluida"}], [{"estado": "invalida_orcamento"}],
                      [{"estado": "invalida_infra_1a"}, {"estado": "invalida_infra_2a_encerra"}],
                      [{"estado": "invalida_infra_1a"}, {"estado": "iniciada"}],
                      [{"estado": "invalida_infra_1a"}, {"estado": "invalida_infra_1a"}]):
        assert pode(historico)[0] is False, historico
