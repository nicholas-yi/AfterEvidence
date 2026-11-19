param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$Path,
    [switch]$Remove
)

# Run a tagged study from its own read-only worktree, so editing main never changes a running
# study's frozen sources. Ignored run data, venvs, vendor checkouts and provider stacks are linked
# (directory junctions) from this checkout, so journals and stores stay in one place.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This helper uses directory junctions and requires Windows.' }

$root = (git rev-parse --show-toplevel).Trim()
if (-not $Path) { $Path = Join-Path (Split-Path $root -Parent) ("AfterEvidence-" + $Tag) }

if ($Remove) {
    git -C $root worktree remove --force $Path
    Write-Output ("Removed worktree " + $Path + "; linked data in " + $root + " is untouched.")
    return
}

if ((git -C $root cat-file -t $Tag 2>$null) -ne 'tag') { throw ('No annotated tag ' + $Tag + '.') }
if (Test-Path -LiteralPath $Path) { throw ($Path + ' already exists.') }
git -C $root worktree add --detach $Path $Tag | Out-Null

foreach ($name in 'runs', '.venv', '.venv-providers', 'vendor', 'providers', 'cache') {
    $source = Join-Path $root ('research\' + $name)
    if (-not (Test-Path -LiteralPath $source)) { continue }
    New-Item -ItemType Junction -Path (Join-Path $Path ('research\' + $name)) -Target $source | Out-Null
}
Write-Output ('Worktree for ' + $Tag + ' at ' + $Path + ' (commit ' + (git -C $Path rev-parse --short HEAD).Trim() + ').')
Write-Output 'Run the stage from that directory; remove it afterwards with -Remove.'
