param([string]$OutDir = "verification_runs/2026-07-14")

$ErrorActionPreference = "Stop"

New-Item -Path $OutDir -Force -ItemType Directory | Out-Null

$questions = @(
    @{ id = "trend";       prompt = "Show the monthly sales trend from dm.dm_sale_dy_total" },
    @{ id = "comparison";  prompt = "Compare total sales by channel from dm.dm_sale_dy_total for 2026-Q1" },
    @{ id = "ranking";     prompt = "Rank top 10 sales performers by total amount in 2026 March" },
    @{ id = "composition"; prompt = "Show the proportion of sales by channel in 2026 March (latest month available)" },
    @{ id = "schema_probe";prompt = "Inspect the structure of dm.dm_sale_dy_total and report the main fields" }
)

$results = @()

foreach ($q in $questions) {
    $id = $q.id
    $prompt = $q.prompt
    $taskFile = Join-Path $OutDir "$id.json"
    Write-Host "==> $id :: $prompt"

    $body = @{ question = $prompt } | ConvertTo-Json
    $r = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/analysis-tasks" `
        -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
    $taskId = ($r.Content | ConvertFrom-Json).task_id

    $final = $null
    $startTime = Get-Date
    while ($true) {
        Start-Sleep -Seconds 4
        $r2 = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/analysis-tasks/$taskId" -UseBasicParsing
        $d = $r2.Content | ConvertFrom-Json
        if ($d.status -in @("succeeded", "failed", "requires_input")) {
            $final = $d
            break
        }
        $elapsed = (Get-Date) - $startTime
        if ($elapsed.TotalSeconds -gt 120) {
            $d | ConvertTo-Json -Depth 5 | Out-File $taskFile -Encoding UTF8
            Write-Host "   ! timeout, snapshot saved"
            break
        }
    }

    if ($null -ne $final) {
        $final | ConvertTo-Json -Depth 8 | Out-File $taskFile -Encoding UTF8
    }
    if ($null -eq $final) {
        Write-Host "   ! no final state captured"
        continue
    }
    $summary = [pscustomobject]@{
        id              = $id
        status          = $final.status
        steps           = ($final.steps | Measure-Object).Count
        finished_steps  = ($final.steps | Where-Object { $_.finished_at } | Measure-Object).Count
        sql_attempts    = if ($final.report) { $final.report.sql_attempts } else { $null }
        rows            = if ($final.report) { $final.report.table.row_count } else { $null }
        duration_ms     = if ($final.report) { $final.report.query_duration_ms } else { $null }
        error_code      = if ($final.error) { $final.error.code } else { "" }
    }
    $results += $summary
    Write-Host ("   status={0} steps={1} finished={2} attempts={3} rows={4} duration_ms={5} err={6}" -f `
        $summary.status, $summary.steps, $summary.finished_steps, `
        $summary.sql_attempts, $summary.rows, $summary.duration_ms, $summary.error_code)
}

$results | ConvertTo-Json -Depth 4 | Out-File (Join-Path $OutDir "_summary.json") -Encoding UTF8
Write-Host "==> Done"
