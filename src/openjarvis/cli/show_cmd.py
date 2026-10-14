"""``jarvis-show`` — Ativação por duas palmas: ouve microfone, detecta duas palmas,
toca jingle, abre interface web e inicia chat por voz."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

console = Console(stderr=True)

# Configurações padrão para detecção de palmas
DEFAULT_CLAP_THRESHOLD = int(os.environ.get("JARVIS_CLAP_THRESH", "1500"))
DEFAULT_MIC_DEVICE = os.environ.get("JARVIS_MIC", None)  # None = default

# Variável global para o processo do servidor
_server_process: Optional[subprocess.Popen] = None


def _rms(data: bytes) -> float:
    """Compute RMS amplitude of 16-bit PCM bytes."""
    import struct

    n = len(data) // 2
    if n == 0:
        return 0.0
    shorts = struct.unpack(f"{n}h", data[: n * 2])
    return (sum(s * s for s in shorts) / n) ** 0.5


def _play_jingle(jingle_path: Path) -> bool:
    """Toca o arquivo jingle.mp3 se existir. Retorna True se tocou."""
    if not jingle_path.exists():
        console.print(f"[dim]Jingle não encontrado em {jingle_path}[/dim]")
        return False
    try:
        import sounddevice as sd
        import soundfile as sf

        data, sr = sf.read(str(jingle_path), dtype="float32")
        sd.play(data, sr)
        sd.wait()
        return True
    except Exception as exc:
        console.print(f"[yellow]Falha ao tocar jingle: {exc}[/yellow]")
        return False


def _open_web_interface(
    port: int = 8000, frontend_port: int = 5173, path: str = "/jarvis"
) -> None:
    """Abre a interface web no navegador padrão."""
    # Frontend (Vite dev server) roda na porta 5173 por padrão
    url = f"http://localhost:{frontend_port}{path}"
    console.print(f"[cyan]Abrindo interface web: {url}[/cyan]")
    try:
        webbrowser.open(url)
    except Exception as exc:
        console.print(f"[yellow]Não foi possível abrir navegador: {exc}[/yellow]")


def _get_uv_path() -> str:
    """Retorna o caminho para o executável uv."""
    # Tenta várias localizações possíveis
    candidates = [
        # 1. Mesmo diretório do Python atual
        str(
            Path(sys.executable).parent
            / ("uv.exe" if sys.platform == "win32" else "uv")
        ),
        # 2. ~/.local/bin (instalação padrão do uv)
        str(
            Path.home()
            / ".local"
            / "bin"
            / ("uv.exe" if sys.platform == "win32" else "uv")
        ),
        # 3. PATH do sistema
        "uv.exe" if sys.platform == "win32" else "uv",
    ]
    for cand in candidates:
        if Path(cand).exists() or cand == "uv":
            return cand
    return "uv"  # fallback


def _hud_events(port: int):
    """Publisher for HUD state while waiting for claps (best-effort)."""
    from openjarvis.cli._hands_free import VoiceEventPublisher

    return VoiceEventPublisher(f"http://127.0.0.1:{port}")


def _start_voice_chat(port: int = 8000, idle_timeout: float = 30.0) -> None:
    """Run a hands-free voice session (``jarvis chat --hands-free``).

    Returns when the session ends (idle timeout or exit phrase).
    """
    # Detecta o diretório do projeto (onde está o pyproject.toml)
    project_dir = (
        Path(__file__).resolve().parents[3]
    )  # src/openjarvis/cli -> project root
    console.print(f"[green]Iniciando sessão de voz em {project_dir}[/green]")
    try:
        subprocess.run(
            _jarvis_cmd(
                "chat",
                "--hands-free",
                "--idle-timeout",
                str(idle_timeout),
                "--events-url",
                f"http://127.0.0.1:{port}",
            ),
            cwd=project_dir,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Sessão de voz terminou com erro: {exc}[/red]")
    except FileNotFoundError:
        console.print(
            "[red]Comando 'uv' não encontrado. "
            "Certifique-se de que uv está no PATH.[/red]"
        )


def _check_server_running(port: int = 8000, host: str = "localhost") -> bool:
    """Verifica se o servidor web está rodando na porta especificada."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def _jarvis_cmd(*args: str) -> list[str]:
    """Run a jarvis subcommand with *this* interpreter (no `uv run` re-sync)."""
    return [sys.executable, "-c", "from openjarvis.cli import main; main()", *args]


def _server_log_path() -> Path:
    log_dir = Path.home() / ".openjarvis"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "show-server.log"


def _start_web_server(port: int = 8000) -> bool:
    """Start `jarvis serve` in background if nothing is listening on ``port``."""
    global _server_process

    if _check_server_running(port, host="127.0.0.1"):
        console.print(f"[dim]Servidor já rodando na porta {port}[/dim]")
        return True

    project_dir = Path(__file__).resolve().parents[3]
    log_path = _server_log_path()
    console.print(
        f"[cyan]Iniciando jarvis serve na porta {port} (log: {log_path})...[/cyan]"
    )

    try:
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        popen_kwargs: dict = {
            "cwd": project_dir,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "env": {**os.environ, "PYTHONIOENCODING": "utf-8"},
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        _server_process = subprocess.Popen(
            _jarvis_cmd("serve", "--host", "127.0.0.1", "--port", str(port)),
            **popen_kwargs,
        )

        # Model/tool loading can take a while on first start.
        for _ in range(90):
            time.sleep(1)
            if _server_process.poll() is not None:
                break
            if _check_server_running(port, host="127.0.0.1"):
                console.print(
                    f"[green]Servidor iniciado em http://127.0.0.1:{port}[/green]"
                )
                return True

        console.print(
            f"[red]Servidor não subiu na porta {port}. "
            f"Últimas linhas de {log_path}:[/red]"
        )
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[
                -15:
            ]
            for line in tail:
                console.print(f"[dim]  {line}[/dim]", markup=False)
        except OSError:
            pass
        return False

    except Exception as exc:
        console.print(f"[red]Erro ao iniciar servidor: {exc}[/red]")
        return False


def _cleanup_server() -> None:
    """Finaliza o processo do servidor se foi iniciado por nós."""
    global _server_process
    if _server_process is not None:
        try:
            if sys.platform == "win32":
                _server_process.terminate()
            else:
                _server_process.kill()
            _server_process.wait(timeout=5)
        except Exception:
            pass
        _server_process = None


def _listen_for_double_clap(
    threshold: int = DEFAULT_CLAP_THRESHOLD,
    mic_device: Optional[int] = None,
    sample_rate: int = 16000,
    chunk: int = 1024,
    clap_window: float = 1.0,  # segundos entre duas palmas
) -> bool:
    """
    Ouve o microfone e detecta duas palmas em sequência.
    Retorna True quando detecta duas palmas.
    """
    try:
        import sounddevice as sd
    except ImportError:
        console.print(
            "[red]sounddevice não instalado. Rode: uv sync --extra voice[/red]"
        )
        return False

    console.print(
        f"[dim]Ouvindo microfone... (threshold={threshold}, "
        f"device={mic_device or 'default'})[/dim]"
    )
    console.print("[dim]Bata duas palmas seguidas para ativar.[/dim]")

    clap_count = 0
    last_clap_time = 0.0
    in_clap = False
    clap_cooldown = 0.15  # segundos para evitar detecção múltipla da mesma palma

    chunks_per_second = sample_rate / chunk
    cooldown_chunks = int(clap_cooldown * chunks_per_second)
    cooldown_counter = 0

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=chunk,
        device=mic_device,
    ) as stream:
        while True:
            raw, _ = stream.read(chunk)
            data = bytes(raw)
            amplitude = _rms(data)

            if cooldown_counter > 0:
                cooldown_counter -= 1

            if amplitude > threshold and cooldown_counter == 0:
                now = time.time()
                if not in_clap:
                    in_clap = True
                    if clap_count == 0 or (now - last_clap_time) <= clap_window:
                        clap_count += 1
                        last_clap_time = now
                        console.print(
                            f"[green]Palma {clap_count} detectada![/green] "
                            f"(RMS={amplitude:.0f})"
                        )
                        if clap_count >= 2:
                            return True
                    else:
                        # Primeira palma muito antiga, reinicia contagem
                        clap_count = 1
                        last_clap_time = now
                        console.print(
                            "[yellow]Janela expirada. "
                            "Reiniciando contagem. Palma 1.[/yellow]"
                        )
                    cooldown_counter = cooldown_chunks
            else:
                in_clap = False

            # Reset se passou muito tempo desde a primeira palma
            if clap_count > 0 and (time.time() - last_clap_time) > clap_window:
                clap_count = 0
                console.print(
                    "[dim]Janela de palmas expirada. Aguardando nova sequência...[/dim]"
                )


@click.command()
@click.option(
    "--threshold",
    "-t",
    type=int,
    default=DEFAULT_CLAP_THRESHOLD,
    show_default=True,
    help=(
        "Sensibilidade da palma (RMS). Menor = mais sensível. "
        "Variável de ambiente: JARVIS_CLAP_THRESH"
    ),
)
@click.option(
    "--mic",
    "-m",
    type=int,
    default=None,
    help=(
        "ID do microfone (use 'python -m sounddevice' para listar). "
        "Variável de ambiente: JARVIS_MIC"
    ),
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=8000,
    show_default=True,
    help="Porta da interface web",
)
@click.option(
    "--no-web",
    is_flag=True,
    default=False,
    help="Não abrir a interface web",
)
@click.option(
    "--no-jingle",
    is_flag=True,
    default=False,
    help="Não tocar o jingle",
)
@click.option(
    "--clap-window",
    type=float,
    default=1.0,
    show_default=True,
    help="Tempo máximo (segundos) entre duas palmas",
)
@click.option(
    "--frontend-port",
    type=int,
    default=5173,
    show_default=True,
    help="Porta do frontend (Vite dev server)",
)
@click.option(
    "--web-path",
    type=str,
    default="/jarvis",
    show_default=True,
    help="Caminho da página no frontend",
)
@click.option(
    "--idle-timeout",
    type=float,
    default=30.0,
    show_default=True,
    help="Segundos de silêncio até a sessão de voz encerrar e voltar às palmas",
)
def show(
    threshold: int,
    mic: Optional[int],
    port: int,
    no_web: bool,
    no_jingle: bool,
    clap_window: float,
    frontend_port: int,
    web_path: str,
    idle_timeout: float,
) -> None:
    """Ativação por duas palmas: ouve o microfone, detecta duas palmas seguidas,
    toca jingle (se existir), abre interface web e inicia chat por voz.

    Variáveis de ambiente:
      JARVIS_CLAP_THRESH  Sensibilidade (padrão: 1500)
      JARVIS_MIC          ID do microfone (padrão: dispositivo padrão)
    """
    console.print("[bold green]🔊 jarvis-show — Ativação por palmas[/bold green]")
    console.print(
        f"  Threshold: {threshold}  |  Mic: {mic or 'default'}  "
        f"|  Janela: {clap_window}s"
    )

    # Caminho do jingle (procura em assets/ na raiz do projeto)
    project_dir = Path(__file__).resolve().parents[3]
    jingle_path = project_dir / "assets" / "jingle.mp3"

    events = None
    hud_opened = False
    try:
        # Inicia servidor web se necessário (antes do loop para estar pronto)
        if not no_web:
            _start_web_server(port)
        events = _hud_events(port)

        # Loop principal: espera duas palmas
        while True:
            events.state("idle")
            detected = _listen_for_double_clap(
                threshold=threshold,
                mic_device=mic,
                clap_window=clap_window,
            )
            if detected:
                console.print(
                    "[bold green]✨ Duas palmas detectadas! "
                    "Ativando Jarvis...[/bold green]"
                )
                events.state("activated")

                if not no_jingle:
                    _play_jingle(jingle_path)

                # Open the HUD once; later sessions reuse the same tab (it
                # reconnects to the WebSocket on its own).
                if not no_web and not hud_opened:
                    _open_web_interface(
                        port, frontend_port=frontend_port, path=web_path
                    )
                    hud_opened = True

                _start_voice_chat(port=port, idle_timeout=idle_timeout)

                # Após o chat terminar, volta a ouvir
                console.print(
                    "\n[dim]Sessão encerrada. Voltando a ouvir palmas...[/dim]\n"
                )
    except KeyboardInterrupt:
        console.print("\n[dim]Encerrado pelo usuário.[/dim]")
    except Exception as exc:
        console.print(f"\n[red]Erro: {exc}[/red]")
        import traceback

        traceback.print_exc()
    finally:
        if events is not None:
            events.state("idle")
            events.close()
        _cleanup_server()


__all__ = ["show"]
