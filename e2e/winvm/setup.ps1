# Fresh winvm clone -> ready to test orch (ORCH-1127). Runs inside the clone as dev (winvm run).
# The golden image is a bare Windows 11 ARM64: no git, no uv, no Python. This installs Git for Windows (portable,
# ARM64, with bash for the CLI smoke), uv and an x64 Python (packages without ARM64 wheels, e.g. cryptography),
# then unpacks the source zip pushed to C:\ci\src.zip into C:\ci\src as a one-commit git repository.
param(
    [string]$GitVersion = "2.56.1",
    [string]$Python = "cpython-3.13-windows-x86_64-none"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ci = "C:\ci"
New-Item -ItemType Directory -Force $ci | Out-Null

function Step($name, [scriptblock]$body) {
    $t = [Diagnostics.Stopwatch]::StartNew()
    & $body
    "STEP $name $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
}

Step "git" {
    $exe = "$ci\PortableGit.7z.exe"
    $url = "https://github.com/git-for-windows/git/releases/download/v$GitVersion.windows.1/PortableGit-$GitVersion-arm64.7z.exe"
    Invoke-WebRequest -UseBasicParsing $url -OutFile $exe
    & $exe "-o$ci\git" -y | Out-Null
    if (-not (Test-Path "$ci\git\cmd\git.exe")) { throw "PortableGit did not unpack" }
}
# Machine-wide PATH so later winvm runs (new sessions) find git, bash and uv.
$add = "$ci\git\cmd;$ci\git\bin;$ci\git\usr\bin;$env:USERPROFILE\.local\bin"
[Environment]::SetEnvironmentVariable("Path", "$add;" + [Environment]::GetEnvironmentVariable("Path", "Machine"), "Machine")
$env:Path = "$add;$env:Path"

Step "uv" {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not on PATH" }
}
Step "python" {
    uv python install $Python
    if ($LASTEXITCODE -ne 0) { throw "uv python install failed" }
}
Step "source" {
    if (Test-Path "$ci\src") { Remove-Item -Recurse -Force "$ci\src" }
    Expand-Archive "$ci\src.zip" "$ci\src"
    Set-Location "$ci\src"
    git -c init.defaultBranch=develop init -q
    git -c user.name=ci -c user.email=ci@localhost add -A
    git -c user.name=ci -c user.email=ci@localhost commit -q -m "ci source"
    if ($LASTEXITCODE -ne 0) { throw "git commit of the source failed" }
}
"SETUP OK" | Write-Host
