$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    if (-not (Get-Command lualatex -ErrorAction SilentlyContinue)) {
        throw 'lualatex não encontrado no PATH.'
    }
    if (-not (Get-Command biber -ErrorAction SilentlyContinue)) {
        throw 'biber não encontrado no PATH.'
    }
    & lualatex -interaction=nonstopmode -halt-on-error main.tex
    if ($LASTEXITCODE -ne 0) { throw 'Primeira passagem LuaLaTeX falhou.' }
    & biber main
    if ($LASTEXITCODE -ne 0) { throw 'Biber falhou.' }
    & lualatex -interaction=nonstopmode -halt-on-error main.tex
    if ($LASTEXITCODE -ne 0) { throw 'Segunda passagem LuaLaTeX falhou.' }
    & lualatex -interaction=nonstopmode -halt-on-error main.tex
    if ($LASTEXITCODE -ne 0) { throw 'Terceira passagem LuaLaTeX falhou.' }
    Write-Output (Join-Path $here 'main.pdf')
}
finally {
    Pop-Location
}
