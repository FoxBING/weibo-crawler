# 更新 yt-dlp
Write-Host "正在更新 yt-dlp..." -ForegroundColor Cyan
uv pip install --upgrade yt-dlp

# 运行爬虫
uv run python weibo.py
pause
