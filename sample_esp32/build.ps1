param([switch]$Flash, [string]$Port = 'COM19')
$ErrorActionPreference = 'Stop'
$idfRoot = 'D:\Espressif\Espressif\frameworks\esp-idf-v5.1.2'
$toolsRoot = 'D:\Espressif\Espressif'
$python = Join-Path $toolsRoot 'python_env\idf5.1_py3.11_env\Scripts\python.exe'
$env:IDF_PATH = $idfRoot
$env:IDF_TOOLS_PATH = $toolsRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:IDF_COMPONENT_MANAGER = '0'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = $idfRoot.Replace('\', '/')
$env:PATH = (Join-Path $toolsRoot 'tools\idf-git\2.43.0\cmd') + ';' + $env:PATH
$env:CCACHE_DIR = Join-Path $PSScriptRoot '.ccache'
$exports = & $python -B "$idfRoot\tools\idf_tools.py" export --format key-value
if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF environment setup failed' }
foreach ($line in $exports) {
    if ($line -match '^([A-Z_]+)=(.*)$') {
        $name = $Matches[1]
        $value = $Matches[2]
        if ($name -eq 'PATH') { $value = $value.Replace('%PATH%', $env:PATH) }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}
Push-Location $PSScriptRoot
try {
    & $python -B "$idfRoot\tools\idf.py" build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    if ($Flash) {
        & $python -B "$idfRoot\tools\idf.py" -p $Port flash
        if ($LASTEXITCODE -ne 0) { throw 'Flash failed' }
    }
} finally {
    Pop-Location
}
