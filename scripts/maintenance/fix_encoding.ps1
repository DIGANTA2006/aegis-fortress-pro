$files = @(
"config.py",
"db.py",
"exchange.py",
"features_extended.py",
"market_maker.py",
"monitor.py",
"risk.py",
"rl_agent.py",
"sentiment.py",
"tick_replay.py",
"utils.py",
"watchdog.py",
"websocket_ob.py"
)

foreach ($file in $files) {

    Write-Host ""
    Write-Host "================================="
    Write-Host "FIXING: $file"
    Write-Host "================================="

    try {

        $content = [System.IO.File]::ReadAllText(
            $file,
            [System.Text.Encoding]::Default
        )

        # remove problematic byte conversions
        $content = $content.Replace([char]0x2013, "-")
        $content = $content.Replace([char]0x2014, "-")
        $content = $content.Replace([char]0x2018, "'")
        $content = $content.Replace([char]0x2019, "'")
        $content = $content.Replace([char]0x201C, '"')
        $content = $content.Replace([char]0x201D, '"')

        [System.IO.File]::WriteAllText(
            $file,
            $content,
            [System.Text.UTF8Encoding]::new($false)
        )

        Write-Host "SUCCESS: $file"

    }
    catch {

        Write-Host "FAILED: $file"
        Write-Host $_

    }

    Start-Sleep -Milliseconds 300
}

Write-Host ""
Write-Host "================================="
Write-Host "ENCODING REPAIR COMPLETED"
Write-Host "================================="
