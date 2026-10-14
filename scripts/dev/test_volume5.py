import subprocess

# Fixed PowerShell script with proper C# using statements
script = """
Add-Type -TypeDefinition @"
using System;
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

result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", script],
    capture_output=True,
    text=True,
    timeout=10
)
print('Fixed script with proper using:')
print('  returncode:', result.returncode)
print('  stdout:', repr(result.stdout))
print('  stderr:', repr(result.stderr))