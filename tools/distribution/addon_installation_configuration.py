"""Explicit, additive installation configuration for the Addons page and adapters.

Selection records are configuration, not signatures or permission to migrate.
Policy paths never select a destination. A configured path is accepted only with
its recorded directory identities and the independently verified client policy.
"""
from dataclasses import dataclass, field, replace
import hashlib
import json
import os
from pathlib import Path
import re

import install_addons as engine
from addon_installation_service import AddonInstallationService, POLICY_NAME, POLICY_STAGE, POLICY_LIMIT
from addon_installation_context import current_windows_context, validate_context, UserContextError
from addon_operation_status import NAME, KNOWN, STAGE, REPORT_PREFIX, MAX_ROOT_ENTRIES


LIMIT = 16384


class ConfigurationError(ValueError):
    def __init__(self, code='unavailable'):
        self.code = code
        super().__init__({
            'unavailable': 'Addon installation configuration is unavailable or unsafe.',
            'conflict': 'Addon backup configuration conflicts with established evidence. Preserve it.',
            'interrupted': 'Addon configuration publication is unfinished. Preserve it for review.',
            'choice_required': 'Confirm the existing addon backup location before continuing.',
            'pending': 'Addon transaction or durable operation evidence requires review before configuration can be provisioned.',
            'missing_established': 'An established addon backup directory is missing. Preserve evidence; do not recreate it.',
            'user_unverified': 'Windows user context is unverified. Use the intended account without elevation; setup handoff is unsupported.',
            'user_conflict': 'Windows user context conflicts with the confirmed configuration. No other account was selected.',
            'identity_unverified': 'Legacy addon configuration has no verified historical account binding. Separate reviewed reauthorization is required; preserve existing evidence.',
        }[code])


@dataclass(frozen=True)
class ConfigurationSelection:
    status: str
    mode: str
    state: Path = field(repr=False)


@dataclass(frozen=True)
class AdoptionCandidate:
    """Read-only consent snapshot; never authorizes an installation or recovery."""
    client: Path = field(repr=False)
    state: Path = field(repr=False)
    bindings: tuple = field(repr=False)
    unresolved: bool = False
    requested: Path | None = field(default=None, repr=False, compare=False)
    authority: object = field(default=None, repr=False)


@dataclass(frozen=True)
class ConfigurationAuthority:
    """Consent binding, not an authentication credential or a recorded path authority."""
    context: object = field(repr=False)
    anchor: tuple = field(repr=False)


@dataclass(frozen=True)
class ConfigurationAdvice:
    status: str
    message: str
    # Availability is configuration advice, never installation success.
    ok: bool = False


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
    """Callers use one per-user registry, not their window data folder.

    Production callers omit local_app_data and use the native current-user query.
    Synthetic tests inject context_provider as well as their temporary root. No
    environment variable or UI switch can replace the native context provider.
    Construction queries OS identity only; lookup performs no provisioning.
    """
    def __init__(self, local_app_data=None, *, context_provider=None, intended_sid=None,
                 launch_context='current_user'):
        self._context_provider = context_provider or current_windows_context
        self._intended_sid, self._launch_context = intended_sid, launch_context
        self._environment_selected = local_app_data is None
        self._anchor_identity = None
        try:
            self._context = self._read_context()
            value = local_app_data if local_app_data is not None else self._context.local_app_data
            self.anchor = _absolute(value)
            if os.path.normcase(str(self.anchor)) != os.path.normcase(str(self._context.local_app_data)):
                raise ConfigurationError('user_conflict')
            self._environment_check()
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError('user_unverified') from exc
        self.registry = self.anchor / 'WoWForever' / 'AddonInstallation'
        self.standard = self.anchor / 'WoWForever' / 'Companion'

    def _read_context(self):
        try:
            return validate_context(self._context_provider(), intended_sid=self._intended_sid,
                                    launch_context=self._launch_context)
        except UserContextError as exc:
            raise ConfigurationError(exc.code) from exc
        except Exception as exc:
            raise ConfigurationError('user_unverified') from exc

    def _environment_check(self):
        value = os.environ.get('LOCALAPPDATA')
        if self._environment_selected and value is not None:
            if os.path.normcase(str(_absolute(value))) != os.path.normcase(str(self.anchor)):
                raise ConfigurationError('user_conflict')

    def _check_context(self):
        current = self._read_context()
        if current != self._context:
            raise ConfigurationError('user_conflict')
        self._environment_check()
        observed = engine._recovery_root_identity(self.anchor)
        if self._anchor_identity is not None and observed != self._anchor_identity:
            raise ConfigurationError('conflict')
        self._anchor_identity = observed
        return observed

    def _paths(self, identity):
        # Path-keyed so replacing a canonical client cannot silently select a new
        # record. The full filesystem identity is independently bound inside it.
        key = hashlib.sha256(identity['path'].encode('utf-8')).hexdigest()
        return self.registry / (key + '.json'), self.registry / (key + '.stage')

    def capture_authority(self):
        identity = self._check_context()
        return ConfigurationAuthority(self._context, tuple(identity[k] for k in ('path', 'device', 'inode')))

    def verify_authority(self, expected):
        current = self.capture_authority()
        if not isinstance(expected, ConfigurationAuthority):
            raise ConfigurationError('user_unverified')
        if expected != current:
            raise ConfigurationError('user_conflict')

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
        self._check_context()
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
        self._check_context()
        return raw, stamp, root_identity

    def _validate(self, raw, client, identity, registry_identity):
        self._check_context()
        record = engine._transaction_json(raw, LIMIT)
        schema = record.get('schema')
        fields = ('schema', 'mode', 'client', 'anchor', 'registry', 'state', 'users')
        engine._fields(record, fields + (('user_sid',) if schema == 2 else ()))
        if type(schema) is not int or schema not in (1, 2) or record['mode'] not in ('default', 'custom'):
            raise ConfigurationError('conflict')
        if schema == 2 and record['user_sid'] != self._context.sid:
            raise ConfigurationError('user_conflict')
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
        self._established_directories(state)
        if record['mode'] == 'default' and os.path.normcase(str(state)) != os.path.normcase(str(self.standard)):
            raise ConfigurationError('conflict')
        recovery, _ = engine._production_recovery_location(client, identity)
        selected = AddonInstallationService(state)
        _, policy = selected._configuration(client, recovery, identity)
        expected = engine._transaction_json(policy, POLICY_LIMIT)
        if record['state'] != expected['state'] or record['users'] != expected['users']:
            raise ConfigurationError('conflict')
        selected._policy(client, recovery, identity)  # Never creates or replaces policy.
        self._check_context()
        if schema == 1:
            # Directory identity proves consistency, not historical account consent.
            # All configured operations share this gate, including recovery and
            # adoption. Preserve the readable record; never upgrade it implicitly.
            raise ConfigurationError('identity_unverified')
        return ConfigurationSelection('available', record['mode'], state)

    @staticmethod
    def _established_directories(state):
        for path in (state, state / 'AddonBackups'):
            # stat errors other than absence must not turn into first use.
            try:
                path.lstat()
            except FileNotFoundError as exc:
                raise ConfigurationError('missing_established') from exc
            engine._transaction_directory(path)

    @staticmethod
    def _no_orphan_status(recovery):
        # With no policy there is no independently authorized backup location.
        # Detect witnesses without trusting/parsing their paths or repairing them.
        if not recovery.exists():
            return
        root_identity = engine._recovery_root_identity(recovery)
        with os.scandir(recovery) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_ROOT_ENTRIES:
                    raise ConfigurationError('pending')
                name = entry.name.casefold()
                if name in (NAME, KNOWN, STAGE) or name.startswith(REPORT_PREFIX):
                    raise ConfigurationError('pending')
        if engine._recovery_root_identity(recovery) != root_identity:
            raise ConfigurationError('conflict')

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
            self._no_orphan_status(recovery)
            self._check_context()
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

    def provision(self, client, *, custom_state=None, expected_client_identity=None, expected_authority=None):
        """Intentional first-use setup only. Historical policy requires adopt()."""
        return self._provision(client, custom_state=custom_state,
                               expected_client_identity=expected_client_identity, expected_authority=expected_authority)

    def inspect(self, client):
        """Sanitized read-only configuration advice; not recovery eligibility."""
        try:
            selection = self.lookup(client)
            if selection.status != 'available':
                return ConfigurationAdvice('provision_available', 'New addon backup configuration can be explicitly provisioned.')
            summary = AddonInstallationService.configured(self).inspect(client).summary
            if summary.status != 'ready':
                return ConfigurationAdvice('pending', 'Addon operation evidence requires explicit review. Configuration was not changed.')
            return ConfigurationAdvice('matching', 'The established addon backup configuration is available.')
        except ConfigurationError as exc:
            return ConfigurationAdvice(exc.code, str(exc))
        except Exception:
            return ConfigurationAdvice('unavailable', str(ConfigurationError()))

    def _adoption_locked(self, client, identity, state):
        self._check_context()
        state = _absolute(state)
        self._established_directories(state)
        recovery, root_identity = engine._production_recovery_location(client, identity)
        selected = AddonInstallationService(state)
        selected._policy(client, recovery, identity)  # Caller-supplied path, never a policy-selected destination.
        _, policy = selected._configuration(client, recovery, identity)
        pending = engine._inspect_production_pending_locked(client, identity)
        if pending['state'] not in ('none', 'valid'):
            raise ConfigurationError('pending')
        durable = selected._durable(client, recovery, identity)
        selected._match_durable(durable, pending)
        unresolved = pending['state'] != 'none' or bool(durable.fence) or (
            durable.document is not None and durable.document['phase'] != 'finalized')
        if durable.document is not None and pending['state'] == 'none':
            durable.verify_terminal(state / 'AddonBackups')
        if root_identity is not None:
            durable.check()
        observed = engine._read_preparation_file(recovery / POLICY_NAME, client.parent, max_bytes=POLICY_LIMIT)
        bindings = (identity, root_identity, policy, observed, durable.raw, durable.stamp,
                    durable.known, durable.known_stamp, durable.fences,
                    selected._pending_key(pending), self._check_context())
        if engine.client_identity(client) != identity:
            raise ConfigurationError('conflict')
        return AdoptionCandidate(client, state, bindings, unresolved, authority=self.capture_authority())

    def adoption_candidate(self, client, state):
        """Explicit independently supplied location; no writes and no policy path discovery."""
        try:
            with engine._transaction_client_lock(client) as (canonical, identity):
                raw, _, registry_identity = self._record(identity)
                if raw is not None and self._validate(raw, canonical, identity, registry_identity).state != _absolute(state):
                    raise ConfigurationError('conflict')
                return replace(self._adoption_locked(canonical, identity, state), requested=Path(client).absolute())
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError('conflict') from exc

    def adopt(self, candidate, *, confirmed=False):
        """Register a confirmed snapshot without moving backups or resolving evidence."""
        if not confirmed:
            raise ConfigurationError('choice_required')
        if not isinstance(candidate, AdoptionCandidate):
            raise ConfigurationError('conflict')
        return self._provision(candidate.client, custom_state=candidate.state,
                               expected_client_identity=candidate.bindings[0], adoption=candidate)

    def _check_adoption(self, candidate, canonical, identity, state):
        self.verify_authority(candidate.authority)
        if (candidate.requested is not None and engine.client_identity(candidate.requested) != identity
                or self._adoption_locked(canonical, identity, state) != candidate):
            raise ConfigurationError('conflict')

    def _provision(self, client, *, custom_state=None, expected_client_identity=None, adoption=None,
                   expected_authority=None):
        """Publish only a newly confirmed selection; never a migration.

        A durable exclusive intent stage precedes state-directory creation. Any
        interrupted outcome preserves that stage and blocks future provisioning.
        No cleanup guesses ownership or deletes existing configuration/backups.
        """
        try:
            with engine._transaction_client_lock(client) as (canonical, identity):
                self._check_context()
                if expected_authority is not None:
                    self.verify_authority(expected_authority)
                if expected_client_identity is not None and identity != expected_client_identity:
                    raise ConfigurationError('conflict')
                anchor_identity = engine._recovery_root_identity(self.anchor)
                mode = 'custom' if custom_state is not None else 'default'
                state = _absolute(custom_state) if custom_state is not None else self.standard
                if adoption is not None:
                    self._check_adoption(adoption, canonical, identity, state)
                    mode = 'default' if state == self.standard else 'custom'
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
                    if adoption is None:
                        raise ConfigurationError('choice_required')
                    # Established policy means missing directories are damage, not
                    # first use. Validate before making even a registry artifact.
                    selected._policy(canonical, recovery, identity)
                else:
                    if adoption is not None:
                        raise ConfigurationError('conflict')
                    self._no_orphan_status(recovery)
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
                self._check_context()
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
                self._check_context()
                if adoption is not None:
                    self._check_adoption(adoption, canonical, identity, state)
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
                record = dict(schema=2, user_sid=self._context.sid, mode=mode, client=identity,
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
                self._check_context()
                if adoption is not None:
                    self._check_adoption(adoption, canonical, identity, state)
                engine._publish_pending_file(publication, target, self.anchor)
                published = engine._read_preparation_file(target, self.anchor, max_bytes=LIMIT)
                if published != (record_raw, artifacts[-1]['verified_stamp']):
                    raise ConfigurationError('conflict')
                self._validate(published[0], canonical, identity, registry_identity)
                if adoption is not None:
                    self._check_adoption(adoption, canonical, identity, state)
                if engine._read_preparation_file(intent, self.anchor) != intent_observed:
                    raise ConfigurationError('conflict')
                engine.safe_target(intent, self.anchor, for_write=True)
                intent.unlink()
                return self._lookup_locked(canonical, identity)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError() from exc
