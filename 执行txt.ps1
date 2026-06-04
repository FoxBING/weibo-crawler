Get-Content failed_yt-dlp_commands.txt | ForEach-Object {
    $cmd = $_.Trim()
    if ($cmd -and -not $cmd.StartsWith('#')) {
        Write-Host "执行: $cmd"
        Invoke-Expression $cmd
    }
}