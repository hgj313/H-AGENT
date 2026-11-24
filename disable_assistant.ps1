# ============================================================
#  停用「本地保险管理AI助手」· 阶段 1 收尾 + 启动飞书打卡直连消费者
# ============================================================
#  2026-11-24
#
#  现状（脚本编写时）：
#    - watchdog  (7080)  : 已停 ✓
#    - 8765 服务 (23808) : 已停 ✓
#    - MQ bridge (7044)  : 仍在运行（Session 0 / SYSTEM），需管理员权限终止
#    - 直连消费者        : 未启动
#
#  本脚本做四件事：
#    1) 写入停用标记 .assistant_disabled —— 防止 8765 / watchdog / bridge 将来被拉起
#    2) 以管理员（High integrity）终止残留的 bridge / watchdog / 8765
#    3) 创建临时 LocalSystem 服务启动 erp_feishu_direct 直连消费者
#       → 消费者跑在 Session 0，用户注销后仍常驻（与原 8765 同等地位）
#    4) 验证：端口释放、消费者进程在、MQ 订阅成功
#
#  为什么必须管理员：
#    Session 0 的 SYSTEM 进程，普通会话（Medium 完整性级别）终止时会被
#    Windows 完整性级别检查拦截 —— Stop-Process / taskkill 均「拒绝访问」。
#    UAC 提升到 High 后完整性检查才放行。
#
#  用法：右键本文件 → 以管理员身份运行
# ============================================================

$ErrorActionPreference = 'Continue'
$Root      = 'C:\insurance-automation'
$Flag      = Join-Path $Root '.assistant_disabled'
$PyExe     = Join-Path $Root 'H-AGENT\.venv\Scripts\python.exe'
$SysRunner = Join-Path $Root '_run_sys_task.py'
$SysStage1 = Join-Path $Root '_sys_stage1.py'
$ConsumerLog = Join-Path $Root 'erp_feishu_direct.log'

function Write-Step($m) { Write-Host $m -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host $m -ForegroundColor Green }
function Write-Err($m)  { Write-Host $m -ForegroundColor Red }

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host '  停用本地保险管理AI助手 · 启动飞书打卡直连消费者' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan

# ---------- 0. 管理员检查 ----------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Err '[X] 当前不是管理员权限，无法终止 Session 0 的 SYSTEM 进程。'
    Write-Err '    请右键本脚本 → 以管理员身份运行。'
    try { $null = Read-Host "按 Enter 键继续..." } catch { }
    exit 1
}
Write-Ok '[OK] 管理员权限已确认'

# ---------- 1. 停用标记 ----------
try {
    ("disabled at " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) | Set-Content -Path $Flag -Encoding UTF8
    Write-Ok "[1/4] 停用标记已写入: $Flag"
} catch {
    Write-Err "[X] 停用标记写入失败: $($_.Exception.Message)"
}

# ---------- 2. 终止残留进程 ----------
Write-Step '[2/4] 终止残留进程（watchdog / MQ bridge / 8765 服务）...'
$killList = @()
foreach ($port in @(8765, 8767)) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($c in $conns) { $killList += $c.OwningProcess }
}
# 已知历史 PID 兜底（端口可能已被释放但进程仍在）
$killList += @(7080, 3840, 7044, 11432, 23808)
$killList = $killList | Sort-Object -Unique

foreach ($procId in $killList) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Ok "  已终止 PID $procId ($($proc.ProcessName))"
        } catch {
            Write-Err "  终止 PID $procId 失败: $($_.Exception.Message)"
        }
    }
}
Start-Sleep -Seconds 2

# ---------- 3. 启动直连消费者（SYSTEM 身份 / Session 0 常驻）----------
Write-Step '[3/4] 创建 LocalSystem 临时服务，启动直连消费者...'
if ((Test-Path $SysRunner) -and (Test-Path $PyExe)) {
    & $PyExe $SysRunner $SysStage1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok '  SYSTEM 服务执行完成（临时服务已自动删除）'
    } else {
        Write-Err "  SYSTEM 服务执行失败，退出码 $LASTEXITCODE"
    }
} else {
    Write-Err "  找不到 $SysRunner 或 $PyExe"
}

# ---------- 4. 验证 ----------
Write-Step '[4/4] 验证结果...'
Start-Sleep -Seconds 3
foreach ($port in @(8765, 8767)) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($null -ne $conns) {
        Write-Err "  端口 $port 仍被占用 (PID $($conns[0].OwningProcess))"
    } else {
        Write-Ok "  端口 $port 已释放"
    }
}

$consumers = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
             Where-Object { $_.CommandLine -match 'erp_feishu_direct' }
if ($null -ne $consumers) {
    foreach ($c in $consumers) {
        Write-Ok "  直连消费者运行中: PID $($c.ProcessId)  Session=$($c.SessionId)"
    }
} else {
    Write-Err '  未发现直连消费者进程'
}

if (Test-Path $ConsumerLog) {
    Write-Host '  --- 消费者日志尾部 ---' -ForegroundColor DarkGray
    Get-Content $ConsumerLog -Tail 14 -Encoding UTF8 | ForEach-Object {
        Write-Host "    $_" -ForegroundColor DarkGray
    }
}

Write-Host ''
Write-Ok '完成。窗口可关闭。'
try { $null = Read-Host "按 Enter 键关闭..." } catch { }
