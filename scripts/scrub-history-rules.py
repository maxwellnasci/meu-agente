#!/usr/bin/env python3
"""Gera o arquivo de regras para `git filter-repo --replace-text`.

Varre TODO o historico de um repositorio (de preferencia um espelho descartavel,
ver docs/LIMPEZA_HISTORICO_GIT.md) e escreve regras `ORIGINAL==>SUBSTITUTO` para:

  --ip VALOR[=SUBSTITUTO]     IP/host literal (substituto padrao: 203.0.113.x,
                              faixa reservada para documentacao - RFC 5737)
  --phone-suffix DIGITOS      telefone brasileiro identificado pelos ultimos
                              digitos (qualquer formato: +55 (41) 9....-DIGITOS,
                              5541....DIGITOS, 41....DIGITOS). Os digitos viram 0,
                              mantendo formato e prefixo 55.

IMPORTANTE: nenhum valor real fica neste arquivo - eles sao passados na linha de
comando. A saida (`--out`) CONTEM os valores reais: nunca a versione nem a
envie ao repositorio. O script so imprime contagens e formas mascaradas.

Uso:
  python3 -I scripts/scrub-history-rules.py --repo /tmp/espelho.git \\
      --ip 198.51.100.7 --phone-suffix 1234 --out /tmp/regras.txt
"""

import argparse
import re
import subprocess
import sys


def _history_patch(repo: str) -> str:
    done = subprocess.run(
        ["git", "--git-dir", repo, "log", "--all", "-p", "--no-color", "-U0", "--format="],
        capture_output=True, text=True, errors="replace", check=True,
    )
    return done.stdout


def _neutralize(value: str) -> str:
    """Troca os digitos por 0, preservando formato e o prefixo 55 (se houver)."""
    keeps_55 = value.lstrip("+ ").startswith("55")
    out, seen = [], 0
    for ch in value:
        if ch.isdigit():
            seen += 1
            out.append(ch if (keeps_55 and seen <= 2) else "0")
        else:
            out.append(ch)
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="caminho do repositorio/espelho (git dir)")
    ap.add_argument("--out", required=True, help="arquivo de regras a escrever (NAO versionar)")
    ap.add_argument("--ip", action="append", default=[], metavar="VALOR[=SUBSTITUTO]")
    ap.add_argument("--phone-suffix", action="append", default=[], metavar="DIGITOS")
    args = ap.parse_args()

    if not args.ip and not args.phone_suffix:
        ap.error("informe ao menos um --ip ou --phone-suffix")

    patch = _history_patch(args.repo)
    rules: list[str] = []

    for n, spec in enumerate(args.ip):
        real, _, fake = spec.partition("=")
        fake = fake or f"203.0.113.{10 + n}"
        rules.append(f"{real}==>{fake}")
        print(f"host/IP #{n + 1} ({real[:3]}…): {patch.count(real)} ocorrencias no historico")

    for suffix in args.phone_suffix:
        if not suffix.isdigit() or len(suffix) < 4:
            ap.error("--phone-suffix deve ter ao menos 4 digitos, so numeros")
        rx = re.compile(
            rf"\+?55 ?\(?\d{{2}}\)? ?9?\d{{4}}-?{suffix}|55\d{{2}}9?\d{{4}}{suffix}|\(?\d{{2}}\)? ?9?\d{{4}}-?{suffix}"
        )
        found = {m for m in rx.findall(patch) if m.count(suffix) == 1}
        # do mais longo para o mais curto: evita trocar so um pedaco de um numero maior
        for phone in sorted(found, key=len, reverse=True):
            rules.append(f"{phone}==>{_neutralize(phone)}")
            shape = re.sub(r"\d", "#", phone)  # so o formato, nunca os digitos
            print(f"telefone formato {shape}: {patch.count(phone)} ocorrencias")

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rules) + "\n")
    print(f"{len(rules)} regras escritas em {args.out}  (contem valores reais - nao versionar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
