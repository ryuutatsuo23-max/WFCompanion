"""Pure merge rules for validated observations. No persistence or UI side effects.

The candidate ledger is separate from manual InventoryBook records. The observation
store applies candidates after rechecking source, link and profile conflicts.
"""
from copy import deepcopy
from dataclasses import dataclass
from character_links import key


@dataclass(frozen=True)
class Decision:
    owner: str
    scope: str
    profile: str | None
    status: str
    reason: str


def plan_sync(observations,identities,links,ledger,*,profiles,manual_locations=(),dirty_locations=(),now,allowed_builds=None):
    """Only complete validated schema-2 latest records may propose a replacement.

ledger keys are (profile ID, scope); records store identity, started/finished epoch
and exact item-ID totals. Callers must supply explicitly saved links and conflict
sets; names never participate. Missing scopes leave the candidate ledger unchanged.
"""
    candidate=deepcopy(ledger);decisions=[];groups={}
    for obs in observations:groups.setdefault((obs.owner,obs.scope),[]).append(obs)
    for (owner,scope),group in groups.items():
        profile=None
        def result(status,reason):decisions.append(Decision(owner,scope,profile,status,reason))
        value=identities.get(owner)
        if value is None or value.get('guid')!=owner:
            result('blocked','Source identity unavailable.');continue
        matches=[link for link in links if key(link['identity'])==key(value)]
        if len(matches)!=1:
            result('blocked','One explicitly saved character link is required.');continue
        profile=matches[0]['profile'];destination=(profile,scope)
        if profile not in profiles or sum(link['profile']==profile for link in links)!=1:
            result('blocked','Destination profile is missing or has conflicting links.');continue
        latest=[o for o in group if not o.interrupted]
        if len(latest)!=1:
            result('blocked','One latest snapshot is required for this location.');continue
        obs=latest[0]
        if allowed_builds is not None and obs.build not in allowed_builds:
            result('blocked','This client build has not been validated for automatic observations.');continue
        if obs.schema!=2 or obs.coverage!='complete' or obs.scan_status!='completed' or obs.unknown_slots:
            result('blocked','Only complete schema-2 scans without unknown slots can update counts.');continue
        if (obs.realm,obs.client_version,obs.interface)!=(value['realm'],value['version'],value['interface']) or not obs.realm:
            result('blocked','Snapshot-time realm/client differs from the reviewed source identity.');continue
        if obs.started_at is None or obs.finished_at is None or obs.started_at>obs.finished_at or obs.finished_at>now+300:
            result('blocked','Missing, inconsistent or future observation time.');continue
        if any(o.interrupted and (o.started_at is None or o.started_at>=obs.started_at) for o in group):
            result('blocked','A newer incomplete attempt exists; retain previous counts.');continue
        if destination in dirty_locations or destination in manual_locations:
            result('conflict','Manual or unsaved applied inventory changes need review.');continue
        prior=ledger.get(destination)
        if prior:
            if key(prior['identity'])!=key(value):
                result('conflict','Existing observation belongs to a different source.');continue
            if obs.finished_at<prior['finished']:
                result('older','Older observation ignored.');continue
            if obs.finished_at==prior['finished']:
                if tuple(obs.rows)==tuple(prior['rows']) and obs.build==prior['build']:
                    result('duplicate','Already recorded; no update.')
                else:result('conflict','Different contents share the same observation time.')
                continue
            if obs.started_at<prior['finished']:
                result('conflict','Overlapping scan times need review.');continue
        candidate[destination]=dict(identity=deepcopy(value),started=obs.started_at,finished=obs.finished_at,
                                    rows=tuple(obs.rows),build=obs.build)
        result('update','Replace only this linked location with its complete observed totals.')
    return candidate,tuple(decisions)
