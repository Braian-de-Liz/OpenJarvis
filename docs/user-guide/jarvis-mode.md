# JARVIS Mode (Hands-Free Voice + HUD)

JARVIS Mode turns OpenJarvis into a hands-free voice assistant with a full-screen, Iron Man style HUD. Clap twice, wait for "Às suas ordens", and talk: the mic reopens after every reply, so no key presses are needed between turns. The browser HUD at `/jarvis` mirrors the session live, with voice state, audio levels, transcripts, tool calls and host telemetry.

Everything runs locally: speech-to-text with faster-whisper, the LLM on Ollama, and text-to-speech with Kokoro.

---

## How it fits together

```
 jarvis show ──(double clap)──► jarvis chat --hands-free
     │                                  │  listen → STT → LLM → TTS (loop)
     │ starts if needed                 │
     ▼                                  ▼ POST /v1/voice/events
 jarvis serve :8000  ───────────────────┘
     │  /v1/voice/ws (WebSocket)    /api/system/metrics (JSON)
     ▼
 /jarvis HUD (browser, Vite :5173 in dev)
```

- **`jarvis show`** listens for a double clap. It starts `jarvis serve` in the background if nothing is listening on the port, opens the HUD once, and then runs a hands-free session. When the session ends, it goes back to waiting for claps.
- **`jarvis chat --hands-free`** runs the continuous voice loop. It runs in its own process and publishes its state to the server. Publishing is best-effort: if the server is down, the session still works, just without a HUD.
- **`jarvis serve`** relays voice events to every connected HUD and serves host telemetry.

---

## Requirements

| Component | Purpose | Notes |
|-----------|---------|-------|
| `server` / `desktop` extras | FastAPI server, faster-whisper, `sounddevice`, `psutil` | `desktop` includes everything in `server` |
| `voice` extra | Kokoro local TTS | Kokoro needs `espeak-ng` on `PATH` for out-of-dictionary words |
| `windows-control` extra | PC control tools (volume, windows, processes, screenshots) | Windows only |
| [Ollama](https://ollama.com) | Local LLM | e.g. `ollama pull qwen2.5:7b` |
| NVIDIA GPU (optional) | Faster STT; GPU telemetry in the HUD | Falls back to CPU automatically |

Install everything without removing packages you already have:

```powershell
uv sync --inexact --extra desktop --extra voice --extra windows-control --extra inference-litellm --extra dev
```

!!! warning "Always use `--inexact`"
    A plain `uv sync` removes every package that is not part of the selected extras. That includes the Windows control tools and the spaCy `en-core-web-sm` model that Kokoro uses for English words, which is installed outside the lockfile. Run `uv sync --inexact --dry-run ...` first if in doubt.

Then check the environment:

```powershell
uv run jarvis doctor
```

Look for **Local LLM (Ollama)** and **Speech backend: faster-whisper ready**.

---

## Quick start

```powershell
cd path\to\jarvis
uv run jarvis show --threshold 30 --clap-window 2.0 --port 8000
```

1. Clap twice. Jarvis answers "Às suas ordens."
2. Speak your command. The mic reopens after each reply.
3. To end the session, say an exit phrase (see below) or stay silent for 30 seconds. It then goes back to waiting for claps.

For the HUD in development, also run the frontend:

```powershell
cd frontend
npm run dev    # http://localhost:5173/jarvis
```

!!! tip "One `jarvis show` at a time"
    Close any old `jarvis show` terminals first. Two instances fight over the microphone, and an instance started before an update keeps running the old code, because Python loads modules only once.

---

## CLI reference

### `jarvis show`

| Option | Default | Description |
|--------|---------|-------------|
| `-t, --threshold` | `1500` (`JARVIS_CLAP_THRESH`) | Clap sensitivity (RMS). Lower is more sensitive; `30` works well for quiet mics |
| `-m, --mic` | system default (`JARVIS_MIC`) | Input device ID (`python -m sounddevice` lists them) |
| `-p, --port` | `8000` | `jarvis serve` port |
| `--clap-window` | `1.0` | Max seconds between the two claps |
| `--idle-timeout` | `30.0` | Seconds of silence before the session ends |
| `--frontend-port` | `5173` | Vite dev server port used to open the HUD |
| `--web-path` | `/jarvis` | HUD path |
| `--no-web` | off | Don't open the HUD |
| `--no-jingle` | off | Don't play the activation jingle |

To calibrate the clap threshold, `python test_clap.py` prints the peak RMS of each clap, and `python test_mic.py` lists input devices and checks capture.

### `jarvis chat --hands-free`

Runs a voice session directly, without claps. `--hands-free` implies `--voice`.

| Option | Default | Description |
|--------|---------|-------------|
| `--idle-timeout` | `30.0` | Seconds without speech before the session ends |
| `--silence-threshold` | auto-calibrated | Mic RMS treated as speech |
| `--events-url` | config `[server]` | `jarvis serve` base URL for HUD events |

### Exit phrases

The whole utterance must match, so "para o Spotify" does **not** end the session. Accents and punctuation are ignored, and an optional "ok / ei / hey Jarvis" prefix or trailing "Jarvis" is accepted.

| Language | Phrases |
|----------|---------|
| Portuguese | *desligar*, *desligue*, *pode desligar*, *parar*, *pare*, *pode parar*, *encerrar*, *encerrar sessão*, *vai dormir*, *voltar a ouvir palmas*, *tchau*, *até logo*, *até mais* |
| English | *stop*, *goodbye*, *shut down*, *go to sleep* |

Example: "Jarvis, desligar."

---

## The HUD (`/jarvis`)

The HUD is a full-screen page outside the normal app layout. Press **Esc** or the ⏻ button to leave it.

| Area | Content |
|------|---------|
| Top bar | Voice state, relay link (`VOZ LINK` / `VOZ OFFLINE`), STT engine/model, clock, audio level |
| Center | Arc reactor and waveform: cyan when idle or listening, purple when speaking or processing; status line and hint |
| Telemetria (SYS·01) | CPU, GPU, RAM, GPU temperature, network up/down |
| Log de Comunicação (COM·02) | Typed chat and voice turns, in time order |
| Controles (CTL·03) | System controls (static placeholders, marked **DEMO**) |
| Ações Rápidas (ACT·04) | One-click commands such as volume, close Chrome or screenshot |

Below 1024 px wide, the panels stack in a single scrolling column. Animations respect `prefers-reduced-motion`.

!!! note "DEMO badge"
    The telemetry panel shows **DEMO** with simulated values whenever `/api/system/metrics` is unreachable or doesn't return JSON. Usually this means `jarvis serve` isn't running or is an old build.

!!! note "Typed commands"
    The HUD input and the quick actions currently add the message to the conversation log only. They are not sent to the agent yet. Voice is the working path.

---

## Configuration

JARVIS Mode reads `~/.openjarvis/config.toml` (`%USERPROFILE%\.openjarvis\config.toml` on Windows):

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen2.5:7b"
preferred_engine = "ollama"
provider = "local"

[speech]
model = "small"      # faster-whisper model size
language = "pt"      # STT language; omit for auto-detect
device = "auto"      # "auto", "cpu" or "cuda"
tts_backend = "kokoro"
voice_id = "pf_dora" # Kokoro Brazilian Portuguese female voice

[agent]
default_agent = "orchestrator"
tools = "mouse,keyboard,window,volume,brightness,media_keys,process_list,screenshot,think"
```

!!! tip "Start with a short tool list"
    Every enabled tool goes into the prompt. With 30+ tools, a 7B local model gets slow and picks tools poorly. Start with a short list like the one above and add tools gradually. Destructive tools such as `process_kill` are best left out of hands-free sessions, because there is no keyboard prompt there to confirm actions.

---

## API reference

### Voice event relay

`POST /v1/voice/events` takes events from the voice loop, and `WS /v1/voice/ws` fans them out to every HUD. A new WebSocket client immediately receives the latest `state`.

```json
{ "type": "state", "data": { "state": "listening" } }
```

| `type` | `data` fields | Notes |
|--------|---------------|-------|
| `state` | `state`, optional `reason` | `idle`, `activated`, `listening`, `transcribing`, `thinking`, `speaking`, `ended` |
| `transcript` | `text` | What the user said (max 4000 chars) |
| `response` | `text` | Assistant reply (max 4000 chars) |
| `level` | `level` (0–1), `source` | `source` is `listening` or `speaking` |
| `tool` | `name`, `phase` | `phase` is `start` or `end` |
| `session` | `engine`, `model` | STT backend info shown in the top bar |

Unknown types and states are dropped, and fields are size-bounded before broadcast. The response is `{"accepted": bool, "clients": int}`.

### Host telemetry

`GET /api/system/metrics`

```json
{ "cpu": 23.3, "ram": 66.8, "gpu": 22.0, "temp": 37.0, "netUp": 0.137, "netDown": 0.042 }
```

| Field | Unit | Source |
|-------|------|--------|
| `cpu`, `ram` | % | `psutil` |
| `gpu` | % utilisation | NVML, first device; `null` without an NVIDIA GPU |
| `temp` | °C (GPU) | NVML; `null` without an NVIDIA GPU. The CPU temperature isn't exposed on Windows |
| `netUp`, `netDown` | Mb/s | `psutil` counter delta since the previous request |

The route returns `503` if `psutil` is not installed.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| HUD shows `VOZ OFFLINE` | `jarvis serve` isn't running on the port. Check `~/.openjarvis/show-server.log`; "Server dependencies not installed" means you need to run the `uv sync --inexact ...` command above |
| Telemetry shows **DEMO** | Same as above, or the server predates the metrics route; restart `jarvis serve` |
| Nothing happens after the claps | An old `jarvis show` (pre hands-free) is still running and waiting for Enter, or two instances are fighting over the mic. Close all of them and start one |
| Claps not detected | Lower `--threshold` (calibrate with `test_clap.py`) or raise `--clap-window` |
| STT crashes on first use with a CUDA/cuBLAS error | With `[speech].device = "auto"`, faster-whisper falls back to CPU automatically when the CUDA runtime DLLs are missing. Set `device = "cpu"` or `"cuda"` to force a choice |
| Jarvis hears but never answers | Check `uv run jarvis doctor`: Ollama must be running with the model pulled. Also try a shorter `[agent].tools` list |
| Session ends while you are still talking | Raise `--idle-timeout` or set `--silence-threshold` lower than the auto-calibrated value |
