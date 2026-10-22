"""Detached Windows update handoff; wait for clean exit, verify, update, restart.

Uses Inno's supported silent maintenance path, scoped to the running installation
and companion component. Never force-kills the app or changes game addon files.
The helper runs outside the application directory so its files can be replaced.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath __CONFIG__ -Raw | ConvertFrom-Json
try {
    $parentProcess = Get-Process -Id $config.pid -ErrorAction SilentlyContinue
    Set-Content -LiteralPath $config.ready -Value 'ready'
    if ($parentProcess -and -not $parentProcess.WaitForExit(120000)) { throw 'Companion did not close. Nothing was updated.' }
    $hashAlgorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($config.installer)
    try { $actualHash = [System.BitConverter]::ToString($hashAlgorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hashAlgorithm.Dispose() }
    if ($actualHash -ne $config.sha256) { throw 'Update checksum changed. Nothing was installed.' }
    $arguments = @('/SILENT','/SP-','/SUPPRESSMSGBOXES','/NORESTART','/RESTARTEXITCODE=3010','/NOCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS','/TYPE=companion','/COMPONENTS=companion',('/DIR="' + $config.directory + '"'),('/LOG="' + $config.log + '"'))
    $installerProcess = Start-Process -FilePath $config.installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Normal
    if ($installerProcess.ExitCode -ne 0) { throw ('Update did not complete (code ' + $installerProcess.ExitCode + '). See ' + $config.log) }
    Start-Process -FilePath $config.executable -WorkingDirectory $config.directory -WindowStyle Normal
} catch {
    $_.Exception.Message | Set-Content -LiteralPath $config.error
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'WFCompanion update needs attention') | Out-Null
}
'''


def start_update(installer, digest, directory):
    """Return a ready helper. Caller must close cleanly or terminate this helper."""
    if sys.platform != 'win32' or not getattr(sys,'frozen',False):
        raise ValueError('Update and restart is available in the installed companion.')
    executable=Path(sys.executable).resolve(strict=True)
    if executable.name.lower()!='wfcompanion.exe' or not (executable.parent/'unins000.exe').is_file():
        raise ValueError('Installation not recognized. Use the downloaded installer manually.')
    installer=Path(installer).resolve(strict=True)
    if hashlib.sha256(installer.read_bytes()).hexdigest()!=digest:
        raise ValueError('Downloaded installer changed; download it again.')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    token=uuid.uuid4().hex
    ready=directory/(token+'.ready');config_path=directory/(token+'.json')
    config=dict(pid=os.getpid(),installer=str(installer),sha256=digest,
                executable=str(executable),directory=str(executable.parent),
                ready=str(ready),log=str(directory/'install.log'),error=str(directory/'update-error.txt'))
    config_path.write_text(json.dumps(config),encoding='utf-8')
    command=SCRIPT.replace('__CONFIG__',"'"+str(config_path).replace("'","''")+"'")
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    environment=dict(os.environ)
    # Do not inherit PowerShell 7's module paths into the Windows 5.1 helper.
    environment['PSModulePath']=str(powershell.parent/'Modules')
    process=subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-Command',command],
                             creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True,env=environment)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if ready.exists():return process
        if process.poll() is not None:break
        time.sleep(.05)
    process.terminate()
    raise OSError('Could not start the update helper. The companion remains open.')
