#Requires -Version 5.1
# Bootstrap wrapper for coursectl (Windows PowerShell / PowerShell 7+).
#
# Thin by design (course spec sections 5.4 and 12): its only job is to
# download the correct prebuilt coursectl binary from the latest GitHub
# Release, verify its checksum, and place it in ./bin/. All real course
# operations live in coursectl itself. macOS/Linux users: run
# scripts/bootstrap.sh instead; both wrappers behave identically.

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 can default to TLS 1.0; GitHub requires TLS 1.2+.
if ($PSVersionTable.PSVersion.Major -lt 6) {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}

$Repo = "ai-eng-bootcamps/ai-native-sweng"
$Api = "https://api.github.com/repos/$Repo/releases/latest"
$InstallDir = Join-Path (Get-Location) "bin"

function Fail([string]$Message) {
    Write-Host "bootstrap: $Message" -ForegroundColor Red
    exit 1
}

# Detect operating system ($IsMacOS/$IsLinux are undefined and therefore
# falsy on Windows PowerShell 5.1, which only runs on Windows).
if ($IsMacOS) { $os = "darwin" }
elseif ($IsLinux) { $os = "linux" }
else { $os = "windows" }

# Detect architecture.
$archRaw = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { (uname -m) }
switch -Regex ($archRaw) {
    "^(AMD64|x86_64)$"  { $arch = "amd64" }
    "^(ARM64|arm64|aarch64)$" { $arch = "arm64" }
    default { Fail "unsupported architecture '$archRaw'" }
}
if ($os -eq "windows" -and $arch -eq "arm64") {
    # No native windows/arm64 build is published; the amd64 binary runs
    # under Windows x64 emulation.
    $arch = "amd64"
}

Write-Host "Looking up the latest coursectl release for $os/$arch..."
try {
    $release = Invoke-RestMethod -Uri $Api -UseBasicParsing
} catch {
    Fail "no release found at https://github.com/$Repo/releases - coursectl has not been published yet"
}
if (-not $release.tag_name -or -not $release.tag_name.StartsWith("coursectl/v")) {
    Fail "latest release '$($release.tag_name)' is not a coursectl release - coursectl has not been published yet"
}

$version = $release.tag_name -replace "^coursectl/", ""
$ext = if ($os -eq "windows") { "zip" } else { "tar.gz" }
$archive = "coursectl_${version}_${os}_${arch}.${ext}"

$asset = $release.assets | Where-Object { $_.name -eq $archive } | Select-Object -First 1
$sums = $release.assets | Where-Object { $_.name -eq "SHA256SUMS" } | Select-Object -First 1
if (-not $asset) { Fail "release $($release.tag_name) has no asset named $archive" }
if (-not $sums) { Fail "release $($release.tag_name) has no SHA256SUMS asset" }

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("coursectl-bootstrap-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading $archive..."
    $archivePath = Join-Path $tmp $archive
    $sumsPath = Join-Path $tmp "SHA256SUMS"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archivePath -UseBasicParsing
    Invoke-WebRequest -Uri $sums.browser_download_url -OutFile $sumsPath -UseBasicParsing

    Write-Host "Verifying SHA256 checksum..."
    $line = (Get-Content $sumsPath) | Where-Object { $_ -match ("\s" + [regex]::Escape($archive) + "$") } | Select-Object -First 1
    if (-not $line) { Fail "$archive is not listed in SHA256SUMS" }
    $expected = ($line -split "\s+")[0].ToLowerInvariant()
    $actual = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { Fail "checksum mismatch for ${archive}: expected $expected, got $actual" }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    if ($ext -eq "zip") {
        Expand-Archive -Path $archivePath -DestinationPath $InstallDir -Force
    } else {
        tar -xzf $archivePath -C $InstallDir
    }
} finally {
    Remove-Item -Recurse -Force $tmp
}

$binary = if ($os -eq "windows") { Join-Path $InstallDir "coursectl.exe" } else { Join-Path $InstallDir "coursectl" }
Write-Host "coursectl $version installed to $binary"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. $binary setup"
Write-Host "  2. $binary status"
Write-Host "Optionally add $InstallDir to your PATH."
