# =====================================================================
# Cadra Trace Tracker v3 — harvest + upload, all in one.
# Runs natively on Windows (PowerShell 5.1+). No plugin, no Python.
# Double-click submit-traces.bat, or run this file in PowerShell.
#
# What it does:
#   1. First run: asks for your roll number once, remembers it.
#   2. Scans Claude Code's local session storage for
#      session transcripts (.jsonl) that reference this project.
#   3. Builds one trace envelope per project session into _traces\pending.
#   4. Uploads envelopes to the program database; moves them to _traces\sent.
#   5. Prints a summary. Safe to run any number of times.
#
# Optional: powershell -File submit-traces.ps1 -ScanOnly   (no upload,
# just report what would be captured — used for troubleshooting)
# =====================================================================
param([switch]$ScanOnly, [switch]$Silent, [switch]$List, [string]$ProjectDir)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------- config
$SupabaseUrl   = "https://pyrpzlppjmejlohiqoyc.supabase.co"
$AnonKey       = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5cnB6bHBwam1lamxvaGlxb3ljIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQ5MjM1NzcsImV4cCI6MjA4MDQ5OTU3N30.wREHqbUvRhBZoeN4IxPMZVc27FfYeFQNMysKQ7icy0I"
$Table         = "tracker_sessions_staging"
$ProjectName   = "claude-code-project"
$CaptureVersion = "2.2.1"

# Candidate roots where the Claude desktop app stores local session data.
$SearchRoots = @(
    (Join-Path $env:APPDATA      "Claude\local-agent-mode-sessions"),
    (Join-Path $env:USERPROFILE  ".claude\projects"),
    (Join-Path $env:LOCALAPPDATA "Claude\local-agent-mode-sessions")
)

# ------------------------------------------------------------- paths
if ($ProjectDir -and (Test-Path $ProjectDir)) {
    $Root = (Resolve-Path $ProjectDir).Path
} else {
    # search upward from cwd for the project folder
    $Root = $null
    $probe = (Get-Location).Path
    for ($i = 0; $i -lt 4 -and $probe; $i++) {
        if (Test-Path (Join-Path $probe ".claude-project")) { $Root = $probe; break }
        $parent = Split-Path -Parent $probe
        if ($parent -eq $probe) { break }
        $probe = $parent
    }
    if (-not $Root) {
        if ($Silent) { exit 0 }
        Write-Host "Could not find the $ProjectName project folder from here. Run this from inside the folder."
        exit 1
    }
}
$Traces  = Join-Path $Root "_traces"
$Pending = Join-Path $Traces "pending"
$Sent    = Join-Path $Traces "sent"
$Log     = Join-Path $Traces "tracker.log"
New-Item -ItemType Directory -Force -Path $Pending, $Sent | Out-Null

# single-flight lock: another uploader running in the last 2 minutes wins
$LockPath = Join-Path $Traces "upload.lock"
if (Test-Path $LockPath) {
    $age = (Get-Date) - (Get-Item $LockPath).LastWriteTime
    if ($age.TotalSeconds -lt 120) { exit 0 }
}
Set-Content -Path $LockPath -Value (Get-Date -Format "o")

function Log($msg) {
    $line = "{0} | {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $msg
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

# ------------------------------------------------------------- identity
$IdentityPath = Join-Path $Traces "identity.json"
$Roll = $null
try { $Roll = (Get-Content -Raw (Join-Path $Root ".claude-project") | ConvertFrom-Json).user_id } catch {}
$ProjName = Split-Path -Leaf $Root   # auto label: workspace folder name else {
    if ($Silent) { exit 0 }   # silent hook run before first-time setup: nothing to do
    Write-Host ""
    Write-Host "=== First-time setup ==="
    Write-Host "Your user ID is checked against the official program roster"
    Write-Host "when traces are uploaded - a wrong user ID will be REJECTED."
    do {
        $Roll = (Read-Host "Enter your 5-digit user ID (issued to you by email, e.g. 47291)").Trim()
        if ($Roll -notmatch "^\d{5}$") {
            Write-Host "That doesn't look right - it must be exactly 5 digits. Try again."
            $Roll = $null
        }
    } while (-not $Roll)
    @{ roll_no = $Roll; activated_at = (Get-Date -Format "o") } |
        ConvertTo-Json | Set-Content -Path $IdentityPath -Encoding UTF8
    Log "IDENTITY  roll $Roll saved"
}
if ($List) {
    try {
        $rows = Invoke-RestMethod -Method Post -Uri "$SupabaseUrl/rest/v1/rpc/tracker_my_sessions_staging" `
            -Headers @{ apikey = $AnonKey; Authorization = "Bearer $AnonKey" } `
            -ContentType "application/json" -Body (@{ p_code = $Roll } | ConvertTo-Json)
    } catch {
        Write-Host "LIST FAILED: could not reach the database. Check internet and retry."
        exit 1
    }
    Write-Host ("SAVED SESSIONS for user {0} ({1} in database):" -f $Roll, @($rows).Count)
    foreach ($r in $rows) {
        $pn = if ($r.project_name) { $r.project_name } else { "-" }
        Write-Host ("  [SAVED] {0}  {1}  '{2}'  turns={3}  id={4}" -f $r.captured_at.Substring(0,16), $pn, $r.title, $r.turn_count, $r.session_id.Substring(0,8))
    }
    $pendingFiles = @(Get-ChildItem -Path $Pending -Filter "*.json" -File -ErrorAction SilentlyContinue)
    if ($pendingFiles.Count -gt 0) {
        Write-Host ("NOT YET SAVED ({0} pending locally):" -f $pendingFiles.Count)
        foreach ($f in $pendingFiles) { Write-Host ("  [PENDING] {0}" -f $f.Name) }
    } else {
        Write-Host "PENDING: none - everything captured locally has been saved."
    }
    exit 0
}
Write-Host ""
Log "RUN START roll=$Roll project=$ProjName scanonly=$ScanOnly"

# ------------------------------------------------------------- harvest
$StatePath = Join-Path $Traces "state.json"
$State = @{}
if (Test-Path $StatePath) {
    (Get-Content -Raw $StatePath | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $State[$_.Name] = [long]$_.Value }
}
$AlreadyDone = @{}
Get-ChildItem -Path $Pending, $Sent -Filter "*.json" -File -ErrorAction SilentlyContinue |
    ForEach-Object { $AlreadyDone[$_.BaseName] = $true }

$RawDir = Join-Path $Traces "raw"   # snapshots written by the Stop/SessionEnd hooks
$JsonlFiles = @()
foreach ($rootDir in ($SearchRoots + $RawDir)) {
    if (Test-Path $rootDir) {
        $JsonlFiles += Get-ChildItem -Path $rootDir -Recurse -Filter "*.jsonl" -File -ErrorAction SilentlyContinue
    }
}
$JsonlFiles = $JsonlFiles | Sort-Object FullName -Unique
Log ("SCAN      {0} transcript file(s) found across {1} storage root(s)" -f $JsonlFiles.Count, ($SearchRoots | Where-Object { Test-Path $_ }).Count)

$found = 0; $new = 0
foreach ($file in $JsonlFiles) {
    # Relevance gate, two ways a session counts as a project session:
    #  1. Claude Code encodes the session's working directory into the parent
    #     folder name under .claude\projects — if the student ran `claude`
    #     inside the project folder, that name contains claude-code-project.
    #  2. Fallback: the transcript content references the project folder.
    $enc = ($Root -replace "[^A-Za-z0-9]", "-")
    $dirMatch = ($file.Directory.Name -eq $enc) -or ($file.Directory.FullName -eq $RawDir)
    if (-not $dirMatch) {
        $esc = $Root.Replace("\", "\\")
        if (-not ((Select-String -Path $file.FullName -Pattern $Root -Quiet -SimpleMatch) -or (Select-String -Path $file.FullName -Pattern $esc -Quiet -SimpleMatch))) { continue }
    }
    $found++

    # ----- parse the transcript
    $entries = @()
    foreach ($line in [System.IO.File]::ReadLines($file.FullName)) {
        if ($line.Trim().Length -eq 0) { continue }
        try { $entries += ($line | ConvertFrom-Json) } catch { continue }
    }
    if ($entries.Count -eq 0) { continue }

    # session id: prefer an explicit field, fall back to the filename stem
    $sessionId = $null
    foreach ($e in $entries) {
        if ($e.PSObject.Properties["sessionId"] -and $e.sessionId) { $sessionId = $e.sessionId; break }
        if ($e.PSObject.Properties["session_id"] -and $e.session_id) { $sessionId = $e.session_id; break }
    }
    if (-not $sessionId) { $sessionId = $file.BaseName }

    $envName = "{0}__{1}" -f $Roll, $sessionId
    $srcSize = [long]$file.Length
    $known = $State.ContainsKey($envName)
    if ($known -and $State[$envName] -ge $srcSize) { continue }   # unchanged since last capture
    $State[$envName] = $srcSize
    $new++

    # turn counting with streaming-chunk dedup: count DISTINCT message ids
    # per role (assistant messages stream as multiple lines sharing an id).
    $userIds = @{}; $asstIds = @{}
    $firstUserText = $null
    $tsFirst = $null; $tsLast = $null
    foreach ($e in $entries) {
        $role = $null
        if ($e.PSObject.Properties["type"] -and ($e.type -in @("user","assistant"))) { $role = $e.type }
        elseif ($e.PSObject.Properties["message"] -and $e.message.PSObject.Properties["role"]) { $role = $e.message.role }
        if ($e.PSObject.Properties["timestamp"] -and $e.timestamp) {
            if (-not $tsFirst) { $tsFirst = $e.timestamp }
            $tsLast = $e.timestamp
        }
        $mid = $null
        if ($e.PSObject.Properties["uuid"]) { $mid = $e.uuid }
        if ($e.PSObject.Properties["message"] -and $e.message.PSObject.Properties["id"] -and $e.message.id) { $mid = $e.message.id }
        if (-not $mid) { $mid = [guid]::NewGuid().ToString() }
        if ($role -eq "user") {
            $userIds[$mid] = $true
            if (-not $firstUserText) {
                $c = $e.message.content
                if ($c -is [string]) { $firstUserText = $c }
                elseif ($c -is [array]) {
                    foreach ($b in $c) { if ($b.type -eq "text" -and $b.text) { $firstUserText = $b.text; break } }
                }
            }
        }
        elseif ($role -eq "assistant") { $asstIds[$mid] = $true }
    }

    # privacy/minimisation: strip inline image payloads before upload
    foreach ($e in $entries) {
        $msgs = @()
        if ($e.PSObject.Properties["message"] -and $e.message -and $e.message.PSObject.Properties["content"]) { $msgs += ,$e.message }
        foreach ($m in $msgs) {
            if ($m.content -is [array]) {
                for ($ci = 0; $ci -lt $m.content.Count; $ci++) {
                    $b = $m.content[$ci]
                    if ($b -and $b.PSObject.Properties["type"] -and $b.type -eq "image") {
                        $m.content[$ci] = [pscustomobject]@{ type = "text"; text = "[image removed before upload]" }
                    }
                }
            }
        }
    }

    $title = if ($firstUserText) { ($firstUserText -replace "\s+"," ").Trim() } else { "Untitled session" }
    if ($title.Length -gt 120) { $title = $title.Substring(0,120) }

    $envelope = [ordered]@{
        envelope_version   = 1
        capture_version    = $CaptureVersion
        plugin_hash        = "harvester-ps1"
        roll_no            = $Roll
        project_name       = $ProjName
        session_id         = $sessionId
        hook_event         = "harvest"
        client_captured_at = (Get-Date -Format "o")
        title              = $title
        started_at         = $tsFirst
        ended_at           = $tsLast
        turn_count         = ($userIds.Count + $asstIds.Count)
        source_file        = $file.FullName
        transcript         = $entries
    }
    $outPath = Join-Path $Pending ($envName + ".json")
    $envelope | ConvertTo-Json -Depth 100 -Compress | Set-Content -Path $outPath -Encoding UTF8
    Log ("CAPTURED  {0}  turns={1}  '{2}'" -f $sessionId, $envelope.turn_count, $title.Substring(0, [Math]::Min(60,$title.Length)))
}
$stateObj = New-Object PSObject
$State.GetEnumerator() | ForEach-Object { $stateObj | Add-Member -NotePropertyName $_.Key -NotePropertyValue $_.Value }
$stateObj | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
Log ("HARVEST   {0} project session(s) found, {1} new/updated envelope(s) written" -f $found, $new)

if ($ScanOnly) {
    Log "SCANONLY  stopping before upload."
    exit 0
}

# ------------------------------------------------------------- upload
$ok = 0; $failed = 0
$pendingFiles = Get-ChildItem -Path $Pending -Filter "*.json" -File
foreach ($f in $pendingFiles) {
    try {
        $envelope = Get-Content -Raw -Path $f.FullName | ConvertFrom-Json
        $row = [ordered]@{
            session_id         = $envelope.session_id
            roll_no            = $envelope.roll_no
            project_name       = $envelope.project_name
            title              = $envelope.title
            started_at         = $envelope.started_at
            ended_at           = $envelope.ended_at
            client_captured_at = $envelope.client_captured_at
            turn_count         = $envelope.turn_count
            envelope_version   = $envelope.envelope_version
            capture_version    = $envelope.capture_version
            plugin_hash        = $envelope.plugin_hash
            hook_event         = $envelope.hook_event
            transcript         = $envelope.transcript
        }
        $body = (@{ p = $row } | ConvertTo-Json -Depth 100 -Compress)
        try {
            Invoke-RestMethod -Method Post `
                -Uri "$SupabaseUrl/rest/v1/rpc/tracker_submit_session_staging" `
                -Headers @{ apikey = $AnonKey; Authorization = "Bearer $AnonKey"; Prefer = "return=minimal" } `
                -ContentType "application/json; charset=utf-8" `
                -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
            Move-Item -Path $f.FullName -Destination (Join-Path $Sent $f.Name) -Force
            Log "UPLOADED  $($f.Name)"
            $ok++
        }
        catch {
            $status = $null
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -eq 409) {
                Move-Item -Path $f.FullName -Destination (Join-Path $Sent $f.Name) -Force
                Log "DUPLICATE $($f.Name) (already in database)"
                $ok++
            }
            else {
                Log "FAILED    $($f.Name) -> HTTP $status : $($_.Exception.Message)"
                $failed++
            }
        }
    }
    catch {
        Log "FAILED    $($f.Name) -> unreadable envelope: $($_.Exception.Message)"
        $failed++
    }
}

Remove-Item -Path $LockPath -Force -ErrorAction SilentlyContinue
Write-Host ""
Log ("DONE      {0} uploaded/confirmed, {1} failed, {2} project session(s) known in total" -f $ok, $failed, ($found))
if ($failed -gt 0) {
    Write-Host "Some uploads failed - files stay in _traces\pending. Just run this again later."
    exit 1
}
Write-Host "All traces submitted successfully."
exit 0
