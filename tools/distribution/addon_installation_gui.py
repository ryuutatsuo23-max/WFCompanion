"""Addons-page transaction adapter: explicit confirmation and recovery only.

Normal GUI construction uses verified current-user configuration. The isolated
startup path excludes this adapter; CLI/setup activation remains separate.
"""
from dataclasses import dataclass, field
from pathlib import Path

import install_addons as engine
from addon_installation_configuration import ConfigurationError, ConfigurationSelection
from addon_installation_service import AddonInstallationService, ServiceResult, configuration_failure


@dataclass(frozen=True)
class ConfirmedInstallation:
    client: Path
    identity: dict = field(repr=False)
    payload: Path
    selected: tuple
    selection: ConfigurationSelection
    provision: bool
    adoption: object = field(default=None, repr=False)
    authority: object = field(default=None, repr=False)


@dataclass(frozen=True)
class InstallationAdvice:
    blocked: bool
    message: str = ''
    recovery_required: bool = False


@dataclass(frozen=True)
class RecoveryTarget:
    client: Path
    requested: Path
    identity: dict = field(repr=False)
    selection: ConfigurationSelection | None = field(repr=False)
    authority: object = field(default=None, repr=False)


class GuiAddonTransactions:
    def __init__(self, configuration, *, custom_state=None):
        # Explicit custom input is a setup choice, never inferred from a window.
        # Without it an established selection wins, including a custom selection.
        self.configuration = configuration
        self.custom_state = Path(custom_state) if custom_state is not None else None
        self.service = AddonInstallationService.configured(configuration)

    def capture_recovery(self, client):
        authority = self.configuration.capture_authority()
        requested = Path(client).absolute()
        canonical = engine.validate_client(requested)
        identity = engine.client_identity(canonical)
        try:
            selection = self._selection(canonical)
            if selection.status != 'available':selection = None
        except Exception:
            selection = None  # Still permit read-only diagnosis; never provision.
        if engine.client_identity(requested) != identity or engine.client_identity(canonical) != identity:
            raise ValueError('Selected game folder changed.')
        self.configuration.verify_authority(authority)
        return RecoveryTarget(canonical, requested, identity, selection, authority)

    def recovery_summary(self, target):
        try:
            self.configuration.verify_authority(target.authority)
        except Exception:
            from addon_installation_service import PendingSummary
            return PendingSummary('unknown', 'unavailable')
        summary = self.service.pending_summary(target.client, expected_client_identity=target.identity,
            expected_selection=target.selection, expected_requested_client=target.requested)
        if target.selection is None:
            # No confirmed configuration at opening: reopen after resolving setup.
            from dataclasses import replace
            summary = replace(summary, configuration='unavailable', may_complete=False, may_rollback=False,
                              may_report=False, reporting_key=None, manual_review=True)
        return summary

    def resolve_recovery(self, target, action, transaction_key):
        try:
            self.configuration.verify_authority(target.authority)
        except ConfigurationError as exc:
            return configuration_failure(exc)
        if target.selection is None:
            # Preserve a specific account/legacy-identity diagnosis, but a newly
            # available selection still cannot authorize this old confirmation.
            try:
                self._selection(target.client)
            except ConfigurationError as exc:
                return configuration_failure(exc)
            return ServiceResult('backup_unavailable', 'configuration_unavailable')
        if action not in ('complete', 'rollback', 'report') or not transaction_key:
            return ServiceResult('recovery_incomplete', 'confirmation_unavailable')
        if action == 'report':
            return self.service.finish_reporting(target.client, expected_reporting=transaction_key,
                expected_client_identity=target.identity, expected_selection=target.selection,
                expected_requested_client=target.requested, expected_authority=target.authority)
        # Both operations revalidate all evidence and the confirmation bindings
        # under the canonical client lock. Neither invokes a new installation.
        operation = self.service.complete if action == 'complete' else self.service.rollback
        return operation(target.client, expected_client_identity=target.identity,
            expected_selection=target.selection, expected_requested_client=target.requested,
            expected_transaction=transaction_key, expected_authority=target.authority)

    def _selection(self, client):
        try:
            selected = self.configuration.lookup(client)
        except ConfigurationError as exc:
            if exc.code != 'choice_required':
                raise
            selected = ConfigurationSelection('adoption', 'default', self.configuration.standard)
        if selected.status == 'available':
            if self.custom_state is not None and self.custom_state != selected.state:
                raise ConfigurationError('conflict')
            return selected
        return ConfigurationSelection(selected.status, 'custom' if self.custom_state is not None else 'default',
                                      self.custom_state if self.custom_state is not None else selected.state)

    def inspect(self, client):
        if client is None:
            return InstallationAdvice(True, 'Choose a game folder before installing addons.')
        summary = self.service.inspect(client).summary
        if summary.status in ('configuration_user_conflict', 'configuration_user_unverified',
                              'configuration_identity_unverified'):
            return InstallationAdvice(True, summary.message)
        if summary.status == 'busy':
            return InstallationAdvice(True, 'Another addon operation is using this game folder. Wait before installing.')
        pending = self.service.pending_summary(client)
        if pending.pending != 'none':
            return InstallationAdvice(True, 'Unfinished addon installation — Recovery required. Preserve backups and recovery evidence.'
                                      if pending.pending == 'valid' else
                                      'Addon installation state could not be verified. Preserve evidence; installation is unavailable.',
                                      recovery_required=True)
        try:
            selected = self._selection(client)
        except ConfigurationError as exc:
            message = (configuration_failure(exc).summary.message
                       if exc.code in ('user_conflict', 'user_unverified', 'identity_unverified') else
                       'Addon backup configuration is unavailable or conflicting. Review the configured location.')
            return InstallationAdvice(True, message)
        except Exception:
            return InstallationAdvice(True, 'Addon backup configuration is unavailable or conflicting. Review the configured location.')
        return InstallationAdvice(False, 'Addon backup setup will be confirmed before installation.'
                                  if selected.status != 'available' else '')

    def capture(self, client, payload, addon):
        authority = self.configuration.capture_authority()
        if addon not in ('WFCore', 'WFStorage', 'WFProfessions'):
            raise ValueError('Unsupported addon selection.')
        canonical = engine.validate_client(client)
        identity = engine.client_identity(canonical)
        selection = self._selection(canonical)
        adoption = (self.configuration.adoption_candidate(client, selection.state)
                    if selection.status == 'adoption' else None)
        if engine.client_identity(canonical) != identity or engine.client_identity(client) != identity:
            raise ValueError('Selected game folder changed.')
        names = ('WFCore',) if addon == 'WFCore' else ('WFCore', addon)
        self.configuration.verify_authority(authority)
        return ConfirmedInstallation(canonical, identity, Path(payload).resolve(), names, selection,
                                     selection.status != 'available', adoption, authority)

    def execute(self, request):
        dispatched = False
        try:
            self.configuration.verify_authority(request.authority)
            if engine.client_identity(request.client) != request.identity:
                return ServiceResult('blocked', 'confirmed_client_changed')
            if self._selection(request.client) != request.selection:
                return ServiceResult('backup_unavailable', 'configuration_conflict')
            selection = request.selection
            if request.adoption is not None:
                selection = self.configuration.adopt(request.adoption, confirmed=True)
            elif request.provision:
                selection = self.configuration.provision(request.client,
                    custom_state=selection.state if selection.mode == 'custom' else None,
                    expected_client_identity=request.identity, expected_authority=request.authority)
            dispatched = True
            return self.service.install(request.payload, request.client, request.selected,
                expected_client_identity=request.identity, expected_selection=selection,
                expected_authority=request.authority)
        except Exception as exc:
            if not dispatched and isinstance(exc, ConfigurationError):
                return configuration_failure(exc)
            # An escaping service exception is not evidence that no files changed.
            return ServiceResult('recovery_incomplete' if dispatched else 'backup_unavailable',
                                 'operation_outcome_unknown' if dispatched else 'configuration_unavailable', exc)
