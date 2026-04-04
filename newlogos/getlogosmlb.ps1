# Define the range of team IDs
$start = 100
$end = 199

# Base URLs for the MLB team logos
$lightBase = "https://www.mlbstatic.com/team-logos/team-cap-on-light/"
$darkBase = "https://www.mlbstatic.com/team-logos/team-cap-on-dark/"

foreach ($i in $start..$end) {
    # Construct URLs and local filenames
    $lightUrl  = "${lightBase}${i}.svg"
    $darkUrl   = "${darkBase}${i}.svg"
    
    $lightFile = "light${i}.svg"
    $darkFile  = "dark${i}.svg"

    # Download the light-on-cap logo
    Write-Host "Downloading $lightUrl..."
    try {
        Invoke-WebRequest -Uri $lightUrl -OutFile $lightFile -ErrorAction Stop
    } catch {
        Write-Warning "Skipped $lightUrl (File may not exist)"
    }

    # Download the dark-on-cap logo
    Write-Host "Downloading $darkUrl..."
    try {
        Invoke-WebRequest -Uri $darkUrl -OutFile $darkFile -ErrorAction Stop
    } catch {
        Write-Warning "Skipped $darkUrl (File may not exist)"
    }
}

