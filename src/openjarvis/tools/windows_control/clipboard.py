"""Clipboard Tools — Read, Write, and History for Windows.

Provides JARVIS-level clipboard control:
- Read text, HTML, RTF, files from clipboard
- Write text, HTML, files to clipboard
- Clipboard history (Windows 10+ Cloud Clipboard)
"""

from __future__ import annotations

import subprocess
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Clipboard Read Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("clipboard_read")
class ClipboardReadTool(BaseTool):
    """Read clipboard content: text, HTML, RTF, file paths."""

    tool_id = "clipboard_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_read",
            description=(
                "Lê conteúdo da área de transferência: texto plano, HTML, RTF, "
                "lista de arquivos. Suporta múltiplos formatos simultâneos."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["text", "html", "rtf", "files", "all"],
                        "description": "Formato a ler",
                        "default": "text",
                    },
                    "max_length": {"type": "integer", "description": "Tamanho máximo do texto retornado", "default": 10000},
                },
                "required": [],
            },
            category="clipboard",
            requires_confirmation=False,
            required_capabilities=["gui:clipboard"],
        )

    def execute(self, **params: Any) -> ToolResult:
        fmt = params.get("format", "text")
        max_length = params.get("max_length", 10000)

        try:
            # Use PowerShell for comprehensive clipboard access
            if fmt == "text":
                script = """
                Add-Type -AssemblyName System.Windows.Forms
                [System.Windows.Forms.Clipboard]::GetText()
                """
            elif fmt == "html":
                script = """
                Add-Type -AssemblyName System.Windows.Forms
                $data = [System.Windows.Forms.Clipboard]::GetDataObject()
                if ($data.GetDataPresent('HTML Format')) {
                    $html = $data.GetData('HTML Format')
                    [System.Text.Encoding]::UTF8.GetString($html)
                }
                """
            elif fmt == "rtf":
                script = """
                Add-Type -AssemblyName System.Windows.Forms
                $data = [System.Windows.Forms.Clipboard]::GetDataObject()
                if ($data.GetDataPresent('Rich Text Format')) {
                    $data.GetData('Rich Text Format')
                }
                """
            elif fmt == "files":
                script = """
                Add-Type -AssemblyName System.Windows.Forms
                $data = [System.Windows.Forms.Clipboard]::GetDataObject()
                if ($data.GetDataPresent([System.Windows.Forms.DataFormats]::FileDrop)) {
                    $files = $data.GetData([System.Windows.Forms.DataFormats]::FileDrop)
                    $files -join '|'
                }
                """
            else:  # all
                script = """
                Add-Type -AssemblyName System.Windows.Forms
                $data = [System.Windows.Forms.Clipboard]::GetDataObject()
                $formats = $data.GetFormats()
                $result = @{}
                foreach ($f in $formats) {
                    try {
                        $val = $data.GetData($f)
                        if ($val -is [string]) {
                            $result[$f] = $val
                        } elseif ($val -is [array]) {
                            $result[$f] = $val -join '|'
                        } else {
                            $result[$f] = $val.GetType().FullName
                        }
                    } catch {
                        $result[$f] = 'ERROR'
                    }
                }
                $result | ConvertTo-Json -Depth 2
                """

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="clipboard_read",
                    content=f"Erro ao ler clipboard: {result.stderr}",
                    success=False,
                )

            output = result.stdout.strip()

            if fmt == "all":
                import json
                try:
                    data = json.loads(output) if output else {}
                except json.JSONDecodeError:
                    data = {"raw": output}
                return ToolResult(
                    tool_name="clipboard_read",
                    content=f"Formatos disponíveis: {', '.join(data.keys())}",
                    success=True,
                    metadata=data,
                )

            if not output:
                return ToolResult(
                    tool_name="clipboard_read",
                    content="Clipboard vazio ou formato não disponível",
                    success=True,
                    metadata={"format": fmt, "empty": True},
                )

            # Truncate if needed
            if len(output) > max_length:
                output = output[:max_length] + f"\n... (truncado, total: {len(result.stdout)} chars)"

            return ToolResult(
                tool_name="clipboard_read",
                content=output,
                success=True,
                metadata={"format": fmt, "length": len(result.stdout)},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="clipboard_read",
                content=f"Erro ao ler clipboard: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Clipboard Write Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("clipboard_write")
class ClipboardWriteTool(BaseTool):
    """Write to clipboard: text, HTML, RTF, files."""

    tool_id = "clipboard_write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_write",
            description=(
                "Escreve na área de transferência: texto, HTML, RTF, ou lista de arquivos. "
                "Pode definir múltiplos formatos simultaneamente."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto plano para copiar"},
                    "html": {"type": "string", "description": "HTML para copiar (formato CF_HTML)"},
                    "rtf": {"type": "string", "description": "RTF para copiar"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Lista de caminhos de arquivos para copiar"},
                    "clear_first": {"type": "boolean", "description": "Limpar clipboard antes de escrever", "default": True},
                },
                "required": [],
            },
            category="clipboard",
            requires_confirmation=False,
            required_capabilities=["gui:clipboard"],
        )

    def execute(self, **params: Any) -> ToolResult:
        text = params.get("text")
        html = params.get("html")
        rtf = params.get("rtf")
        files = params.get("files")
        clear_first = params.get("clear_first", True)

        if not any([text, html, rtf, files]):
            return ToolResult(
                tool_name="clipboard_write",
                content="Forneça pelo menos um de: text, html, rtf, files",
                success=False,
            )

        try:
            # Build PowerShell script
            script_parts = []
            if clear_first:
                script_parts.append("[System.Windows.Forms.Clipboard]::Clear()")

            data_obj = "$data = New-Object System.Windows.Forms.DataObject"

            if text is not None:
                escaped = text.replace("'", "''").replace("\r\n", "`r`n").replace("\n", "`n")
                script_parts.append(f"$data.SetText('{escaped}')")

            if html is not None:
                # CF_HTML format requires header
                html_escaped = html.replace("'", "''").replace("\r\n", "`r`n").replace("\n", "`n")
                script_parts.append(f"""
                $htmlHeader = @"
Version:0.9
StartHTML:00000000
EndHTML:00000000
StartFragment:00000000
EndFragment:00000000
"@
                $htmlContent = '<html><body><!--StartFragment-->{html_escaped}<!--EndFragment--></body></html>'
                $htmlBytes = [System.Text.Encoding]::UTF8.GetBytes($htmlContent)
                $headerBytes = [System.Text.Encoding]::UTF8.GetBytes($htmlHeader)
                $ms = New-Object System.IO.MemoryStream
                $ms.Write($headerBytes, 0, $headerBytes.Length)
                $ms.Write($htmlBytes, 0, $htmlBytes.Length)
                $data.SetData('HTML Format', $ms)
                """)

            if rtf is not None:
                rtf_escaped = rtf.replace("'", "''")
                script_parts.append(f"$data.SetData('Rich Text Format', '{rtf_escaped}')")

            if files:
                file_list = ",".join(f"'{f.replace("'", "''")}'" for f in files)
                script_parts.append(f"$data.SetFileDropList(@({file_list}))")

            script_parts.append("[System.Windows.Forms.Clipboard]::SetDataObject($data, $true)")

            script = """
            Add-Type -AssemblyName System.Windows.Forms
            """ + "\n".join(script_parts)

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="clipboard_write",
                    content=f"Erro ao escrever clipboard: {result.stderr}",
                    success=False,
                )

            formats = []
            if text: formats.append("text")
            if html: formats.append("html")
            if rtf: formats.append("rtf")
            if files: formats.append(f"files ({len(files)})")

            return ToolResult(
                tool_name="clipboard_write",
                content=f"Copiado para clipboard: {', '.join(formats)}",
                success=True,
                metadata={"formats": formats},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="clipboard_write",
                content=f"Erro ao escrever clipboard: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Clipboard History Tool (Windows 10+ Cloud Clipboard)
# ---------------------------------------------------------------------------

@ToolRegistry.register("clipboard_history")
class ClipboardHistoryTool(BaseTool):
    """Access Windows Cloud Clipboard history (Win+V)."""

    tool_id = "clipboard_history"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_history",
            description=(
                "Acessa histórico da área de transferência do Windows (Win+V). "
                "Lista itens recentes, fixa/desfixa, limpa histórico. Requer Windows 10 1809+."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "pin", "unpin", "delete", "clear"],
                        "description": "Ação no histórico",
                        "default": "list",
                    },
                    "index": {"type": "integer", "description": "Índice do item no histórico (0 = mais recente)"},
                    "limit": {"type": "integer", "description": "Máximo de itens para listar", "default": 20},
                },
                "required": ["action"],
            },
            category="clipboard",
            requires_confirmation=False,
            required_capabilities=["gui:clipboard"],
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        index = params.get("index")
        limit = params.get("limit", 20)

        try:
            # Windows Cloud Clipboard is not directly accessible via public API.
            # We can only simulate Win+V or use third-party tools.
            # For now, provide a PowerShell-based approach that reads from
            # the clipboard history database (requires specific permissions).

            if action == "list":
                # Try to read from clipboard history database
                script = f"""
                $dbPath = "$env:LOCALAPPDATA\\Microsoft\\Windows\\Clipboard\\Clipboard.dat"
                if (Test-Path $dbPath) {{
                    # This is a binary format, hard to parse without Windows.Data.PackageManager
                    "Histórico da área de transferência encontrado em: $dbPath"
                    "Nota: Leitura direta requer APIs internas do Windows."
                    "Use 'clipboard_read' para item atual ou ferramentas de terceiros para histórico completo."
                }} else {{
                    "Histórico da área de transferência não encontrado ou desabilitado."
                    "Verifique Configurações > Sistema > Área de transferência > Histórico da área de transferência."
                }}
                """
            else:
                return ToolResult(
                    tool_name="clipboard_history",
                    content=f"Ação '{action}' não implementada diretamente. Histórico do Windows requer APIs internas.",
                    success=False,
                )

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )

            return ToolResult(
                tool_name="clipboard_history",
                content=result.stdout.strip() or result.stderr.strip(),
                success=result.returncode == 0,
                metadata={"action": action},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="clipboard_history",
                content=f"Erro no histórico do clipboard: {exc}",
                success=False,
            )