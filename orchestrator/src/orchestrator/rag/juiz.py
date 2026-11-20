"""Juiz LLM da Missao 8 (avaliacao de ponta a ponta do RAG, docs/RAG.md).

Dois prompts CONGELADOS, cada um num arquivo com hash registrado aqui:

- `fixtures/rag/juiz_fidelidade_v1.md` (metrica d): ve SO a pergunta, os
  trechos recuperados e a resposta crua. Nunca o gabarito;
- `fixtures/rag/juiz_correcao_v1.md` (metrica f, e o julgamento das
  sem_resposta na metrica e): ve a pergunta, o gabarito e a resposta crua.
  Nao ve os trechos.

O modelo e de OUTRO provedor (Google, via OpenRouter) que o que responde
(DeepSeek), temperatura 0, raciocinio "low" fixo e saida em JSON schema.
Mudar prompt, modelo ou parametros = novo pre-registro (v2), nunca editar o v1.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from orchestrator.rag.ingest import ORCHESTRATOR_DIR

JUIZ_MODELO = "google/gemini-3.8-flash"
JUIZ_TEMPERATURA = 0
JUIZ_REASONING_EFFORT = "low"

PROMPT_FIDELIDADE = ORCHESTRATOR_DIR / "fixtures" / "rag" / "juiz_fidelidade_v1.md"
PROMPT_CORRECAO = ORCHESTRATOR_DIR / "fixtures" / "rag" / "juiz_correcao_v1.md"
# sha256 dos arquivos acima, registrados no pre-registro da Missao 8 (docs/RAG.md).
HASH_PROMPT_FIDELIDADE = "3657408ae718107075f778f840376293baeea06f9fe18871574b1d7e4ffc63be"
HASH_PROMPT_CORRECAO = "8cf37eb0cce76c11a28211be7e99075cb5b2bbddcebb82b1aabd7702ecd04a80"

# Campos do gabarito que o juiz de FIDELIDADE nunca pode receber.
CAMPOS_DO_GABARITO = ("resposta_esperada", "criterio_acerto", "aceita_tambem")

_SECOES = re.compile(r"^=== (SISTEMA|USUARIO|SCHEMA) ===$", re.MULTILINE)
# Delimitadores dos prompts: dado que tente fechar/abrir um bloco e neutralizado.
_TAG_FORJADA = re.compile(r"<\s*/?\s*(pergunta|trechos|trecho|resposta|gabarito|criterio|aceita_tambem)\b", re.IGNORECASE)


class PromptAdulterado(RuntimeError):
    """O arquivo do prompt nao bate com o hash pre-registrado."""


def sha256_arquivo(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class PromptJuiz:
    nome: str
    sistema: str
    usuario: str
    schema: dict
    hash: str


def carregar_prompt(path: Path, hash_esperado: str, nome: str) -> PromptJuiz:
    """Le o prompt congelado e RECUSA se o hash nao for o pre-registrado."""
    atual = sha256_arquivo(path)
    if atual != hash_esperado:
        raise PromptAdulterado(
            f"prompt do juiz {nome} ({path.name}) mudou: sha256 {atual} != pre-registrado {hash_esperado}. "
            "Mudar o prompt exige um v2 com novo pre-registro."
        )
    texto = Path(path).read_text(encoding="utf-8")
    partes = _SECOES.split(texto)
    secoes = {partes[i]: partes[i + 1].strip() for i in range(1, len(partes) - 1, 2)}
    return PromptJuiz(nome, secoes["SISTEMA"], secoes["USUARIO"], json.loads(secoes["SCHEMA"]), atual)


def prompt_fidelidade() -> PromptJuiz:
    return carregar_prompt(PROMPT_FIDELIDADE, HASH_PROMPT_FIDELIDADE, "fidelidade")


def prompt_correcao() -> PromptJuiz:
    return carregar_prompt(PROMPT_CORRECAO, HASH_PROMPT_CORRECAO, "correcao")


def _dado(texto: str | None) -> str:
    return _TAG_FORJADA.sub("[delimitador removido]", texto or "")


def formatar_trechos(trechos: list[dict]) -> str:
    if not trechos:
        return "(nenhum trecho foi recuperado: o manual nao foi consultado ou nada foi encontrado)"
    return "\n\n".join(
        f"[trecho n={t['n']} | {t['pop']} | secao \"{_dado(t['secao'])}\"]\n{_dado(t['texto'])}" for t in trechos
    )


def montar_fidelidade(p: PromptJuiz, pergunta: str, trechos: list[dict], resposta: str) -> list:
    """So pergunta, trechos e resposta: a assinatura nao aceita gabarito."""
    usuario = (
        p.usuario.replace("{{PERGUNTA}}", _dado(pergunta))
        .replace("{{TRECHOS}}", formatar_trechos(trechos))
        .replace("{{RESPOSTA}}", _dado(resposta))
    )
    return [SystemMessage(content=p.sistema), HumanMessage(content=usuario)]


def montar_correcao(p: PromptJuiz, item: dict, resposta: str) -> list:
    usuario = (
        p.usuario.replace("{{PERGUNTA}}", _dado(item["pergunta"]))
        .replace("{{RESPOSTA_ESPERADA}}", _dado(item.get("resposta_esperada")))
        .replace("{{CRITERIO}}", _dado(item.get("criterio_acerto")))
        .replace("{{ACEITA_TAMBEM}}", _dado(item.get("aceita_tambem")))
        .replace("{{RESPOSTA}}", _dado(resposta))
    )
    return [SystemMessage(content=p.sistema), HumanMessage(content=usuario)]


def criar_llm(api_key: str, p: PromptJuiz) -> ChatOpenAI:
    return ChatOpenAI(
        model=JUIZ_MODELO,
        temperature=JUIZ_TEMPERATURA,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        extra_body={
            "reasoning": {"effort": JUIZ_REASONING_EFFORT},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": f"juiz_{p.nome}_v1", "strict": True, "schema": p.schema},
            },
        },
    )


def extrair_json(conteudo) -> dict:
    """O JSON da resposta (tolera cerca ```json, que alguns provedores poem)."""
    texto = conteudo if isinstance(conteudo, str) else str(conteudo)
    texto = texto.strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", texto)
    return json.loads(texto)


def veredito_fidelidade(dados: dict) -> dict:
    """Derivado EM CODIGO da lista de afirmacoes (o juiz so classifica cada uma)."""
    afirmacoes = dados.get("afirmacoes") or []
    nao_suportadas = [a for a in afirmacoes if not a.get("suportada")]
    inconsistentes = [
        a for a in afirmacoes
        if (a.get("suportada") and a.get("gravidade") != "nenhuma")
        or (not a.get("suportada") and a.get("gravidade") == "nenhuma")
    ]
    return {
        "fiel_estrito": not nao_suportadas,
        "sem_grave": not any(a.get("gravidade") == "grave" for a in nao_suportadas),
        "n_afirmacoes": len(afirmacoes),
        "n_nao_suportadas": len(nao_suportadas),
        "n_inconsistentes": len(inconsistentes),
    }


async def julgar(llm, mensagens: list) -> tuple[dict, dict]:
    """Uma chamada ao juiz. Devolve (json do juiz, metadados de uso)."""
    resposta = await llm.ainvoke(mensagens)
    meta = getattr(resposta, "response_metadata", None) or {}
    uso = {
        "modelo_devolvido": meta.get("model_name"),
        "token_usage": meta.get("token_usage"),
        "usage_metadata": getattr(resposta, "usage_metadata", None),
    }
    return extrair_json(resposta.content), uso
