[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetProject,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'game-runtime-mcp-host'
$sourceSkill = Join-Path $source 'SKILL.md'
if (-not (Test-Path -LiteralPath $sourceSkill -PathType Leaf)) {
    throw "스킬 원본을 찾을 수 없습니다: $sourceSkill"
}

$resolvedProject = (Resolve-Path -LiteralPath $TargetProject).Path
$skillsRoot = Join-Path $resolvedProject '.agents\skills'
$target = Join-Path $skillsRoot 'game-runtime-mcp-host'

if ((Test-Path -LiteralPath $target) -and -not $Force) {
    throw "스킬이 이미 존재합니다: $target. 교체하려면 -Force를 사용하세요."
}

New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
$staged = Join-Path $skillsRoot ('.game-runtime-mcp-host.installing.' + [Guid]::NewGuid().ToString('N'))

try {
    Copy-Item -LiteralPath $source -Destination $staged -Recurse

    $stagedSkill = Join-Path $staged 'SKILL.md'
    if (-not (Test-Path -LiteralPath $stagedSkill -PathType Leaf)) {
        throw "임시 설치본에 SKILL.md가 없습니다: $stagedSkill"
    }

    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }

    Move-Item -LiteralPath $staged -Destination $target
}
finally {
    if (Test-Path -LiteralPath $staged) {
        Remove-Item -LiteralPath $staged -Recurse -Force
    }
}

Write-Output "game-runtime-mcp-host 스킬을 설치했습니다: $target"
Write-Output '프로젝트 로컬 스킬을 다시 읽도록 새 Codex 세션을 여세요.'
