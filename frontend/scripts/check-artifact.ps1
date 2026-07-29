$html = (Invoke-WebRequest -UseBasicParsing http://localhost:3000).Content
$scripts = [regex]::Matches($html, 'src="([^"]+\.js)"') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
$result = @()
foreach ($script in $scripts) {
  $content = (Invoke-WebRequest -UseBasicParsing ("http://localhost:3000" + $script)).Content
  if ($content -match 'artifact-empty|未打开任何分析资产|artifact-content') {
    $result += [pscustomobject]@{
      Chunk         = $script
      HasEmptyUI    = ($content -match '未打开任何分析资产')
      HasEmptyClass = ($content -match 'artifact-empty')
      HasContent    = ($content -match 'artifact-content')
      HasIsEmpty    = ($content -match 'is-empty')
    }
  }
}
if ($result.Count -eq 0) { Write-Output 'No artifact chunk found.' } else { $result | Format-List }
