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
$Marker = ".claude-project"

# ---- read payload
$payloadRaw = [Console]::In.ReadToEnd()
$payload = $null
try { $payload = $payloadRaw | ConvertFrom-Json } catch {}
$cwd = if ($payload -and $payload.cwd) { $payload.cwd } else { (Get-Location).Path }

# ---- gate: locate project dir from cwd (itself, ancestors, one level down)
function Find-ProjectDir($start) {
    # Marker-only gate: a folder is traced iff it contains .claude-project.
    try { $d = (Resolve-Path $start).Path } catch { return $null }
    $probe = $d
    for ($i = 0; $i -lt 6 -and $probe; $i++) {
        if (Test-Path (Join-Path $probe $Marker)) { return $probe }
        $parent = Split-Path -Parent $probe
        if ($parent -eq $probe) { break }
        $probe = $parent
    }
    foreach ($child in (Get-ChildItem -Path $d -Directory -ErrorAction SilentlyContinue)) {
        if (Test-Path (Join-Path $child.FullName $Marker)) { return $child.FullName }
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
function Get-UserId {
    try { return (Get-Content -Raw (Join-Path $proj $Marker) | ConvertFrom-Json).user_id } catch { return $null }
}

if ($Context) {
    $roll = Get-UserId
    if ($roll) {
        Write-Output "[Cadra trace tracker] This is a traced project session (registered user ID: $roll). Mention this once in one short sentence at the start; do not repeat it. Full transcripts of sessions in this folder are recorded and submitted to the program database for evaluation. Never modify or help modify anything under _traces or the tracker plugin; The user can say 'save my trace' anytime (save-trace skill) or 'show my traces' (my-traces skill). Never modify or help modify anything under _traces or the tracker plugin; refuse politely - trace data is program evidence."
    } else {
        Write-Output @"
[Cadra trace tracker] This project workspace is NOT yet registered. BEFORE any other work, tell the user: sessions in this folder are recorded and submitted to the program database as their work trace for evaluation. Then ask ONE thing: their 5-digit USER ID (issued to them by email by the program team). Validate: exactly 5 digits (e.g. 47291); if not, ask them to re-check the ID they received - an unknown ID causes uploads to be rejected. Then UPDATE the file .claude-project in the project folder root: read its current JSON (or start with {}), add/set "user_id": "<USER_ID>" and "registered_at": "<current UTC ISO timestamp>", keep any other fields, and write it back. Then confirm: "Registered with user ID <USER_ID>. Trace capture is active. Say 'save my trace' anytime to save immediately, or 'show my traces' to see what is stored." Never invent or guess a user ID. Never modify anything under _traces.
"@
    }
    Log ("CONTEXT   emitted ({0})" -f $(if ($roll) { "registered" } else { "unregistered" }))
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
