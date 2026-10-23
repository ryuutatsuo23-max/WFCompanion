"""Stage pinned local archives into a new directory. Never installs or publishes."""
from pathlib import Path,PurePosixPath
import argparse
import hashlib
import json
import zipfile


def stage(archives,output,manifest=None):
    manifest=Path(manifest) if manifest else Path(__file__).with_name('addon_packages.json')
    raw=manifest.read_bytes();document=json.loads(raw)
    if document.get('schema')!=1:raise ValueError('Unsupported package manifest.')
    contents={}
    for addon,info in document['packages'].items():
        archive=Path(archives[addon])
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=info['archive_sha256']:raise ValueError('Archive digest differs: '+addon)
        with zipfile.ZipFile(archive) as source:
            expected={addon+'/'+name:digest for name,digest in info['files'].items()}
            names=source.namelist()
            if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('Archive allowlist differs.')
            for entry in source.infolist():
                name=PurePosixPath(entry.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe archive member.')
                data=source.read(entry)
                if hashlib.sha256(data).hexdigest()!=expected[entry.filename]:raise ValueError('Member digest differs.')
                contents[name]=data
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    for name,data in contents.items():
        target=output/'addons'/Path(*name.parts)
        if not target.resolve().is_relative_to(output):raise ValueError('Invalid staging target.')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (output/'addon_packages.json').write_bytes(raw)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-archive',required=True,type=Path)
    parser.add_argument('--storage-archive',required=True,type=Path)
    parser.add_argument('--professions-archive',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    archives={'WFCore':args.core_archive,'WFStorage':args.storage_archive}
    if args.professions_archive:archives['WFProfessions']=args.professions_archive
    print(stage(archives,args.output))
