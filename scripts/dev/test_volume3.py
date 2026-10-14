import os
os.environ['OPENJARVIS_CONFIG'] = 'configs/openjarvis/examples/jarvis-windows.toml'

import openjarvis.tools

from openjarvis.tools.windows_control.system_controls import VolumeControlTool

tool = VolumeControlTool()

# Test with a simpler PowerShell command first
script = 'Write-Host "Hello from PowerShell"'
success, output = tool._run_powershell(script)
print('Simple script:')
print('  success:', success)
print('  output:', repr(output))

# Now test the actual script with error capture
script2 = """
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class Audio {
    [DllImport("winmm.dll")] public static extern int waveOutGetVolume(IntPtr hwo, out uint pdwVolume);
    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr hwo, uint dwVolume);
}
"@
$vol = 0
[Audio]::waveOutGetVolume([IntPtr]::Zero, [ref]$vol) | Out-Null
$left = $vol & 0xFFFF
$right = ($vol >> 16) & 0xFFFF
$avg = (($left + $right) / 2) / 65535 * 100
[math]::Round($avg)
"""

import subprocess
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", script2],
    capture_output=True,
    text=True,
    timeout=10
)
print('Full script with error capture:')
print('  returncode:', result.returncode)
print('  stdout:', repr(result.stdout))
print('  stderr:', repr(result.stderr))