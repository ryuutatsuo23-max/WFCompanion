"""Offline only: parse source and exercise extracted pure functions with managed fake jobs.

No Add-Type, native helper, registry/account APIs, real job/process, installer or network execution.
The native interop correction still needs a separately authorized isolated Windows probe.
"""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASE = '273a807072997bcdd66e6401c69d6baf7fddbca3'
ROOT = None
PWSH = None

def digest(data):
    return hashlib.sha256(data).hexdigest()

DRIVER = r'''
param([string]$Common,[string]$Scenario,[string]$Evidence)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Common,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Syntax error'}
$definitions=@()
foreach($name in @('Get-FailureMetadata','Close-LifecycleJob','Write-Record')) {
 $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
 if($nodes.Count -ne 1){throw 'Ambiguous pure function'}
 $definitions+=$nodes[0].Extent.Text
}
$pure=Join-Path $Evidence 'pure.ps1'
[IO.File]::WriteAllText($pure,($definitions -join "`n"))
. $pure
function Check([bool]$Ok,[string]$Reason){if(-not $Ok){throw $Reason}}
$canary='PRIVATE_SECRET_CREDENTIAL C:\private\profile\key='+('X'*10000)
function Fake-Error {
 try {throw [Management.Automation.MethodInvocationException]::new($canary,[ArgumentNullException]::new($canary))}
 catch {return $_}
}
$output=$null
if($Scenario -eq 'diagnostics') {
 $errorRecord=Fake-Error
 $parameter=(Get-Command Get-FailureMetadata).Parameters['Stage']
 $stages=@(($parameter.Attributes|Where-Object {$_ -is [Management.Automation.ValidateSetAttribute]}).ValidValues)
 Check ($stages.Count -ge 25) 'Missing phases'
 $reports=@()
 foreach($stage in $stages){
  $r=Get-FailureMetadata $stage $errorRecord;$encoded=$r|ConvertTo-Json -Depth 8 -Compress
  Check ($r.stage -ceq $stage -and $r.exceptions.Count -le 3) 'Phase/chain mismatch'
  Check ([Text.Encoding]::UTF8.GetByteCount($encoded) -le 2048) 'Diagnostic too large'
  Check (-not $encoded.Contains('PRIVATE_SECRET') -and -not $encoded.Contains('C:\private') -and -not $encoded.Contains('XXXXX')) 'Message leak'
  Check ($r.exceptions[0].class -ceq 'MethodInvocationException') 'Outer class'
  Check ($r.exceptions[1].class -ceq 'ArgumentNullException') 'Inner class'
  Check ($null -eq $r.source -or $r.source -cin @('guest.ps1','common.ps1','controller.ps1')) 'Path leak'
  $reports+=,$r
 }
 $rejected=$false;try{Get-FailureMetadata 'unapproved-secret-stage' $errorRecord|Out-Null}catch{$rejected=$true}
 Check $rejected 'Unknown stage accepted'
 $output=@{passed=$true;phases=$stages.Count;reports=$reports}
} elseif($Scenario -eq 'diagnostic-types') {
 try{throw [FormatException]::new($canary)}catch{$r=Get-FailureMetadata 'operation-job-drain' $_}
 Check ($r.exceptions[0].class -ceq 'OtherException') 'Unknown exception name disclosed'
 try{throw [ComponentModel.Win32Exception]::new(5,$canary)}catch{$native=Get-FailureMetadata 'cleanup-active-before' $_}
 Check ($native.exceptions[0].native_error -eq 5) 'Native code missing'
 $inner=[Exception]::new($canary)
 for($i=0;$i -lt 8;$i++){$inner=[InvalidOperationException]::new($canary,$inner)}
 try{throw $inner}catch{$bounded=Get-FailureMetadata 'operation-job-drain' $_}
 Check ($bounded.exceptions.Count -eq 3) 'Unbounded chain'
 $output=@{passed=$true;unknown=$r;native=$native;bounded=$bounded}
} elseif($Scenario -eq 'publication-failure') {
 $path=Join-Path $Evidence 'existing.json'
 [IO.File]::WriteAllText($path,'original-sentinel')
 $failed=$false;try{Write-Record $path @{status='failed';diagnostic=(Get-FailureMetadata 'operation-job-drain' (Fake-Error))}}catch{$failed=$true}
 Check ($failed -and [IO.File]::ReadAllText($path) -ceq 'original-sentinel') 'Evidence overwrite/false success'
 $output=@{passed=$true;publication_rejected=$failed;original_preserved=$true}
} else {
 $job=[pscustomobject]@{activeCalls=0;disposeCalls=0;nativeCloses=0;terminateCalls=0;closed=$false;activeCount=0;mode=$Scenario}
 if($Scenario -in @('active','terminate-fails','survivors')){$job.activeCount=2}
 $job|Add-Member ScriptMethod Active {
  $this.activeCalls++
  if($this.closed){throw [ObjectDisposedException]::new('synthetic')}
  if($this.mode -eq 'query-before-fails' -or ($this.mode -eq 'query-after-fails' -and $this.activeCalls -eq 2)){throw [InvalidOperationException]::new('private-canary')}
  return $this.activeCount
 }
 $job|Add-Member ScriptMethod Terminate {
  $this.terminateCalls++
  if($this.mode -eq 'terminate-fails'){throw [InvalidOperationException]::new('private-canary')}
  if($this.mode -ne 'survivors'){$this.activeCount=0}
 }
 $job|Add-Member ScriptMethod Dispose {
  $this.disposeCalls++
  if($this.closed){return}
  $this.closed=$true;$this.nativeCloses++
  if($this.mode -eq 'dispose-fails'){throw [InvalidOperationException]::new('possibly consumed')}
 }
 $r=if($Scenario -eq 'absent'){Close-LifecycleJob $null}else{Close-LifecycleJob $job}
 if($Scenario -eq 'absent') {Check (-not $r.present -and -not $r.disposal_attempted -and $null -eq $r.active_after) 'Absent owner claimed'}
 else {
  Check ($job.nativeCloses -eq 1 -and $job.disposeCalls -eq 1 -and $r.disposal_attempted) 'Exactly-once cleanup attempt'
  if($Scenario -in @('empty','active','repeat')){Check (-not $r.uncertain -and $r.active_after -eq 0 -and $r.disposal_succeeded) 'Ordinary cleanup failed'}
  else {Check $r.uncertain 'Cleanup uncertainty accepted'}
  if($Scenario -eq 'query-before-fails'){Check ($null -eq $r.active_before -and $null -eq $r.active_after -and -not $r.termination_attempted) 'Invented observation'}
  if($Scenario -eq 'dispose-fails'){Check (-not $r.disposal_succeeded) 'Close failure accepted'}
  if($Scenario -eq 'active'){Check ($r.termination_attempted -and $r.termination_succeeded -and $r.active_before -eq 2) 'Termination not distinguished'}
  if($Scenario -eq 'repeat'){$again=Close-LifecycleJob $job;Check ($job.nativeCloses -eq 1 -and $again.uncertain) 'Repeated cleanup consumed twice'}
 }
 $output=@{passed=$true;record=$r;fake_native_closes=$job.nativeCloses;fake_dispose_calls=$job.disposeCalls}
}
$output|ConvertTo-Json -Depth 12 -Compress
'''

class OfflineFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((HERE/'execution-plan.json').read_bytes())
        cls.raw = (HERE/'execution-capsule.zip').read_bytes()
        with zipfile.ZipFile(io.BytesIO(cls.raw)) as z:
            cls.members = {i.filename:z.read(i) for i in z.infolist()}
        cls.common = cls.members['harness/common.ps1'].decode('utf-8-sig')
        cls.guest = cls.members['harness/guest.ps1'].decode('utf-8-sig')
        cls.controller = cls.members['harness/controller.ps1'].decode('utf-8-sig')
        cls.common_path = ROOT/'common.ps1';cls.common_path.write_text(cls.common,encoding='utf-8',newline='\n')
        cls.driver = ROOT/'pure-functions.ps1';cls.driver.write_text(DRIVER,encoding='utf-8',newline='\n')
        spec=importlib.util.spec_from_file_location('reviewed_bootstrap',HERE/'prepare_hosted.py')
        cls.bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.bootstrap)

    def probe(self, scenario):
        target=ROOT/scenario;target.mkdir()
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',str(self.driver),'-Common',str(self.common_path),'-Scenario',scenario,'-Evidence',str(target)],capture_output=True,timeout=20)
        (target/'stdout.txt').write_bytes(result.stdout);(target/'stderr.txt').write_bytes(result.stderr)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace'))
        record=json.loads(result.stdout);self.assertTrue(record['passed']);return record

    def test_native_current_query_uses_raw_null_without_adopting_handle(self):
        self.assertIn('QueryCurrentJobInformation(IntPtr.Zero,1,out a',self.common)
        self.assertIn('EntryPoint="QueryInformationJobObject",SetLastError=true',self.common)
        self.assertIn('QueryCurrentJobInformation(IntPtr j,int kind,out Accounting info,uint size,IntPtr length)',self.common)
        self.assertNotIn('QueryInformationJobObject(null',self.common)
        self.assertIn('QueryInformationJobObject(SafeFileHandle j',self.common)
        self.assertIn('QueryInformationJobObject(handle,1,out a',self.common)
        self.assertIn('handle.SetHandleAsInvalid(); Check(CloseHandle(raw))',self.common)

    def test_stage_diagnostics_all_fixed_phases(self): self.probe('diagnostics')
    def test_exception_redaction_and_native_codes(self): self.probe('diagnostic-types')
    def test_exclusive_diagnostic_publication_failure(self): self.probe('publication-failure')
    def test_empty_job_cleanup(self): self.probe('empty')
    def test_active_job_termination_observed(self): self.probe('active')
    def test_unacquired_job_not_claimed(self): self.probe('absent')
    def test_initial_query_failure_still_disposes(self): self.probe('query-before-fails')
    def test_final_query_failure_still_disposes(self): self.probe('query-after-fails')
    def test_termination_failure_still_disposes(self): self.probe('terminate-fails')
    def test_close_failure_is_uncertain_without_retry(self): self.probe('dispose-fails')
    def test_survivors_never_report_empty(self): self.probe('survivors')
    def test_repeat_cleanup_has_no_second_fake_native_close(self): self.probe('repeat')

    def test_failure_stage_precedes_suspected_call_and_receipt(self):
        self.assertLess(self.guest.index("$script:failureStage='operation-job-drain'"),self.guest.index('[LifecycleNative]::CurrentActive()'))
        self.assertLess(self.guest.index('[LifecycleNative]::CurrentActive()'),self.guest.index('$records.Add('))
        self.assertIn('operation_cleanup_failure=$operationCleanupFailure',self.guest)
        self.assertIn('if($null -eq $operationFailure)',self.guest)
        self.assertIn('exit 91',self.guest)

    def test_cleanup_evidence_precedes_completion_and_failure_stays_failure(self):
        c=self.controller
        self.assertLess(c.index('$cleanup=Close-LifecycleJob $job;$job=$null'),c.index('control\\cleanup.json'))
        self.assertLess(c.index('control\\cleanup.json'),c.index('control\\done.json'))
        self.assertIn("$passed=$false;$failure='CleanupUncertain'",c)
        self.assertIn('if(-not $passed){exit 1}',c)
        self.assertIn('[Diagnostics.Stopwatch]::GetTimestamp() -ge $deadline){$passed=$false}',c)

    def test_capsule_and_every_member_authenticate(self):
        files,dirs=self.bootstrap.verify_capsule(HERE/'execution-capsule.zip',self.plan)
        self.assertEqual((len(files),len(dirs)),(40,46))
        self.assertEqual(digest(self.raw),self.plan['capsule']['sha256'])
        self.assertEqual(len(self.raw),self.plan['capsule']['size'])

    def test_changed_member_is_rejected_even_with_new_archive_hash(self):
        p=ROOT/'corrupted-capsule.zip'
        with zipfile.ZipFile(p,'w') as z:
            for name,data in self.members.items():z.writestr(name,data+b'changed' if name=='harness/guest.ps1' else data)
        plan=copy.deepcopy(self.plan);data=p.read_bytes();plan['capsule'].update(size=len(data),sha256=digest(data))
        with self.assertRaises(ValueError):self.bootstrap.verify_capsule(p,plan)

    def test_hosted_authorization_controls_reject_drift(self):
        env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',GITHUB_REPOSITORY='ryuutatsuo23-max/WFCompanion',GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',COMPUTERNAME='synthetic-hosted',GITHUB_RUN_ID='123',GITHUB_SHA='a'*40,GITHUB_REF='refs/heads/'+self.plan['proposed_branch'],GITHUB_WORKFLOW_REF='ryuutatsuo23-max/WFCompanion/.github/workflows/windows-build.yml@refs/heads/'+self.plan['proposed_branch'])
        auth=self.bootstrap.hosted_binding(env,self.plan,'fresh',self.plan['plan_id'],'a'*40)
        self.assertEqual(auth['run_id'],'123')
        for key,value in [('GITHUB_RUN_ATTEMPT','2'),('RUNNER_ENVIRONMENT','self-hosted'),('COMPUTERNAME','RYUU'),('GITHUB_SHA','b'*40),('GITHUB_EVENT_NAME','push'),('GITHUB_REF','refs/heads/main')]:
            with self.subTest(key=key):
                bad=dict(env);bad[key]=value
                with self.assertRaises(ValueError):self.bootstrap.hosted_binding(bad,self.plan,'fresh',self.plan['plan_id'],'a'*40)

    def test_isolation_limits_installer_pins_and_watchdog_unchanged(self):
        env=dict(os.environ,GIT_ALLOW_PROTOCOL='file',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='NUL')
        def old(path):return subprocess.check_output(['git','-C',str(REPO),'show',BASE+':tools/installer-lifecycle/'+path],env=env,timeout=30)
        prior=json.loads(old('execution-plan.json'))
        normalized=copy.deepcopy(self.plan)
        for key in ('capsule','capsule_manifest_sha256','runtime_sources'):normalized[key]=prior[key]
        self.assertEqual(normalized,prior)
        with zipfile.ZipFile(io.BytesIO(old('execution-capsule.zip'))) as z:
            for name in ('harness/host_guard.ps1','harness/collect.ps1','artifact-lock.json','payload-manifest.json'):
                self.assertEqual(self.members[name],z.read(name))
            for name in z.namelist():
                if name.startswith('fixtures/'):self.assertEqual(self.members[name],z.read(name))
        for marker in ('$deadline=$start+1200L*$frequency','-ge 15',"'S-1-5-32-545'",'$job.Assign($child)',"$psi.Environment.Clear()"):
            self.assertIn(marker,self.controller)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence-root',required=True,type=Path);p.add_argument('--pwsh',required=True)
    args,rest=p.parse_known_args();ROOT=args.evidence_root.resolve();PWSH=args.pwsh
    if ROOT.exists() or ROOT.is_relative_to(REPO):raise SystemExit('Fresh external test evidence required')
    ROOT.mkdir(parents=False)
    unittest.main(argv=[sys.argv[0],*rest],verbosity=2)
