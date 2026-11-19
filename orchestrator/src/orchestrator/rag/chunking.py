"""Chunking dos POPs: um chunk por secao `##`, mais o preambulo.

Regras (docs/RAG.md, Missao 3):

- cada secao `##` vira um chunk, do cabecalho ate o proximo `#`/`##`
  (subsecoes `###` ficam dentro da secao `##` delas);
- o PREAMBULO, entre o titulo `#` e a primeira `##`, vira um chunk proprio
  cuja `secao` e o texto do titulo `#`. E nele que esta, por exemplo, a
  revogacao do POP-06 (q13 do gabarito); sem esse chunk a q13 seria
  irrespondivel por construcao;
- preambulo vazio (titulo seguido direto de `##`) nao gera chunk;
- cabecalhos dentro de bloco de codigo cercado (```) sao ignorados.

`secao` guarda o texto exato do cabecalho, sem os `#`: e o mesmo formato do
`secao_fonte` do gabarito, e a avaliacao compara pelo par (arquivo, secao).
"""

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    arquivo: str  # nome do arquivo (ex.: "pop-01-recebimento-de-mercadorias.md")
    secao: str  # texto exato do cabecalho, sem os "#"
    texto: str  # texto do chunk, incluindo a linha do cabecalho
    colecao: str  # ex.: "supermercado"
    titulo_documento: str = ""  # titulo "#" do arquivo (contexto para o indice)

    @property
    def chave(self) -> tuple[str, str]:
        return (self.arquivo, self.secao)

    def texto_indexado(self) -> str:
        """Texto que vai para o embedding e para o FTS5: o titulo do documento
        na frente, para a secao "2. Sangria" carregar o "POP-04 — Abertura e
        Fechamento de Caixa" junto."""
        if self.titulo_documento and self.titulo_documento != self.secao:
            return f"{self.titulo_documento}\n{self.texto}"
        return self.texto


def _cabecalhos(linhas: list[str]) -> list[tuple[int, int, str]]:
    """(indice da linha, nivel, titulo) de cada cabecalho fora de bloco de codigo."""
    achados, em_codigo = [], False
    for i, linha in enumerate(linhas):
        if _FENCE.match(linha):
            em_codigo = not em_codigo
            continue
        if em_codigo:
            continue
        m = _HEADING.match(linha)
        if m:
            achados.append((i, len(m.group(1)), m.group(2).strip()))
    return achados


def chunk_markdown(texto: str, arquivo: str, colecao: str) -> list[Chunk]:
    linhas = texto.splitlines()
    cabecalhos = [c for c in _cabecalhos(linhas) if c[1] <= 2]  # so "#" e "##" cortam
    titulo = next((t for _, nivel, t in cabecalhos if nivel == 1), "")
    chunks: list[Chunk] = []
    for n, (inicio, nivel, secao) in enumerate(cabecalhos):
        fim = cabecalhos[n + 1][0] if n + 1 < len(cabecalhos) else len(linhas)
        bloco = "\n".join(linhas[inicio:fim]).strip()
        corpo = "\n".join(linhas[inicio + 1 : fim]).strip()
        if nivel == 1 and not corpo:
            continue  # titulo seguido direto de "##": sem preambulo
        chunks.append(Chunk(arquivo=arquivo, secao=secao, texto=bloco, colecao=colecao, titulo_documento=titulo))
    return chunks


def chunk_corpus(diretorio: Path, colecao: str) -> list[Chunk]:
    """Todos os `*.md` do diretorio, em ordem de nome (determinismo)."""
    chunks: list[Chunk] = []
    for caminho in sorted(Path(diretorio).glob("*.md")):
        chunks.extend(chunk_markdown(caminho.read_text(encoding="utf-8"), caminho.name, colecao))
    chaves = [c.chave for c in chunks]
    duplicadas = sorted({k for k in chaves if chaves.count(k) > 1})
    if duplicadas:
        raise ValueError(f"secoes duplicadas no corpus (a avaliacao compara por arquivo+secao): {duplicadas}")
    return chunks
