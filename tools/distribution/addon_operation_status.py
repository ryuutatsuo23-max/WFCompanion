"""Service-only durable outcome evidence, not a replacement/recovery engine.

Record writes and explicit resolution of older attempts require the client lock.
This attempt's marker is cleared only after successful lock exit; surviving
reporting evidence gates other service installs.
No recorded path selects a filesystem destination. Partial publications are kept.
"""
import json
import os
import re
import uuid

import install_addons as engine

NAME = 'operation-status.json'
STAGE = '.operation-status.stage'
KNOWN = 'operation-status-known.json'
LIMIT = 2 * engine.MAX_TRANSACTION_BYTES + 16384
REPORT_LIMIT = 4096
MAX_REPORTS = 64
MAX_ROOT_ENTRIES = 4096
REPORT_PREFIX = '.operation-reporting'
REPORT_NAME = re.compile(r'\.operation-reporting-([a-f0-9]{32})(?:-([a-f0-9]{32}))?\.json')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


class StatusError(ValueError):
    def __init__(self):
        super().__init__('Durable addon operation evidence requires review; preserve it.')


class OperationStatus:
    def __init__(self, client, root, identity, policy):
        self.client, self.root, self.identity = client, root, identity
        self.policy = engine._byte_description(policy)
        self.root_identity = engine._recovery_root_identity(root) if root.exists() else None
        self.document = None
        self.raw, self.stamp = self.read(NAME)
        self.known, self.known_stamp = self.read(KNOWN)
        self.attempt = None
        self._reporting_users = None
        expected_known = encode(dict(schema=1,client=identity,policy=self.policy,root=self.root_identity))
        if (self.known is not None and self.known != expected_known) or ((self.raw is None) != (self.known is None)):
            raise StatusError()
        if self.read(STAGE)[0] is not None:
            raise StatusError()
        if self.raw is not None:
            value = engine._transaction_json(self.raw, LIMIT)
            engine._fields(value, ('schema', 'client', 'root', 'policy', 'transaction', 'transaction_digest',
                                   'receipt', 'outcome', 'phase'))
            if (type(value['schema']) is not int or value['schema'] != 1
                    or value['client'] != identity or value['root'] != self.root_identity
                    or value['policy'] != self.policy
                    or value['phase'] not in ('active', 'terminal', 'finalized')
                    or value['outcome'] not in (None, 'installation', 'rollback')
                    or (value['phase'] == 'active') != (value['outcome'] is None)):
                raise StatusError()
            record = engine.validate_transaction(encode(value['transaction']), client, root)
            engine._size_hash(value['transaction_digest'])
            if engine._byte_description(encode(record)) != value['transaction_digest']:
                raise StatusError()
            if not isinstance(value['receipt'], str):raise StatusError()
            receipt = value['receipt'].encode('utf-8')
            if engine._byte_description(receipt) != {k: record['receipt'][k] for k in ('size', 'sha256')}:
                raise StatusError()
            engine._completion_receipt({'record': record, '_bindings': [(None, None, receipt)]}, client)
            self.document = value
        # Enumerate even without status: an orphan marker is evidence, not first use.
        self.fences = self._reporting_evidence()

    @property
    def fence(self):
        """Any unresolved attempt, including the previous transaction-only format."""
        return self.fences or None

    def read(self, name):
        return engine._read_preparation_file(self.root / name, self.client.parent,
                                             missing=True, max_bytes=LIMIT)

    def fence_path(self):
        if self.attempt is None or self.document is None:raise StatusError()
        return self.root / (REPORT_PREFIX + '-' + self.document['transaction']['id'] + '-' + self.attempt + '.json')

    def _reporting_evidence(self):
        """Bounded, read-only discovery; never follow directory entries or recorded paths."""
        if self.root_identity is None:
            if self.root.exists():raise StatusError()
            return {}
        if engine._recovery_root_identity(self.root) != self.root_identity:raise StatusError()
        found = {}
        with os.scandir(self.root) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_ROOT_ENTRIES:raise StatusError()
                if not entry.name.casefold().startswith(REPORT_PREFIX):continue
                match = REPORT_NAME.fullmatch(entry.name)
                if match is None or len(found) >= MAX_REPORTS:raise StatusError()
                transaction, attempt = match.groups()
                if any(uuid.UUID(hex=value).version != 4 for value in (transaction, attempt) if value):
                    raise StatusError()
                raw, stamp = engine._read_preparation_file(self.root / entry.name, self.client.parent,
                                                           max_bytes=REPORT_LIMIT)
                if self.document is None or transaction != self.document['transaction']['id']:
                    raise StatusError()
                expected = dict(client=self.identity, policy=self.policy,
                                transaction=self.document['transaction_digest'])
                if attempt is not None:expected.update(schema=2, attempt=attempt)
                # Exact old/new fields and byte bindings; filenames alone prove nothing.
                if raw != encode(expected):raise StatusError()
                found[entry.name] = (raw, stamp)
        if engine._recovery_root_identity(self.root) != self.root_identity:raise StatusError()
        return found

    def check(self):
        if (engine.client_identity(self.client) != self.identity
                or engine._recovery_root_identity(self.root) != self.root_identity
                or self.read(NAME) != (self.raw, self.stamp)
                or self.read(KNOWN) != (self.known, self.known_stamp)
                or self._reporting_evidence() != self.fences):
            raise StatusError()

    def match(self, pending):
        """A record can corroborate evidence, never replace missing originals."""
        if self.document is not None and pending['state'] == 'valid':
            if encode(pending['record']) != encode(self.document['transaction']):
                raise StatusError()

    def write(self, value):
        self.check()
        raw = encode(value)
        if len(raw) > LIMIT:
            raise StatusError()
        if self.read(STAGE)[0] is not None:
            raise StatusError()
        artifacts = []
        engine._write_preparation_artifact(self.root / STAGE, self.client.parent, raw, artifacts, [])
        self.check()
        if self.read(STAGE) != (raw, artifacts[-1]['verified_stamp']):
            raise StatusError()
        if self.raw is None:
            engine._publish_pending_file(self.root / STAGE, self.root / NAME, self.client.parent)
        else:
            engine.safe_target(self.root / NAME, self.client.parent, for_write=True)
            os.replace(self.root / STAGE, self.root / NAME)
        observed, stamp = self.read(NAME)
        if observed != raw or stamp != artifacts[-1]['verified_stamp']:
            raise StatusError()
        self.raw, self.stamp, self.document = observed, stamp, value

    def begin(self, pending):
        if pending['state'] != 'valid':
            raise StatusError()
        # This also supports an explicit recovery of pre-status transactions.
        if self.document is not None and self.document['transaction']['id'] == pending['record']['id']:
            self.match(pending)
            self.check()
            self._ensure_fence()
            return
        if self.document is not None:
            if self.fence is not None or self.document['phase'] != 'finalized':
                raise StatusError()
            # New installation has already independently checked the prior state.
        value = dict(schema=1, client=self.identity, root=self.root_identity, policy=self.policy,
                     transaction=pending['record'], transaction_digest=engine._byte_description(encode(pending['record'])),
                     receipt=engine._completion_receipt(pending, self.client).decode('utf-8'),
                     outcome=None, phase='active')
        self.check()
        if self.known is None:
            known=encode(dict(schema=1,client=self.identity,policy=self.policy,root=self.root_identity))
            artifacts=[]
            engine._write_preparation_artifact(self.root/KNOWN,self.client.parent,known,artifacts,[])
            self.known,self.known_stamp=known,artifacts[-1]['verified_stamp']
        self.write(value)
        self._ensure_fence()

    def _ensure_fence(self):
        self.check()
        if self.attempt is not None:return
        if len(self.fences) >= MAX_REPORTS:raise StatusError()
        self.attempt = uuid.uuid4().hex
        fence = encode(dict(schema=2, attempt=self.attempt, client=self.identity, policy=self.policy,
                            transaction=self.document['transaction_digest']))
        artifacts = []
        engine._write_preparation_artifact(self.fence_path(), self.client.parent, fence, artifacts, [])
        self.fences[self.fence_path().name] = (fence, artifacts[-1]['verified_stamp'])
        self.check()

    def terminal(self, pending, outcome):
        self.match(pending)
        if self.document is None or self.fence is None:
            raise StatusError()
        engine._verify_terminal_destinations(pending, outcome)
        self.write(dict(self.document, phase='terminal', outcome=outcome))

    def verify_terminal(self, users):
        """Read-only corroboration after retirement, never a restore authority."""
        if self.document is None or self.document['outcome'] is None:
            raise StatusError()
        self.check()
        record = self.document['transaction']
        outcome = self.document['outcome']
        for item in record['files']:
            raw, _ = engine._read_preparation_file(self.client / 'Interface/AddOns' / item['path'],
                                                  self.client, missing=True)
            expected = item['replacement'] if outcome == 'installation' else item['original']
            if (None if raw is None else engine._byte_description(raw)) != expected:
                raise StatusError()
        # Retained originals survive retirement. Reuse their authoritative verifier.
        receipt = self.document['receipt'].encode('utf-8')
        retained = engine.RetainedUserBackup(record, receipt, self.client, self.root, users)
        retained.verify(require_receipt=outcome == 'installation')
        self.check()

    def finished(self, outcome, users, *, verify_configuration):
        if self.document is None or self.document['outcome'] != outcome:
            raise StatusError()
        if engine._inspect_pending_locked(self.client, self.root, locked_identity=self.identity)['state'] != 'none':
            raise StatusError()
        self.verify_terminal(users)
        # Markerless completion retries also need their own reporting ownership.
        self._ensure_fence()
        self.write(dict(self.document, phase='finalized'))
        # Publication is preparation, not authorization to retire evidence. It can
        # fail late or allow external changes after the earlier terminal check.
        self._retire_previous_reports(users, verify_configuration)
        self._reporting_users = users

    def _retire_previous_reports(self, users, verify_configuration):
        """Under the client lock, resolve captured older attempts after verified completion.

        Our independently verified marker remains throughout. Ambiguous removals
        fail closed; no inspection or post-release cleanup removes another attempt.
        """
        def verify():
            # The service owns configuration authority; reuse its validators
            # while the same canonical client mutex is still held.
            verify_configuration()
            if engine._inspect_pending_locked(self.client, self.root, locked_identity=self.identity)['state'] != 'none':
                raise StatusError()
            self.verify_cleanup()
            self.verify_terminal(users)

        own = self.fence_path().name
        verify()  # Required even when there are no older markers to remove.
        for name in tuple(self.fences):
            if name == own:continue
            self.check()
            raw, stamp = self.fences[name]
            path = self.root / name
            if engine._read_preparation_file(path, self.client.parent, max_bytes=REPORT_LIMIT) != (raw, stamp):
                raise StatusError()
            verify()
            path.unlink()
            del self.fences[name]
            self.check()

    def verify_cleanup(self):
        """Permit a reporting retry only when owned artifacts are already gone.

        Never remove orphan evidence here. Unexpected/residual files need review.
        """
        self.check()
        record = self.document['transaction']
        for item in record['files']:
            if engine._read_preparation_file(self.client / 'Interface/AddOns' / item['stage'],
                                              self.client, missing=True)[0] is not None:
                raise StatusError()
        directory = self.root / ('prepare-' + record['id'])
        engine.safe_target(directory, self.root)
        if directory.exists():
            engine._transaction_directory(directory)
            # Completed installation preserves its receipt directory. All other
            # entries, including empty backup directories, are residual evidence.
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name != 'manifest.json':raise StatusError()
            raw, _ = engine._read_preparation_file(directory / 'manifest.json', self.root)
            if raw != self.document['receipt'].encode('utf-8'):raise StatusError()

    def reported(self):
        """Only after successful lock release; no addon/evidence mutation here.

        Remove only this attempt's marker. A retry may hold the client mutex now;
        its distinct marker must survive and prevent a clean current-state result.
        """
        if (self.document is None or self.document['phase'] != 'finalized'
                or self.attempt is None or self._reporting_users is None):
            raise StatusError()
        self.check()
        if self.read(STAGE)[0] is not None:
            raise StatusError()
        if engine._read_preparation_file(self.fence_path(), self.client.parent, max_bytes=REPORT_LIMIT) != self.fences[self.fence_path().name]:
            raise StatusError()
        # Lock exit and service postchecks may take time. This read-only content
        # check does not authorize mutation/recovery, and retains our marker on
        # failure. The final check-to-unlink filesystem race remains unavoidable.
        self.verify_terminal(self._reporting_users)
        self.fence_path().unlink()
        del self.fences[self.fence_path().name]
        # Recheck after unlink too: a newer retry may have started after check().
        self.check()
        if self.fences:raise StatusError()
