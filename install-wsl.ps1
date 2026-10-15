<#
.SYNOPSIS
  Windows 에서 WSL2 + Ubuntu 를 만들고, 그 안에 al-alloy-design 을 설치합니다 (bootstrap.py 까지 한 번에).

.DESCRIPTION
  1. 사전 점검        Windows 빌드, 가상화, 디스크, 메모리
  2. Windows 기능     WSL, 가상 머신 플랫폼 (필요하면 재부팅 후 자동으로 이어서 실행)
  3. 배포판           Ubuntu 설치 (--no-launch, 첫 실행 화면이 다른 명령을 막지 않게)
  4. 사용자           리눅스 계정 생성, 기본 사용자 지정, 비밀번호 입력
  5. 메모리           %UserProfile%\.wslconfig 의 memory (기본: RAM 의 약 65%)
  6. 프로젝트         apt 패키지 -> git clone -> python3 bootstrap.py --yes

  이미 끝난 단계는 건너뛰므로 몇 번을 다시 실행해도 됩니다.
  로그: %LOCALAPPDATA%\al-alloy-design\install-wsl.log

  저장소를 받은 뒤 install.cmd 를 더블클릭하면 이 스크립트가 실행됩니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-wsl.ps1 -User alloy -MemoryGB 20 -ModelRepo unsloth/Qwen3-14B-GGUF
#>
[CmdletBinding()]
param(
    [string]$User = "",                 # 리눅스 사용자 이름 (비우면 기존 기본 사용자, 없으면 물어봄)
    [string]$Distro = "Ubuntu",         # wsl --list --online 의 이름
    [int]$MemoryGB = 0,                 # WSL 메모리 상한 (0 = RAM 의 약 65%)
    [string]$ModelRepo = "",            # 모델 직접 지정 (예: unsloth/Qwen3-14B-GGUF). 비우면 bootstrap.py 가 메모리에 맞춰 고름
    [string]$Quant = "Q4_K_M",
    [string]$RepoUrl = "https://github.com/Godorina/al-alloy-design.git",
    [string]$Branch = "windows-support",
    [string]$Dir = "al-alloy-design",   # 리눅스 홈 아래 폴더 이름
    [switch]$SkipBootstrap,             # WSL 준비와 clone 까지만 하고 bootstrap.py 는 감지만
    [switch]$NoExisting,                # 이 PC 에 이미 있는 모델(Ollama, LM Studio 등)을 쓰지 않고 새로 다운로드
    [switch]$Yes,                       # 확인 질문 생략 (재부팅 확인 포함)
    [switch]$Resume                     # 재부팅 후 자동 실행용 (저장해 둔 옵션을 불러옴)
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"                                   # wsl.exe 출력을 UTF-16 대신 UTF-8 로
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$StateDir = Join-Path $env:LOCALAPPDATA "al-alloy-design"
$StateFile = Join-Path $StateDir "install-wsl.json"
$LogFile = Join-Path $StateDir "install-wsl.log"
$LxssKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"
$OptionNames = "User", "Distro", "MemoryGB", "ModelRepo", "Quant", "RepoUrl", "Branch", "Dir", "SkipBootstrap", "NoExisting", "Yes"
New-Item -ItemType Directory -Force $StateDir | Out-Null

if ($Resume -and (Test-Path $StateFile)) {
    $saved = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($name in $OptionNames) {
        if ($null -ne $saved.$name) { Set-Variable -Name $name -Value $saved.$name }
    }
}

# ---------------------------------------------------------------- 출력 도우미

function Write-Step([string]$n, [string]$title) { Write-Host "`n[$n] $title" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Info([string]$msg) { Write-Host "        $msg" }
function Write-Warn([string]$msg) { Write-Host "    !   $msg" -ForegroundColor Yellow }
function Stop-Install([string]$msg) {
    Write-Host "`n실패: $msg" -ForegroundColor Red
    Write-Host "로그: $LogFile  (같은 명령을 다시 실행하면 끝난 단계는 건너뜁니다)"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
function Confirm-Step([string]$question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$question [Y/n]"
    return -not ($answer.Trim().ToLower() -in @("n", "no"))
}

# ---------------------------------------------------------------- 시스템 도우미

function Invoke-Elevated([string]$file, [string[]]$arguments) {
    # 스크립트는 일반 권한으로 돌고, 관리자 권한이 필요한 명령만 UAC 로 올립니다
    try {
        $p = Start-Process -FilePath $file -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        return $p.ExitCode
    } catch {
        Stop-Install "관리자 권한 요청(UAC)이 거부되었습니다: $file $($arguments -join ' ')"
    }
}

function Test-RebootPending {
    # 기능을 켠 뒤 적용 대기 중이면 생깁니다. 시작 메뉴의 "다시 시작"은 이 적용을 미룰 수 있어 재부팅 후에도 남아 있을 수 있습니다
    return Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
}

function Test-WslInstalled {
    # 기능만 켜진 Windows 의 wsl.exe 는 "설치되지 않음" 안내만 하고 0 이 아닌 코드로 끝납니다
    $ErrorActionPreference = "Continue"   # 5.1 은 리디렉션한 stderr 를 오류로 바꿔 Stop 이면 여기서 끝납니다
    & wsl.exe --version *> $null
    return $LASTEXITCODE -eq 0
}

function Save-Options {
    $state = [ordered]@{}
    foreach ($name in $OptionNames) {
        $value = Get-Variable -Name $name -ValueOnly
        if ($value -is [System.Management.Automation.SwitchParameter]) { $value = $value.IsPresent }
        $state[$name] = $value
    }
    $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
}

function Request-Reboot([string]$why) {
    Write-Warn $why
    if (-not $PSCommandPath) { Stop-Install "재부팅 후 이어서 실행하려면 이 스크립트를 파일로 저장해서 실행하세요 (README 참고)." }
    Save-Options
    # 다운로드 폴더에서 지워져도 이어서 실행되도록 고정 경로에 복사해 둡니다
    $self = Join-Path $StateDir "install-wsl.ps1"
    if ($PSCommandPath -ne $self) { Copy-Item -Force $PSCommandPath $self }
    $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File `"$self`" -Resume"
    Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "al-alloy-design-install" -Value $cmd
    Write-Info "재부팅 후 로그인하면 이 설치가 자동으로 이어서 실행됩니다."
    Write-Info "시작 메뉴의 '다시 시작'은 기능 적용을 미룰 수 있어서, 이 스크립트가 shutdown /r 로 재부팅합니다."
    if (-not (Confirm-Step "지금 재부팅할까요? (열린 작업을 먼저 저장하세요)")) {
        Write-Info "나중에 재부팅하려면 PowerShell 에서:  shutdown /r /t 0   (시작 메뉴의 '다시 시작' 말고)"
        try { Stop-Transcript | Out-Null } catch {}
        exit 0
    }
    try { Stop-Transcript | Out-Null } catch {}
    shutdown.exe /r /t 10 /c "al-alloy-design: WSL 기능 적용을 위해 재부팅합니다"
    exit 0
}

function Get-DistroInfo([string]$name) {
    if (-not (Test-Path $LxssKey)) { return $null }
    foreach ($key in Get-ChildItem $LxssKey -ErrorAction SilentlyContinue) {
        $p = Get-ItemProperty $key.PSPath
        if ($p.DistributionName -eq $name) {
            return [pscustomobject]@{ Path = $key.PSPath; Version = $p.Version; DefaultUid = $p.DefaultUid }
        }
    }
    return $null
}

function Get-WslArgs([string[]]$Cmd, [switch]$AsRoot, [string]$Cd) {
    $who = if ($AsRoot) { "root" } else { $User }
    return @("-d", $Distro, "-u", $who, "--cd", $Cd, "--") + $Cmd
}

function Invoke-Wsl([string[]]$Cmd, [switch]$AsRoot, [string]$Cd = "~", [switch]$AllowFail) {
    # 화면(콘솔)에 그대로 연결해서 실행합니다: 진행 표시와 비밀번호 입력이 정상으로 보이고, 출력이 반환값에 섞이지 않습니다
    $wslArgs = Get-WslArgs -Cmd $Cmd -AsRoot:$AsRoot -Cd $Cd | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }
    $p = Start-Process -FilePath "wsl.exe" -ArgumentList $wslArgs -NoNewWindow -PassThru
    $null = $p.Handle   # 이것이 없으면 Windows PowerShell 에서 ExitCode 가 비는 경우가 있습니다
    $p.WaitForExit()
    if ($p.ExitCode -ne 0 -and -not $AllowFail) { Stop-Install "wsl $($Cmd -join ' ') (종료 코드 $($p.ExitCode))" }
    return $p.ExitCode
}

function Get-WslOutput([string[]]$Cmd, [switch]$AsRoot, [string]$Cd = "~", [switch]$AllowFail) {
    $wslArgs = Get-WslArgs -Cmd $Cmd -AsRoot:$AsRoot -Cd $Cd
    $ErrorActionPreference = "Continue"   # 5.1: 리디렉션한 stderr(예: "no such user")가 Stop 에서는 예외가 됩니다
    $out = & wsl.exe @wslArgs 2>$null
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) { Stop-Install "wsl $($Cmd -join ' ') (종료 코드 $LASTEXITCODE)" }
    return ($out | Out-String).Trim()
}

# scripts/install-cuda-wsl.sh 와 같은 기준: 최신 Ubuntu(glibc 2.42+)에서는 CUDA 13.2 이상만 컴파일됩니다
$MinCuda = [version]"13.2"

function Get-NvidiaSmiText {
    if (-not (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) { return $null }
    $ErrorActionPreference = "Continue"
    return (& nvidia-smi.exe 2>$null | Out-String)
}

function Get-GpuPlan([string[]]$names, [string]$smiText) {
    # Mode: cuda (GPU 로 설치) | cpu (NVIDIA 아님) | no-driver | old-driver
    $nvidia = @($names | Where-Object { $_ -match "NVIDIA" }) | Select-Object -First 1
    if (-not $nvidia) { return [pscustomobject]@{ Mode = "cpu"; Name = ($names -join ", "); Cuda = $null } }
    if (-not $smiText) { return [pscustomobject]@{ Mode = "no-driver"; Name = $nvidia; Cuda = $null } }
    $cuda = if ($smiText -match 'CUDA Version:\s*([0-9]+\.[0-9]+)') { $Matches[1] } else { $null }
    $mode = if ($cuda -and [version]$cuda -ge $MinCuda) { "cuda" } else { "old-driver" }
    return [pscustomobject]@{ Mode = $mode; Name = $nvidia; Cuda = $cuda }
}

function ConvertTo-GB([string]$value) {
    if ($value -match '^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*$') {
        $n = [double]$Matches[1]
        switch ($Matches[2].ToUpper()) {
            "T" { return $n * 1024 }
            "G" { return $n }
            "M" { return $n / 1024 }
            "K" { return $n / 1024 / 1024 }
            default { return $n / 1GB }
        }
    }
    return $null
}

function Set-WslMemory([int]$targetGB) {
    # [wsl2] 섹션의 memory= 만 바꾸고 나머지 설정은 그대로 둡니다. 이미 목표 이상이면 건드리지 않습니다
    $path = Join-Path $env:USERPROFILE ".wslconfig"
    $lines = @(if (Test-Path $path) { Get-Content $path })
    $section = ""; $sectionAt = -1; $memoryAt = -1; $current = $null
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[(.+?)\]\s*$') {
            $section = $Matches[1].ToLower()
            if ($section -eq "wsl2") { $sectionAt = $i }
        } elseif ($section -eq "wsl2" -and $lines[$i] -match '^\s*memory\s*=\s*(.+?)\s*$') {
            $memoryAt = $i; $current = ConvertTo-GB $Matches[1]
        }
    }
    if ($null -ne $current -and $current -ge $targetGB) {
        Write-Ok ".wslconfig memory=$([math]::Round($current, 1))GB (목표 ${targetGB}GB 이상이라 그대로 둡니다)"
        return $false
    }
    $entry = "memory=${targetGB}GB"
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) { $list.Add($line) }
    if ($memoryAt -ge 0) { $list[$memoryAt] = $entry }
    elseif ($sectionAt -ge 0) { $list.Insert($sectionAt + 1, $entry) }
    else { if ($list.Count) { $list.Add("") }; $list.Add("[wsl2]"); $list.Add($entry) }
    [IO.File]::WriteAllLines($path, $list, (New-Object Text.UTF8Encoding $false))
    Write-Ok ".wslconfig 에 $entry 를 썼습니다 ($path)"
    return $true
}

# ---------------------------------------------------------------- 시작

Start-Transcript -Path $LogFile -Append | Out-Null
Write-Host "al-alloy-design: WSL 설치 도우미" -ForegroundColor Cyan
if ($Resume) { Write-Info "재부팅 후 이어서 실행합니다." }

# 1. 사전 점검 ---------------------------------------------------------------
Write-Step 1 "사전 점검"
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
if ($build -lt 19041) { Stop-Install "WSL2 는 Windows 10 2004(빌드 19041) 이상이 필요합니다. 현재 빌드 $build" }
Write-Ok "$($os.Caption) (빌드 $build)"

$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Write-Ok "메모리 ${ramGB}GB"

$freeGB = [math]::Round((Get-PSDrive ($env:SystemDrive.TrimEnd(":"))).Free / 1GB)
if ($freeGB -lt 30) { Write-Warn "$($env:SystemDrive) 여유 공간이 ${freeGB}GB 입니다. 모델·빌드에 20~30GB 가 필요합니다." }
else { Write-Ok "$($env:SystemDrive) 여유 공간 ${freeGB}GB" }

$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
if (-not (Get-CimInstance Win32_ComputerSystem).HypervisorPresent -and -not $cpu.VirtualizationFirmwareEnabled) {
    Write-Warn "CPU 가상화가 꺼져 있는 것 같습니다. WSL2 가 안 켜지면 BIOS/UEFI 에서 Intel VT-x / AMD SVM 을 켜세요."
} else { Write-Ok "가상화 사용 가능" }

# GPU: NVIDIA + 드라이버가 CUDA 13.2 이상이면 GPU 로, 아니면 CPU 로. 드라이버만 문제면 여기서 미리 물어봅니다
$Gpu = Get-GpuPlan @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) (Get-NvidiaSmiText)
switch ($Gpu.Mode) {
    "cuda" { Write-Ok "GPU: $($Gpu.Name) (드라이버 CUDA $($Gpu.Cuda)) -> GPU 로 설치" }
    "cpu" { Write-Ok "GPU: $($Gpu.Name) -> NVIDIA 가 아니라 CPU 로 설치 (느립니다)" }
    default {
        $why = if ($Gpu.Mode -eq "no-driver") { "드라이버(nvidia-smi)가 없습니다" } else { "드라이버가 CUDA $($Gpu.Cuda) 까지만 지원합니다 ($MinCuda 이상 필요)" }
        Write-Warn "GPU: $($Gpu.Name) 가 있지만 $why."
        Write-Info "NVIDIA 드라이버를 설치/업데이트하면 GPU 로 훨씬 빠르게 돌릴 수 있습니다: https://www.nvidia.com/Download/index.aspx"
        if (Confirm-Step "지금은 CPU 로 계속할까요? (n: 드라이버 페이지를 열고 멈춥니다. 업데이트 후 install.cmd 를 다시 실행하세요)") {
            $Gpu.Mode = "cpu-forced"
        } else {
            Start-Process "https://www.nvidia.com/Download/index.aspx"
            try { Stop-Transcript | Out-Null } catch {}
            exit 0
        }
    }
}

$existing = Get-DistroInfo $Distro
if (-not $User -and -not ($existing -and $existing.DefaultUid)) {
    $suggest = $env:USERNAME.ToLower() -replace '[^a-z0-9_-]', ''
    if ($suggest -notmatch '^[a-z_]') { $suggest = "alloy" }
    $User = $suggest
    if (-not $Yes) {
        $typed = Read-Host "리눅스 사용자 이름 [$suggest]"
        if ($typed.Trim()) { $User = $typed.Trim() }
    }
}
if ($User -and $User -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { Stop-Install "리눅스 사용자 이름은 영문 소문자, 숫자, _, - 만 됩니다: $User" }

# 2. Windows 기능 ------------------------------------------------------------
Write-Step 2 "Windows 기능 (WSL, 가상 머신 플랫폼)"
$changed = $false   # 이번 실행에서 WSL 쪽을 실제로 바꿨을 때만 재부팅합니다 (Windows 업데이트의 재부팅 대기와 구분)
if (Test-WslInstalled) { Write-Ok "WSL 설치됨" }
else {
    $changed = $true
    Write-Info "WSL 을 설치합니다 (관리자 권한 창이 뜨면 '예')"
    $null = Invoke-Elevated "wsl.exe" @("--install", "--no-distribution")
    if (-not (Test-WslInstalled)) {
        # 오래된 기본 wsl.exe 는 --no-distribution 을 모를 수 있습니다. 배포판 이름을 주는 형식은 모두 받습니다
        $null = Invoke-Elevated "wsl.exe" @("--install", "-d", $Distro)
    }
}

$missing = @()
foreach ($feature in "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform") {
    $state = (Get-CimInstance Win32_OptionalFeature -Filter "Name='$feature'").InstallState
    if ($state -ne 1) { $missing += $feature } else { Write-Ok "$feature 켜짐" }
}
if ($missing.Count) {
    Write-Info "기능을 켭니다: $($missing -join ', ') (관리자 권한 창이 뜨면 '예')"
    $dismArgs = @("/online", "/enable-feature", "/all", "/norestart") + @($missing | ForEach-Object { "/featurename:$_" })
    $code = Invoke-Elevated "dism.exe" $dismArgs
    if ($code -notin @(0, 3010)) { Stop-Install "DISM 이 실패했습니다 (종료 코드 $code)" }
    Write-Ok "기능을 켰습니다 (종료 코드 $code)"
    $changed = $true
}
if ($changed -and (Test-RebootPending)) { Request-Reboot "켠 기능을 적용하려면 재부팅이 필요합니다." }
elseif (Test-RebootPending) { Write-Info "Windows 에 다른 재부팅 대기(예: Windows 업데이트)가 있지만 WSL 과는 무관해 계속합니다." }
if (-not (Test-WslInstalled)) { Stop-Install "WSL 이 설치되지 않았습니다. 'wsl --install' 을 직접 실행한 뒤 이 스크립트를 다시 실행하세요." }

# 3. 배포판 ------------------------------------------------------------------
Write-Step 3 "$Distro 설치"
$info = Get-DistroInfo $Distro
if ($info) { Write-Ok "$Distro 가 이미 있습니다" }
else {
    & wsl.exe --install -d $Distro --no-launch
    $info = Get-DistroInfo $Distro
    if (-not $info) {
        if (Test-RebootPending) { Request-Reboot "배포판을 설치하려면 재부팅이 한 번 더 필요합니다." }
        Stop-Install "$Distro 가 등록되지 않았습니다. 'wsl --list --online' 으로 이름을 확인하세요."
    }
    Write-Ok "$Distro 를 설치했습니다"
}
# 첫 실행 화면(OOBE)은 입력을 기다리는 동안 다른 wsl 명령을 모두 멈추게 합니다. 계정은 4 단계에서 직접 만듭니다
Set-ItemProperty $info.Path -Name RunOOBE -Value 0 -Type DWord
if ($info.Version -ne 2) {
    Write-Info "WSL2 로 바꿉니다"
    & wsl.exe --set-version $Distro 2
    if ($LASTEXITCODE -ne 0) { Stop-Install "wsl --set-version $Distro 2 실패. BIOS 가상화를 확인하세요." }
}
Write-Ok "WSL2"

# 4. 사용자 ------------------------------------------------------------------
Write-Step 4 "리눅스 사용자"
if (-not $User) {
    $User = Get-WslOutput -AsRoot -Cd "/" -Cmd @("id", "-nu", "$($info.DefaultUid)")
    Write-Ok "기존 기본 사용자 '$User' 를 씁니다"
}
$uid = Get-WslOutput -AsRoot -Cd "/" -AllowFail -Cmd @("id", "-u", $User)
if ($uid -match '^\d+$') { Write-Ok "'$User' (uid $uid) 가 이미 있습니다" }
else {
    $null = Invoke-Wsl -AsRoot -Cd "/" -Cmd @("useradd", "-m", "-s", "/bin/bash", "-G", "sudo,adm,users", $User)
    $uid = Get-WslOutput -AsRoot -Cd "/" -Cmd @("id", "-u", $User)
    Write-Ok "'$User' (uid $uid) 를 만들었습니다"
}
Set-ItemProperty $info.Path -Name DefaultUid -Value ([int]$uid) -Type DWord
Write-Ok "기본 사용자: $User"

$passwdStatus = Get-WslOutput -AsRoot -Cd "/" -Cmd @("passwd", "-S", $User)
if (($passwdStatus -split '\s+')[1] -ne "P") {
    Write-Info "'$User' 의 비밀번호를 정하세요 (sudo 에 씁니다. 입력해도 화면에 안 보이는 게 정상입니다)."
    $set = $false
    for ($try = 1; $try -le 3 -and -not $set; $try++) {
        $set = (Invoke-Wsl -AsRoot -Cd "/" -AllowFail -Cmd @("passwd", $User)) -eq 0
    }
    if (-not $set) { Stop-Install "비밀번호를 설정하지 못했습니다. 나중에: wsl -u root passwd $User" }
}
Write-Ok "비밀번호 설정됨"

# 5. 메모리 ------------------------------------------------------------------
Write-Step 5 "WSL 메모리"
$target = if ($MemoryGB -gt 0) { $MemoryGB } else { [int][math]::Max(8, [math]::Min($ramGB - 4, [math]::Round($ramGB * 0.65))) }
if (Set-WslMemory $target) {
    Write-Info "적용을 위해 WSL 을 재시작합니다"
    & wsl.exe --shutdown
}

# 6. 프로젝트 ----------------------------------------------------------------
Write-Step 6 "al-alloy-design 설치 (WSL 안)"
Write-Info "apt 패키지 (git, curl, cmake, build-essential)"
$apt = @("env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "-q", "-o", "Acquire::Max-FutureTime=86400")
$null = Invoke-Wsl -AsRoot -Cd "/" -Cmd ($apt + @("update"))
$null = Invoke-Wsl -AsRoot -Cd "/" -Cmd ($apt + @("-y", "install", "git", "curl", "ca-certificates", "cmake", "build-essential"))
Write-Ok "apt 패키지"

$linuxHome = Get-WslOutput -Cmd @("printenv", "HOME")
$project = "$linuxHome/$Dir"
if ((Invoke-Wsl -AllowFail -Cmd @("test", "-d", "$project/.git")) -eq 0) {
    Write-Info "$project 가 이미 있어 최신으로 받습니다"
    $null = Invoke-Wsl -AllowFail -Cmd @("git", "-C", $project, "pull", "--ff-only")
} else {
    $null = Invoke-Wsl -Cmd @("git", "clone", "-b", $Branch, $RepoUrl, $project)
}
Write-Ok "저장소: $project ($Branch)"

# GPU 로 갈 때만: WSL 안에서도 GPU 가 보이는지 확인하고 CUDA 빌드 도구를 root 로 미리 설치합니다 (bootstrap.py 의 sudo 질문을 피함)
if ($Gpu.Mode -eq "cuda") {
    $wslSmi = Get-WslOutput -AllowFail -Cmd @("nvidia-smi")
    if ($wslSmi -notmatch 'CUDA Version:\s*([0-9]+\.[0-9]+)') {
        Write-Warn "Windows 에는 NVIDIA GPU 가 있지만 WSL 안에서 보이지 않습니다 (wsl --update 후 재부팅하면 대개 해결). 이번에는 CPU 로 진행합니다."
        $Gpu.Mode = "cpu-forced"
    } elseif ((Invoke-Wsl -AllowFail -Cmd @("test", "-x", "/usr/local/cuda/bin/nvcc")) -eq 0) {
        Write-Ok "CUDA 빌드 도구 있음"
    } else {
        Write-Info "CUDA 빌드 도구 설치 (약 1GB, 드라이버는 설치하지 않음)"
        if ((Invoke-Wsl -AsRoot -Cd $project -AllowFail -Cmd @("bash", "scripts/install-cuda-wsl.sh", $Gpu.Cuda)) -eq 0) {
            Write-Ok "CUDA 빌드 도구"
        } else {
            Write-Warn "CUDA 빌드 도구를 설치하지 못해 CPU 로 진행합니다 (위 메시지를 확인하고 install.cmd 를 다시 실행하면 GPU 로 다시 빌드합니다)."
            $Gpu.Mode = "cpu-forced"
        }
    }
}

$bootArgs = @("--yes")
if ($ModelRepo) { $bootArgs += @("--repo", $ModelRepo, "--quant", $Quant) }
if ($NoExisting) { $bootArgs += "--no-existing" }
# 이미 받아 둔 모델: bootstrap.py 가 WSL 안과 Windows 쪽(C:\Users\*\.ollama, .lmstudio 등)을 찾아 쓰고,
# Ollama 모델 폴더를 옮겨 둔 경우(OLLAMA_MODELS)만 여기서 알려 줍니다
$ollamaDir = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if (-not $ollamaDir) { $ollamaDir = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine") }
if ($ollamaDir -and (Test-Path $ollamaDir)) {
    $wslOllama = Get-WslOutput -AllowFail -Cmd @("wslpath", "-u", $ollamaDir.Replace("\", "/"))
    if ($wslOllama) { $bootArgs += @("--search", "$wslOllama".Trim()) }
}
if ($SkipBootstrap) { $bootArgs = @("--detect-only") }
if ($Gpu.Mode -eq "cpu-forced") { $bootArgs += "--cpu" }   # NVIDIA 가 있어도 CPU 로: 중간에 CUDA 설치·sudo 를 다시 시도하지 않게
Write-Info "python3 bootstrap.py $($bootArgs -join ' ')"
$null = Invoke-Wsl -Cd $project -Cmd (@("python3", "bootstrap.py") + $bootArgs)

# 요약: 실제로 GPU 를 쓰는지는 빌드된 llama-server 가 보는 장치로 확인합니다
Write-Step "요약" "설치 결과"
$devices = Get-WslOutput -AllowFail -Cmd @("$linuxHome/.local/bin/llama-server", "--list-devices")
$cudaDevice = if ($devices -match '(CUDA\d+:[^\r\n]+)') { $Matches[1].Trim() } else { $null }
if ($cudaDevice) { Write-Ok "계산 장치: GPU ($cudaDevice)" }
elseif ($Gpu.Mode -eq "cuda") { Write-Warn "계산 장치: CPU (GPU 로 빌드되지 않았습니다. 위 llama.cpp 빌드 메시지를 확인하세요)" }
else { Write-Ok "계산 장치: CPU" }
$selection = Get-WslOutput -AllowFail -Cd $project -Cmd @("cat", ".llm/selection.json")
try { $sel = $selection | ConvertFrom-Json; Write-Ok "모델: $($sel.repo) ($($sel.quant))" } catch { Write-Info "모델: (아직 선택 안 됨)" }
$status = Get-WslOutput -AllowFail -Cd $project -Cmd @(".venv/bin/python", "llm/serve.py", "status")
if ($status -match 'healthy: True') { Write-Ok "모델 서버: 켜져 있음 (http://127.0.0.1:8080)" } else { Write-Info "모델 서버: 꺼져 있음 (켜기: cd ~/$Dir && .venv/bin/python llm/serve.py start)" }

Remove-Item $StateFile -ErrorAction SilentlyContinue
Write-Host "`n끝났습니다." -ForegroundColor Green
Write-Info "Ubuntu 열기:  시작 메뉴 > $Distro   (또는 PowerShell 에서 wsl)"
Write-Info "설계 실행:    cd ~/$Dir && .venv/bin/python design.py `"6xxx T6 압출, UTS 330 MPa 이상, 연신율 10% 이상`""
if ($SkipBootstrap) { Write-Info "설치 계속:    cd ~/$Dir && python3 bootstrap.py" }
try { Stop-Transcript | Out-Null } catch {}
