param([string]$ProjectName = '')
# Run from the existing repository. This script updates only its Compose assistant service.
$ErrorActionPreference = 'Stop'
function Assert-DockerSuccess([string]$Action) {
    if ($LASTEXITCODE -ne 0) { throw "$Action failed; stopping without touching other services." }
}
$lookupArgs = @()
if ($ProjectName) { $lookupArgs += @('--project-name', $ProjectName) }
$assistantIds = @(docker compose @lookupArgs ps -a -q assistant)
Assert-DockerSuccess 'Finding existing assistant'
if ($assistantIds.Count -ne 1) {
    throw 'Expected one existing assistant. Run in its checkout; if originally using -p, pass -ProjectName with that same name. No new project was created.'
}
$assistantId = $assistantIds[0].Trim()
$labels = docker inspect --format '{{json .Config.Labels}}' $assistantId | ConvertFrom-Json
Assert-DockerSuccess 'Reading Compose labels'
$project = $labels.'com.docker.compose.project'
$workingDir = $labels.'com.docker.compose.project.working_dir'
$files = $labels.'com.docker.compose.project.config_files'
if (-not $project -or -not $workingDir -or -not $files) { throw 'Existing Compose identity/configuration is unavailable; refusing to guess.' }
$repoRoot = (Get-Location).Path.Replace('\','/').TrimEnd('/')
if ($workingDir.Replace('\','/').TrimEnd('/') -ine $repoRoot) {
    throw 'Container belongs to a different checkout/host path. Use its original checkout and Compose configuration.'
}
$composeArgs = @('--project-name', $project)
foreach ($file in ($files -split ',')) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Original Compose file not found: $file" }
    $composeArgs += @('--file', $file)
}
$envFile = Join-Path (Get-Location).Path '.env'
if (-not (Test-Path -LiteralPath $envFile)) { throw 'Existing .env is missing; refusing to replace your configuration.' }
$settingsText = [IO.File]::ReadAllText($envFile)
foreach ($setting in @('EMAIL_SENDING_ENABLED=false','EMAIL_AUTO_APPROVED=false','ENABLE_BRAVE_SEARCH=false','AI_PROVIDER=local')) {
    $key = ($setting -split '=',2)[0]
    $pattern = '(?m)^\s*' + [regex]::Escape($key) + '\s*=.*$'
    if ([regex]::IsMatch($settingsText,$pattern)) { $settingsText = [regex]::Replace($settingsText,$pattern,$setting) }
    else { $settingsText = $settingsText.TrimEnd() + "`n" + $setting + "`n" }
}
# Preserve all other settings and credentials without printing their contents.
[IO.File]::WriteAllText($envFile,$settingsText,[Text.UTF8Encoding]::new($false))
docker compose @composeArgs config --quiet
Assert-DockerSuccess 'Validating original Compose configuration'
$running = docker inspect --format '{{.State.Running}}' $assistantId
Assert-DockerSuccess 'Checking assistant state'
if ($running.Trim() -ne 'true') {
    docker start $assistantId
    Assert-DockerSuccess 'Starting only the existing assistant for backup'
}
$backupCode = @'
import os, pathlib, sqlite3, datetime
root = pathlib.Path(os.environ.get('DATA_DIR', 'data'))
backup = root / 'backups'
backup.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
for path in root.glob('*.sqlite'):
    target = backup / (path.stem + '-' + stamp + '.sqlite')
    source = sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    print('SQLite backup created:', target.name)
'@
$backupCode | docker compose @composeArgs exec -T assistant python -
Assert-DockerSuccess 'Backing up SQLite in the existing data volume'
docker compose @composeArgs up -d --no-deps --build assistant
Assert-DockerSuccess 'Updating only assistant'
$healthCode = @'
import json, urllib.request
with urllib.request.urlopen('http://localhost:8000/health', timeout=10) as response:
    data = json.load(response)
assert data['email_sending_enabled'] is False, 'Email sending must stay disabled'
print(data)
'@
$ready = $false
for ($attempt=0; $attempt -lt 15; $attempt++) {
    $healthCode | docker compose @composeArgs exec -T assistant python -
    if ($LASTEXITCODE -eq 0) { $ready=$true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw 'Assistant did not become healthy. Inspect docker compose logs for assistant only; no other service was restarted.' }
Write-Host 'Assistant updated. Existing project identity, data volume and Compose overrides preserved. No n8n workflow or unrelated service was changed.'
