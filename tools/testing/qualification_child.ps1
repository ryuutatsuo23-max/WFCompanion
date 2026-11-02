param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Phase)
$ErrorActionPreference = 'Stop'
try {
    if ($env:WF_FROZEN_CI -ne '1' -or $Root -notmatch '^C:\\wf-frozen-ci-[a-f0-9]{32}$') { throw 'Not a qualification invocation' }
    $request = Get-Content -LiteralPath (Join-Path $Root 'request.json') -Raw | ConvertFrom-Json
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if ($identity.User.Value -ne $request.sid -or $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
        @($identity.Groups | Where-Object Value -eq 'S-1-5-32-544').Count) { throw 'Unexpected child account' }
    # Use the genuinely loaded new account profile; do not spoof native Known Folders.
    $env:LOCALAPPDATA = [Environment]::GetFolderPath('LocalApplicationData')
    $env:APPDATA = [Environment]::GetFolderPath('ApplicationData')
    $env:USERPROFILE = [Environment]::GetFolderPath('UserProfile')
    if (-not $env:LOCALAPPDATA -or -not $env:USERPROFILE -or $env:USERPROFILE -notlike "C:\Users\$($request.account)*") { throw 'Profile was not loaded' }
    $env:HOME = $env:USERPROFILE
    $env:HOMEDRIVE = 'C:'; $env:HOMEPATH = $env:USERPROFILE.Substring(2)
    $env:TEMP = Join-Path $Root 'temporary'; $env:TMP = $env:TEMP
    $env:QT_QPA_PLATFORM = 'offscreen'; $env:PYTHONDONTWRITEBYTECODE = '1'; $env:PYTHONNOUSERSITE = '1'
    $permit = Join-Path $Root "permits\$Phase"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $permit)) {
        if ($timer.Elapsed.TotalSeconds -ge 10) { throw 'Parent ownership permit missing' }
        Start-Sleep -Milliseconds 25
    }
    if ((Get-Content -LiteralPath $permit -Raw) -ne $request.invocation) { throw 'Wrong ownership permit' }
    if ($Phase -eq 'smoke') {
        if (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'WoWForever')) { throw 'Nonfresh test profile' }
        $executable = $request.public_exe
        $arguments = @('--smoke-test', (Join-Path $Root 'smoke'))
        $expected = $request.public_exe_sha256
    } else {
        if ($Phase -notin @('positive','interrupt-recovery','recover','reporting','interrupt-changed','reject-changed','unsafe','lock')) { throw 'Unknown phase' }
        $executable = $request.exe
        $arguments = @('--wf-qualification', $Root, $Phase)
        $expected = $request.exe_sha256
    }
    if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Frozen executable mismatch' }
    $start = [Diagnostics.ProcessStartInfo]::new($executable)
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true; $start.WorkingDirectory = $Root
    foreach ($argument in $arguments) { $start.ArgumentList.Add($argument) }
    $app = [Diagnostics.Process]::Start($start)
    try {
        # Parent job contains this process and every child; parent enforces the deadline.
        $app.WaitForExit()
        $code = $app.ExitCode
        if ($Phase -eq 'smoke' -and ($code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $Root 'smoke\smoke-ok.txt')))) { throw 'Public smoke failed' }
        @{phase=$Phase;pid=$app.Id;exit_code=$code;sid=$identity.User.Value;profile_loaded=$true} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root "results\$Phase-process.json") -Encoding utf8NoBOM
    } finally { $app.Dispose() }
    exit $code
} catch {
    # No exception text, invocation arguments or credentials in logs.
    Write-Output ('Qualification child failed: ' + $_.Exception.GetType().Name)
    exit 93
}
