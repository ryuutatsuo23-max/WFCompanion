param([Parameter(Mandatory)][string]$Evidence)
$ErrorActionPreference = 'Stop'
# This account-creating controller must never operate on a personal/self-hosted PC.
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:RUNNER_OS -ne 'Windows' -or $env:GITHUB_REPOSITORY -ne 'ryuutatsuo23-max/WFCompanion' -or
    $env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:COMPUTERNAME -in @('RYUU','Drago2') -or
    (Get-CimInstance Win32_OperatingSystem).Caption -notlike '*Windows Server*') { throw 'Requires fresh standard GitHub-hosted Windows Server VM' }
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 required' }
$binding = Get-Content -LiteralPath (Join-Path $Evidence 'build-binding.json') -Raw | ConvertFrom-Json
if ($binding.commit -ne $env:WF_TEST_COMMIT -or (git rev-parse HEAD) -ne $binding.commit) { throw 'Build source mismatch' }
function Assert-Bundle([string]$Directory, $Inventory) {
    $actual = @(Get-ChildItem -LiteralPath $Directory -File -Recurse)
    if ($actual.Count -ne @($Inventory.PSObject.Properties).Count) { throw 'Bundle membership mismatch' }
    foreach ($item in $actual) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked bundle input' }
        $relative = [IO.Path]::GetRelativePath($Directory,$item.FullName).Replace('\','/')
        $entry = $Inventory.$relative
        if (-not $entry -or $item.Length -ne $entry.size -or (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'Bundle integrity mismatch' }
    }
}
Assert-Bundle $binding.original $binding.original_inventory
Assert-Bundle $binding.instrumented $binding.instrumented_inventory
$knownGameRoots = @('C:\Program Files\World of Warcraft','C:\Program Files (x86)\World of Warcraft','C:\Blizzard\World of Warcraft','D:\Blizzard\World of Warcraft')
foreach ($path in $knownGameRoots) { if (Test-Path -LiteralPath $path) { throw 'Unexpected game directory on hosted runner' } }
$profiles = @(Get-CimInstance Win32_UserProfile | Where-Object { -not $_.Special })
foreach ($profile in $profiles) {
    if ((Split-Path $profile.LocalPath -Leaf) -notin @('runneradmin','Administrator','defaultuser0')) { throw 'Unexpected preexisting non-system profile' }
    if (Test-Path -LiteralPath (Join-Path $profile.LocalPath 'AppData\Local\WoWForever')) { throw 'Unexpected Companion state on hosted runner' }
}

# SafeHandle owns the job. Every case starts with a handshake before the app runs.
Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;
public sealed class FrozenJob : IDisposable {
 [StructLayout(LayoutKind.Sequential)] struct Basic { public long a,b; public uint flags; public UIntPtr min,max; public uint count; public UIntPtr affinity; public uint priority,scheduling; }
 [StructLayout(LayoutKind.Sequential)] struct IO { public ulong a,b,c,d,e,f; }
 [StructLayout(LayoutKind.Sequential)] struct Extended { public Basic basic; public IO io; public UIntPtr p,j,pp,pj; }
 [StructLayout(LayoutKind.Sequential)] struct Accounting { public long a,b,c,d; public uint faults,total,active,terminated; }
 [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateJobObjectW(IntPtr sa,string name);
 [DllImport("kernel32",SetLastError=true)] static extern bool SetInformationJobObject(SafeFileHandle j,int kind,ref Extended info,uint size);
 [DllImport("kernel32",SetLastError=true)] static extern bool AssignProcessToJobObject(SafeFileHandle j,SafeProcessHandle p);
 [DllImport("kernel32",SetLastError=true)] static extern bool IsProcessInJob(SafeProcessHandle p,SafeFileHandle j,out bool yes);
 [DllImport("kernel32",SetLastError=true)] static extern bool QueryInformationJobObject(SafeFileHandle j,int kind,out Accounting info,uint size,IntPtr length);
 [DllImport("kernel32",SetLastError=true)] static extern bool TerminateJobObject(SafeFileHandle j,uint exit);
 [DllImport("advapi32",SetLastError=true)] static extern bool OpenProcessToken(SafeProcessHandle p,uint access,out SafeAccessTokenHandle token);
 [DllImport("advapi32",SetLastError=true)] static extern bool GetTokenInformation(SafeAccessTokenHandle t,int kind,out int value,int size,out int length);
 SafeFileHandle handle;
 static void Check(bool ok) { if(!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); }
 public FrozenJob() {
  handle=CreateJobObjectW(IntPtr.Zero,null);
  if(handle.IsInvalid) throw new InvalidOperationException("Job creation failed");
  var info=new Extended(); info.basic.flags=0x2000;
  try { Check(SetInformationJobObject(handle,9,ref info,(uint)Marshal.SizeOf<Extended>())); }
  catch { handle.Dispose(); throw; }
 }
 public void Assign(Process p) { Check(AssignProcessToJobObject(handle,p.SafeHandle)); bool yes; Check(IsProcessInJob(p.SafeHandle,handle,out yes)); if(!yes) throw new InvalidOperationException("Job membership missing"); }
 public uint Active() { Accounting a; Check(QueryInformationJobObject(handle,1,out a,(uint)Marshal.SizeOf<Accounting>(),IntPtr.Zero)); return a.active; }
 public void Terminate() { Check(TerminateJobObject(handle,94)); }
 public static int[] VerifyToken(Process p,string sid) {
  SafeAccessTokenHandle token; Check(OpenProcessToken(p.SafeHandle,8,out token));
  using(token) using(var identity=new WindowsIdentity(token.DangerousGetHandle())) {
   if(identity.User.Value!=sid) throw new InvalidOperationException("Wrong token SID");
   foreach(var group in identity.Groups) if(group.Value=="S-1-5-32-544") throw new InvalidOperationException("Administrator SID present, including deny-only");
   int elevation,type,session,length;
   Check(GetTokenInformation(token,20,out elevation,4,out length));
   Check(GetTokenInformation(token,18,out type,4,out length));
   Check(GetTokenInformation(token,12,out session,4,out length));
   if(elevation!=0 || type!=1 || session<=0) throw new InvalidOperationException("Not an interactive standard-user token");
   return new int[]{elevation,type,session};
  }
 }
 public void Dispose() { handle.Dispose(); }
}
'@
$invocation = [Guid]::NewGuid().ToString('N')
$root = "C:\wf-frozen-ci-$invocation"
if (Test-Path -LiteralPath $root) { throw 'Workspace must be fresh' }
$name = 'wfci' + $invocation.Substring(0,12)
# Random password exists only in controller memory and the credential API call.
$password = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(36)) + '!aA9'
$secure = ConvertTo-SecureString $password -AsPlainText -Force
$password = $null
$account = New-LocalUser -Name $name -Password $secure -AccountNeverExpires -Description 'Disposable hosted-runner frozen qualification'
Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $account
if (@(Get-LocalGroupMember -SID 'S-1-5-32-544' | Where-Object SID -eq $account.SID).Count) { throw 'Test account is an administrator' }
New-Item -ItemType Directory -Path $root | Out-Null
foreach ($child in @('cases','results','temporary','smoke','permits')) { New-Item -ItemType Directory -Path (Join-Path $root $child) | Out-Null }
$acl = Get-Acl -LiteralPath $root
$acl.SetAccessRuleProtection($true,$false)
foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($account.SID,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $root -AclObject $acl
foreach ($child in @('cases','results','temporary','smoke')) {
    $path = Join-Path $root $child; $childAcl = Get-Acl -LiteralPath $path
    $childAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($account.SID,'Modify','ContainerInherit,ObjectInherit','None','Allow'))
    Set-Acl -LiteralPath $path -AclObject $childAcl
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'qualification_child.ps1') -Destination (Join-Path $root 'child.ps1')
$request = @{invocation=$invocation;commit=$binding.commit;account=$name;sid=$account.SID.Value;
    exe=(Join-Path $binding.instrumented 'WFCompanion.exe');exe_sha256=$binding.instrumented_inventory.'WFCompanion.exe'.sha256;
    public_exe=(Join-Path $binding.original 'WFCompanion.exe');public_exe_sha256=$binding.original_inventory.'WFCompanion.exe'.sha256}
$request | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'request.json') -Encoding utf8NoBOM
# Outbound network blocking applies only to these two CI-created executable paths.
foreach ($exe in @($request.exe,$request.public_exe)) {
    New-NetFirewallRule -DisplayName "WF qualification $invocation $([IO.Path]::GetDirectoryName($exe))" -Direction Outbound -Program $exe -Action Block -Profile Any | Out-Null
}
$summary = @{schema=1;commit=$binding.commit;invocation=$invocation;runner_environment=$env:RUNNER_ENVIRONMENT;
    runner_name=$env:RUNNER_NAME;image_os=$env:ImageOS;image_version=$env:ImageVersion;test_sid=$account.SID.Value;
    known_game_directories_absent=$true;preexisting_companion_state_absent=$true;network_block_rules_created=$true;
    network_profiles=@(Get-NetFirewallProfile | Select-Object Name,Enabled);cases=@();status='running'}
$clock = [Diagnostics.Stopwatch]::StartNew()
try {
    foreach ($phase in @('smoke','positive','interrupt-recovery','recover','reporting','interrupt-changed','reject-changed','unsafe','lock')) {
        if ($clock.Elapsed.TotalSeconds -ge 480) { throw 'Batch deadline exceeded' }
        Assert-Bundle $binding.original $binding.original_inventory
        Assert-Bundle $binding.instrumented $binding.instrumented_inventory
        $job = [FrozenJob]::new(); $process = $null; $caseClock = [Diagnostics.Stopwatch]::StartNew()
        try {
            $start = [Diagnostics.ProcessStartInfo]::new((Get-Process -Id $PID).Path)
            $start.UseShellExecute=$false; $start.CreateNoWindow=$true; $start.LoadUserProfile=$true
            $start.UserName=$name; $start.Domain=$env:COMPUTERNAME; $start.Password=$secure; $start.WorkingDirectory=$root
            $start.Environment.Clear()
            foreach ($key in @('SystemRoot','WINDIR','COMSPEC','ProgramFiles','ProgramFiles(x86)')) { if ([Environment]::GetEnvironmentVariable($key)) { $start.Environment[$key]=[Environment]::GetEnvironmentVariable($key) } }
            $start.Environment['PATH']="$env:SystemRoot\System32;$env:SystemRoot"
            $start.Environment['WF_FROZEN_CI']='1'
            foreach ($arg in @('-NoLogo','-NoProfile','-NonInteractive','-File',(Join-Path $root 'child.ps1'),'-Root',$root,'-Phase',$phase)) { $start.ArgumentList.Add($arg) }
            $process = [Diagnostics.Process]::Start($start)
            $job.Assign($process)
            $token = [FrozenJob]::VerifyToken($process,$account.SID.Value)
            [IO.File]::WriteAllText((Join-Path $root "permits\$phase"),$invocation)
            $remainingMs = [int][Math]::Floor([Math]::Min(60000-$caseClock.Elapsed.TotalMilliseconds,480000-$clock.Elapsed.TotalMilliseconds))
            if ($remainingMs -le 0 -or -not $process.WaitForExit($remainingMs)) { $job.Terminate(); throw 'Frozen case deadline exceeded' }
            $expected = if ($phase.StartsWith('interrupt-')) { 73 } else { 0 }
            if ($process.ExitCode -ne $expected) { throw "Qualification phase failed: $phase (exit $($process.ExitCode))" }
            $wait = [Diagnostics.Stopwatch]::StartNew()
            while ($job.Active() -ne 0 -and $wait.Elapsed.TotalSeconds -lt 3) { Start-Sleep -Milliseconds 25 }
            if ($job.Active() -ne 0 -or $caseClock.Elapsed.TotalSeconds -ge 65) { $job.Terminate(); throw 'Process cleanup unverified' }
            $child = Get-Content -LiteralPath (Join-Path $root "results\$phase-process.json") -Raw | ConvertFrom-Json
            if ($child.exit_code -ne $expected -or $child.sid -ne $account.SID.Value -or $child.phase -ne $phase) { throw 'Contradictory process record' }
            if ($phase -ne 'smoke') {
                $result = Get-Content -LiteralPath (Join-Path $root "results\$phase.json") -Raw | ConvertFrom-Json
                if ($result.commit -ne $binding.commit -or $result.invocation -ne $invocation -or $result.pid -ne $child.pid -or
                    $result.exe_sha256 -ne $request.exe_sha256 -or -not $result.frozen -or $result.token.elevated -ne 0 -or
                    $result.token.elevation_type -ne 1 -or $result.token.sid -ne $account.SID.Value -or
                    ($expected -eq 0 -and $result.status -ne 'passed') -or ($expected -eq 73 -and -not $result.expected_interruption)) { throw 'Invalid frozen evidence' }
            }
            $summary.cases += @{phase=$phase;exit_code=$process.ExitCode;expected_exit=$expected;elapsed=$caseClock.Elapsed.TotalSeconds;
                parent_token=@{elevated=$token[0];type=$token[1];session=$token[2];administrator_sid_present=$false};job_empty=$true}
            Write-Output "Frozen qualification passed: $phase"
        } finally {
            try { if ($job.Active() -ne 0) { $job.Terminate() } }
            finally {
                try {
                    # Also stop a child whose job assignment failed before its permit.
                    if ($process -and -not $process.HasExited) {
                        $process.Kill()
                        if (-not $process.WaitForExit(5000)) { throw 'Owned controller did not terminate' }
                    }
                } finally { if ($process) { $process.Dispose() }; $job.Dispose() }
            }
        }
        if ($caseClock.Elapsed.TotalSeconds -ge 65) { throw 'Case disposal deadline exceeded' }
    }
    Assert-Bundle $binding.original $binding.original_inventory
    Assert-Bundle $binding.instrumented $binding.instrumented_inventory
    if ($clock.Elapsed.TotalSeconds -ge 480) { throw 'Final batch deadline exceeded' }
    $summary.status='passed'
} catch {
    $summary.status='failed'; $summary.failure_type=$_.Exception.GetType().Name
    # Only controller-generated failure messages are printed; credentials were never arguments.
    Write-Output ('Frozen qualification failed: ' + $_.Exception.GetType().Name)
    throw
} finally {
    $summary.elapsed=$clock.Elapsed.TotalSeconds
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $Evidence 'qualification-summary.json') -Encoding utf8NoBOM
    # Copy only bounded allowlisted result JSON, never profiles, credentials or stdout.
    foreach ($resultFile in Get-ChildItem -LiteralPath (Join-Path $root 'results') -File -Filter '*.json') {
        if ($resultFile.Length -gt 262144 -or $resultFile.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unsafe result evidence' }
        Copy-Item -LiteralPath $resultFile.FullName -Destination (Join-Path $Evidence $resultFile.Name)
    }
    $secure.Dispose()
}
