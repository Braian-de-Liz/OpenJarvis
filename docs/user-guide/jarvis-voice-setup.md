# Voz na HUD com o Claude Code (guia para testar em casa)

Este guia monta a voz do JARVIS usando o **Claude Code como cérebro** (login do seu plano, sem API key). Ele foi escrito em uma máquina **sem microfone e com Python 3.13**, então algumas etapas não puderam ser testadas ali. A tabela abaixo diz exatamente o que foi e o que não foi verificado.

## O que foi verificado e o que falta

| Parte | Estado | Observação |
|-------|--------|-----------|
| Claude Code na HUD (modos **Conversa** e **Agente**) | Testado | Conversa ≈ 320–370 tokens por mensagem; Agente ≈ 22 mil |
| Reconhecimento de fala (faster-whisper) | Testado | Áudio gerado → texto, pelo backend do projeto e pelo endpoint `POST /v1/speech/transcribe` |
| Síntese de voz (Kokoro) | **Não instalado** | O Kokoro 0.9+ exige Python **< 3.13**; o ambiente de teste usava 3.13 |
| Captura do microfone no navegador | **Não testado** | A máquina de teste não tem microfone |
| Voz de ponta a ponta (falar → Claude → resposta falada) | **Não testado** | Depende dos dois itens acima |

## Como a voz se encaixa no Claude Code

A voz não conversa com o Claude: ela só converte áudio em texto e texto em áudio, localmente.

```
Microfone ──► faster-whisper (local) ──► texto ──► Claude Code (plano) ──► texto ──► Kokoro (local) ──► alto-falante
```

- O Claude só vê texto. Não sabe se veio da voz ou do teclado.
- Reconhecimento e síntese rodam na sua máquina: não usam API e não consomem o limite do plano.
- Só o passo do meio gasta o plano: no modo **Conversa**, cerca de 320–370 tokens por mensagem.

## Pré-requisitos

1. **Python 3.12** (o Kokoro não instala em 3.13). O projeto aceita `>=3.10,<3.14`.
2. **Node.js 22+** (o agente do Claude Code roda via Node).
3. **Claude Code instalado e logado** na conta do plano (`claude auth status` deve mostrar `authMethod: "claude.ai"`).
4. **Nenhuma `ANTHROPIC_API_KEY` definida.** Se houver, o servidor recusa o Claude Code (erro 409) de propósito, para nunca cobrar por token.
5. **espeak-ng** (Windows), para o Kokoro falar palavras fora do dicionário. Instalador em <https://github.com/espeak-ng/espeak-ng/releases>; o projeto procura os dados em `C:\Program Files\eSpeak NG\espeak-ng-data`.
6. Um microfone, claro.

## Passo a passo (Windows / PowerShell)

Na pasta do projeto, na branch `feat/jarvis-mode`:

```powershell
git checkout feat/jarvis-mode

# 1. Python 3.12 (se ainda não tiver)
winget install Python.Python.3.12        # comando não verificado nesta sessão
py -3.12 --version

# 2. Ambiente virtual com 3.12
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1

# 3. Dependências (o download do Kokoro/PyTorch é grande, na casa de GBs)
pip install -e ".[dev,server,speech,voice,screen]"

# 4. Frontend
cd frontend
bun install          # ou: npm install --engine-strict=false
cd ..
```

Se o `pip install` do Kokoro falhar com `Requires-Python <3.13`, o ambiente ativo não é o 3.12. Confira com `python --version`.

### Configuração da voz

Crie ou edite `~\.openjarvis\config.toml`:

```toml
[speech]
model = "small"        # faster-whisper: tiny, base, small, medium, large-v3
language = "pt"        # idioma do reconhecimento; omita para detectar sozinho
device = "cpu"         # "auto", "cpu" ou "cuda"
compute_type = "int8"  # leve para CPU
tts_backend = "kokoro"
voice_id = "pf_dora"   # voz feminina em português do Brasil
```

Nos testes, o modelo `base` em CPU com `int8` transcreveu em menos de 1 segundo.

## Subindo tudo

Em dois terminais, com o ambiente 3.12 ativo no primeiro:

```powershell
# Terminal 1 - servidor
jarvis serve

# Terminal 2 - HUD
cd frontend
bun run dev
```

Abra a URL que o Vite mostrar (por exemplo `http://localhost:5173/jarvis`). O microfone do navegador só funciona em `localhost` ou HTTPS, e o navegador vai pedir permissão.

### Escolher o Claude Code na HUD

1. Clique no ícone de ajustes (ou na pílula **MODELO**).
2. Em **Fonte de IA**, escolha **CLAUDE CODE**.
3. Escolha **CONVERSA** (leve, sem ferramentas) ou **AGENTE** (ferramentas do Claude Code, ~22 mil tokens por mensagem).
4. Feche e use **Falar** para falar, ou digite.

Se o botão estiver cinza, recarregue a página e passe o mouse nele para ver o motivo.

## Como conferir cada peça

```powershell
# Reconhecimento de fala
curl http://localhost:8000/v1/speech/health        # esperado: {"available":true,"backend":"faster-whisper"}

# Síntese de voz
curl http://localhost:8000/v1/speech/tts/health    # esperado: {"available":true,...}

# Modelos oferecidos (deve listar claude-code e claude-code-agent)
curl http://localhost:8000/v1/models

# Diagnóstico geral
jarvis doctor
```

Na HUD, o botão **Testar voz** deve falar uma frase de teste.

## Problemas conhecidos

| Sintoma | Causa provável | O que fazer |
|---------|---------------|-------------|
| `No text-to-speech backend available` | Kokoro não instalado, ou Python 3.13 | Use o ambiente 3.12 e instale o extra `voice` |
| `No speech backend configured` | Extra `speech` não instalado | `pip install -e ".[speech]"` |
| Erro 409 ao falar com o Claude Code | `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` definida | Remova a variável e reinicie o servidor |
| Botão CLAUDE CODE cinza | Lista de modelos antiga, ou Node ausente no servidor | Recarregue a página; confira `node --version` |
| Primeira fala demora | Download dos modelos (Whisper, Kokoro) | Espere; só acontece na primeira vez |
| Erro de CUDA/cuBLAS no reconhecimento | Drivers CUDA ausentes | `device = "cpu"` no `config.toml` |
| Avisos de symlink do Hugging Face no Windows | Modo desenvolvedor desligado | Só aviso; funciona, usa mais disco |
| Palavras estranhas em português | `espeak-ng` ausente | Instale o espeak-ng (pré-requisito 5) |

## Quando algo der errado

Anote o texto exato do erro e em qual passo ocorreu. As três checagens (`speech/health`, `speech/tts/health`, `v1/models`) separam rapidamente se o problema é no reconhecimento, na síntese ou na conexão com o Claude Code.

Veja também o guia geral: [JARVIS Mode](jarvis-mode.md).
