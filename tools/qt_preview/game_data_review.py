"""WFCore review only: no Lua execution, identity mapping or inventory writes."""
from pathlib import Path
from datetime import datetime
from core_observations import decode
from probe_report import ReportError,CLIENT

MAX_BYTES=64*1024*1024


def installation_status(roots=None):
    """Read folder markers only; presence does not establish client compatibility."""
    roots=roots if roots is not None else (CLIENT,CLIENT.parent/'_classic_beta_')
    found=[];unreadable=False
    for root in roots:
        root=Path(root)
        try:
            (root/'Wow.exe').stat()
            addons=root/'Interface'/'AddOns'
            installed=[]
            for name in ('WFCore','WFStorage'):
                try:(addons/name/(name+'.toc')).stat();installed.append(name)
                except FileNotFoundError:pass
            state='Core + Storage files found' if len(installed)==2 else 'Storage missing' if installed==['WFCore'] else 'Core missing' if installed==['WFStorage'] else 'Core + Storage files not found'
            found.append(f'{root.name}: {state}')
        except FileNotFoundError:pass
        except OSError:unreadable=True
    if found:return 'Game folders — '+'; '.join(found)+'. File presence only; enabled addons and game access are not checked.'+(' Another folder could not be checked.' if unreadable else '')
    if unreadable:return 'Game folders could not be checked. Offline planning is still available.'
    return 'No game found in the usual folders. You can plan offline, or choose a saved addon file in Review game data.'


def discover():
    roots=(CLIENT,CLIENT.parent/'_classic_beta_')
    return sorted({p.resolve() for root in roots for p in
                   (root/'WTF'/'Account').glob('*/SavedVariables/WFCore.lua')},key=str)


def read(path):
    path=Path(path);before=path.stat()
    if before.st_size>MAX_BYTES:raise ReportError('Saved file exceeds 64 MiB.')
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    after=path.stat()
    if (before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size):
        raise ReportError('The game changed this file while reading. Check again after /reload.')
    return decode(raw)


def observed_time(value):
    if value is None:return 'Time not recorded'
    try:return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError,OSError,OverflowError):return 'Time unavailable'


def sync_status(observation):
    """Explain evidence gaps without granting permission to overwrite inventory."""
    if observation is None:
        return 'Not checked · keep previous records', 'No saved observation. This location is not confirmed empty.'
    if observation.schema==2 and observation.coverage=='complete' and not observation.interrupted:
        return ('Complete saved scan · sync not enabled',
                f'{observation.observed_slots} occupied and {observation.empty_slots} confirmed empty slots; no unresolved slots. '
                'The saved evidence passed structural checks. Live validation, character linking, freshness and conflict rules still gate automatic replacement. '
                'Bags and bank were scanned separately, not as one transaction.')
    reasons=[]
    if observation.interrupted:reasons.append('This is an incomplete attempt; it does not replace the earlier saved scan.')
    if observation.coverage!='attempted':reasons.append('Not all declared slots were checked.')
    if observation.unknown_slots:
        reasons.append(f'{observation.unknown_slots} slot(s) are unresolved; they may be empty or unreadable.')
    if observation.finished_at is None or observation.started_at is None:
        reasons.append('The scan has no complete observation time.')
    elif observation.finished_at<observation.started_at:
        reasons.append('The observation times are inconsistent.')
    if reasons:
        return 'Needs fuller scan · keep previous records',' '.join(reasons)+' Observed item quantities are subtotals only.'
    return ('Needs sync setup · review only',
            'No unresolved slots were reported. Automatic sync still needs verified location coverage, '
            'a character link and conflict checks. Missing items must not be cleared on this evidence alone.')


def locations(observations):
    """Keep latest and interrupted attempts separate; never choose by name."""
    owners={o.owner:o.label for o in observations}
    result=[]
    for owner,name in sorted(owners.items(),key=lambda x:(x[1],x[0])):
        for scope in ('bags','bank'):
            found=[o for o in observations if o.owner==owner and o.scope==scope]
            if not found:result.append((owner,name,scope,None))
            else:
                for observation in found:result.append((owner,name,scope,observation))
    return result
