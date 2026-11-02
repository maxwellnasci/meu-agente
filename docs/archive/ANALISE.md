# Análise das Variáveis de Ambiente (OpenClaw)

Esta é a documentação explicativa de cada variável de ambiente presente no arquivo `.env.example` do repositório OpenClaw.

## 1. Gateway Auth + Paths (Autenticação e Caminhos do Gateway)
- **`OPENCLAW_GATEWAY_TOKEN`**: Token de autenticação exigido caso o gateway esteja exposto além da rede local (loopback). Se não preenchido, o sistema gera um automaticamente no primeiro início. É a principal chave de segurança do Gateway.
- **`OPENCLAW_GATEWAY_PASSWORD`**: Senha opcional que pode ser usada como alternativa ao `OPENCLAW_GATEWAY_TOKEN`.
- **`OPENCLAW_STATE_DIR`**: Define o diretório onde o OpenClaw salvará o estado (arquivos locais). O padrão é `~/.openclaw`.
- **`OPENCLAW_CONFIG_PATH`**: Caminho para o arquivo de configuração JSON do OpenClaw. Padrão: `~/.openclaw/openclaw.json`.
- **`OPENCLAW_HOME`**: Diretório home base considerado pelo sistema, geralmente a pasta do usuário (`~`).
- **`OPENCLAW_AUTH_PROFILE_SECRET_DIR`**: Diretório absoluto fora da pasta de estado montada (útil para Docker) onde ficarão as chaves de criptografia do perfil de autenticação.
- **`OPENCLAW_INCLUDE_ROOTS`**: Lista de diretórios permitidos (separados por `:` ou `;`) onde a diretiva de inclusão `$include` do `openclaw.json` pode buscar arquivos. Se não definida, restringe-se apenas à pasta do arquivo de configuração.
- **`OPENCLAW_LOAD_SHELL_ENV`**: Se definido (ex: `1`), faz com que o OpenClaw tente carregar variáveis de ambiente diretamente do perfil de shell do usuário.
- **`OPENCLAW_SHELL_ENV_TIMEOUT_MS`**: Tempo limite (em milissegundos) para carregar o ambiente do shell (padrão 15 segundos).

## 2. Model Provider API Keys (Chaves de API de Provedores de Modelos)
Estas são as chaves das IAs que fornecerão "inteligência" ao sistema. Você deve configurar pelo menos uma:
- **`OPENAI_API_KEY` / `OPENAI_API_KEY_1` / `OPENAI_API_KEYS`**: Chaves de API para usar modelos da OpenAI (ex: ChatGPT).
- **`ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY_1` / `ANTHROPIC_API_KEYS`**: Chaves para usar os modelos Claude, da Anthropic.
- **`GEMINI_API_KEY` / `GEMINI_API_KEY_1` / `GEMINI_API_KEYS`**: Chaves para os modelos Gemini, do Google.
- **`OPENROUTER_API_KEY`**: Chave do OpenRouter (um agregador de várias IAs).
- **`OPENCLAW_LIVE_*_KEY`**: Chaves específicas para instâncias live/produção de OpenAI, Anthropic ou Gemini.
- **`GOOGLE_API_KEY`**: Chave geral da API do Google.
- Provedores adicionais: **`ZAI_API_KEY`**, **`AI_GATEWAY_API_KEY`**, **`TOKENHUB_API_KEY`**, **`LKEAP_API_KEY`**, **`MINIMAX_API_KEY`**, **`SYNTHETIC_API_KEY`**.

## 3. Channels (Canais de Comunicação)
Configurações para os bots se conectarem a plataformas de comunicação. Defina apenas as que você for usar:
- **`TELEGRAM_BOT_TOKEN`**: Token fornecido pelo BotFather para o seu bot no Telegram.
- **`DISCORD_BOT_TOKEN`**: Token da sua aplicação/bot no Discord.
- **`SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`**: Tokens para conectar o agente a um workspace do Slack.
- **`MATTERMOST_BOT_TOKEN` / `MATTERMOST_URL`**: Token e URL do servidor para o Mattermost.
- **`ZALO_BOT_TOKEN`**: Token para o aplicativo de mensagens Zalo.
- **`OPENCLAW_TWITCH_ACCESS_TOKEN`**: Token Oauth para interagir em chats da Twitch.

## 4. Tools + Voice/Media (Ferramentas e Mídias)
Chaves para serviços auxiliares (pesquisa na web, processamento de áudio/voz, etc):
- Pesquisa na Web:
  - **`BRAVE_API_KEY`**: Pesquisas pela API do Brave Search.
  - **`PERPLEXITY_API_KEY`**: Uso do modelo Perplexity focado em busca e respostas atuais.
  - **`FIRECRAWL_API_KEY`**: Para uso da ferramenta de web scraping e crawling Firecrawl.
- Voz e Áudio:
  - **`ELEVENLABS_API_KEY` / `XI_API_KEY`**: Geração de voz realista usando ElevenLabs.
  - **`INWORLD_API_KEY`**: Chave para os serviços Inworld AI (criação de personagens e NPCs).
  - **`DEEPGRAM_API_KEY`**: Transcrição avançada de áudio (Speech-to-Text) usando Deepgram.
