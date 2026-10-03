# Sessão 01–02/10/2026 — token em produção, Molde 1 testado e próximos passos de venda

## 1. Resumo do dia

- Autenticação por token entre gateway e orquestrador ativada e validada em produção.
- Achado e desligado um segundo conector do túnel de produção rodando no notebook.
- Molde 1 (instância por cliente) testado no Kali, com dois scripts novos de verificação.
- Revisões feitas rodando os testes de novo, não confiando em relatório.
- Próximo foco: oferta e roteiro de demo para um piloto com cliente real.

## 2. Produção

Token ativo e validado. Detalhes, hipóteses e pendências em
[producao-contabo-token.md](producao-contabo-token.md); o mecanismo está em
[autenticacao-token.md](autenticacao-token.md).

## 3. Molde 1 (instância por cliente)

Testado no Kali, numa pasta descartável. Commit `1667258`.

**`check-instancia.sh`** — validação pós-deploy da instância:

- containers do gateway e do orquestrador saudáveis (reprova container *unhealthy*);
- `/health` do orquestrador = 200;
- token carregado e igual no gateway e no orquestrador (comparado por hash, nunca impresso);
- `POST /v1/turn` sem token = 401; com token e corpo inválido = 422 (não chama IA);
- nenhuma porta publicada fora do loopback (localhost);
- aviso quando `dmPolicy` está aberto (vira ❌ com `--cliente`).

**`teste-webhook.sh`** — simula uma mensagem da Meta com assinatura HMAC:

- assinatura inválida = 403, sem custo;
- trava de segurança que falha **fechada**: só libera o envio com chaves de teste;
  aborta se não conseguir ler as variáveis ou se o orquestrador não for encontrado.

- **CONFIRMADO:** os testes acima, revisados pelo Claude Code rodando de novo
  (inclusive os casos negativos: token errado, container *unhealthy* simulado,
  `--cliente`, orquestrador ausente, assinatura inválida).
- **NÃO CONFIRMADO:** resposta real do agente (a chave de IA do teste é falsa e
  voltou a mensagem de fallback); instalação em servidor novo; webhook com a
  Meta de verdade.

## 4. Decisões e pontos em aberto

- **`dmPolicy` do template:** o molde nasce com `dmPolicy: "open"` e
  `allowFrom: ["*"]` — qualquer número é atendido e gasta a conta de IA. Para
  cliente, o mais seguro é lista de números permitidos. **DECISÃO PENDENTE.**
- **OpenRouter x DeepSeek:** RECOMENDAÇÃO (ainda não decidida): usar
  OpenRouter para teste e primeiros clientes e, para clientes que tratam
  dados pessoais, um modelo hospedado fora da China por padrão. **A
  CONFERIR** nos sites oficiais antes de usar com cliente: a taxa do
  OpenRouter na compra de créditos (cerca de 5,5% segundo artigos de
  terceiros), se o preço por token é igual ao do provedor, e onde a API
  hospedada da DeepSeek processa os dados (a LGPD pesa para dados
  pessoais).
- **Para onde vai cada chamada de IA** (supervisor, especialistas, chave
  DeepSeek do gateway): pergunta **GUARDADA** para antes da demo com chave
  real. **SUPOSIÇÃO:** o gateway usa DeepSeek e o orquestrador usa OpenRouter;
  não verificado.
- **Demo ao vivo com a Meta** (túnel novo com outro identificador, número de
  teste, chave nova): **ADIADA.**

## 5. Método de trabalho

- Claude Code analisa e propõe tarefas; Antigravity executa só no Kali;
  Claude Code revisa rodando os testes de novo.
- Regras que funcionaram:
  - todo teste tem um caso **negativo**;
  - separar **CONFIRMADO** de **HIPÓTESE**;
  - trava de segurança tem que **falhar fechada**.

## 6. Erros e lições do dia

- Um segundo conector do túnel de produção rodava no notebook (serviço de
  usuário que subia no boot) e atendia parte das mensagens com erro. Foi
  desabilitado. **Lição:** o túnel de produção nunca roda em outra máquina.
- Um teste deu 200 sem token e a causa **NÃO** foi explicada (hipótese não
  confirmada: container com versão antiga do código).
- Um relatório disse "100% batendo" sobre um documento que tinha uma seção
  marcada CONFIRMADO sem prova.
- Comandos propostos com `>` apagariam o `.env`; usamos `>>` e backup.

## 7. Pendências

- [ ] Imagem nova do gateway com token no `orchestrator-bridge`.
- [ ] 403 na API do n8n (causa desconhecida).
- [ ] Seção "cutover" do `ESTADO_ATUAL.md` desatualizada.
- [ ] Imagens do gateway e do orquestrador em registry.
- [ ] Bootstrap de VPS.
- [ ] Decidir o padrão de `dmPolicy`.
- [ ] Apagar o backup no servidor após alguns dias estáveis.

## 8. Próximo passo

Montar a oferta e o roteiro de demo para um piloto com cliente real.
Primeiro alvo **AINDA NÃO ESCOLHIDO.**
