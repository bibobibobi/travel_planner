"""Durable deployment transaction state machine; no privileged CLI is exposed.

The caller must hold the lifecycle lock, validate releases, and implement the
fixed-service switch, restart, and health-check operations. This module does
not itself establish the trustworthiness of paths or service callbacks.
"""
import json
import os
import re
import tempfile
from pathlib import Path

SHA = re.compile(r'[0-9a-f]{40}\Z')


class TransactionError(RuntimeError):
    pass


def valid_revision(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def validate_state(state):
    if not isinstance(state, dict) or set(state) != {'current', 'previous', 'transaction'}:
        raise TransactionError('invalid transaction state')
    if not valid_revision(state['current']):
        raise TransactionError('invalid current revision')
    if state['previous'] is not None and not valid_revision(state['previous']):
        raise TransactionError('invalid previous revision')
    tx = state['transaction']
    if tx is not None and (not isinstance(tx, dict) or
                           set(tx) not in ({'old', 'new'}, {'old', 'new', 'restart_uncertain'}) or
                           not valid_revision(tx['old']) or not valid_revision(tx['new']) or
                           ('restart_uncertain' in tx and not isinstance(tx['restart_uncertain'], bool)) or
                           tx['old'] != state['current'] or tx['new'] == tx['old']):
        raise TransactionError('invalid pending transaction')
    return state


class StateStore:
    """Write one root-protected state file with atomic replacement and fsync."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'deployment-state.json'

    def load(self):
        # The caller must verify that the directory and file are root-owned and
        # inaccessible to untrusted writers before creating a StateStore.
        with self.path.open('r', encoding='ascii') as stream:
            return validate_state(json.load(stream))

    def save(self, state):
        validate_state(state)
        descriptor, name = tempfile.mkstemp(prefix='.deployment-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
                json.dump(state, stream, sort_keys=True, separators=(',', ':'))
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name == 'posix':
                directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def recover(store, switch, restart_and_check):
    state = store.load()
    tx = state['transaction']
    if tx is None:
        return False
    if tx.get('restart_uncertain', False):
        raise TransactionError('restart job status uncertain; pending transaction preserved')
    try:
        switch(tx['old'])
    except OSError as error:
        raise TransactionError('rollback switch failed; pending transaction preserved') from error
    if not restart_and_check():
        raise TransactionError('rollback health check failed; pending transaction preserved')
    store.save({'current': tx['old'], 'previous': state['previous'], 'transaction': None})
    return True


def deploy(store, revision, switch, restart_and_check):
    state = store.load()
    if state['transaction'] is not None:
        raise TransactionError('pending transaction requires recovery')
    if not valid_revision(revision) or revision == state['current']:
        raise TransactionError('invalid target revision')
    old = state['current']
    state['transaction'] = {'old': old, 'new': revision}
    store.save(state)  # durable before touching current
    try:
        switch(revision)
        if not restart_and_check():
            raise TransactionError('new release failed health checks')
    except (TransactionError, OSError):
        if recover(store, switch, restart_and_check):
            raise TransactionError('deployment failed; rollback succeeded') from None
        raise
    store.save({'current': revision, 'previous': old, 'transaction': None})
