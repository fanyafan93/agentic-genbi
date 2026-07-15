param(
    [string]$OutDir = "verification_runs/2026-07-15"
)

$ErrorActionPreference = "Stop"

New-Item -Path $OutDir -Force -ItemType Directory | Out-Null
$fullPath = Join-Path (Get-Location) $OutDir

$questions = @(
    @{ id = "trend";       prompt = "Show the monthly sales trend from dm.dm_sale_dy_total" },
    @{ id = "comparison";  prompt = "Compare total sales by channel from dm.dm_sale_dy_total for 2026-Q1" },
    @{ id = "ranking";     prompt = "Rank top 10 sales performers by total amount in 2026 July" },
    @{ id = "composition"; prompt = "Show the proportion of sales by channel in 2026 July" },
    @{ id = "schema_probe";prompt = "Inspect the structure of dm.dm_sale_dy_total and report the main fields" }
)

$results = @()
$summaryLog = Join-Path $OutDir "_summary.txt"

"=== MVP acceptance run @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File $summaryLog

foreach ($q in $questions) {
    $id = $q.id
    $prompt = $q.prompt
    $taskFile = Join-Path $OutDir "$id.json"
    "" | Out-File -Append $summaryLog
    "[==> $id] $prompt" | Out-File -Append $summaryLog

    $body = @{ question = $prompt } | ConvertTo-Json -Compress
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/analysis-tasks" `
            -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
    } catch {
        "    POST failed: $($_.Exception.Message)" | Out-File -Append $summaryLog
        continue
    }

    try {
        $taskId = ($r.Content | ConvertFrom-Json).task_id
    } catch {
        "    POST returned non-JSON: $($r.Content.Substring(0, [Math]::Min(160, $r.Content.Length)))" | Out-File -Append $summaryLog
        continue
    }

    "[task] $taskId" | Out-File -Append $summaryLog

    $final = $null
    $start = Get-Date
    while ($true) {
        Start-Sleep -Seconds 4
        try {
            $r2 = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/analysis-tasks/$taskId" -UseBasicParsing
        } catch {
            Start-Sleep -Seconds 2
            continue
        }
        $d = $r2.Content | ConvertFrom-Json
        if ($d.status -in @("succeeded","failed","requires_input")) {
            $final = $d
            break
        }
        if (((Get-Date) - $start).TotalSeconds -gt 180) {
            "    timed out at 180s, status=$($d.status), steps=$($d.steps.Count)" | Out-File -Append $summaryLog
            break
        }
    }

    if ($null -eq $final) { continue }
    $final | ConvertTo-Json -Depth 8 | Out-File $taskFile -Encoding UTF8

    $finished = ($final.steps | Where-Object { $_.finished_at } | Measure-Object).Count
    $total    = ($final.steps | Measure-Object).Count
    $attempts = if ($final.report) { $final.report.sql_attempts } else { "" }
    $rows     = if ($final.report) { $final.report.table.row_count } else { "" }
    $duration = if ($final.report) { $final.report.query_duration_ms } else { "" }
    $err      = if ($final.error) { $final.error.code } else { "" }
    $message  = if ($final.error) { $final.error.message } else { "" }

    $line = "    status={0,-15} steps={1,2}/{2,-2} attempts={3,-1} rows={4,-4} duration_ms={5,-5} err={6}" -f `
        $final.status, $finished, $total, $attempts, $rows, $duration, $err
    $line | Out-File -Append $summaryLog
    if ($err) {
        "    message: $message" | Out-File -Append $summaryLog
    }

    $results += [pscustomobject]@{
        id        = $id
        status    = $final.status
        steps     = $total
        finished  = $finished
        attempts  = $attempts
        rows      = $rows
        duration  = $duration
        err_code  = $err
        err_msg   = $message
    }
}

$results | ConvertTo-Json -Depth 4 | Out-File (Join-Path $OutDir "_summary.json") -Encoding UTF8
""  | Out-File -Append $summaryLog
"Done. JSON snapshots are in $fullPath" | Out-File -Append $summaryLog
Write-Host "Done. See $summaryLog"
