import pytest

from deploy.server import deployment_transaction as tx

OLD = 'a' * 40
NEW = 'b' * 40


@pytest.fixture
def store(tmp_path):
    result = tx.StateStore(tmp_path)
    result.save({'current': OLD, 'previous': None, 'transaction': None})
    return result


def test_success_records_new_and_previous(store):
    switched = []
    tx.deploy(store, NEW, switched.append, lambda: True)
    assert switched == [NEW]
    assert store.load() == {'current': NEW, 'previous': OLD, 'transaction': None}


def test_health_failure_restores_previous_and_fails(store):
    switched = []
    checks = iter([False, True])
    with pytest.raises(tx.TransactionError, match='rollback succeeded'):
        tx.deploy(store, NEW, switched.append, lambda: next(checks))
    assert switched == [NEW, OLD]
    assert store.load()['transaction'] is None
    assert store.load()['current'] == OLD


def test_failed_rollback_retains_pending_for_recovery(store):
    switched = []
    with pytest.raises(tx.TransactionError, match='rollback health check failed'):
        tx.deploy(store, NEW, switched.append, lambda: False)
    assert switched == [NEW, OLD]
    assert store.load()['transaction'] == {'old': OLD, 'new': NEW}
    assert tx.recover(store, switched.append, lambda: True)
    assert store.load()['transaction'] is None


def test_rollback_switch_failure_is_explicit_and_preserves_transaction(store):
    def switch(revision):
        if revision == OLD:
            raise OSError('simulated')
    with pytest.raises(tx.TransactionError, match='rollback switch failed'):
        tx.deploy(store, NEW, switch, lambda: False)
    assert store.load()['transaction'] == {'old': OLD, 'new': NEW}


def test_uncertain_restart_prevents_recovery_switch(store):
    state = store.load()
    state['transaction'] = {'old': OLD, 'new': NEW, 'restart_uncertain': True}
    store.save(state)
    switched = []
    with pytest.raises(tx.TransactionError, match='restart job status uncertain'):
        tx.recover(store, switched.append, lambda: True)
    assert not switched
    assert store.load()['transaction']['restart_uncertain'] is True


def test_invalid_uncertainty_marker_is_rejected(store):
    state = store.load()
    state['transaction'] = {'old': OLD, 'new': NEW, 'restart_uncertain': 'false'}
    with pytest.raises(tx.TransactionError, match='invalid pending'):
        store.save(state)


def test_interruption_before_switch_requires_recovery(store):
    def interrupted(revision):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        tx.deploy(store, NEW, interrupted, lambda: True)
    assert store.load()['transaction'] == {'old': OLD, 'new': NEW}
    switched = []
    assert tx.recover(store, switched.append, lambda: True)
    assert switched == [OLD]


def test_interruption_after_switch_recovers_old(store):
    switched = []
    def interrupted(revision):
        switched.append(revision)
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        tx.deploy(store, NEW, interrupted, lambda: True)
    assert store.load()['transaction'] == {'old': OLD, 'new': NEW}
    assert tx.recover(store, switched.append, lambda: True)
    assert switched == [NEW, OLD]


def test_malformed_state_is_rejected(store):
    store.path.write_text('{"current":"../bad"}', encoding='ascii')
    with pytest.raises(tx.TransactionError):
        store.load()
