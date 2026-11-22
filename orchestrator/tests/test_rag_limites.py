"""Ferramenta de limites - Parte 1: temperaturas (docs/RAG.md, "Ferramenta de limites").

A prova do "100 de 100", sem LLM nenhum:

1. ORACULO INDEPENDENTE: as 7 regras reescritas a mao, com if/else, sem ler o
   YAML nem chamar o modulo, comparadas com `verificar_temperatura` numa grade
   de −30 °C a +30 °C (passo 0,5) por regra, mais cada limite exato e
   limite ± 0,1. O numero de casos e conferido (grade vazia nao passa).
2. Os casos do erro real (q02: frango congelado a −10 °C), com "-" e "−".
3. `ler_temperatura`: entradas aceitas e as que TEM de dar None.
4. SEM_REGRA para categoria/contexto desconhecidos (nunca a regra parecida).
5. A tabela contra os POPs: cada trecho_literal existe, byte a byte, na secao
   de origem; o sha256 de cada secao bate (editou o POP -> quebra); cada
   limite numerico aparece no trecho; cada °C das secoes tem regra.
6. "Teste que nunca falha e bug": cada protecao e quebrada numa COPIA
   (modulo, YAML ou POP em tmp) e a mesma verificacao tem de acusar.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from orchestrator.rag import limites
from orchestrator.rag.chunking import chunk_markdown

ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
TABELA = ORCHESTRATOR_DIR / "fixtures" / "rag" / "limites" / "temperaturas_v1.yaml"
CORPUS = ORCHESTRATOR_DIR / "fixtures" / "rag" / "supermercado"
D = Decimal
MENOS = "−"  # o sinal de menos unicode que os POPs usam

# =============================================================================
# 1. Oraculo independente (escrito a mao a partir dos POPs; NAO usa o YAML)
# =============================================================================


def oraculo(contexto: str, categoria: str, v: Decimal) -> str:
    """POP-01 secao 4 (tabela "Aceitar até") e POP-05 secao 4, reescritos a mao."""
    if contexto == "recebimento":
        if categoria == "congelados":
            return "DENTRO" if v <= D("-12") else "FORA"
        if categoria == "resfriados":
            return "DENTRO" if v <= D("7") else "FORA"
        if categoria == "laticinios":
            return "DENTRO" if v <= D("10") else "FORA"
        if categoria == "frios_fatiados":
            return "DENTRO" if v <= D("8") else "FORA"
        return "SEM_REGRA"
    if contexto == "armazenamento":
        if categoria == "congelados":
            return "DENTRO" if v <= D("-18") else "FORA"
        if categoria == "resfriados":
            return "DENTRO" if D("0") <= v <= D("4") else "FORA"
        if categoria == "laticinios_e_frios":
            return "DENTRO" if D("0") <= v <= D("8") else "FORA"
        return "SEM_REGRA"
    return "SEM_REGRA"


# (contexto, categoria) -> (min, max, como o max/min aparece na frase, pop, secao), tambem a mao.
SEC_01 = ("POP-01", "4. Temperatura na chegada")
SEC_05 = ("POP-05", "4. Temperatura de armazenamento e exposição")
REGRAS_A_MAO = {
    ("recebimento", "congelados"): (None, D("-12"), f"{MENOS}12 °C", None, *SEC_01),
    ("recebimento", "resfriados"): (None, D("7"), "7 °C", None, *SEC_01),
    ("recebimento", "laticinios"): (None, D("10"), "10 °C", None, *SEC_01),
    ("recebimento", "frios_fatiados"): (None, D("8"), "8 °C", None, *SEC_01),
    ("armazenamento", "congelados"): (None, D("-18"), f"{MENOS}18 °C", None, *SEC_05),
    ("armazenamento", "resfriados"): (D("0"), D("4"), "4 °C", "0 °C", *SEC_05),
    ("armazenamento", "laticinios_e_frios"): (D("0"), D("8"), "8 °C", "0 °C", *SEC_05),
}
FIM = {
    "recebimento": ("aceitar", "recusar"),
    "armazenamento": ("dentro da faixa", "fora da faixa"),
}

# Grade exata em Decimal (nada de float): −30, −29,5, ..., +30 -> 121 valores.
GRADE = [D("-30") + n * D("0.5") for n in range(121)]
DECIMO = D("0.1")


def _pontas(minimo, maximo) -> list[Decimal]:
    pontas = [maximo, maximo - DECIMO, maximo + DECIMO]
    if minimo is not None:
        pontas += [minimo, minimo - DECIMO, minimo + DECIMO]
    return pontas


def _direcao_esperada(v, minimo, maximo) -> str:
    if v > maximo:
        return "ACIMA"
    if minimo is not None and v < minimo:
        return "ABAIXO"
    if v == maximo or (minimo is not None and v == minimo):
        return "IGUAL"
    return "ENTRE" if minimo is not None else "ABAIXO"


def _tem_celsius(frase: str, numero: str) -> bool:
    """`numero` ("7 °C") inteiro na frase: "7 °C" nao vale dentro de "−27 °C" ou "1,7 °C"."""
    return (
        re.search(r"(?<![\d" + MENOS + r"\-,])" + re.escape(numero), frase) is not None
    )


def comparar_com_oraculo(verificar) -> tuple[int, list[str]]:
    """Roda a grade + pontas de cada regra. Devolve (casos rodados, divergencias)."""
    rodados, divergencias = 0, []
    for (ctx, cat), (
        minimo,
        maximo,
        max_txt,
        min_txt,
        pop,
        secao,
    ) in REGRAS_A_MAO.items():
        for v in GRADE + _pontas(minimo, maximo):
            rodados += 1
            esperado = oraculo(ctx, cat, v)
            try:
                r = verificar(ctx, cat, v)
            except Exception as e:  # noqa: BLE001 - mutante que quebra tambem diverge
                divergencias.append(f"{ctx}/{cat} {v}: erro {type(e).__name__}: {e}")
                continue
            fim = FIM[ctx][0] if esperado == "DENTRO" else FIM[ctx][1]
            direcao = _direcao_esperada(v, minimo, maximo)
            problemas = []
            if r.veredito.value != esperado:
                problemas.append(f"veredito {r.veredito.value} != {esperado}")
            if not r.frase.endswith(f": {fim}"):
                problemas.append(f"frase nao termina em {fim!r}")
            if f" {direcao} " not in r.frase:
                problemas.append(f"frase sem {direcao!r}")
            if not _tem_celsius(r.frase, max_txt) or (
                min_txt and direcao != "ACIMA" and not _tem_celsius(r.frase, min_txt)
            ):
                problemas.append("frase sem o limite")
            if (r.pop, r.secao) != (pop, secao):
                problemas.append(f"fonte {(r.pop, r.secao)}")
            if (
                r.limite is None
                or not isinstance(r.limite.max, Decimal)
                or r.limite.max != maximo
            ):
                problemas.append(f"limite.max {getattr(r.limite, 'max', None)!r}")
            elif minimo is not None and (
                not isinstance(r.limite.min, Decimal) or r.limite.min != minimo
            ):
                problemas.append(f"limite.min {r.limite.min!r}")
            if not isinstance(r.valor, Decimal) or r.valor != v:
                problemas.append(f"valor {r.valor!r}")
            if problemas:
                divergencias.append(
                    f"{ctx}/{cat} {v}: {'; '.join(problemas)} | {r.frase}"
                )
    return rodados, divergencias


CASOS_ESPERADOS = 7 * len(GRADE) + 5 * 3 + 2 * 6  # 847 da grade + 27 das pontas = 874


def test_oraculo_independente_bate_100_por_cento(capsys):
    rodados, divergencias = comparar_com_oraculo(limites.verificar_temperatura)
    with capsys.disabled():
        print(
            f"\n[oraculo] {rodados} casos rodados, {rodados - len(divergencias)} bateram"
        )
    assert rodados == CASOS_ESPERADOS == 874
    assert divergencias == []


def test_sinonimos_caem_na_mesma_regra_da_categoria():
    tabela = limites.carregar_tabela(TABELA)
    for regra in tabela.regras:
        for nome in regra.sinonimos:
            for v in (D("-20"), regra.limite.max, regra.limite.max + DECIMO):
                a = limites.verificar_temperatura(regra.contexto, nome, v)
                b = limites.verificar_temperatura(regra.contexto, regra.categoria, v)
                assert (a.regra_id, a.veredito) == (regra.id, b.veredito), (
                    regra.id,
                    nome,
                    v,
                )
    # os exemplos do pedido, a mao
    assert limites.verificar_temperatura(
        "recebimento", "frango congelado", D("-10")
    ).regra_id == ("recebimento-congelados")
    assert limites.verificar_temperatura(
        "recebimento", "Carne Resfriada", D("5")
    ).regra_id == ("recebimento-resfriados")


# =============================================================================
# 2. O erro real (q02) e a precisao
# =============================================================================


@pytest.mark.parametrize("sinal", ["-", MENOS])
@pytest.mark.parametrize(
    ("numero", "veredito", "fim"),
    [
        ("10", "FORA", "recusar"),
        ("12", "DENTRO", "aceitar"),
        ("12,1", "DENTRO", "aceitar"),
        ("11,9", "FORA", "recusar"),
    ],
)
def test_caso_real_frango_congelado(sinal, numero, veredito, fim):
    valor = limites.ler_temperatura(f"{sinal}{numero}")
    assert valor == -D(numero.replace(",", "."))
    r = limites.verificar_temperatura("recebimento", "congelados", valor)
    assert r.veredito.value == veredito
    assert r.frase.endswith(f": {fim}")
    assert (r.pop, r.secao) == SEC_01


def test_caso_real_frase_inteira_da_q02():
    valor = limites.ler_temperatura(
        "chegou frango congelado marcando -10 graus no termometro, aceito?"
    )
    r = limites.verificar_temperatura("recebimento", "frango congelado", valor)
    assert (
        r.frase
        == f"{MENOS}10 °C está ACIMA de {MENOS}12 °C, o máximo para congelados no recebimento: recusar"
    )
    assert any("descongelamento" in s for s in r.ressalvas)


@pytest.mark.parametrize(
    ("ctx", "cat", "valor", "esperado"),
    [
        # float arredonda estes para o limite e erraria o veredito
        ("recebimento", "congelados", "-11.99999999999999999999", "FORA"),
        ("recebimento", "congelados", "-12.00000000000000000001", "DENTRO"),
        ("recebimento", "resfriados", "7.0000000000000000001", "FORA"),
        ("armazenamento", "resfriados", "4.0000000000000000001", "FORA"),
        ("armazenamento", "laticinios_e_frios", "8.00000000000000000001", "FORA"),
    ],
)
def test_precisao_decimal_onde_float_erraria(ctx, cat, valor, esperado):
    assert float(D(valor)) == float(
        round(D(valor))
    )  # o caso existe: float perde a diferenca
    assert limites.verificar_temperatura(ctx, cat, D(valor)).veredito.value == esperado


def test_tipos_decimal_e_recusa_de_float():
    assert isinstance(limites.ler_temperatura("-10,5"), Decimal)
    for regra in limites.carregar_tabela(TABELA).regras:
        assert isinstance(regra.limite.max, Decimal)
        assert regra.limite.min is None or isinstance(regra.limite.min, Decimal)
    for ruim in (-10.0, True, "-10", None):
        with pytest.raises(TypeError):
            limites.verificar_temperatura("recebimento", "congelados", ruim)
    for nao_finito in (D("NaN"), D("Infinity"), D("-Infinity")):
        with pytest.raises(ValueError):
            limites.verificar_temperatura("recebimento", "congelados", nao_finito)
    assert (
        limites.verificar_temperatura("recebimento", "congelados", -13).veredito.value
        == "DENTRO"
    )  # int ok


# =============================================================================
# 3. ler_temperatura
# =============================================================================

ACEITAS = [
    ("-10", "-10"),
    (f"{MENOS}10", "-10"),
    ("-10,5", "-10.5"),
    ("-10.5", "-10.5"),
    ("-10 graus", "-10"),
    (f"{MENOS}10 °C", "-10"),
    (f"{MENOS}10 °C", "-10"),  # espaco nao separavel
    ("-10 ºC", "-10"),  # "º" ordinal, comum no teclado
    ("-10°C", "-10"),
    ("menos 10", "-10"),
    ("Menos 10 graus", "-10"),
    ("10 negativos", "-10"),
    ("10 graus negativos", "-10"),
    ("4", "4"),
    ("+4", "4"),
    ("4,5 graus", "4.5"),
    ("0", "0"),
    ("-0,5", "-0.5"),
    ("o termometro marcou -18 graus.", "-18"),
    ("chegou frango congelado marcando -10 graus no termometro, aceito?", "-10"),
]

RECUSADAS = [
    "dez graus negativos",  # por extenso
    "uns -10",  # aproximacao
    "cerca de -10",
    "aproximadamente -10",
    "mais ou menos 10",  # contem "menos 10", mas e aproximacao
    "quase -12",
    "menos de 10",  # comparacao, nao "−10"
    "abaixo de -10",
    "acima de 4",
    "até -12",
    "10 abaixo de zero",  # fora da lista pedida: na duvida, None
    "sem número nenhum",
    "",
    "-10 a -12",  # faixa
    "entre -10 e -12",
    "-10 ou -12",
    "3 volumes a -10",  # dois numeros
    "pop-01 marcou -10",
    "-10 negativos",  # duplo negativo
    "menos 10 negativos",
    "menos -10",
    "--10",
    "-10 positivos",
    "–10",  # traco "–" (en dash): sinal ou faixa? None
    "—10",
    "- 10",  # sinal solto ou marcador de lista?
    "-10°F",
    "-10 fahrenheit",
    "1.000",  # milhar?
    "10,555",  # 3 casas
    "1000",
    "nan",
    "inf",
    "-10x",
    "x-10",
    "temperatura negativa de 10",  # marcador longe do numero
    f"{MENOS}18 °C ou menos",
]


@pytest.mark.parametrize(("texto", "esperado"), ACEITAS)
def test_ler_temperatura_aceita(texto, esperado):
    valor = limites.ler_temperatura(texto)
    assert isinstance(valor, Decimal)
    assert valor == D(esperado)


@pytest.mark.parametrize("texto", RECUSADAS)
def test_ler_temperatura_na_duvida_devolve_none(texto):
    assert limites.ler_temperatura(texto) is None


def test_ler_temperatura_recusa_nao_texto():
    with pytest.raises(TypeError):
        limites.ler_temperatura(None)  # type: ignore[arg-type]


# =============================================================================
# 4. SEM_REGRA
# =============================================================================

DESCONHECIDOS = [
    ("recebimento", "queijo"),  # laticinio ou frio fatiado? ambiguo de proposito
    ("recebimento", "hortifrúti"),  # "sem limite" no POP-01
    ("recebimento", "frios"),  # o POP-01 so tem "frios fatiados"
    ("recebimento", "frango resfriado"),
    ("recebimento", "congeladoss"),
    ("recebimento", "congelad"),
    ("recebimento", "laticinios_e_frios"),  # categoria so do armazenamento
    ("recebimento", ""),
    ("armazenamento", "queijo"),
    ("armazenamento", "hortifruti"),
    ("armazenamento", "frios fatiadoss"),
    ("exposição", "congelados"),
    ("transporte", "congelados"),
    ("", "congelados"),
    ("recebimentos", "congelados"),
]


def problemas_sem_regra(verificar) -> list[str]:
    erros = []
    for ctx, cat in DESCONHECIDOS:
        for v in (D("-30"), D("-12"), D("0"), D("5"), D("30")):
            r = verificar(ctx, cat, v)
            if (
                r.veredito.value != "SEM_REGRA"
                or r.limite is not None
                or r.pop is not None
            ):
                erros.append(f"{ctx}/{cat} {v}: {r.veredito.value} ({r.regra_id})")
            elif "não sei" not in r.frase:
                erros.append(f"{ctx}/{cat}: frase sem 'não sei'")
    return erros


def test_sem_regra_para_desconhecidos():
    assert problemas_sem_regra(limites.verificar_temperatura) == []


# =============================================================================
# 5. A tabela contra os POPs
# =============================================================================


def _celsius_como_no_pop(texto_decimal: str) -> str:
    return texto_decimal.replace("-", MENOS) + " °C"


def problemas_de_integridade(tabela: Path, corpus: Path) -> list[str]:
    dados = yaml.safe_load(tabela.read_text(encoding="utf-8"))
    problemas: list[str] = []
    secoes: dict[tuple[str, str], str] = {}
    for fonte in dados["secoes_fonte"]:
        arquivo, secao = fonte["arquivo"], fonte["secao"]
        caminho = corpus / arquivo
        if not caminho.exists():
            problemas.append(f"{arquivo}: arquivo nao existe")
            continue
        achados = [
            c
            for c in chunk_markdown(caminho.read_text(encoding="utf-8"), arquivo, "x")
            if c.secao == secao
        ]
        if len(achados) != 1:
            problemas.append(
                f"{arquivo}: secao {secao!r} nao encontrada (titulo exato)"
            )
            continue
        texto = achados[0].texto
        secoes[(arquivo, secao)] = texto
        if hashlib.sha256(texto.encode("utf-8")).hexdigest() != fonte["sha256"]:
            problemas.append(
                f"{arquivo} / {secao}: sha256 mudou - o POP foi editado, revise a tabela"
            )
        if not caminho.name.upper().startswith(fonte["pop"]):
            problemas.append(f"{arquivo}: pop {fonte['pop']} nao bate com o arquivo")

    for regra in dados["regras"]:
        rid = regra["id"]
        chave = (regra["arquivo"], regra["secao"])
        if chave not in secoes:
            problemas.append(f"{rid}: secao de origem sem sha256 em secoes_fonte")
            continue
        texto_secao = secoes[chave]
        texto_arquivo = (corpus / regra["arquivo"]).read_text(encoding="utf-8")
        trechos = list(regra["trecho_literal"]) + list(regra.get("ressalvas") or [])
        for trecho in trechos:
            if trecho not in texto_arquivo:
                problemas.append(f"{rid}: trecho_literal nao existe no POP: {trecho!r}")
            elif trecho not in texto_secao:
                problemas.append(
                    f"{rid}: trecho_literal fora da secao {regra['secao']!r}"
                )
        for campo in ("min", "max"):
            if campo not in regra:
                continue
            numero = _celsius_como_no_pop(str(regra[campo]))
            padrao = re.compile(r"(?<![\d" + MENOS + r"\-,])" + re.escape(numero))
            if not any(padrao.search(t) for t in regra["trecho_literal"]):
                problemas.append(
                    f"{rid}: {campo} {regra[campo]!r} ({numero}) nao aparece no trecho_literal"
                )

    # Toda temperatura escrita nas secoes de origem e limite de alguma regra dela.
    for (arquivo, secao), texto in secoes.items():
        limites_da_secao = {
            _celsius_como_no_pop(str(r[c]))
            for r in dados["regras"]
            if (r["arquivo"], r["secao"]) == (arquivo, secao)
            for c in ("min", "max")
            if c in r
        }
        for m in re.finditer(r"[" + MENOS + r"\-]?\d+(?:,\d+)? °C", texto):
            if m.group() not in limites_da_secao:
                problemas.append(
                    f"{arquivo} / {secao}: {m.group()} no POP sem regra na tabela"
                )
    return problemas


def test_tabela_bate_com_os_pops():
    assert problemas_de_integridade(TABELA, CORPUS) == []


def test_tabela_carrega_e_tem_as_7_regras():
    tabela = limites.carregar_tabela(TABELA)
    assert {(r.contexto, r.categoria) for r in tabela.regras} == set(REGRAS_A_MAO)
    assert len(tabela.regras) == 7


@pytest.mark.parametrize(
    ("original", "quebrado", "mensagem"),
    [
        ('max: "-12"', "max: -12", "string"),  # numero cru do YAML (int/float)
        ('max: "7"', "max: 7.0", "string"),
        (
            'tipo: faixa\n    min: "0"\n    max: "4"',
            'tipo: faixa\n    min: "4"\n    max: "0"',
            "min >= max",
        ),
        (
            'tipo: faixa\n    min: "0"\n    max: "4"',
            'tipo: faixa\n    max: "4"',
            "precisa de 'min'",
        ),
        ('tipo: maximo\n    max: "7"', 'tipo: minimo\n    max: "7"', "tipo"),
        (
            '    inclusivo: true\n    inclusivo_porque: >-\n      "Aceitar até 7',
            '    inclusivo: 1\n    inclusivo_porque: >-\n      "Aceitar até 7',
            "true/false",
        ),
        (
            "sinonimos: [laticínio, laticínios, iogurte]",
            "sinonimos: [laticínio, laticínios, iogurte, presunto fatiado]",
            "duas regras",
        ),
        ('max: "-18"', 'max: "NaN"', "finito"),
    ],
)
def test_carregador_recusa_tabela_malformada(tmp_path, original, quebrado, mensagem):
    texto = TABELA.read_text(encoding="utf-8")
    assert texto.count(original) == 1, original
    copia = tmp_path / "t.yaml"
    copia.write_text(texto.replace(original, quebrado), encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(mensagem)):
        limites.carregar_tabela(copia)


# =============================================================================
# 6. Mutantes: cada protecao, quebrada numa COPIA, tem de ser acusada
# =============================================================================


def _modulo_mutante(monkeypatch, original: str, novo: str):
    """Copia do limites.py com UMA troca, carregada como modulo separado."""
    fonte = Path(limites.__file__).read_text(encoding="utf-8")
    assert fonte.count(original) == 1, (
        f"trecho do mutante sumiu do limites.py: {original!r}"
    )
    mod = types.ModuleType("orchestrator.rag._limites_mutante")
    mod.__file__ = limites.__file__
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    # so o proprio limites.py, com uma troca escrita neste arquivo
    exec(compile(fonte.replace(original, novo), limites.__file__, "exec"), mod.__dict__)  # noqa: S102
    return mod


def _tabela_mutante(tmp_path, original: str, novo: str) -> Path:
    texto = TABELA.read_text(encoding="utf-8")
    assert texto.count(original) == 1, f"trecho do mutante sumiu do YAML: {original!r}"
    copia = tmp_path / "temperaturas_mutante.yaml"
    copia.write_text(texto.replace(original, novo), encoding="utf-8")
    return copia


def _verificar_com(tabela_path: Path, mod=limites):
    tabela = mod.carregar_tabela(tabela_path)
    return lambda ctx, cat, v: mod.verificar_temperatura(ctx, cat, v, tabela=tabela)


def _casos_reais_falham(mod) -> bool:
    """O teste do erro real (q02) acusaria o mutante?"""
    for sinal in ("-", MENOS):
        for numero, esperado in (
            ("10", "FORA"),
            ("12", "DENTRO"),
            ("12,1", "DENTRO"),
            ("11,9", "FORA"),
        ):
            v = mod.ler_temperatura(f"{sinal}{numero}")
            if v != -D(numero.replace(",", ".")):
                return True
            if (
                mod.verificar_temperatura("recebimento", "congelados", v).veredito.value
                != esperado
            ):
                return True
    return False


def test_mutante_sinal_invertido_no_yaml(tmp_path):
    copia = _tabela_mutante(tmp_path, 'max: "-12"', 'max: "12"')
    _, divergencias = comparar_com_oraculo(_verificar_com(copia))
    assert divergencias, "oraculo nao viu o sinal invertido"
    assert any(
        "nao aparece no trecho_literal" in p
        for p in problemas_de_integridade(copia, CORPUS)
    )


def test_mutante_sinal_perdido_na_leitura(monkeypatch):
    mod = _modulo_mutante(
        monkeypatch, "return -valor if negativo else valor", "return valor"
    )
    assert _casos_reais_falham(mod)
    assert any(mod.ler_temperatura(t) != D(e) for t, e in ACEITAS)


def test_mutante_inclusivo_trocado_no_yaml(tmp_path):
    copia = _tabela_mutante(
        tmp_path, 'max: "-12"\n    inclusivo: true', 'max: "-12"\n    inclusivo: false'
    )
    _, divergencias = comparar_com_oraculo(_verificar_com(copia))
    assert any("recebimento/congelados -12:" in d for d in divergencias)


def test_mutante_inclusivo_trocado_no_codigo(monkeypatch):
    mod = _modulo_mutante(
        monkeypatch,
        'if valor > lim.max:\n            return False, f"{v} está ACIMA de {mx}, o máximo"',
        'if valor >= lim.max:\n            return False, f"{v} está ACIMA de {mx}, o máximo"',
    )
    _, divergencias = comparar_com_oraculo(_verificar_com(TABELA, mod))
    assert divergencias
    assert _casos_reais_falham(mod)  # −12 viraria "recusar"


def test_mutante_regra_mais_parecida_no_lugar_de_sem_regra(monkeypatch):
    mod = _modulo_mutante(
        monkeypatch,
        "    if regra is None:\n        return _sem_regra(contexto, categoria, valor)",
        "    if regra is None and ctx in CONTEXTOS:\n"
        "        import difflib\n"
        "        nomes = [k[1] for k in tab.indice if k[0] == ctx]\n"
        "        perto = difflib.get_close_matches(normalizar_nome(categoria), nomes, n=1, cutoff=0.0)\n"
        "        regra = tab.indice[(ctx, perto[0])] if perto else None\n"
        "    if regra is None:\n        return _sem_regra(contexto, categoria, valor)",
    )
    assert problemas_sem_regra(mod.verificar_temperatura)


def test_mutante_float_no_valor(monkeypatch):
    mod = _modulo_mutante(
        monkeypatch,
        "    valor = Decimal(valor)\n",
        "    valor = Decimal(float(valor))\n",
    )
    erros = [
        (ctx, cat, v)
        for ctx, cat, v, esperado in (
            ("recebimento", "congelados", "-11.99999999999999999999", "FORA"),
            ("recebimento", "resfriados", "7.0000000000000000001", "FORA"),
        )
        if mod.verificar_temperatura(ctx, cat, D(v)).veredito.value != esperado
    ]
    assert erros, "o teste de precisao nao pegou o float"


def test_mutante_float_nos_limites(monkeypatch):
    mod = _modulo_mutante(
        monkeypatch,
        'limite=Limite(tipo=tipo, min=minimo, max=maximo, inclusivo=bruta["inclusivo"])',
        "limite=Limite(tipo=tipo, min=None if minimo is None else float(minimo), max=float(maximo), "
        'inclusivo=bruta["inclusivo"])',
    )
    regras = mod.carregar_tabela(TABELA).regras
    assert not all(
        isinstance(r.limite.max, Decimal) for r in regras
    )  # o que test_tipos_decimal_... confere
    _, divergencias = comparar_com_oraculo(_verificar_com(TABELA, mod))
    assert divergencias


def test_mutante_trecho_literal_adulterado(tmp_path):
    # Troca o "−" (U+2212) do POP por "-" ASCII: o tipo de deriva que digitar a mao causa.
    copia = _tabela_mutante(
        tmp_path,
        f'"| Congelados           | {MENOS}12 °C      |',
        '"| Congelados           | -12 °C      |',
    )
    problemas = problemas_de_integridade(copia, CORPUS)
    assert any("trecho_literal nao existe no POP" in p for p in problemas)


def test_mutante_pop_editado(tmp_path):
    corpus = tmp_path / "supermercado"
    shutil.copytree(CORPUS, corpus)
    pop = corpus / "pop-01-recebimento-de-mercadorias.md"
    texto = pop.read_text(encoding="utf-8")
    # Edicao que NAO toca nenhum trecho_literal: so o sha256 da secao pode pegar.
    assert texto.count("**3 volumes por lote**") == 1
    pop.write_text(
        texto.replace("**3 volumes por lote**", "**5 volumes por lote**"),
        encoding="utf-8",
    )
    problemas = problemas_de_integridade(TABELA, corpus)
    assert problemas and all("sha256 mudou" in p for p in problemas)


def test_mutante_pop_ganha_temperatura_sem_regra(tmp_path):
    corpus = tmp_path / "supermercado"
    shutil.copytree(CORPUS, corpus)
    pop = corpus / "pop-05-higienizacao-e-seguranca-alimentar.md"
    texto = pop.read_text(encoding="utf-8")
    linha = "- Laticínios e frios: de **0 °C a 8 °C**."
    pop.write_text(
        texto.replace(linha, linha + "\n- Bebidas: até 12 °C."), encoding="utf-8"
    )
    problemas = problemas_de_integridade(TABELA, corpus)
    assert any("12 °C no POP sem regra" in p for p in problemas)
