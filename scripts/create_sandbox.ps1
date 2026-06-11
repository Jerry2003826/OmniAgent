param(
    [string]$Target = "omni-sandbox"
)

$ErrorActionPreference = "Stop"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$root = [System.IO.Path]::GetFullPath($Target)

New-Item -ItemType Directory -Path $root -Force | Out-Null
Push-Location $root
try {
    if (-not (Test-Path ".git")) {
        git init | Out-Null
    }

    [System.IO.File]::WriteAllText(
        (Join-Path $root "package.json"),
        @'
{
  "name": "omni-sandbox",
  "version": "0.0.0",
  "private": true,
  "packageManager": "pnpm@10.0.0",
  "scripts": {
    "test": "node test.js",
    "build": "node build.js"
  }
}
'@ + "`n",
        $utf8NoBom
    )

    [System.IO.File]::WriteAllText(
        (Join-Path $root "pnpm-lock.yaml"),
        @'
lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

importers:
  .: {}
'@ + "`n",
        $utf8NoBom
    )

    [System.IO.File]::WriteAllText(
        (Join-Path $root "test.js"),
        "console.log(""sandbox test ok"");`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $root "build.js"),
        "console.log(""sandbox build ok"");`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $root "CLAUDE.md"),
        @'
# OmniMemory Sandbox

Use this disposable repository for OmniMemory hook and transcript spikes.
'@ + "`n",
        $utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $root ".gitignore"),
        @'
.omni/generated/
node_modules/
'@ + "`n",
        $utf8NoBom
    )

    git add package.json pnpm-lock.yaml test.js build.js CLAUDE.md .gitignore | Out-Null
    git -c user.name="Omni Sandbox" -c user.email="omni-sandbox@local.invalid" commit -m "sandbox init" 2>$null | Out-Null

    Write-Output $root
}
finally {
    Pop-Location
}
