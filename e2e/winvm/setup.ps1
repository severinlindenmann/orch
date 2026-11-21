# Fresh winvm clone -> ready to test orch (ORCH-1127). Runs inside the clone as dev (winvm run).
# The golden image is a bare Windows 11 ARM64: no git, no uv, no Python. This installs Git for Windows (portable,
# ARM64, with bash for the CLI smoke), uv and an x64 Python (packages without ARM64 wheels, e.g. cryptography),
# then unpacks the source zip pushed to C:\ci\src.zip into C:\ci\src as a one-commit git repository.
# Every download is pinned to one version and its SHA-256 (from the release page) and checked before it runs.
# uv checks the hash of the Python it installs itself. To update: change a version and its hash together.
param(
    [string]$GitVersion = "2.56.1",
    [string]$GitSha256 = "0dca0d9f760924a7e6752235d7dd6eb1a9b508ee714b6ed15d89252e5a58c5c9",
    [string]$UvVersion = "0.13.9",
    [string]$UvSha256 = "72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878",
    [string]$Python = "cpython-3.13-windows-x86_64-none"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ci = "C:\ci"
New-Item -ItemType Directory -Force $ci | Out-Null

# Windows PowerShell 5.1 with "Stop" turns any line a program writes to stderr (progress, warnings) into a
# fatal error: run programs through Invoke-Native, which judges them by their exit code only.
function Invoke-Native {
    $ErrorActionPreference = "Continue"
    & $args[0] @($args | Select-Object -Skip 1) 2>&1 | ForEach-Object { "$_" } | Write-Host
    return $LASTEXITCODE
}

function Get-Checked($url, $out, $sha) {
    Invoke-WebRequest -UseBasicParsing $url -OutFile $out
    $got = (Get-FileHash -Algorithm SHA256 $out).Hash.ToLower()
    if ($got -ne $sha.ToLower()) { Remove-Item -Force $out; throw "SHA-256 of $url is $got, expected $sha" }
}

function Step($name, [scriptblock]$body) {
    $t = [Diagnostics.Stopwatch]::StartNew()
    & $body
    "STEP $name $([int]$t.Elapsed.TotalSeconds)s" | Write-Host
}

Step "git" {
    $exe = "$ci\PortableGit.7z.exe"
    $url = "https://github.com/git-for-windows/git/releases/download/v$GitVersion.windows.1/PortableGit-$GitVersion-arm64.7z.exe"
    Get-Checked $url $exe $GitSha256
    $null = Invoke-Native $exe "-o$ci\git" -y
    if (-not (Test-Path "$ci\git\cmd\git.exe")) { throw "PortableGit did not unpack" }
}
# Machine-wide PATH so later winvm runs (new sessions) find git, bash and uv.
$add = "$ci\git\cmd;$ci\git\bin;$ci\git\usr\bin;$env:USERPROFILE\.local\bin"
[Environment]::SetEnvironmentVariable("Path", "$add;" + [Environment]::GetEnvironmentVariable("Path", "Machine"), "Machine")
$env:Path = "$add;$env:Path"

Step "uv" {
    $zip = "$ci\uv.zip"
    Get-Checked "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-aarch64-pc-windows-msvc.zip" $zip $UvSha256
    New-Item -ItemType Directory -Force "$env:USERPROFILE\.local\bin" | Out-Null
    Expand-Archive -Force $zip "$env:USERPROFILE\.local\bin"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not on PATH" }
}
Step "python" {
    if ((Invoke-Native uv python install $Python) -ne 0) { throw "uv python install failed" }
}
Step "source" {
    if (Test-Path "$ci\src") { Remove-Item -Recurse -Force "$ci\src" }
    Expand-Archive "$ci\src.zip" "$ci\src"
    Set-Location "$ci\src"
    if ((Invoke-Native git -c init.defaultBranch=develop init -q) -ne 0) { throw "git init failed" }
    if ((Invoke-Native git -c core.autocrlf=false add -A) -ne 0) { throw "git add failed" }
    if ((Invoke-Native git -c user.name=ci -c user.email=ci@localhost commit -q -m "ci source") -ne 0) {
        throw "git commit of the source failed"
    }
}
"SETUP OK" | Write-Host
