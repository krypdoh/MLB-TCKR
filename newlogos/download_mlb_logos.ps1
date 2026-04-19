# Download all MLB team logos from ESPN CDN
# URL pattern: https://a.espncdn.com/i/teamlogos/mlb/500-dark/scoreboard/{abbr}.png

$baseUrl = "https://a.espncdn.com/i/teamlogos/mlb/500-dark/scoreboard"
$outputDir = "$PSScriptRoot\png"

# All 30 MLB teams with their ESPN abbreviations
$teams = @(
    @{ Abbr = "ari"; Name = "Arizona Diamondbacks" },
    @{ Abbr = "atl"; Name = "Atlanta Braves" },
    @{ Abbr = "bal"; Name = "Baltimore Orioles" },
    @{ Abbr = "bos"; Name = "Boston Red Sox" },
    @{ Abbr = "chc"; Name = "Chicago Cubs" },
    @{ Abbr = "cws"; Name = "Chicago White Sox" },
    @{ Abbr = "cin"; Name = "Cincinnati Reds" },
    @{ Abbr = "cle"; Name = "Cleveland Guardians" },
    @{ Abbr = "col"; Name = "Colorado Rockies" },
    @{ Abbr = "det"; Name = "Detroit Tigers" },
    @{ Abbr = "hou"; Name = "Houston Astros" },
    @{ Abbr = "kc";  Name = "Kansas City Royals" },
    @{ Abbr = "laa"; Name = "Los Angeles Angels" },
    @{ Abbr = "lad"; Name = "Los Angeles Dodgers" },
    @{ Abbr = "mia"; Name = "Miami Marlins" },
    @{ Abbr = "mil"; Name = "Milwaukee Brewers" },
    @{ Abbr = "min"; Name = "Minnesota Twins" },
    @{ Abbr = "nym"; Name = "New York Mets" },
    @{ Abbr = "nyy"; Name = "New York Yankees" },
    @{ Abbr = "oak"; Name = "Athletics" },
    @{ Abbr = "phi"; Name = "Philadelphia Phillies" },
    @{ Abbr = "pit"; Name = "Pittsburgh Pirates" },
    @{ Abbr = "sd";  Name = "San Diego Padres" },
    @{ Abbr = "sf";  Name = "San Francisco Giants" },
    @{ Abbr = "sea"; Name = "Seattle Mariners" },
    @{ Abbr = "stl"; Name = "St. Louis Cardinals" },
    @{ Abbr = "tb";  Name = "Tampa Bay Rays" },
    @{ Abbr = "tex"; Name = "Texas Rangers" },
    @{ Abbr = "tor"; Name = "Toronto Blue Jays" },
    @{ Abbr = "wsh"; Name = "Washington Nationals" }
)

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
    Write-Host "Created output directory: $outputDir"
}

$success = 0
$failed  = 0

foreach ($team in $teams) {
    $url      = "$baseUrl/$($team.Abbr).png"
    $destFile = Join-Path $outputDir "$($team.Abbr).png"

    try {
        Invoke-WebRequest -Uri $url -OutFile $destFile -ErrorAction Stop
        $size = (Get-Item $destFile).Length
        Write-Host "  OK  $($team.Abbr).png  ($size bytes)  — $($team.Name)"
        $success++
    }
    catch {
        Write-Warning "FAIL  $($team.Abbr)  — $($team.Name): $_"
        $failed++
    }
}

Write-Host ""
Write-Host "Done. $success downloaded, $failed failed."
Write-Host "Files saved to: $outputDir"
