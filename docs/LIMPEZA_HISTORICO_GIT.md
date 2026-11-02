# Limpeza de IP/telefone no histórico do git (S-06)

Contexto: ver `docs/SEGURANCA_AUDITORIA_2026-11-02.md`, achado **S-06**. O repositório é
**público** e contém, no histórico, o IP do servidor de produção, um segundo IP e um
telefone real. Corrigir só o HEAD **não** remove nada do histórico.

> **Esta operação reescreve todos os SHAs e exige *force push*. É irreversível no
> remoto.** Só execute depois de decidir (veja "Antes de decidir").
> A cópia de teste feita na auditoria (espelho descartável) mostrou: 189 commits antes
> e depois, **0** ocorrências restantes em todo o histórico, 15 arquivos alterados
> (14 docs + 1 teste TypeScript), 38 linhas de docs.

## Antes de decidir

| Opção | Quando faz sentido | Custo |
|---|---|---|
| **Tornar o repositório privado** | enquanto não houver um portfólio pronto para mostrar | nenhum no histórico; perde visibilidade pública |
| **Limpar o histórico e manter público** | repo será mostrado a recrutadores | reescreve SHAs; todo clone precisa ser refeito; forks/caches do GitHub podem reter objetos antigos |
| **Aceitar o risco** | IP de VPS não é segredo de autenticação | continua sendo reconhecimento + telefone (PII) público |

Observações: um IP de VPS **não pode ser "rotacionado"** como uma senha — a mitigação
real é firewall/`allowlist` no servidor (ver `SECURITY.md`). O telefone é PII do
operador. Se houver *forks* ou *pull requests* abertos, os objetos antigos continuam
acessíveis por SHA no GitHub até a coleta de lixo; para remoção total, peça ao
suporte do GitHub a limpeza de caches e referências antigas.

## Ordem correta

1. **Mesclar primeiro** a branch de endurecimento (`worktree-security-hardening-2026-11`)
   na `master` — a limpeza muda os SHAs, então é a *última* coisa a fazer.
2. Fazer **backup**: `git clone --mirror <remoto> backup-antes-da-limpeza.git` (guardar fora do repo).

## Procedimento (sempre em um espelho descartável)

```bash
# 0) ferramenta (uma vez)
pip install git-filter-repo

# 1) espelho descartável do estado final
git clone --mirror https://github.com/<usuario>/meu-agente.git /tmp/limpeza.git

# 2) gerar as regras (valores reais ficam SÓ no arquivo de regras; NÃO versionar)
python3 -I scripts/scrub-history-rules.py --repo /tmp/limpeza.git \
    --ip <IP_PRODUCAO>=203.0.113.10 --ip <OUTRO_IP>=203.0.113.11 \
    --phone-suffix <ULTIMOS_DIGITOS> --out /tmp/regras.txt
#    → confira as contagens; o telefone aparece só como formato (#####), nunca os dígitos

# 3) reescrever o histórico DO ESPELHO
cd /tmp/limpeza.git && git filter-repo --replace-text /tmp/regras.txt --force

# 4) verificar (todos devem dar 0 / mesmo número de commits)
git rev-list --all --count
git log --all -p --format= | grep -c '<IP_PRODUCAO>'
git log --all -p --format= | grep -c '<ULTIMOS_DIGITOS>'
```

5. **Testes.** Faça checkout do espelho limpo e rode: `cd orchestrator && pytest -q`
   e — **obrigatório** — os testes TypeScript de `extensions/ask-max`
   (`resolve-hook.test.ts` teve os números trocados; não pôde ser executado na
   auditoria porque depende do SDK do OpenClaw).
6. **Publicar** (só depois dos passos acima e do backup):
   ```bash
   git remote add origin https://github.com/<usuario>/meu-agente.git   # no espelho limpo
   git push --force origin master        # e cada branch que deva sobreviver
   ```
   Não use `--mirror` sem querer: ele também apaga no remoto as refs que não existem no espelho.
7. **Refazer todos os clones** (Kali, servidores que fazem `git pull`): trabalho local
   não enviado se perde com `reset --hard`. Verifique antes se algum servidor tem um
   `git pull` agendado — ele quebraria com o histórico reescrito.

## O que a ferramenta substitui

- IP/host informado → endereço da faixa de documentação (RFC 5737, `203.0.113.x`).
- Telefone identificado pelos últimos dígitos → mesmo formato, com os dígitos zerados
  (prefixo `55` preservado), em qualquer formato (`+55 (41) 9....-XXXX`, `5541...`, `41...`).

Revise o que mais pode ser PII no seu caso (outros telefones, e-mails, nomes de clientes)
e rode a ferramenta com novas regras — ela só conhece o que você informar.
