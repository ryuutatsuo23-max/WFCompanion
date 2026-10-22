"""Build an allowlisted local or public installer; never publish or copy saves."""
from pathlib import Path
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from audit_payload import audit,ROOT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--iscc',type=Path);parser.add_argument('--public',action='store_true');args=parser.parse_args()
    compiler=args.iscc.resolve(strict=True) if args.iscc else None
    stage=ROOT/'build'/('installer-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    stage.mkdir(parents=True,exist_ok=False);payload=stage/'payload'
    manifest=audit();files=manifest['files']
    branding_source=ROOT/'tools/distribution/assets'
    if args.public:
        from public_branding import render
        branding_source=stage/'branding';render(branding_source)
    for row in files:
        source=ROOT/row['path'];target=payload/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Source changed during staging.')
        target.write_bytes(raw)
    # Local testing includes the existing catalogue. Public redistribution review
    # remains a separate release gate; no command here publishes this build.
    source=ROOT/'tools/offline_preview/data/item_sample.json'
    target=payload/'tools/offline_preview/data/item_sample.json';target.parent.mkdir(parents=True)
    if args.public:
        target.write_text(json.dumps(dict(version=1,revision='public-empty-v1',items=[],coverage_note='No bundled catalogue. Your captured items and manual plans are kept separately.')))
    else:shutil.copy2(source,target)
    shutil.copy2(ROOT/'tools/distribution/install_addons.py',payload/'install_addons.py')
    # Only the reviewed, hash-pinned theme files; never copy the whole private art tree.
    art_manifest=json.loads((ROOT/'tools/distribution/theme_assets.json').read_text())
    for row in ([] if args.public else art_manifest['files']):
        relative=Path(row['path'])
        art_root=(ROOT/'tools/offline_preview/theme_art').resolve()
        source=art_root/relative
        if relative.is_absolute() or '..' in relative.parts or not source.resolve().is_relative_to(art_root):
            raise ValueError('Invalid theme asset path')
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Theme asset changed: '+str(relative))
        target=payload/'tools/offline_preview/theme_art'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    branding=payload/'branding';branding.mkdir()
    for name in ('forever.ico','SOURCES.md'):
        shutil.copy2(branding_source/name,branding/name)
    notices=payload/'notices';notices.mkdir()
    for package in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6'):
        dist=importlib.metadata.distribution(package)
        for item in dist.files or ():
            if 'license' in str(item).lower() or 'copying' in str(item).lower():
                original=Path(dist.locate_file(item))
                if original.is_file():
                    dest=notices/package/Path(str(item)).name;dest.parent.mkdir(exist_ok=True);shutil.copy2(original,dest)
    if args.public:
        public_notices=ROOT/'tools/distribution/public_notices'
        for notice in public_notices.iterdir():
            if notice.is_file():shutil.copy2(notice,notices/notice.name)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,notices/'Python-LICENSE.txt')
    (payload/'BUILD-NOTICE.txt').write_text('Local test build. Not published. Includes explicitly selected theme artwork, textures and fonts for user testing. Artwork, catalogue and font redistribution review remains required before public release. Personal saves are excluded.\n')
    if args.public:
        (payload/'BUILD-NOTICE.txt').write_text('WFCompanion public build. Original branding; system font fallback. No Blizzard artwork, font files, bulk third-party catalogue or personal saves bundled. Qt/PySide are dynamically linked and replaceable; see notices.\n')
    locals={p.stem for p in payload.rglob('*.py')};imports={'PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets','PySide6.QtMultimedia','sqlite3','ctypes','urllib.request','urllib.error','ssl','json','csv'}
    for source in payload.rglob('*.py'):
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig'))):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and node.module else []
            for name in names:
                if name.split('.')[0] not in locals:imports.add(name)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','WFCompanion','--distpath',str(stage/'dist'),'--workpath',str(stage/'work'),'--specpath',str(stage),'--add-data',str(payload)+';payload','--paths',str(payload)]
    if args.public:
        imports.discard('PySide6.QtMultimedia')
        for name in ('QtMultimedia','QtMultimediaWidgets','QtQml','QtQuick','QtPdf','QtVirtualKeyboard'):
            command += ['--exclude-module','PySide6.'+name]
    for name in sorted(imports):command+=['--hidden-import',name]
    command.append(str(ROOT/'tools/distribution/launcher.py'))
    command[3:3]=['--icon',str(branding_source/'forever.ico')]
    # Do not accidentally collect unrelated DLLs from developer tools on PATH
    # (for example Poppler's incompatible ICU). Windows supplies Qt's ICU API.
    environment=dict(os.environ)
    environment['PATH']=os.pathsep.join((str(Path(sys.executable).parent),sys.base_prefix,str(Path(os.environ['SystemRoot'])/'System32'),os.environ['SystemRoot']))
    subprocess.run(command,check=True,env=environment)
    if args.public:
        # Remove optional plugins that pull unrelated Qt modules into QtGui.
        qtroot=(stage/'dist/WFCompanion/_internal/PySide6').resolve(strict=True)
        patterns=('plugins/platforminputcontexts/*','plugins/imageformats/qpdf.dll','plugins/multimedia/*','Qt6Qml*.dll','Qt6Quick*.dll','Qt6Pdf*.dll','Qt6VirtualKeyboard*.dll','Qt6Multimedia*.dll','avcodec-*.dll','avformat-*.dll','avutil-*.dll','swresample-*.dll','swscale-*.dll')
        for pattern in patterns:
            for unused in qtroot.glob(pattern):
                if unused.is_file() and unused.resolve().is_relative_to(qtroot):unused.unlink()
    output=ROOT/'dist'/stage.name;output.mkdir(parents=True,exist_ok=False)
    if compiler is None:
        (output/'source-audit.json').write_text(json.dumps(manifest,indent=2))
        print(json.dumps({'application':str(stage/'dist/WFCompanion/WFCompanion.exe'),'status':'bundle built; run ISCC with Payload, Version and Output definitions to compile installer'}))
        return
    version_module=ast.parse((ROOT/'tools/qt_preview/release_updates.py').read_text())
    version=next(ast.literal_eval(n.value) for n in version_module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets))
    definitions=['/DPublicBuild=1'] if args.public else []
    subprocess.run([str(compiler),*definitions,'/DPayload='+str(stage/'dist/WFCompanion'),'/DVersion='+version,'/DOutput='+str(output),'/DBranding='+str(branding_source),str(ROOT/'tools/distribution/installer.iss')],check=True)
    installer=output/'WFCompanion-Setup.exe';digest=hashlib.sha256(installer.read_bytes()).hexdigest()
    (output/'WFCompanion-Setup.exe.sha256').write_text(digest+'  WFCompanion-Setup.exe\n')
    manifest['stage']='public-build' if args.public else 'local-test-build';manifest['payload']=[dict(path=str(p.relative_to(payload)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(payload.rglob('*')) if p.is_file()]
    (output/'build-manifest.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'installer':str(installer),'application':str(stage/'dist/WFCompanion/WFCompanion.exe'),'sha256':digest}))


if __name__=='__main__':main()
