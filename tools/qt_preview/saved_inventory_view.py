"""Direct, read-only linked snapshots. Never writes the planning observation ledger."""
from character_links import LinkStore
from game_data_review import read


def linked_snapshots(directory,profile):
    links=[entry for entry in LinkStore(directory).records['links'] if entry['profile']==profile]
    if len(links)>1:raise ValueError('Multiple source links require review.')
    if not links:return None
    identity=links[0]['identity'];result={}
    observations=read(identity['source'])
    for observation in observations:
        if observation.owner!=identity['guid']:continue
        if observation.schema==2 and (observation.realm!=identity['realm'] or
                observation.client_version!=identity['version'] or observation.interface!=identity['interface']):
            raise ValueError('Saved character identity differs from its link.')
        # Retain the last completed observation separately from a failed newer attempt.
        existing=result.get(observation.scope)
        if existing is not None and not existing['interrupted']:continue
        result[observation.scope]=dict(identity=identity,rows=observation.rows,
            finished=observation.finished_at,coverage=observation.coverage,
            unknown=observation.unknown_slots,interrupted=observation.interrupted,
            direct=True,names=dict(observation.item_names))
    return result
