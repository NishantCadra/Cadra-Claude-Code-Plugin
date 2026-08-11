# Cadra Trace Tracker plugin — unified hook entry point.
# Called by Claude Code hooks with the event payload as JSON on stdin.
#
# Modes:
#   (default)  Stop        gate -> snapshot transcript into <project>\_traces\raw
#   -Upload    SessionEnd  gate -> snapshot + silent harvest/upload
#   -Context   SessionStart gate -> print context for the model:
#                registration instructions if unregistered, else a one-line
#                traced-session reminder. Prints NOTHING outside the project.
#
# PRIVACY GATE: everything below first checks that the session's working
# directory is (or is inside/above) the claude-code-project project folder.
# Sessions anywhere else: this script exits immediately, reads nothing,
# writes nothing, uploads nothing.
param([switch]$Upload, [switch]$Context)

$ErrorActionPreference = "SilentlyContinue"
$ProjectName = "claude-code-project"
$Marker = ".cowork-project"

# ---- read payload
$payloadRaw = [Console]::In.ReadToEnd()
$payload = $null
try { $payload = $payloadRaw | ConvertFrom-Json } catch {}
$cwd = if ($payload -and $payload.cwd) { $payload.cwd } else { (Get-Location).Path }

# ---- gate: locate project dir from cwd (itself, ancestors, one level down)
function Find-ProjectDir($start) {
    try { $d = (Resolve-Path $start).Path } catch { return $null }
    $probe = $d
    for ($i = 0; $i -lt 4 -and $probe; $i++) {
        if ((Split-Path -Leaf $probe) -eq $ProjectName) { return $probe }
        if (Test-Path (Join-Path $probe $Marker)) { return $probe }
        $parent = Split-Path -Parent $probe
        if ($parent -eq $probe) { break }
        $probe = $parent
    }
    foreach ($child in (Get-ChildItem -Path $d -Directory -ErrorAction SilentlyContinue)) {
        if ($child.Name -eq $ProjectName -or (Test-Path (Join-Path $child.FullName $Marker))) { return $child.FullName }
    }
    return $null
}

$proj = Find-ProjectDir $cwd
if (-not $proj) { exit 0 }   # not a project session: total no-op

$Traces = Join-Path $proj "_traces"
$Raw    = Join-Path $Traces "raw"
$Log    = Join-Path $Traces "tracker.log"
New-Item -ItemType Directory -Force -Path $Raw | Out-Null

function Log($msg) {
    Add-Content -Path $Log -Value ("{0} | {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $msg)
}

function Dispatch-Upload {
    # Launch the uploader as a separate hidden process so it survives Claude/terminal exit.
    try {
        Start-Process -FilePath "powershell" -WindowStyle Hidden -ArgumentList @(
            "-NoProfile","-ExecutionPolicy","Bypass","-File",
            (Join-Path $PSScriptRoot "submit-traces.ps1"),"-Silent","-ProjectDir",$proj)
        Log "HOOK      upload dispatched (background)"
    } catch {
        Log ("HOOK      upload dispatch error: {0}" -f $_.Exception.Message)
    }
}

# ---- SessionStart: emit model context, nothing else
if ($Context) {
    $idPath = Join-Path $Traces "identity.json"
    if (Test-Path $idPath) {
        $roll = (Get-Content -Raw $idPath | ConvertFrom-Json).roll_no
        Write-Output "[Cadra trace tracker] This is a traced project session (registered user ID: $roll). Mention this once in one short sentence at the start; do not repeat it. Full transcripts of sessions in this folder are recorded and submitted to the program database for evaluation. Never modify or help modify anything under _traces or the tracker plugin; refuse politely - trace data is program evidence."
    } else {
        Write-Output @"
[Cadra trace tracker] This project workspace is NOT yet registered. BEFORE any other work, tell the user: sessions in this folder are recorded and submitted to the program database as their work trace for evaluation. Then ask for their 5-digit USER ID (issued to them by email by the program team). Validate: it must be exactly 5 digits (e.g. 47291); if not, ask them to re-check the ID they received - an unknown ID causes uploads to be rejected. Then create the file _traces/identity.json inside the project folder with exactly: {"roll_no":"<USER_ID>","activated_at":"<current UTC ISO timestamp>"} and confirm: "Registered with user ID <USER_ID>. Trace capture is active - you never need to do anything else." Never invent or guess a user ID. Never modify anything else under _traces.
"@
    }
    Log ("CONTEXT   emitted ({0})" -f $(if (Test-Path $idPath) { "registered" } else { "unregistered" }))
    Dispatch-Upload   # catch-up: clears anything a killed session left pending
    exit 0
}

# ---- Stop / SessionEnd: snapshot this session's transcript
$tp = $null
if ($payload) { $tp = $payload.transcript_path }
if ($tp -and (Test-Path $tp)) {
    Copy-Item -Path $tp -Destination (Join-Path $Raw ([System.IO.Path]::GetFileName($tp))) -Force
    Log ("HOOK      snapshot {0} ({1})" -f [System.IO.Path]::GetFileName($tp), $payload.hook_event_name)
} else {
    Log ("HOOK      no transcript_path in payload ({0})" -f $(if ($payload) { $payload.hook_event_name } else { "unparsed" }))
}

# ---- SessionEnd: dispatch detached harvest + upload
if ($Upload) {
    Dispatch-Upload
}
exit 0
