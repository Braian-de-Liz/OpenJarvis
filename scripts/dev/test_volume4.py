import os
os.environ['OPENJARVIS_CONFIG'] = 'configs/openjarvis/examples/jarvis-windows.toml'

import openjarvis.tools

from openjarvis.tools.windows_control.system_controls import VolumeControlTool

tool = VolumeControlTool()

# Fixed PowerShell script using -band and -shr instead of & and >>
script = """
Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
public class Audio {
    [DllImport("winmm.dll")] public static extern int waveOutGetVolume(IntPtr hwo, out uint pdwVolume);
    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr hwo, uint dwVolume);
}
"@
$vol = 0
[Audio]::waveOutGetVolume([IntPtr]::Zero, [ref]$vol) | Out-Null
$left = $vol -band 0xFFFF
$right = ($vol -shr 16) -band 0xFFFF
$avg = (($left + $right) / 2) / 65535 * 100
[math]::Round($avg)
"""

import subprocess
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", script],
    capture_output=True,
    text=True,
    timeout=10
)
print('Fixed script:')
print('  returncode:', result.returncode)
print('  stdout:', repr(result.stdout))
print('  stderr:', repr(result.stderr))