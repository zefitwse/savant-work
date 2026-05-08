param(
    [switch]$Build,
    [switch]$PullImages,
    [int]$KafkaSampleCount = 20,
    [int]$StartupWaitSeconds = 8,
    [int]$ReplaySeconds = 35
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Wait-ContainerHealthy {
    param(
        [string]$Name,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $Name 2>$null
        if ($LASTEXITCODE -eq 0 -and ($status -eq "healthy" -or $status -eq "running")) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Container $Name did not become healthy/running within $TimeoutSeconds seconds."
}

function Stop-LoopingSources {
    $oldErrorActionPreference = $ErrorActionPreference
    $nativePreferenceExists = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($nativePreferenceExists) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
    }
    try {
        $ErrorActionPreference = "Continue"
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        docker compose -f docker-compose.savant.yml stop source-video source-video-raw *> $null
    } catch {
        # Source adapters run an infinite-loop video and may already be stopped.
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
}

function Get-DockerLogsText {
    param(
        [string]$ContainerName,
        [int]$Tail = 300
    )

    $oldErrorActionPreference = $ErrorActionPreference
    $nativePreferenceExists = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($nativePreferenceExists) {
        $oldNativePreference = $PSNativeCommandUseErrorActionPreference
    }
    try {
        $ErrorActionPreference = "Continue"
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        return (docker logs $ContainerName --tail $Tail 2>&1)
    } catch {
        return @()
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }
}

function Invoke-ControlApiSmokeTest {
    Write-Step "Checking Control API"
    $health = $null
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:18080/health" -TimeoutSec 5
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if ($null -eq $health) {
        throw "Control API did not respond before timeout."
    }
    if ($health.status -ne "ok") {
        throw "Control API health check failed."
    }

    $cameraConfig = @{
        camera_id = "test_video"
        version = "full-test-$(Get-Date -Format yyyyMMddHHmmss)"
        roi = @(@{
            name = "full_frame"
            polygon = @(@(0, 0), @(1280, 0), @(1280, 720), @(0, 720))
        })
        thresholds = @{
            person = 0.25
            vehicle = 0.3
        }
        algorithm_params = @{
            ttl_frames = 90
            attribute_cooldown_frames = 30
        }
        privacy = @{
            enabled = $true
            masked_roles = @("operator", "guest")
        }
    } | ConvertTo-Json -Depth 8

    Invoke-RestMethod `
        -Uri "http://127.0.0.1:18080/configs/cameras" `
        -Method Post `
        -ContentType "application/json" `
        -Body $cameraConfig `
        -TimeoutSec 10 | Out-Null
}

function Get-EventSummary {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Kafka sample file not found: $Path"
    }

    $events = @()
    $buffer = New-Object System.Collections.Generic.List[string]
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed) {
            continue
        }
        if ($trimmed -eq "{") {
            $buffer.Clear()
        }
        $buffer.Add($line)
        if ($trimmed -ne "}") {
            continue
        }
        try {
            $wrapper = ($buffer -join "`n") | ConvertFrom-Json
            if ($wrapper.value) {
                $events += ($wrapper.value | ConvertFrom-Json)
            }
        } catch {
            continue
        }
    }

    $personCount = @($events | Where-Object { $_.class_name -eq "person" }).Count
    $enteredCount = @($events | Where-Object { $_.event_type -eq "object_entered" }).Count
    $changedCount = @($events | Where-Object { $_.event_type -eq "attribute_changed" }).Count
    $expiredCount = @($events | Where-Object { $_.event_type -eq "object_expired" }).Count
    $trackIdCount = @($events | Where-Object { $null -ne $_.track_id }).Count
    $cropUriCount = @($events | Where-Object { $_.attributes -and $_.attributes.crop_uri }).Count
    $gpuRefCount = @($events | Where-Object { $_.attributes -and $_.attributes.gpu_memory_ref }).Count

    [pscustomobject]@{
        SampleEvents = $events.Count
        PersonEvents = $personCount
        ObjectEntered = $enteredCount
        AttributeChanged = $changedCount
        ObjectExpired = $expiredCount
        EventsWithTrackId = $trackIdCount
        EventsWithCropUri = $cropUriCount
        EventsWithGpuMemoryRef = $gpuRefCount
    }
}

function Get-MetadataSummary {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Metadata output not found: $Path"
    }

    $videoFrames = @()
    foreach ($line in Get-Content $Path) {
        if (-not $line.Trim()) {
            continue
        }
        try {
            $frame = $line | ConvertFrom-Json
            if ($frame.schema -eq "VideoFrame") {
                $videoFrames += $frame
            }
        } catch {
            continue
        }
    }

    $personObjects = @($videoFrames | ForEach-Object { $_.metadata.objects } | Where-Object { $_.label -eq "person" })
    $framesWithPerson = @(
        $videoFrames | Where-Object {
            @($_.metadata.objects | Where-Object { $_.label -eq "person" }).Count -gt 0
        }
    )
    $uniqueIds = @($personObjects | ForEach-Object { $_.object_id } | Sort-Object -Unique)
    $maxConfidence = 0
    if ($personObjects.Count -gt 0) {
        $maxConfidence = ($personObjects | Measure-Object -Property confidence -Maximum).Maximum
    }

    [pscustomobject]@{
        VideoFrames = $videoFrames.Count
        FramesWithPerson = $framesWithPerson.Count
        PersonDetections = $personObjects.Count
        UniquePersonIds = ($uniqueIds -join ",")
        MaxPersonConfidence = [math]::Round([double]$maxConfidence, 4)
    }
}

try {
    Write-Step "Checking prerequisites"
    Require-Command docker

    if (-not (Test-Path "test.mp4")) {
        throw "test.mp4 not found in project root."
    }

    Write-Step "Ensuring shared Docker network"
    docker network inspect deepstream_coursework_default *> $null
    if ($LASTEXITCODE -ne 0) {
        docker network create deepstream_coursework_default | Out-Null
    }

    Write-Step "Starting Kafka and Control API"
    docker compose -f docker-compose.kafka.yml up -d
    docker compose -f docker-compose.control.yml up -d --build
    Wait-ContainerHealthy -Name "coursework-redpanda" -TimeoutSeconds 90
    Wait-ContainerHealthy -Name "coursework-control-api" -TimeoutSeconds 90

    Invoke-ControlApiSmokeTest

    if ($PullImages) {
        Write-Step "Pulling Savant images"
        docker pull ghcr.io/insight-platform/savant-deepstream:latest
        docker pull ghcr.io/insight-platform/savant-adapters-gstreamer:latest
    }

    if ($Build) {
        Write-Step "Building Savant module image"
        docker compose -f docker-compose.savant.yml build
    }

    Write-Step "Starting Savant modules, OpenTelemetry Collector, and sinks (dual output: raw and masked)"
    docker compose -f docker-compose.savant.yml up -d otel-collector savant-module-masked savant-module-raw sink-video-files-masked sink-video-files-raw sink-zlm-rtmp-masked sink-zlm-rtmp-raw zlm
    Wait-ContainerHealthy -Name "coursework-otel-collector" -TimeoutSeconds 60
    Wait-ContainerHealthy -Name "coursework-savant-module-masked" -TimeoutSeconds 120
    Wait-ContainerHealthy -Name "coursework-savant-module-raw" -TimeoutSeconds 120
    Start-Sleep -Seconds $StartupWaitSeconds

    Write-Step "Preparing fresh output directories"
    $maskedOutputDir = Join-Path $ProjectRoot "runtime\savant-output"
    $rawOutputDir = Join-Path $ProjectRoot "runtime\raw-output"
    $cropOutputDir = Join-Path $ProjectRoot "runtime\crops"
    $metadataPath = Join-Path $maskedOutputDir "metadata.json"
    $videoPath = Join-Path $maskedOutputDir "video.mov"
    $rawVideoPath = Join-Path $rawOutputDir "video.mov"
    
    New-Item -ItemType Directory -Force -Path $maskedOutputDir | Out-Null
    New-Item -ItemType Directory -Force -Path $rawOutputDir | Out-Null
    if (Test-Path $cropOutputDir) {
        Remove-Item -LiteralPath $cropOutputDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $cropOutputDir | Out-Null

    Write-Step "Listening for fresh Kafka events"
    $samplePath = Join-Path $ProjectRoot ".codex_tmp\full_test_kafka_events.jsonl"
    New-Item -ItemType Directory -Force -Path (Split-Path $samplePath) | Out-Null
    if (Test-Path $samplePath) {
        Remove-Item -LiteralPath $samplePath -Force
    }
    $consumeJob = Start-Job -ScriptBlock {
        param($Count)
        docker exec coursework-redpanda rpk topic consume deepstream.events --brokers localhost:9092 -n $Count -o end
    } -ArgumentList $KafkaSampleCount
    Start-Sleep -Seconds 2

    Write-Step "Replaying infinite-loop test.mp4 through both Savant modules (raw and masked)"
    docker compose -f docker-compose.savant.yml up -d source-video source-video-raw
    Start-Sleep -Seconds $ReplaySeconds

    Write-Step "Waiting for dual output videos to be generated"
    $maxWaitSeconds = 60
    $deadline = (Get-Date).AddSeconds($maxWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Test-Path $rawVideoPath) -and (Test-Path $videoPath)) {
            $rawSize = (Get-Item $rawVideoPath -ErrorAction SilentlyContinue).Length
            $maskedSize = (Get-Item $videoPath -ErrorAction SilentlyContinue).Length
            if ($rawSize -gt 0 -and $maskedSize -gt 0) {
                Write-Host "Both videos generated: raw=$rawSize bytes, masked=$maskedSize bytes" -ForegroundColor Green
                break
            }
        }
        Write-Host "Waiting for videos... (raw exists: $(Test-Path $rawVideoPath), masked exists: $(Test-Path $videoPath))" -ForegroundColor Yellow
        Start-Sleep -Seconds 3
        if ((Get-Date) -ge $deadline) {
            throw "Timeout waiting for videos to be generated. raw=$(Test-Path $rawVideoPath), masked=$(Test-Path $videoPath)"
        }
    }

    Write-Step "Stopping infinite-loop source adapters before post-processing outputs"
    Stop-LoopingSources
    Start-Sleep -Seconds 3

    Write-Step "Exporting Re-ID target crops from raw video and Savant metadata"
    python scripts\export_reid_crops.py `
        --metadata runtime\savant-output\metadata.json `
        --video runtime\raw-output\video.mov `
        --output-dir runtime\crops `
        --uri-prefix runtime\crops `
        --max-crops 50

    Write-Step "Generating preview screenshots"
    python scripts\render_privacy_outputs.py `
        --source test.mp4 `
        --metadata runtime\savant-output\metadata.json `
        --raw-output runtime\raw-output\video.mov `
        --raw-shot .codex_tmp\privacy_admin_raw_output.jpg `
        --masked-source runtime\savant-output\video.mov `
        --masked-shot .codex_tmp\privacy_operator_masked_output.jpg

    Write-Step "Collecting Kafka samples"
    Wait-Job $consumeJob -Timeout 45 | Out-Null
    if ($consumeJob.State -eq "Running") {
        Stop-Job $consumeJob
    }
    Receive-Job $consumeJob | Set-Content -Path $samplePath -Encoding UTF8
    Remove-Job $consumeJob -Force

    $eventSummary = Get-EventSummary -Path $samplePath
    $metadataSummary = Get-MetadataSummary -Path $metadataPath
    $video = Get-Item $videoPath -ErrorAction Stop
    $rawVideo = Get-Item $rawVideoPath -ErrorAction Stop

    if ($eventSummary.SampleEvents -eq 0) {
        throw "No Kafka events were consumed from deepstream.events."
    }
    if ($metadataSummary.PersonDetections -eq 0) {
        throw "No person detections found in metadata.json."
    }
    if ($eventSummary.EventsWithTrackId -eq 0) {
        throw "Kafka events did not include track_id."
    }
    if ($eventSummary.EventsWithGpuMemoryRef -eq 0) {
        throw "Kafka events did not include gpu_memory_ref."
    }
    if ($eventSummary.EventsWithCropUri -eq 0) {
        throw "Kafka events did not include crop_uri."
    }
    if ($video.Length -le 0) {
        throw "Masked output video.mov is empty."
    }
    if ($rawVideo.Length -le 0) {
        throw "Raw output video.mov is empty."
    }
    $cropFiles = @(Get-ChildItem -LiteralPath $cropOutputDir -Recurse -File -Filter *.jpg -ErrorAction SilentlyContinue)
    if ($cropFiles.Count -eq 0) {
        throw "No target crop images were generated in runtime/crops."
    }
    Start-Sleep -Seconds 5
    $otelLogs = Get-DockerLogsText -ContainerName "coursework-otel-collector" -Tail 2000
    if (($otelLogs -join "`n") -notmatch "savant\.|Traces") {
        throw "OpenTelemetry Collector did not receive Savant trace spans."
    }

    Write-Step "Dual output test passed"
    Write-Host "Kafka sample summary:" -ForegroundColor Green
    $eventSummary | Format-List
    Write-Host "Metadata summary:" -ForegroundColor Green
    $metadataSummary | Format-List
    Write-Host "Masked output video:" -ForegroundColor Green
    $video | Select-Object FullName, Length, LastWriteTime | Format-List
    Write-Host "Raw output video:" -ForegroundColor Green
    $rawVideo | Select-Object FullName, Length, LastWriteTime | Format-List
    Write-Host "Generated target crops:" -ForegroundColor Green
    $cropFiles | Select-Object -First 5 FullName, Length, LastWriteTime | Format-List
    Write-Host "OpenTelemetry Collector received Savant spans." -ForegroundColor Green
    Write-Host "Kafka sample file: $samplePath"
    Write-Host ""
    Write-Host "Output URLs:" -ForegroundColor Cyan
    Write-Host "  Masked RTSP: rtsp://127.0.0.1:8554/live/ppt_cascade_masked"
    Write-Host "  Raw RTSP: rtsp://127.0.0.1:8554/live/ppt_cascade_raw"
    Write-Host "  Masked HTTP-FLV: http://127.0.0.1:8080/live/ppt_cascade_masked.live.flv"
    Write-Host "  Raw HTTP-FLV: http://127.0.0.1:8080/live/ppt_cascade_raw.live.flv"
} catch {
    Stop-LoopingSources
    Write-Host ""
    Write-Host "Full test failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Useful diagnostics:" -ForegroundColor Yellow
    Write-Host "  docker ps -a"
    Write-Host "  docker logs coursework-savant-module-masked --tail 120"
    Write-Host "  docker logs coursework-savant-module-raw --tail 120"
    Write-Host "  docker logs coursework-zlm --tail 120"
    Write-Host "  docker logs coursework-redpanda --tail 120"
    exit 1
}
