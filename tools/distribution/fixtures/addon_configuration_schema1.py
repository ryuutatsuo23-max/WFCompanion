"""Explicit, additive installation configuration; no production callers yet.

Selection records are configuration, not signatures or permission to migrate.
Policy paths never select a destination. A configured path is accepted only with
its recorded directory identities and the independently verified client policy.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re

import install_addons as engine
from addon_installation_service import AddonInstallationService, POLICY_NAME, POLICY_STAGE, POLICY_LIMIT


LIMIT = 16384


class ConfigurationError(ValueError):
    def __init__(self, code='unavailable'):
        self.code = code
        super().__init__({
            'unavailable': 'Addon installation configuration is unavailable or unsafe.',
            'conflict': 'Addon backup configuration conflicts with established evidence. Preserve it.',
            'interrupted': 'Addon configuration publication is unfinished. Preserve it for review.',
            'choice_required': 'Confirm the existing addon backup location before continuing.',
            'pending': 'Resolve the pending addon transaction before provisioning configuration.',
        }[code])


@dataclass(frozen=True)
class ConfigurationSelection:
    status: str
    mode: str
    state: Path = field(repr=False)


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or len(str(path)) > 4096 or str(path).startswith('\\\\'):
        raise ValueError('Unsupported configuration directory.')
    for part in path.parts[1:]:
        if (part in ('.', '..') or part.endswith(('.', ' ')) or ':' in part
                or '~' in part or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', part, re.I)):
            raise ValueError('Unsupported configuration directory.')
    if os.path.abspath(path) != str(path):
        raise ValueError('Configuration path must be normalized.')
    return path


class InstallationConfiguration:
    """All future callers use one per-user registry, not their window data folder.

    local_app_data is an explicit test/host configuration input. Production callers
    will omit it. Construction and lookup perform no provisioning.
    """
    def __init__(self, local_app_data=None):
        value = local_app_data if local_app_data is not None else os.environ.get('LOCALAPPDATA', '')
        self.anchor = _absolute(value)
        self.registry = self.anchor / 'WoWForever' / 'AddonInstallation'
        self.standard = self.anchor / 'WoWForever' / 'Companion'

    def _paths(self, identity):
        # Path-keyed so replacing a canonical client cannot silently select a new
        # record. The full filesystem identity is independently bound inside it.
        key = hashlib.sha256(identity['path'].encode('utf-8')).hexdigest()
        return self.registry / (key + '.json'), self.registry / (key + '.stage')

    def _registry_identity(self):
        engine._transaction_directory(self.anchor)
        engine._check_windows_link_support(self.anchor)
        engine.safe_target(self.registry, self.anchor)
        if self.registry.exists():
            return engine._recovery_root_identity(self.registry)
        # Permission errors are not interpreted as absence.
        parent = self.registry.parent if self.registry.parent.exists() else self.anchor
        engine._transaction_directory(parent)
        with os.scandir(parent):
            pass
        return None

    def _record(self, identity):
        root_identity = self._registry_identity()
        target, stage = self._paths(identity)
        staged, _ = engine._read_preparation_file(stage, self.anchor, missing=True, max_bytes=LIMIT)
        publishing, _ = engine._read_preparation_file(self.registry / (target.stem + '.publish'), self.anchor,
                                                     missing=True, max_bytes=LIMIT)
        if staged is not None or publishing is not None:
            raise ConfigurationError('interrupted')
        raw, stamp = engine._read_preparation_file(target, self.anchor, missing=True, max_bytes=LIMIT)
        if self._registry_identity() != root_identity:
            raise ConfigurationError('conflict')
        return raw, stamp, root_identity

    def _validate(self, raw, client, identity, registry_identity):
        record = engine._transaction_json(raw, LIMIT)
        engine._fields(record, ('schema', 'mode', 'client', 'anchor', 'registry', 'state', 'users'))
        if type(record['schema']) is not int or record['schema'] != 1 or record['mode'] not in ('default', 'custom'):
            raise ConfigurationError('conflict')
        for key in ('client', 'anchor', 'registry', 'state', 'users'):
            engine._fields(record[key], ('path', 'device', 'inode'))
            if (not isinstance(record[key]['path'], str) or
                    any(type(record[key][k]) is not int or record[key][k] <= 0 for k in ('device', 'inode'))):
                raise ConfigurationError('conflict')
        if (record['client'] != identity or record['anchor'] != engine._recovery_root_identity(self.anchor)
                or record['registry'] != registry_identity):
            raise ConfigurationError('conflict')
        engine._fields(record['state'], ('path', 'device', 'inode'))
        state = _absolute(record['state']['path'])
        if record['mode'] == 'default' and os.path.normcase(str(state)) != os.path.normcase(str(self.standard)):
            raise ConfigurationError('conflict')
        recovery, _ = engine._production_recovery_location(client, identity)
        selected = AddonInstallationService(state)
        _, policy = selected._configuration(client, recovery, identity)
        expected = engine._transaction_json(policy, POLICY_LIMIT)
        if record['state'] != expected['state'] or record['users'] != expected['users']:
            raise ConfigurationError('conflict')
        selected._policy(client, recovery, identity)  # Never creates or replaces policy.
        return ConfigurationSelection('available', record['mode'], state)

    def _lookup_locked(self, client, identity):
        raw, stamp, registry_identity = self._record(identity)
        if raw is None:
            recovery, _ = engine._production_recovery_location(client, identity)
            # No path is selected from an old policy. The caller must explicitly
            # supply and verify the old location when adopting it into the registry.
            for name in (POLICY_NAME, POLICY_STAGE):
                existing, _ = engine._read_preparation_file(recovery / name, client.parent,
                                                            missing=True, max_bytes=POLICY_LIMIT)
                if existing is not None:
                    raise ConfigurationError('choice_required')
            if engine._inspect_production_pending_locked(client, identity)['state'] != 'none':
                raise ConfigurationError('pending')
            return ConfigurationSelection('unconfigured', 'default', self.standard)
        selection = self._validate(raw, client, identity, registry_identity)
        if self._record(identity) != (raw, stamp, registry_identity) or engine.client_identity(client) != identity:
            raise ConfigurationError('conflict')
        return selection

    def lookup(self, client):
        """Read-only; unconfigured is a proposal, never permission to install."""
        try:
            with engine._transaction_client_lock(client) as (canonical, identity):
                return self._lookup_locked(canonical, identity)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError() from exc

    def provision(self, client, *, custom_state=None, expected_client_identity=None):
        """Intentional first-use setup or explicit adoption; never a migration.

        A durable exclusive intent stage precedes state-directory creation. Any
        interrupted outcome preserves that stage and blocks future provisioning.
        No cleanup guesses ownership or deletes existing configuration/backups.
        """
        try:
            with engine._transaction_client_lock(client) as (canonical, identity):
                if expected_client_identity is not None and identity != expected_client_identity:
                    raise ConfigurationError('conflict')
                anchor_identity = engine._recovery_root_identity(self.anchor)
                mode = 'custom' if custom_state is not None else 'default'
                state = _absolute(custom_state) if custom_state is not None else self.standard
                raw, _, registry_identity = self._record(identity)
                if raw is not None:
                    selected = self._lookup_locked(canonical, identity)
                    if os.path.normcase(str(state)) != os.path.normcase(str(selected.state)):
                        raise ConfigurationError('conflict')
                    return selected
                recovery, recovery_identity = engine._production_recovery_location(canonical, identity)
                pending = engine._inspect_production_pending_locked(canonical, identity)
                previous, _ = engine._read_preparation_file(recovery / POLICY_NAME, canonical.parent,
                                                            missing=True, max_bytes=POLICY_LIMIT)
                stage_policy, _ = engine._read_preparation_file(recovery / POLICY_STAGE, canonical.parent,
                                                                missing=True, max_bytes=POLICY_LIMIT)
                if stage_policy is not None:
                    raise ConfigurationError('interrupted')
                if pending['state'] != 'none' and not (pending['state'] == 'valid' and previous is not None):
                    raise ConfigurationError('pending')
                selected = AddonInstallationService(state)
                if previous is not None:
                    # Established policy means missing directories are damage, not
                    # first use. Validate before making even a registry artifact.
                    selected._policy(canonical, recovery, identity)
                for protected in (canonical, recovery, self.registry):
                    if state.is_relative_to(protected) or protected.is_relative_to(state):
                        raise ConfigurationError('conflict')
                engine.safe_target(state / 'AddonBackups', Path(state.anchor))
                ancestor = state
                while not ancestor.exists():
                    ancestor = ancestor.parent
                ancestor_identity = engine._recovery_root_identity(ancestor)
                if engine._recovery_root_identity(self.anchor) != anchor_identity:
                    raise ConfigurationError('conflict')
                engine._preparation_mkdir(self.registry, self.anchor, [])
                created_identity = self._registry_identity()
                if registry_identity is not None and created_identity != registry_identity:
                    raise ConfigurationError('conflict')
                registry_identity = created_identity
                target, intent = self._paths(identity)
                intent_raw = json.dumps(dict(schema=1, client=identity, mode=mode, state=str(state)), sort_keys=True).encode()
                if len(intent_raw)>LIMIT:raise ConfigurationError('conflict')
                engine._write_preparation_artifact(intent, self.anchor, intent_raw, [], [])
                intent_observed = engine._read_preparation_file(intent, self.anchor, max_bytes=LIMIT)
                if (engine.client_identity(canonical) != identity
                        or engine._recovery_root_identity(self.anchor) != anchor_identity
                        or engine._recovery_root_identity(ancestor) != ancestor_identity
                        or engine._production_recovery_location(canonical, identity) != (recovery, recovery_identity)):
                    raise ConfigurationError('conflict')
                if previous is None:
                    engine._preparation_mkdir(state / 'AddonBackups', ancestor, [])
                _, policy = selected._configuration(canonical, recovery, identity)
                selected._policy(canonical, recovery, identity, create=True)
                bindings = engine._transaction_json(policy, POLICY_LIMIT)
                record = dict(schema=1, mode=mode, client=identity,
                              anchor=anchor_identity, registry=registry_identity,
                              state=bindings['state'], users=bindings['users'])
                record_raw = json.dumps(record, sort_keys=True).encode()
                if len(record_raw)>LIMIT:raise ConfigurationError('conflict')
                # Keep the intent separate: it remains a fail-closed witness until
                # the final configuration has been published AND reverified.
                publication = self.registry / (target.stem + '.publish')
                artifacts = []
                engine._write_preparation_artifact(publication, self.anchor, record_raw, artifacts, [])
                self._validate(record_raw, canonical, identity, registry_identity)
                if (engine._read_preparation_file(publication, self.anchor) != (record_raw, artifacts[-1]['verified_stamp'])
                        or engine._read_preparation_file(intent, self.anchor) != intent_observed
                        or self._registry_identity() != registry_identity):
                    raise ConfigurationError('conflict')
                engine._publish_pending_file(publication, target, self.anchor)
                published = engine._read_preparation_file(target, self.anchor, max_bytes=LIMIT)
                if published != (record_raw, artifacts[-1]['verified_stamp']):
                    raise ConfigurationError('conflict')
                self._validate(published[0], canonical, identity, registry_identity)
                if engine._read_preparation_file(intent, self.anchor) != intent_observed:
                    raise ConfigurationError('conflict')
                engine.safe_target(intent, self.anchor, for_write=True)
                intent.unlink()
                return self._lookup_locked(canonical, identity)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError() from exc
