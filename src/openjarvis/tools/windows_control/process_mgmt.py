"""Process Management Tools — List, Kill, Info, Services for Windows.

Provides JARVIS-level process control:
- List processes with filters (name, PID, CPU, memory)
- Kill processes by PID or name
- Get detailed process info (threads, modules, handles, paths)
- Windows Services control (start, stop, restart, status)
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Process List Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("process_list")
class ProcessListTool(BaseTool):
    """List running processes with filtering and sorting options."""

    tool_id = "process_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="process_list",
            description=(
                "Lista processos em execução com filtros: nome, PID, uso de CPU/memória. "
                "Suporta ordenação e limitação de resultados."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "description": "Filtrar por nome do processo (parcial, case-insensitive)"},
                    "pid": {"type": "integer", "description": "Filtrar por PID específico"},
                    "sort_by": {"type": "string", "enum": ["cpu", "memory", "name", "pid"], "description": "Ordenar por", "default": "cpu"},
                    "limit": {"type": "integer", "description": "Máximo de processos a retornar", "default": 50},
                    "include_system": {"type": "boolean", "description": "Incluir processos do sistema", "default": False},
                },
                "required": [],
            },
            category="process",
            requires_confirmation=False,
            required_capabilities=["system:process"],
        )

    def execute(self, **params: Any) -> ToolResult:
        filter_name = params.get("filter", "").lower()
        target_pid = params.get("pid")
        sort_by = params.get("sort_by", "cpu")
        limit = params.get("limit", 50)
        include_system = params.get("include_system", False)

        try:
            # Use PowerShell for rich process info
            script = """
            $procs = Get-Process
            if ($args[0]) { $procs = $procs | Where-Object { $_.ProcessName -like "*$args[0]*" } }
            if ($args[1]) { $procs = $procs | Where-Object { $_.Id -eq $args[1] } }
            if (-not $args[2]) { $procs = $procs | Where-Object { $_.SessionId -ne 0 -or $_.ProcessName -in @('explorer', 'dwm', 'taskhostw') } }
            $procs | Select-Object Id, ProcessName, CPU, WS, PM, NPM, Handles, Threads, StartTime, Path, SessionId | Sort-Object $args[3] -Descending | Select-Object -First $args[4] | ConvertTo-Json -Depth 2
            """

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script, filter_name, str(target_pid) if target_pid else "", str(include_system).lower(), sort_by, str(limit)],
                capture_output=True, text=True, timeout=15
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="process_list",
                    content=f"Erro ao listar processos: {result.stderr}",
                    success=False,
                )

            import json
            try:
                processes = json.loads(result.stdout) if result.stdout.strip() else []
                if isinstance(processes, dict):
                    processes = [processes]
            except json.JSONDecodeError:
                processes = []

            # Format output
            lines = [f"{'PID':>6}  {'CPU%':>6}  {'Mem(MB)':>8}  {'Nome'}"]
            for p in processes:
                cpu = p.get("CPU", 0) or 0
                ws_mb = (p.get("WS", 0) or 0) / 1024 / 1024
                name = p.get("ProcessName", "N/A")
                pid = p.get("Id", 0)
                lines.append(f"{pid:>6}  {cpu:>6.1f}  {ws_mb:>8.1f}  {name}")

            content = "\n".join(lines[:limit + 1])
            return ToolResult(
                tool_name="process_list",
                content=content,
                success=True,
                metadata={"processes": processes, "count": len(processes)},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="process_list",
                content=f"Erro ao listar processos: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Process Kill Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("process_kill")
class ProcessKillTool(BaseTool):
    """Kill processes by PID or name. Supports force kill and tree kill."""

    tool_id = "process_kill"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="process_kill",
            description=(
                "Finaliza processos por PID ou nome. Suporta força (force kill) "
                "e eliminação em árvore (processo + filhos). Requer confirmação."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "PID do processo a finalizar"},
                    "name": {"type": "string", "description": "Nome do processo (finaliza todos com esse nome)"},
                    "force": {"type": "boolean", "description": "Forçar finalização (SIGKILL / TerminateProcess)", "default": False},
                    "tree": {"type": "boolean", "description": "Finalizar processo e todos os filhos", "default": False},
                },
                "required": [],
            },
            category="process",
            requires_confirmation=True,
            required_capabilities=["system:process"],
        )

    def execute(self, **params: Any) -> ToolResult:
        pid = params.get("pid")
        name = params.get("name")
        force = params.get("force", False)
        tree = params.get("tree", False)

        if not pid and not name:
            return ToolResult(
                tool_name="process_kill",
                content="Forneça 'pid' ou 'name' para identificar o processo",
                success=False,
            )

        try:
            if tree:
                # Use taskkill /T for tree kill
                if pid:
                    cmd = ["taskkill", "/PID", str(pid), "/T"]
                else:
                    cmd = ["taskkill", "/IM", name, "/T"]
                if force:
                    cmd.append("/F")
            else:
                if pid:
                    cmd = ["taskkill", "/PID", str(pid)]
                else:
                    cmd = ["taskkill", "/IM", name]
                if force:
                    cmd.append("/F")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                target = f"PID {pid}" if pid else f"nome '{name}'"
                return ToolResult(
                    tool_name="process_kill",
                    content=f"Processo(s) {target} finalizado(s) com sucesso",
                    success=True,
                    metadata={"pid": pid, "name": name, "force": force, "tree": tree},
                )
            else:
                return ToolResult(
                    tool_name="process_kill",
                    content=f"Falha ao finalizar: {result.stderr}",
                    success=False,
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="process_kill",
                content="Timeout ao tentar finalizar processo",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="process_kill",
                content=f"Erro ao finalizar processo: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Process Info Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("process_info")
class ProcessInfoTool(BaseTool):
    """Get detailed information about a specific process."""

    tool_id = "process_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="process_info",
            description=(
                "Obtém informações detalhadas de um processo: threads, módulos (DLLs), "
                "handles, caminho do executável, linha de comando, usuário, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pid": {"type": "integer", "description": "PID do processo"},
                    "name": {"type": "string", "description": "Nome do processo (usa o primeiro encontrado)"},
                    "include_threads": {"type": "boolean", "description": "Incluir lista de threads", "default": False},
                    "include_modules": {"type": "boolean", "description": "Incluir módulos carregados (DLLs)", "default": False},
                },
                "required": [],
            },
            category="process",
            requires_confirmation=False,
            required_capabilities=["system:process"],
        )

    def execute(self, **params: Any) -> ToolResult:
        pid = params.get("pid")
        name = params.get("name")
        include_threads = params.get("include_threads", False)
        include_modules = params.get("include_modules", False)

        if not pid and not name:
            return ToolResult(
                tool_name="process_info",
                content="Forneça 'pid' ou 'name'",
                success=False,
            )

        try:
            filter_clause = f"Id -eq {pid}" if pid else f"ProcessName -like '*{name}*'"
            script = f"""
            $proc = Get-Process | Where-Object {{ {filter_clause} }} | Select-Object -First 1
            if (-not $proc) {{ exit 1 }}
            $info = @{{
                Id = $proc.Id
                ProcessName = $proc.ProcessName
                CPU = $proc.CPU
                WS = $proc.WorkingSet64
                PM = $proc.PagedMemorySize64
                NPM = $proc.NonpagedSystemMemorySize64
                Handles = $proc.HandleCount
                Threads = $proc.Threads.Count
                StartTime = $proc.StartTime
                Path = $proc.Path
                SessionId = $proc.SessionId
                UserName = ($proc | Select-Object -ExpandProperty UserName -ErrorAction SilentlyContinue)
                MainWindowTitle = $proc.MainWindowTitle
                Responding = $proc.Responding
                PriorityClass = $proc.PriorityClass
            }}
            """

            if include_threads:
                script += """
                $info.Threads = @()
                foreach ($t in $proc.Threads) {
                    $info.Threads += @{ Id = $t.Id; StartTime = $t.StartTime; CPU = $t.TotalProcessorTime.TotalMilliseconds; State = $t.ThreadState; WaitReason = $t.WaitReason }
                }
                """

            if include_modules:
                script += """
                $info.Modules = @()
                foreach ($m in $proc.Modules) {
                    $info.Modules += @{ Name = $m.ModuleName; Path = $m.FileName; BaseAddress = $m.BaseAddress; Size = $m.ModuleMemorySize }
                }
                """

            script += "$info | ConvertTo-Json -Depth 4"

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=15
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="process_info",
                    content=f"Processo não encontrado ou erro: {result.stderr}",
                    success=False,
                )

            import json
            info = json.loads(result.stdout)

            # Format readable output
            lines = [
                f"PID: {info.get('Id')}",
                f"Nome: {info.get('ProcessName')}",
                f"Caminho: {info.get('Path', 'N/A')}",
                f"CPU Total: {info.get('CPU', 0):.1f}s",
                f"Memória (WS): {info.get('WS', 0) / 1024 / 1024:.1f} MB",
                f"Handles: {info.get('Handles', 0)}",
                f"Threads: {info.get('Threads', 0)}",
                f"Iniciado: {info.get('StartTime', 'N/A')}",
                f"Usuário: {info.get('UserName', 'N/A')}",
                f"Janela: {info.get('MainWindowTitle', 'N/A')}",
                f"Respondendo: {info.get('Responding', False)}",
                f"Prioridade: {info.get('PriorityClass', 'N/A')}",
            ]

            if include_threads and info.get("Threads"):
                lines.append(f"\nThreads ({len(info['Threads'])}):")
                for t in info["Threads"][:10]:
                    lines.append(f"  TID {t['Id']}: CPU={t['CPU']:.1f}ms State={t['State']}")
                if len(info["Threads"]) > 10:
                    lines.append(f"  ... e mais {len(info['Threads']) - 10} threads")

            if include_modules and info.get("Modules"):
                lines.append(f"\nMódulos ({len(info['Modules'])}):")
                for m in info["Modules"][:15]:
                    lines.append(f"  {m['Name']} ({m['Size'] / 1024:.0f} KB)")
                if len(info["Modules"]) > 15:
                    lines.append(f"  ... e mais {len(info['Modules']) - 15} módulos")

            return ToolResult(
                tool_name="process_info",
                content="\n".join(lines),
                success=True,
                metadata=info,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="process_info",
                content=f"Erro ao obter info do processo: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Service Control Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("service")
class ServiceControlTool(BaseTool):
    """Control Windows Services: start, stop, restart, status, enable/disable."""

    tool_id = "service"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="service",
            description=(
                "Controla serviços do Windows: iniciar, parar, reiniciar, status, "
                "habilitar/desabilitar (startup automático/manual/desabilitado)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop", "restart", "status", "enable", "disable", "list"],
                        "description": "Ação a executar",
                    },
                    "name": {"type": "string", "description": "Nome do serviço (ex: 'wuauserv' para Windows Update)"},
                    "display_name": {"type": "string", "description": "Nome de exibição do serviço"},
                    "startup_type": {"type": "string", "enum": ["auto", "manual", "disabled"], "description": "Tipo de inicialização para enable/disable", "default": "auto"},
                },
                "required": ["action"],
            },
            category="process",
            requires_confirmation=True,
            required_capabilities=["system:service"],
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "")
        name = params.get("name")
        display_name = params.get("display_name")
        startup_type = params.get("startup_type", "auto")

        if action != "list" and not name and not display_name:
            return ToolResult(
                tool_name="service",
                content="Forneça 'name' ou 'display_name' do serviço",
                success=False,
            )

        try:
            if action == "list":
                script = "Get-Service | Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json"
            else:
                identifier = name if name else f"'{display_name}'"
                if action in ("start", "stop", "restart"):
                    verb = {"start": "Start", "stop": "Stop", "restart": "Restart"}[action]
                    script = f"Get-Service {identifier} | {verb}-Service -PassThru | Select-Object Name, DisplayName, Status | ConvertTo-Json"
                elif action in ("enable", "disable"):
                    st = {"auto": "Automatic", "manual": "Manual", "disabled": "Disabled"}[startup_type]
                    script = f"Set-Service {identifier} -StartupType {st} -PassThru | Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json"
                elif action == "status":
                    script = f"Get-Service {identifier} | Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json"
                else:
                    return ToolResult(tool_name="service", content=f"Ação desconhecida: {action}", success=False)

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=15
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="service",
                    content=f"Erro no serviço: {result.stderr}",
                    success=False,
                )

            import json
            try:
                services = json.loads(result.stdout) if result.stdout.strip() else []
                if isinstance(services, dict):
                    services = [services]
            except json.JSONDecodeError:
                services = []

            if action == "list":
                lines = [f"{'Nome':<30} {'Display Name':<40} {'Status':<12} {'Inicialização'}"]
                for s in services:
                    lines.append(f"{s.get('Name',''):<30} {s.get('DisplayName',''):<40} {s.get('Status',''):<12} {s.get('StartType','')}")
                content = "\n".join(lines[:100])
            else:
                s = services[0] if services else {}
                content = f"Serviço: {s.get('DisplayName', s.get('Name', name))}\nStatus: {s.get('Status', 'N/A')}\nInicialização: {s.get('StartType', 'N/A')}"

            return ToolResult(
                tool_name="service",
                content=content,
                success=True,
                metadata={"services": services, "action": action},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="service",
                content=f"Erro no controle de serviço: {exc}",
                success=False,
            )