# Dev helper for reading /ask answers by hand.
#
# PowerShell aliases `curl` to Invoke-WebRequest, and nesting quotes inside a
# JSON body on the command line is painful in every shell. This does the
# quoting for you so a question can be typed as plain text.
#
# Load it once per terminal:
#     . .\scripts\ask.ps1
#
# Then:
#     ask "Why was the Berlin Wall built?"
#     ask "Why was the Berlin Wall built?" -k 10

function ask {
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Question,

        [int]$k = 5,

        [string]$BaseUrl = "http://localhost:8000"
    )

    $body = @{ question = $Question; k = $k } | ConvertTo-Json

    try {
        $response = Invoke-RestMethod -Uri "$BaseUrl/ask" -Method Post `
            -ContentType "application/json; charset=utf-8" -Body $body
    }
    catch {
        Write-Host "Request failed: $_" -ForegroundColor Red
        Write-Host "Is the server up? uv run uvicorn eurohistory_rag.api.main:app"
        return
    }

    Write-Host ""
    Write-Host $response.answer
    Write-Host ""

    if ($response.sources.Count -eq 0) {
        Write-Host "No sources cited." -ForegroundColor Yellow
    }
    else {
        $response.sources |
            Format-Table @{ L = "n"; E = { $_.n }; W = 3 },
                         @{ L = "source"; E = { $_.source } },
                         @{ L = "score"; E = { "{0:N3}" -f $_.score }; W = 6 },
                         @{ L = "url"; E = { $_.url } } -AutoSize
    }

    Write-Host "model: $($response.model)" -ForegroundColor DarkGray
}

# The passage a citation points at, for checking whether it says what the
# answer claims. This is the step-14 question that matters most.
function ask-text {
    param(
        [Parameter(Mandatory = $true, Position = 0)]
        [string]$Question,

        [int]$n = 1,

        [int]$k = 5,

        [string]$BaseUrl = "http://localhost:8000"
    )

    $body = @{ question = $Question; k = $k } | ConvertTo-Json
    $response = Invoke-RestMethod -Uri "$BaseUrl/ask" -Method Post `
        -ContentType "application/json; charset=utf-8" -Body $body

    $source = $response.sources | Where-Object { $_.n -eq $n }
    if ($null -eq $source) {
        Write-Host "The answer does not cite [$n]." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "[$n] $($source.source)" -ForegroundColor Cyan
    Write-Host $source.url -ForegroundColor DarkGray
    Write-Host ""
    Write-Host $source.text
}
