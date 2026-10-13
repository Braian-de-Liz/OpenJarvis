import os
os.environ['OPENJARVIS_CONFIG'] = 'configs/openjarvis/examples/jarvis-windows.toml'

import openjarvis.tools

from openjarvis.tools.windows_control.system_controls import VolumeControlTool

tool = VolumeControlTool()

# Test the _run_powershell method directly
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
$left = $vol & 0xFFFF
$right = ($vol >> 16) & 0xFFFF
$avg = (($left + $right) / 2) / 65535 * 100
[math]::Round($avg)
"""

success, output = tool._run_powershell(script)
print('success:', success)
print('output:', repr(output))
print('output.isdigit():', output.isdigit() if success else 'N/A')