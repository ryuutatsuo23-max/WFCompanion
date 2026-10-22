"""Build an exact-base, changed-file Inno installer from two public app bundles.

No binary deltas, deletions or runtime changes: use the full installer for those.
Run with --base APP --target APP --from-version X --to-version Y --output DIR
--iscc ISCC.exe. Output is local only and must accompany the full release assets.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import shutil
import ast


def inventory(root):
    root=Path(root).resolve(strict=True);result={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or p.is_junction():raise ValueError('Linked bundle entries are unsupported')
        if p.is_file():
            name=p.relative_to(root).as_posix()
            if not re.fullmatch(r'[A-Za-z0-9_./ +\-]+',name) or '..' in name.split('/'):
                raise ValueError('Unsupported bundle path: '+name)
            result[name]=dict(size=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    if 'WFCompanion.exe' not in result:raise ValueError('Not a companion bundle')
    return result


def compare(base,target):
    a,b=inventory(base),inventory(target)
    changed=[n for n in b if a.get(n)!=b[n]]
    # Keep file ownership and uninstaller coverage unchanged in this first format.
    if a.keys()!=b.keys():raise ValueError('Added or removed files require the full installer')
    runtime=[n for n in changed if n!='WFCompanion.exe' and not n.startswith('_internal/payload/') and n!='_internal/base_library.zip']
    if runtime:raise ValueError('Runtime changes require the full installer: '+str(runtime))
    return a,b,changed


def build(base,target,old,new,output,iscc):
    for value in (old,new):
        if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value):raise ValueError('Invalid version')
    if tuple(map(int,new.split('.')))<=tuple(map(int,old.split('.'))):raise ValueError('Target must be newer')
    base=Path(base).resolve(strict=True);target=Path(target).resolve(strict=True)
    for bundle,expected in ((base,old),(target,new)):
        tree=ast.parse((bundle/'_internal/payload/tools/qt_preview/release_updates.py').read_text(encoding='utf-8-sig'))
        actual=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets))
        if actual!=expected:raise ValueError('Bundle version does not match requested patch version')
    a,b,changed=compare(base,target)
    if not changed:raise ValueError('No changed files')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    asset='WFCompanion-patch-from-'+old+'.exe'
    payload=output/'payload';payload.mkdir()
    for n in changed:
        dest=payload/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target/n,dest)
    from public_branding import render
    branding=output/'branding';render(branding)
    lines=['function PrepareToInstall(var NeedsRestart: Boolean): String;',
           'begin', "  Result := 'This installation differs from the required base. Use the full installer.';",
           "  if not UnlinkedTree(ExpandConstant('{app}')) then Exit;", '  try']
    for n,row in a.items():
        path='{app}\\'+n.replace('/','\\')
        lines.append("    if (not FileExists(ExpandConstant('"+path+"'))) or (CompareText(GetSHA256OfFile(ExpandConstant('"+path+"')), '"+row['sha256']+"') <> 0) then Exit;")
    lines += ["    Result := '';",'  except','  end;','end;']
    source=output/'patch.iss';source.write_text('\n'.join(lines),encoding='utf-8')
    subprocess.run([str(iscc),'/DPublicBuild=1','/DPayload='+str(payload),'/DVersion='+new,'/DOutput='+str(output),'/DBranding='+str(branding),'/DPatchName='+asset[:-4],'/DPatchValidation='+str(source),str(Path(__file__).with_name('installer.iss'))],check=True,stdout=subprocess.DEVNULL)
    exe=output/asset;digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    (output/(asset+'.sha256')).write_text(digest+'  '+asset+'\n')
    metadata=dict(schema=1,base=old,target=new,asset=asset,sha256=digest,size=exe.stat().st_size,files=a)
    (output/('WFCompanion-patch-from-'+old+'.json')).write_text(json.dumps(metadata,sort_keys=True),encoding='utf-8')
    report=dict(base=old,target=new,files=len(a),changed_files=len(changed),changed_bytes=sum(b[n]['size'] for n in changed),total_bytes=sum(x['size'] for x in b.values()),patch_bytes=exe.stat().st_size,changed=changed)
    (output/'comparison.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for arg in ('base','target','from-version','to-version','output','iscc'):p.add_argument('--'+arg,required=True)
    args=p.parse_args();print(json.dumps(build(args.base,args.target,args.from_version,args.to_version,args.output,args.iscc),indent=2))
