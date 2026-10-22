"""Read addon saves and persist linked observations separately from manual data."""
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Signal
from game_data_review import discover,read,sync_status
import os


def retained_notice(prepared):
    """An unavailable source does not erase observations or imply a fresh sync."""
    store,links,_candidate,_decisions,signatures=prepared
    available={os.path.normcase(source) for source in signatures}
    unavailable={e['profile'] for e in links.records['links'] if e['identity']['source'] not in available}
    locations=sum(profile in unavailable for profile,_scope in store.ledger)
    if not locations:return ''
    return (f'{locations} saved location(s) retained for offline use · linked addon save unavailable. '
            'Counts are from the last saved snapshots; no new updates from that source.')


class SaveWatcher:
    def __init__(self):self.cache={}

    def poll(self):
        paths=discover();current={};errors=0
        for path in paths:
            key=str(path)
            try:
                stat=path.stat();signature=(stat.st_mtime_ns,stat.st_size)
                previous=self.cache.get(key)
                if previous and previous[0]==signature:current[key]=previous;continue
                observations=read(path)
                current[key]=(signature,observations)
            except (OSError,ValueError):errors+=1
        self.cache=current  # Removed/failed sources never retain a success badge.
        characters=sum(len({o.owner for o in records}) for _,records in current.values())
        observations=sum(len(records) for _,records in current.values())
        if not paths:return 'No saved addon data yet · checking automatically.'
        if errors:return f'{errors} saved file(s) could not be checked · open review for details.'
        if not observations:return 'Saved files found · no readable bags or bank observations yet.'
        incomplete=sum(sync_status(o)[0].startswith('Needs fuller scan') for _,records in current.values() for o in records)
        status=f'{incomplete} observation(s) need a fuller scan' if incomplete else 'sync setup still required'
        return f'Saved game data available · {characters} character record(s) in {len(current)} file(s) · {status}. Existing counts kept.'


class Result(QObject):
    ready=Signal(str,object)


class PollJob(QRunnable):
    def __init__(self,watcher,directory=None,profiles=()):
        super().__init__();self.watcher=watcher;self.directory=directory;self.profiles=profiles;self.result=Result()

    def run(self):
        prepared=None
        try:
            message=self.watcher.poll()
            if self.directory is not None:
                from observed_inventory import prepare
                prepared=prepare(self.directory,self.watcher.cache,self.profiles)
        except Exception:message='Could not update saved addon observations · existing records kept; check source files and links.'
        self.result.ready.emit(message,prepared)


class GameDataMonitor(QObject):
    status=Signal(str)

    def __init__(self,host):
        super().__init__(host);self.host=host;self.watcher=SaveWatcher();self.busy=False
        self.enabled=True;self.timer=QTimer(self);self.timer.setInterval(30000)
        self.timer.timeout.connect(self.poll);self.timer.start()
        QTimer.singleShot(0,self.poll)

    def set_enabled(self,enabled):
        self.enabled=enabled
        if enabled:self.timer.start();self.poll()
        else:self.timer.stop();self.status.emit('Automatic checks paused · manual review is still available.')

    def poll(self):
        if not self.enabled or self.busy or getattr(self.host,'testing',False):return
        self.busy=True;self.expected_profiles=self.host.data.profile_bytes
        self.job=PollJob(self.watcher,self.host.data.directory,{p.id for p in self.host.data.saved_profiles})
        self.job.result.ready.connect(self.receive);QThreadPool.globalInstance().start(self.job)

    def receive(self,message,prepared=None):
        self.busy=False
        if not self.enabled:return
        if prepared is not None:
            try:
                from observed_inventory import apply_prepared
                changed,decisions=apply_prepared(self.host.data,prepared,self.expected_profiles)
                if changed:
                    message='Saved addon observations updated automatically. Manual inventory and unfinished edits are unchanged.'
                    self.host.stock_changed()
                elif any(d.status=='duplicate' for d in decisions):message='Linked addon observations are up to date. Manual inventory stays separate.'
                if any(d.status in ('blocked','conflict') for d in decisions):message+=' Some locations need review; previous observations kept.'
                retained=retained_notice(prepared)
                if retained:message=(message+' ' if decisions else '')+retained
            except (ValueError,OSError):message='Addon update paused · records or links changed, or an applied inventory edit needs saving. Previous observations kept.'
        self.status.emit(message)
