<# 
.SYNOPSIS
    jarvis-show - Ativação do Jarvis por duas palmas (PowerShell wrapper)

.DESCRIPTION
    Ouve o microfone, detecta duas palmas seguidas, toca jingle (se existir),
    abre interface web e inicia chat por voz.

.PARAMETER Threshold
    Sensibilidade da palma (RMS). Menor = mais sensível. Padrão: 1500 (env JARVIS_CLAP_THRESH)

.PARAMETER Mic
    ID do microfone. Use 'python -m sounddevice' para listar. Padrão: default (env JARVIS_MIC)

.PARAMETER Port
    Porta da interface web. Padrão: 8000

.PARAMETER NoWeb
    Não abrir a interface web

.PARAMETER NoJingle
    Não tocar o jingle

.PARAMETER ClapWindow
    Tempo máximo (segundos) entre duas palmas. Padrão: 1.0

.EXAMPLE
    .\jarvis-show.ps1

.EXAMPLE
    .\jarvis-show.ps1 -Threshold 1000 -Mic 9

.EXAMPLE
    .\jarvis-show.ps1 -NoWeb -ClapWindow 1.5
#>

param(
    [int]$Threshold = 1500,
    [int]$Mic = $null,
    [int]$Port = 8000,
    [switch]$NoWeb,
    [switch]$NoJingle,
    [float]$ClapWindow = 1.0
)

# Usa variáveis de ambiente se não passadas como parâmetro
if ($env:JARVIS_CLAP_THRESH) { $Threshold = [int]$env:JARVIS_CLAP_THRESH }
if ($env:JARVIS_MIC) { $Mic = [int]$env:JARVIS_MIC }

# Resolve caminhos dinamicamente
$jarvisDir = Join-Path $env:USERPROFILE "desktop\jarvis"
$uvPath = Join-Path $env:USERPROFILE ".local\bin\uv.exe"

# Adiciona uv ao PATH temporariamente
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  jarvis-show - Ativação por duas palmas" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuração:" -ForegroundColor Yellow
Write-Host "  Threshold (sensibilidade): $Threshold"
Write-Host "  Microfone: $(if ($Mic) { $Mic } else { 'default' })"
Write-Host "  Porta web: $Port"
Write-Host ""
Write-Host "Pressione Ctrl+C para sair." -ForegroundColor Gray
Write-Host ""

# Muda para o diretório do projeto
if (-not (Test-Path $jarvisDir)) {
    Write-Error "Diretório do projeto não encontrado: $jarvisDir"
    exit 1
}
Set-Location $jarvisDir

if (-not (Test-Path $uvPath)) {
    Write-Error "uv.exe não encontrado em: $uvPath"
    exit 1
}

# Executa o comando jarvis show com os parâmetros
$argsList = @("run", "jarvis", "show", "--threshold", $Threshold.ToString(), "--port", $Port.ToString(), "--clap-window", $ClapWindow.ToString())
if ($Mic) { $argsList += "--mic", $Mic.ToString() }
if ($NoWeb) { $argsList += "--no-web" }
if ($NoJingle) { $argsList += "--no-jingle" }

& $uvPath $argsList