"""Windows Registry Tools — Read, Write, Search registry keys and values.

Provides JARVIS-level registry access:
- Read registry values (string, DWORD, QWORD, binary, multi-string)
- Write registry values with type safety
- Search registry keys/values recursively
- Support for all root keys (HKLM, HKCU, HKCR, HKU, HKCC)
"""

from __future__ import annotations

import subprocess
from typing import Any, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


# ---------------------------------------------------------------------------
# Registry Read Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("registry_read")
class RegistryReadTool(BaseTool):
    """Read Windows Registry values."""

    tool_id = "registry_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="registry_read",
            description=(
                "Lê valores do Registro do Windows: string, DWORD, QWORD, "
                "binário, multi-string. Suporta HKLM, HKCU, HKCR, HKU, HKCC."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Caminho da chave (ex: 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion')"},
                    "value": {"type": "string", "description": "Nome do valor (vazio para valor padrão '(Default)')"},
                    "root": {"type": "string", "enum": ["HKLM", "HKCU", "HKCR", "HKU", "HKCC"], "description": "Raiz do registro (padrão: inferido do key)", "default": ""},
                },
                "required": ["key"],
            },
            category="registry",
            requires_confirmation=False,
            required_capabilities=["system:registry"],
        )

    def _parse_key(self, key: str, root: str) -> tuple[str, str]:
        """Parse key path into root and subkey."""
        roots = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER",
                 "HKCR": "HKEY_CLASSES_ROOT", "HKU": "HKEY_USERS", "HKCC": "HKEY_CURRENT_CONFIG"}

        # Check if key starts with a root
        for short, long in roots.items():
            if key.upper().startswith(short + "\\") or key.upper().startswith(long + "\\"):
                return long, key[key.index("\\") + 1:]

        # Use provided root or default to HKCU
        root_long = roots.get(root.upper(), "HKEY_CURRENT_USER") if root else "HKEY_CURRENT_USER"
        return root_long, key

    def execute(self, **params: Any) -> ToolResult:
        key = params.get("key", "")
        value = params.get("value", "")
        root = params.get("root", "")

        if not key:
            return ToolResult(
                tool_name="registry_read",
                content="Parâmetro 'key' é obrigatório",
                success=False,
            )

        try:
            root_long, subkey = self._parse_key(key, root)

            # Build PowerShell command
            if value:
                script = f"""
                $val = Get-ItemProperty -Path "Registry::{root_long}\\{subkey}" -Name "{value}" -ErrorAction SilentlyContinue
                if ($val) {{ $val.{value} }} else {{ "VALUE_NOT_FOUND" }}
                """
            else:
                script = f"""
                $vals = Get-ItemProperty -Path "Registry::{root_long}\\{subkey}" -ErrorAction SilentlyContinue
                if ($vals) {{
                    $vals.PSObject.Properties | Where-Object {{ $_.Name -notlike 'PS*' }} | ForEach-Object {{
                        @{{ Name = $_.Name; Value = $_.Value; Type = $_.TypeNameOfValue }}
                    }} | ConvertTo-Json -Depth 2
                }} else {{
                    "KEY_NOT_FOUND"
                }}
                """

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="registry_read",
                    content=f"Erro ao ler registro: {result.stderr}",
                    success=False,
                )

            output = result.stdout.strip()

            if output in ("VALUE_NOT_FOUND", "KEY_NOT_FOUND", ""):
                return ToolResult(
                    tool_name="registry_read",
                    content=f"Chave/valor não encontrado: {root_long}\\{subkey}" + (f"\\{value}" if value else ""),
                    success=False,
                )

            import json
            try:
                data = json.loads(output)
                if isinstance(data, list):
                    # Multiple values
                    lines = [f"Valores em {root_long}\\{subkey}:"]
                    for v in data:
                        lines.append(f"  {v['Name']} ({v['Type']}) = {v['Value']}")
                    content = "\n".join(lines)
                else:
                    # Single value
                    content = f"{value} = {output}"
                    data = {"name": value, "value": output}
            except json.JSONDecodeError:
                content = output
                data = {"raw": output}

            return ToolResult(
                tool_name="registry_read",
                content=content,
                success=True,
                metadata=data,
            )

        except Exception as exc:
            return ToolResult(
                tool_name="registry_read",
                content=f"Erro ao ler registro: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Registry Write Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("registry_write")
class RegistryWriteTool(BaseTool):
    """Write Windows Registry values."""

    tool_id = "registry_write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="registry_write",
            description=(
                "Escreve valores no Registro do Windows: string (REG_SZ), "
                "expandable string (REG_EXPAND_SZ), DWORD (REG_DWORD), "
                "QWORD (REG_QWORD), binary (REG_BINARY), multi-string (REG_MULTI_SZ)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Caminho da chave"},
                    "value": {"type": "string", "description": "Nome do valor"},
                    "data": {"description": "Dados a escrever (string, número, array, bytes)"},
                    "type": {"type": "string", "enum": ["string", "expand_string", "dword", "qword", "binary", "multi_string"], "description": "Tipo do valor", "default": "string"},
                    "root": {"type": "string", "enum": ["HKLM", "HKCU", "HKCR", "HKU", "HKCC"], "description": "Raiz do registro", "default": ""},
                    "create_key": {"type": "boolean", "description": "Criar chave se não existir", "default": True},
                },
                "required": ["key", "value", "data"],
            },
            category="registry",
            requires_confirmation=True,
            required_capabilities=["system:registry"],
        )

    def _parse_key(self, key: str, root: str) -> tuple[str, str]:
        roots = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER",
                 "HKCR": "HKEY_CLASSES_ROOT", "HKU": "HKEY_USERS", "HKCC": "HKEY_CURRENT_CONFIG"}
        for short, long in roots.items():
            if key.upper().startswith(short + "\\") or key.upper().startswith(long + "\\"):
                return long, key[key.index("\\") + 1:]
        root_long = roots.get(root.upper(), "HKEY_CURRENT_USER") if root else "HKEY_CURRENT_USER"
        return root_long, key

    def execute(self, **params: Any) -> ToolResult:
        key = params.get("key", "")
        value = params.get("value", "")
        data = params.get("data")
        reg_type = params.get("type", "string")
        root = params.get("root", "")
        create_key = params.get("create_key", True)

        if not key or not value:
            return ToolResult(
                tool_name="registry_write",
                content="Parâmetros 'key' e 'value' são obrigatórios",
                success=False,
            )

        try:
            root_long, subkey = self._parse_key(key, root)

            # Map type to PowerShell property type
            type_map = {
                "string": "String",
                "expand_string": "ExpandString",
                "dword": "DWord",
                "qword": "QWord",
                "binary": "Binary",
                "multi_string": "MultiString",
            }
            ps_type = type_map.get(reg_type, "String")

            # Format data for PowerShell
            if reg_type == "multi_string" and isinstance(data, list):
                data_str = ",".join(f"'{str(d).replace("'", "''")}'" for d in data)
                data_cmd = f"@({data_str})"
            elif reg_type == "binary" and isinstance(data, (list, bytes)):
                if isinstance(data, str):
                    # Assume hex string
                    data_cmd = f"0x{data.replace(' ', '').replace('0x', '')}"
                else:
                    data_cmd = ",".join(str(b) for b in data)
                    data_cmd = f"@({data_cmd})"
            elif reg_type in ("dword", "qword"):
                data_cmd = str(int(data))
            else:
                data_str = str(data).replace("'", "''")
                data_cmd = f"'{data_str}'"

            script = f"""
            $path = "Registry::{root_long}\\{subkey}"
            if ({str(create_key).lower()}) {{
                New-Item -Path $path -Force | Out-Null
            }}
            New-ItemProperty -Path $path -Name "{value}" -Value {data_cmd} -PropertyType {ps_type} -Force | Out-Null
            "OK"
            """

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="registry_write",
                    content=f"Erro ao escrever registro: {result.stderr}",
                    success=False,
                )

            return ToolResult(
                tool_name="registry_write",
                content=f"Valor '{value}' escrito em {root_long}\\{subkey} (tipo: {reg_type})",
                success=True,
                metadata={"key": f"{root_long}\\{subkey}", "value": value, "type": reg_type},
            )

        except Exception as exc:
            return ToolResult(
                tool_name="registry_write",
                content=f"Erro ao escrever registro: {exc}",
                success=False,
            )


# ---------------------------------------------------------------------------
# Registry Search Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("registry_search")
class RegistrySearchTool(BaseTool):
    """Search Windows Registry for keys/values matching a pattern."""

    tool_id = "registry_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="registry_search",
            description=(
                "Busca no Registro do Windows: chaves, valores ou dados que correspondam "
                "a um padrão. Suporta busca recursiva em HKLM, HKCU, HKCR, HKU."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Padrão de busca (suporta wildcards * e ?)"},
                    "root": {"type": "string", "enum": ["HKLM", "HKCU", "HKCR", "HKU", "HKCC", "all"], "description": "Raiz(es) para buscar", "default": "all"},
                    "search_in": {"type": "string", "enum": ["keys", "values", "data", "all"], "description": "Onde buscar", "default": "all"},
                    "max_results": {"type": "integer", "description": "Máximo de resultados", "default": 50},
                    "timeout": {"type": "integer", "description": "Timeout em segundos", "default": 30},
                },
                "required": ["pattern"],
            },
            category="registry",
            requires_confirmation=False,
            required_capabilities=["system:registry"],
        )

    def execute(self, **params: Any) -> ToolResult:
        pattern = params.get("pattern", "")
        root = params.get("root", "all")
        search_in = params.get("search_in", "all")
        max_results = params.get("max_results", 50)
        timeout = params.get("timeout", 30)

        if not pattern:
            return ToolResult(
                tool_name="registry_search",
                content="Parâmetro 'pattern' é obrigatório",
                success=False,
            )

        try:
            roots = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER",
                     "HKCR": "HKEY_CLASSES_ROOT", "HKU": "HKEY_USERS", "HKCC": "HKEY_CURRENT_CONFIG"}

            if root == "all":
                root_list = list(roots.values())
            else:
                root_list = [roots.get(root.upper(), "HKEY_CURRENT_USER")]

            # Build search script
            search_roots = "','".join(root_list)
            script = f"""
            $roots = @('{search_roots}')
            $pattern = "{pattern.replace("'", "''")}"
            $results = @()
            $count = 0

            foreach ($root in $roots) {{
                try {{
                    $keys = Get-ChildItem -Path "Registry::$root" -Recurse -ErrorAction SilentlyContinue
                    foreach ($key in $keys) {{
                        if ($count -ge {max_results}) {{ break }}

                        # Search in key name
                        if ("{search_in}" -in @("keys", "all") -and $key.Name -like "*$pattern*") {{
                            $results += @{{ Type = "Key"; Path = $key.Name; Match = "KeyName" }}
                            $count++
                        }}

                        # Search in values
                        if ($count -ge {max_results}) {{ break }}
                        if ("{search_in}" -in @("values", "data", "all")) {{
                            $props = $key.Property
                            foreach ($prop in $props) {{
                                if ($count -ge {max_results}) {{ break }}
                                $val = $key.GetValue($prop)
                                $valStr = if ($val -is [array]) {{ $val -join ',' }} else {{ [string]$val }}

                                if ("{search_in}" -in @("values", "all") -and $prop -like "*$pattern*") {{
                                    $results += @{{ Type = "ValueName"; Path = $key.Name; Name = $prop; Value = $valStr; Match = "ValueName" }}
                                    $count++
                                }}
                                if ($count -ge {max_results}) {{ break }}
                                if ("{search_in}" -in @("data", "all") -and $valStr -like "*$pattern*") {{
                                    $results += @{{ Type = "ValueData"; Path = $key.Name; Name = $prop; Value = $valStr; Match = "ValueData" }}
                                    $count++
                                }}
                            }}
                        }}
                    }}
                }} catch {{ }}
            }}
            $results | Select-Object -First {max_results} | ConvertTo-Json -Depth 3
            """

            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=timeout + 5
            )

            if result.returncode != 0:
                return ToolResult(
                    tool_name="registry_search",
                    content=f"Erro na busca: {result.stderr}",
                    success=False,
                )

            import json
            try:
                data = json.loads(result.stdout) if result.stdout.strip() else []
                if isinstance(data, dict):
                    data = [data]
            except json.JSONDecodeError:
                data = []

            lines = [f"Resultados da busca por '{pattern}' ({len(data)} encontrados):"]
            for r in data[:max_results]:
                if r.get("Type") == "Key":
                    lines.append(f"  [Chave] {r['Path']}")
                else:
                    lines.append(f"  [Valor] {r['Path']}\\{r['Name']} = {r['Value']} (match: {r['Match']})")

            return ToolResult(
                tool_name="registry_search",
                content="\n".join(lines),
                success=True,
                metadata={"results": data, "count": len(data), "pattern": pattern},
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="registry_search",
                content=f"Busca excedeu timeout de {timeout}s",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="registry_search",
                content=f"Erro na busca do registro: {exc}",
                success=False,
            )