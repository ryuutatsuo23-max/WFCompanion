"""Shared addon transaction service, used by the Addons page and explicit adapters.

Installation state is an explicit persistent configuration, not a window's data
directory. Policy files are additive; existing settings/history are never migrated.
"""
from dataclasses import dataclass, field
from pathlib import Path
import json
import os

import install_addons as engine
from addon_operation_status import OperationStatus, StatusError, KNOWN


POLICY_NAME='user-backup-policy.json'
POLICY_STAGE='.user-backup-policy.stage'
POLICY_LIMIT=16384
MESSAGES={
    'ready':'No pending addon installation. Backup configuration is available.',
    'installation_complete':'Addon installation and retained backups verified.',
    'blocked':'Addon installation was blocked before replacement.',
    'busy':'Another addon operation is using this game folder.',
    'recovery_pending':'An addon installation needs explicit recovery or completion.',
    'recovery_incomplete':'Recovery evidence is invalid, ambiguous or incomplete. Preserve it.',
    'rollback_complete':'Original addon files restored and rollback finalized.',
    'finalization_pending':'Installation finalization is unresolved. Preserve backups and recovery evidence.',
    'backup_unavailable':'Addon backup configuration is missing, changed, inaccessible or unsafe. Preserve existing backups.',
    'no_pending':'No pending transaction; no completion or recovery was inferred.',
}


@dataclass(frozen=True)
class ServiceResult:
    category: str
    diagnostic: str=''
    _details: object=field(default=None,repr=False,compare=False)

    @property
    def message(self):return MESSAGES[self.category]

    @property
    def ok(self):
        # Even a verified rollback means the requested installation failed.
        # Inspection/recovery callers must inspect their explicit category.
        return self.category=='installation_complete'

    def __bool__(self):
        raise TypeError('Check ServiceResult.ok or category explicitly.')

    @property
    def summary(self):
        """Path-free presentation; private exception objects never cross this API."""
        original = self
        late = self.diagnostic == 'lock_or_postcheck'
        if late and isinstance(self._details, dict):
            prior = self._details.get('operation_result')
            if isinstance(prior, ServiceResult):
                original = prior
        verified = {'installation_complete': 'installation', 'rollback_complete': 'rollback'}.get(original.category)
        status = self.category
        message = self.message
        if self.diagnostic == 'durable_resolved' and isinstance(self._details, dict):
            verified = self._details.get('outcome')
            message = 'No pending operation. The previous ' + verified + ' and finalization were verified.'
        if self.diagnostic == 'durable_status' and isinstance(self._details, dict):
            verified = self._details.get('outcome')
            if verified:
                message = ('Installation files were verified' if verified == 'installation' else
                           'Previous addon files were verified restored') + '; finalization or reporting still requires review.'
        if late and verified:
            status = verified + '_complete_with_error'
            message = ('Installation was verified, but a later operation check failed. Review status; do not reinstall automatically.'
                       if verified == 'installation' else
                       'Previous addon files were restored, but a later operation check failed. Review status before installing again.')
        elif self.diagnostic in ('pending_invalid', 'pending_ambiguous'):
            status = self.diagnostic
        elif self.diagnostic == 'configuration_conflict':
            status = 'configuration_conflict'
            message = 'Addon backup configuration conflicts with established evidence. Preserve it and review the configured location.'
        elif self.diagnostic in ('configuration_user_unverified', 'configuration_user_conflict',
                                  'configuration_identity_unverified',
                                  'configuration_missing_established', 'configuration_choice_required'):
            status = self.diagnostic
            message = {
                'configuration_user_unverified': 'Windows user context is unverified. Use the intended account without elevation.',
                'configuration_user_conflict': 'Windows user context changed or conflicts with this configuration. Installation is unavailable.',
                'configuration_identity_unverified': 'Legacy addon configuration has no verified historical account binding. Preserve it; a separately reviewed reauthorization is required.',
                'configuration_missing_established': 'An established backup directory is missing. Preserve existing evidence; do not recreate it.',
                'configuration_choice_required': 'Explicitly confirm the existing addon backup location before continuing.',
            }[self.diagnostic]
        return ResultSummary(status, self.ok, verified, late, message)


@dataclass(frozen=True)
class ResultSummary:
    status: str
    ok: bool
    verified_outcome: str | None
    late_error: bool
    message: str
    automatic_reinstall: bool = False


@dataclass(frozen=True)
class PendingSummary:
    """Attempt-local advice, never authority to mutate or proof of past success."""
    pending: str
    configuration: str
    may_complete: bool = False
    may_rollback: bool = False
    manual_review: bool = True
    advisory: bool = True
    addons: tuple = ()
    transaction_key: tuple | None = None
    inspection: str = 'verified'
    verified_outcome: str | None = None
    finalization: str | None = None
    may_report: bool = False
    reporting_key: tuple | None = field(default=None, repr=False)


class BackupConfigurationError(ValueError):
    pass


def configuration_failure(exc):
    """One allowlisted, path-free mapping for service and GUI configuration errors."""
    code = exc.code if exc.code in ('conflict', 'user_unverified', 'user_conflict',
                                   'identity_unverified', 'missing_established', 'choice_required') else 'unavailable'
    return ServiceResult('backup_unavailable', 'configuration_' + code, exc)


def standard_installation_state():
    """Common future GUI/CLI/setup default; no filesystem access or fallback."""
    value=os.environ.get('LOCALAPPDATA')
    if not value or not Path(value).is_absolute():
        raise BackupConfigurationError('Persistent installation state is unavailable.')
    return Path(value)/'WoWForever'/'Companion'


class AddonInstallationService:
    def __init__(self,installation_state=None,*,configuration=None):
        # Require an explicit absolute policy, even in tests. Never use cwd or GUI
        # session state as an implicit substitute. Construction does not do I/O.
        self.configuration=configuration
        if configuration is not None:
            if installation_state is not None:raise BackupConfigurationError('Choose one configuration source.')
            self.state=None
            return
        if installation_state is None:raise BackupConfigurationError('Absolute installation state required.')
        self.state=Path(installation_state)
        if not self.state.is_absolute():raise BackupConfigurationError('Absolute installation state required.')

    @classmethod
    def standard(cls):return cls(standard_installation_state())

    @classmethod
    def configured(cls,configuration):
        """Explicit isolated opt-in. Resolve/revalidate selection under each lock."""
        return cls(configuration=configuration)

    def _active(self,canonical,identity):
        if self.configuration is None:return self,None
        from addon_installation_configuration import ConfigurationError
        try:selection=self.configuration._lookup_locked(canonical,identity)
        except ConfigurationError:raise
        except Exception as exc:raise BackupConfigurationError('Configuration could not be verified.') from exc
        if selection.status!='available':raise BackupConfigurationError('Configuration must be explicitly provisioned.')
        return AddonInstallationService(selection.state),selection

    @staticmethod
    def _pending_key(status):
        if status['state']!='valid':return None
        # Bind consent to the exact independently validated transaction bytes.
        return (status['record']['id'],engine._byte_description(status['_bindings'][1][2])['sha256'])

    @staticmethod
    def _reporting_key(durable):
        # Consent is for this exact status and set of reporting attempts, not
        # merely a transaction UUID. Revalidate under the client lock before use.
        durable.check()
        return (durable.document['transaction']['id'], durable.document['outcome'],
                engine._byte_description(durable.raw)['sha256'], durable.stamp, durable.known_stamp,
                tuple((name, engine._byte_description(raw)['sha256'], stamp)
                      for name, (raw, stamp) in sorted(durable.fences.items())))

    @staticmethod
    def _confirmed_client(canonical,identity,expected_identity,requested):
        if expected_identity is not None and identity!=expected_identity:
            raise BackupConfigurationError('Confirmed client identity changed.')
        if requested is not None and engine.client_identity(requested)!=identity:
            raise BackupConfigurationError('Confirmed client alias changed.')

    def pending_summary(self,client,*,expected_client_identity=None,expected_selection=None,expected_requested_client=None):
        """Read-only, including policy and retained-copy checks; never provisions."""
        try:
            with engine._transaction_client_lock(client) as (canonical,identity):
                self._confirmed_client(canonical,identity,expected_client_identity,expected_requested_client)
                recovery,root_identity=engine._production_recovery_location(canonical,identity)
                status=engine._inspect_production_pending_locked(canonical,identity)
                configuration='available';active=None;selection=None
                try:
                    active,selection=self._active(canonical,identity)
                    if expected_selection is not None and selection!=expected_selection:
                        raise BackupConfigurationError('Confirmed configuration changed.')
                    if root_identity is None and status['state']=='none':
                        active._configuration(canonical,recovery,identity)
                    else:active._policy(canonical,recovery,identity)
                except Exception:
                    configuration='unavailable'
                complete=False;rollback=False;durable=None;reporting=False;reporting_key=None;unresolved=False
                if configuration=='available':
                    durable=active._durable(canonical,recovery,identity)
                    active._match_durable(durable,status)
                    if durable.document is not None and status['state']=='none':
                        if durable.fence is not None or durable.document['phase']!='finalized':
                            # Settled history does not freeze addon bytes or old
                            # backups; unresolved outcomes still require both.
                            durable.verify_terminal(active.state/'AddonBackups')
                            # Reporting is distinct from restoration. Residual
                            # recovery artifacts still require manual review.
                            unresolved=True
                            try:
                                durable.verify_cleanup()
                                reporting_key=self._reporting_key(durable)
                                reporting=True
                            except Exception:
                                pass
                if status['state']=='valid' and configuration=='available':
                    rollback=True  # Engine preflight already verified every original and expected destination state.
                    try:
                        engine._verify_terminal_destinations(status,'installation')
                        retained=engine.RetainedUserBackup(status['record'],engine._completion_receipt(status,canonical),
                                                         canonical,recovery,active.state/'AddonBackups')
                        retained.verify()
                        complete=True
                    except Exception:
                        pass  # Not eligible; no completion or repair is attempted.
                if selection is not None and self.configuration._lookup_locked(canonical,identity)!=selection:
                    raise BackupConfigurationError('Configuration changed.')
                if (engine.client_identity(canonical)!=identity or
                        engine._production_recovery_location(canonical,identity)!=(recovery,root_identity)):
                    raise ValueError('Locked identity changed.')
                summary=PendingSummary('unresolved' if unresolved else status['state'],configuration,complete,rollback,
                                       configuration!='available' or status['state'] in ('invalid','ambiguous') or (unresolved and not reporting),
                                       addons=(tuple(durable.document['transaction']['expanded']) if unresolved else
                                               tuple(status['record']['expanded']) if status['state']=='valid' else ()),
                                       transaction_key=self._pending_key(status),
                                       verified_outcome=durable.document['outcome'] if durable and durable.document else None,
                                       finalization=durable.document['phase'] if durable and durable.document else None,
                                       may_report=reporting,reporting_key=reporting_key)
            return summary
        except Exception as exc:
            busy=isinstance(exc,ValueError) and str(exc).startswith('Another addon installation')
            return PendingSummary('unknown','unavailable',inspection='busy' if busy else 'unavailable')

    def _configuration(self,client,recovery,identity):
        try:
            state=engine._transaction_directory(self.state)
            users=engine._transaction_directory(state/'AddonBackups')
            for protected in (client,recovery):
                if users.is_relative_to(protected) or protected.is_relative_to(users):
                    raise ValueError('Overlapping backup scope.')
            expected=dict(schema=1,client=identity,state=engine._recovery_root_identity(state),
                          users=engine._recovery_root_identity(users))
            raw=json.dumps(expected,sort_keys=True).encode('utf-8')
            if len(raw)>POLICY_LIMIT:raise ValueError('Policy too large.')
            return users,raw
        except Exception as exc:
            raise BackupConfigurationError('Backup configuration unavailable.') from exc

    def _durable(self,canonical,recovery,identity):
        _,policy=self._configuration(canonical,recovery,identity)
        try:
            policy_exists=engine._read_preparation_file(recovery/POLICY_NAME,canonical.parent,missing=True,max_bytes=POLICY_LIMIT)[0] is not None
            known=engine._read_preparation_file(recovery/KNOWN,canonical.parent,missing=True,max_bytes=POLICY_LIMIT)[0]
            if policy_exists or known is not None:self._policy(canonical,recovery,identity)
        except Exception as exc:raise BackupConfigurationError('Established backup policy unavailable.') from exc
        try:return OperationStatus(canonical,recovery,identity,policy)
        except Exception as exc:raise StatusError() from exc

    def _match_durable(self,durable,status):
        if (durable.document is not None and status['state']=='valid'
                and durable.document['transaction']['id']!=status['record']['id']
                and durable.document['phase']=='finalized' and durable.fence is None):
            # Crash after publishing the next pending marker, before replacing
            # the settled status slot. Prove the prior state still holds; only
            # explicit recovery/completion can adopt the new pending transaction.
            durable.verify_terminal(self.state/'AddonBackups')
        else:durable.match(status)

    @staticmethod
    def _durable_result(durable):
        value=durable.document
        return ServiceResult('finalization_pending' if value and value['outcome'] else 'recovery_incomplete',
                             'durable_status',dict(outcome=value['outcome'] if value else None,
                                                  phase=value['phase'] if value else None))

    def _policy(self,client,recovery,identity,*,create=False):
        """Only expected paths are used. Untrusted policy bytes never select roots."""
        users,expected=self._configuration(client,recovery,identity)
        try:
            raw,stamp=engine._read_preparation_file(recovery/POLICY_NAME,client.parent,
                                                  missing=True,max_bytes=POLICY_LIMIT)
            staged,_=engine._read_preparation_file(recovery/POLICY_STAGE,client.parent,
                                                 missing=True,max_bytes=POLICY_LIMIT)
            if staged is not None:raise ValueError('Unresolved policy publication; preserve it.')
            if raw is None:
                if not create:raise ValueError('No established backup policy for pending transaction.')
                engine._preparation_mkdir(recovery,client.parent,[])
                # Exclusive stage plus Windows non-overwriting publication. Failure
                # leaves evidence; never automatically repair or remove a stage.
                artifacts=[]
                engine._write_preparation_artifact(recovery/POLICY_STAGE,client.parent,expected,artifacts,[])
                if engine._read_preparation_file(recovery/POLICY_STAGE,client.parent)!=(expected,artifacts[-1]['verified_stamp']):
                    raise ValueError('Policy stage changed.')
                engine._publish_pending_file(recovery/POLICY_STAGE,recovery/POLICY_NAME,client.parent)
                raw,stamp=engine._read_preparation_file(recovery/POLICY_NAME,client.parent,max_bytes=POLICY_LIMIT)
            if raw!=expected:raise ValueError('Backup policy mismatch.')
            if self._configuration(client,recovery,identity)!=(users,expected):raise ValueError('Backup configuration changed.')
            if engine._read_preparation_file(recovery/POLICY_NAME,client.parent,max_bytes=POLICY_LIMIT)!=(raw,stamp):
                raise ValueError('Backup policy changed.')
            return users
        except Exception as exc:
            raise BackupConfigurationError('Backup policy could not be verified.') from exc

    @staticmethod
    def _pending(status):
        return ServiceResult('recovery_pending' if status['state']=='valid' else 'recovery_incomplete',
                             'pending_'+status['state'],status)

    @staticmethod
    def _outcome(result):
        state=result['state']
        category={'installation_complete':'installation_complete','rollback_complete':'rollback_complete',
                  'finalization_pending':'finalization_pending','recovery_pending':'recovery_pending',
                  'blocked':'blocked'}.get(state,'recovery_incomplete')
        if result.get('phase')=='retained_backup':category='backup_unavailable'
        return ServiceResult(category,'executor_'+state,result)

    def _run(self,operation,client,payload=None,selected=(),*,expected_client_identity=None,expected_selection=None,
             expected_requested_client=None,expected_transaction=None,expected_authority=None,expected_reporting=None):
        result=None;entered=False;operation_started=False;durable=None;report=False
        try:
            with engine._transaction_client_lock(client) as (canonical,identity):
                entered=True
                if expected_authority is not None:
                    self.configuration.verify_authority(expected_authority)
                self._confirmed_client(canonical,identity,expected_client_identity,expected_requested_client)
                recovery,root_identity=engine._production_recovery_location(canonical,identity)
                status=engine._inspect_production_pending_locked(canonical,identity)
                active,selection=self._active(canonical,identity)
                if expected_selection is not None and selection!=expected_selection:
                    raise BackupConfigurationError('Confirmed configuration changed.')
                def verify_reporting_configuration():
                    if expected_authority is not None:
                        self.configuration.verify_authority(expected_authority)
                    self._confirmed_client(canonical,identity,expected_client_identity,expected_requested_client)
                    if engine._production_recovery_location(canonical,identity)!=(recovery,root_identity):
                        raise BackupConfigurationError('Recovery policy location changed.')
                    active._policy(canonical,recovery,identity)
                    if selection is not None and self.configuration._lookup_locked(canonical,identity)!=selection:
                        raise BackupConfigurationError('Configuration changed during status publication.')
                if (expected_transaction is not None and status['state']=='valid'
                        and self._pending_key(status)!=expected_transaction):
                    raise ValueError('Confirmed pending transaction changed.')
                durable=active._durable(canonical,recovery,identity)
                if operation=='report':
                    # This entry point can only finish a confirmed markerless
                    # outcome. It must never fall through to install/rollback.
                    if (expected_reporting is None or status['state']!='none' or durable.document is None
                            or durable.document['outcome'] not in ('installation','rollback')
                            or (durable.document['phase']=='finalized' and durable.fence is None)
                            or self._reporting_key(durable)!=expected_reporting):
                        raise ValueError('Confirmed reporting evidence changed.')
                if durable.document is not None:
                    # A settled previous transaction may coexist with a new legacy
                    # pending transaction only after explicit manual review.
                    active._match_durable(durable,status)
                    if status['state']=='none':
                        if durable.document['phase']!='finalized' or durable.fence is not None:
                            # Only unresolved outcomes depend on historic bytes.
                            # A new install independently validates current inputs.
                            durable.verify_terminal(active.state/'AddonBackups')
                            if operation not in ('complete','rollback','report') or (operation!='report' and
                                    (operation=='complete') != (durable.document['outcome']=='installation')):
                                result=self._durable_result(durable)
                            else:
                                # Retry reporting only after independently verifying
                                # finalized bytes, policy and retained backups.
                                active._policy(canonical,recovery,identity)
                                durable.verify_cleanup()
                                durable.finished(durable.document['outcome'],active.state/'AddonBackups',
                                                 verify_configuration=verify_reporting_configuration)
                                result=ServiceResult(durable.document['outcome']+'_complete')
                                report=True
                if result is not None:pass
                elif status['state']!='none' and (operation in ('inspect','install') or status['state']!='valid'):
                    result=self._pending(status)
                elif status['state']=='none' and operation in ('rollback','complete'):
                    result=ServiceResult('no_pending')
                else:
                    if operation=='inspect' and root_identity is None:
                        active._configuration(canonical,recovery,identity)
                    else:
                        # First install can establish policy only in safe no-pending
                        # state. Existing pending evidence always requires a policy.
                        users=active._policy(canonical,recovery,identity,create=operation=='install')
                    current_root=engine._production_recovery_location(canonical,identity)[1]
                    if root_identity is not None and current_root!=root_identity:
                        raise BackupConfigurationError('Recovery policy location changed.')
                    root_identity=current_root
                    # Policy creation may have initialized the root. Capture its
                    # identity only after that explicit preparation has succeeded.
                    durable=active._durable(canonical,recovery,identity)
                    if engine.client_identity(canonical)!=identity:raise ValueError('Locked client changed.')
                    if operation=='inspect':
                        result=(ServiceResult('ready','durable_resolved',dict(outcome=durable.document['outcome']))
                                if durable.document else ServiceResult('ready'))
                    elif operation=='install':
                        # An escaping exception is not proof that the executor made
                        # no writes. Only its returned outcome can establish that.
                        operation_started=True
                        result=self._outcome(engine._execute_transaction_locked(payload,canonical,selected,recovery,identity,
                                                                                retained_backup_root=users,observer=durable))
                    elif operation=='rollback':
                        operation_started=True
                        durable.begin(status)
                        recovered=engine._recover_pending_locked(canonical,recovery,identity)
                        if recovered['state']!='rollback_complete':
                            result=ServiceResult('recovery_incomplete','rollback_unresolved',recovered)
                        else:
                            completed=engine._finalize_transaction_locked(canonical,recovery,identity,'rollback',observer=durable)
                            result=ServiceResult('rollback_complete' if completed['state']=='rollback_complete' and not completed['failures']
                                                 else 'recovery_incomplete','rollback_finalization',completed)
                    else:
                        operation_started=True
                        durable.begin(status)
                        # Never use the recovery-only completion default. Derive
                        # and verify retained copies with the established policy.
                        retained=engine.RetainedUserBackup(status['record'],engine._completion_receipt(status,canonical),
                                                         canonical,recovery,users)
                        retained.verify()
                        completed=engine._finalize_transaction_locked(canonical,recovery,identity,'installation',retained=retained,observer=durable)
                        result=ServiceResult('installation_complete' if completed['state']=='installation_complete' and not completed['failures']
                                             else 'finalization_pending','installation_finalization',completed)
                if engine._production_recovery_location(canonical,identity)!=(recovery,root_identity):
                    raise ValueError('Recovery root changed.')
                if selection is not None and self.configuration._lookup_locked(canonical,identity)!=selection:
                    raise BackupConfigurationError('Configuration changed.')
                if result.category in ('installation_complete','rollback_complete') and not report:
                    durable.finished('installation' if result.category=='installation_complete' else 'rollback',users,
                                     verify_configuration=verify_reporting_configuration)
                    report=True
                if report:
                    active._policy(canonical,recovery,identity)
                    if selection is not None and self.configuration._lookup_locked(canonical,identity)!=selection:
                        raise BackupConfigurationError('Configuration changed during status publication.')
                    durable.check()
            if report:durable.reported()  # Never clear reporting uncertainty before mutex release.
            return result
        except Exception as exc:
            # Fixed categories/messages only; private diagnostics are not rendered.
            if result is not None:
                category=result.category
                if category in ('installation_complete','rollback_complete'):
                    category='finalization_pending'
                elif category in ('ready','no_pending'):
                    category='recovery_incomplete'
                # Preserve unresolved outcomes and both layers of diagnostics.
                # A late error cannot turn pending recovery into a pre-write block.
                return ServiceResult(category,'lock_or_postcheck',
                                     dict(operation_result=result,late_error=exc))
            if operation_started:
                return ServiceResult('finalization_pending' if operation=='complete' else 'recovery_incomplete',
                                     'operation_outcome_unknown',exc)
            if isinstance(exc,StatusError):
                if durable is not None and durable.document is not None:
                    prior=self._durable_result(durable)
                    return ServiceResult(prior.category,prior.diagnostic,dict(prior._details,error=exc))
                return ServiceResult('recovery_incomplete','durable_status_invalid',exc)
            if isinstance(exc,BackupConfigurationError):
                return ServiceResult('backup_unavailable','backup_policy',exc)
            # Avoid importing configuration at module load (it reuses this service).
            from addon_installation_configuration import ConfigurationError
            if isinstance(exc,ConfigurationError):
                return configuration_failure(exc)
            busy=not entered and isinstance(exc,ValueError) and str(exc).startswith('Another addon installation')
            return ServiceResult('busy' if busy else 'blocked' if not entered or operation=='install' else
                                 'finalization_pending' if operation=='complete' else 'recovery_incomplete',
                                 'lock' if not entered else 'operation',exc)

    def inspect(self,client):return self._run('inspect',client)
    def finish_reporting(self,client,*,expected_reporting,expected_client_identity=None,expected_selection=None,
                         expected_requested_client=None,expected_authority=None):
        return self._run('report',client,expected_reporting=expected_reporting,
                         expected_client_identity=expected_client_identity,expected_selection=expected_selection,
                         expected_requested_client=expected_requested_client,expected_authority=expected_authority)
    def install(self,payload,client,selected,*,expected_client_identity=None,expected_selection=None,expected_authority=None):
        return self._run('install',client,payload,selected,expected_client_identity=expected_client_identity,
                         expected_selection=expected_selection,expected_authority=expected_authority)
    def rollback(self,client,*,expected_client_identity=None,expected_selection=None,
                 expected_requested_client=None,expected_transaction=None,expected_authority=None):
        return self._run('rollback',client,expected_client_identity=expected_client_identity,
                         expected_selection=expected_selection,expected_requested_client=expected_requested_client,
                         expected_transaction=expected_transaction,expected_authority=expected_authority)
    def complete(self,client,*,expected_client_identity=None,expected_selection=None,
                 expected_requested_client=None,expected_transaction=None,expected_authority=None):
        return self._run('complete',client,expected_client_identity=expected_client_identity,
                         expected_selection=expected_selection,expected_requested_client=expected_requested_client,
                         expected_transaction=expected_transaction,expected_authority=expected_authority)
