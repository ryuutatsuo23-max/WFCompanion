"""Stable GitHub release checks and bounded, checksum-verified downloads.

No installer is executed here. HTTPS and release checksums provide transport and
integrity checks; they are not a substitute for a publisher signing certificate.
"""
from pathlib import Path
import hashlib
import json
import re
import urllib.request
from urllib.parse import urlsplit
from urllib.error import HTTPError

VERSION='0.1.20'
REPOSITORY='ryuutatsuo23-max/WFCompanion'
ASSET='WFCompanion-Setup.exe'
API=f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_INSTALLER=800*1024*1024


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value):
        raise ValueError('Unsupported stable version.')
    return tuple(map(int,value.removeprefix('v').split('.')))


def candidate(document,current=VERSION):
    if not isinstance(document,dict):raise ValueError('Invalid release response.')
    if document.get('draft') is not False or document.get('prerelease') is not False:return None
    tag=document.get('tag_name');new=version(tag)
    if new<=version(current):return None
    assets=document.get('assets')
    if not isinstance(assets,list):raise ValueError('Release assets missing.')
    selected={}
    for name in (ASSET,ASSET+'.sha256'):
        matching=[a for a in assets if isinstance(a,dict) and a.get('name')==name]
        if len(matching)!=1:raise ValueError('Expected one '+name)
        item=matching[0];url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
        if item.get('browser_download_url')!=url:raise ValueError('Unexpected download location.')
        size=item.get('size')
        if type(size) is not int or not 0<size<=(MAX_INSTALLER if name==ASSET else 512):raise ValueError('Unexpected release size.')
        selected[name]=(url,size)
    result=dict(version=tag,installer=selected[ASSET],checksum=selected[ASSET+'.sha256'])
    prefix='WFCompanion-patch-from-'+current.removeprefix('v')
    optional={}
    for suffix,limit in (('.json',2_000_000),('.exe',MAX_INSTALLER),('.exe.sha256',512)):
        name=prefix+suffix;matches=[a for a in assets if isinstance(a,dict) and a.get('name')==name]
        url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
        if len(matches)==1 and matches[0].get('browser_download_url')==url and type(matches[0].get('size')) is int and 0<matches[0]['size']<=limit:
            optional[suffix]=(url,matches[0]['size'])
    if len(optional)==3:result['patch']=dict(base=current.removeprefix('v'),asset=prefix+'.exe',metadata=optional['.json'],installer=optional['.exe'],checksum=optional['.exe.sha256'])
    return result


def request(url):
    class SecureRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            validate_url(newurl)
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    validate_url(url)
    return urllib.request.build_opener(SecureRedirect()).open(urllib.request.Request(url,headers={'User-Agent':'WFCompanion/'+VERSION,'Accept':'application/vnd.github+json'}),timeout=20)


def validate_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com') or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Unexpected update transport.')


def check():
    try:
        with request(API) as stream:raw=stream.read(2_000_001)
    except HTTPError as exc:
        if exc.code==404:return None
        raise
    if len(raw)>2_000_000:raise ValueError('Release response too large.')
    return candidate(json.loads(raw))


def download(release,directory,progress=None):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    # Revalidate the descriptor so callers cannot redirect this downloader.
    tag=release['version'];version(tag)
    asset=release.get('asset',ASSET)
    if asset!=ASSET and not re.fullmatch(r'WFCompanion-patch-from-(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\.exe',asset):raise ValueError('Invalid update asset')
    for name,field in ((asset,'installer'),(asset+'.sha256','checksum')):
        if release[field][0]!=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}':raise ValueError('Unexpected download location.')
    with request(release['checksum'][0]) as stream:raw=stream.read(513)
    match=re.fullmatch(rb'([0-9a-fA-F]{64})[ \t]+\*?'+re.escape(asset.encode())+rb'\s*',raw)
    if not match:raise ValueError('Invalid installer checksum.')
    expected=match[1].decode().lower()
    if release.get('sha256',expected)!=expected:raise ValueError('Patch checksum disagreement')
    target=directory/(tag+'-'+asset)
    partial=target.with_suffix('.part');digest=hashlib.sha256();size=0
    try:
        if progress:progress(0,release['installer'][1])
        with request(release['installer'][0]) as stream,partial.open('wb') as output:
            while block:=stream.read(1024*1024):
                size+=len(block)
                if size>MAX_INSTALLER or size>release['installer'][1]:raise ValueError('Installer exceeds declared size.')
                digest.update(block);output.write(block)
                if progress:progress(size,release['installer'][1])
        if size!=release['installer'][1] or digest.hexdigest()!=expected:raise ValueError('Installer checksum/size mismatch.')
        partial.replace(target)
        return target
    finally:
        if partial.exists():partial.unlink()
