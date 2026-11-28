#!/usr/bin/python3
"""Candidate single-lock receive/build/deploy pipeline; no arbitrary paths."""
import os
import subprocess
import sys

import deployment_controller as controller
import deployment_transaction as transaction
import receive_artifact as receiver
import release_builder as builder
import release_tree


class PipelineError(RuntimeError):
    pass


def run(fd):
    lock = receiver.take_lock()
    try:
        store = controller.open_store()
        if controller.recover_if_needed(store):
            raise PipelineError('pending transaction recovered; retry request')
        received = receiver.accept(fd, lifecycle_fd=lock, allow_existing=True)
        revision, digest = received
        release = controller.RELEASES / revision
        if os.path.lexists(release):
            if controller.validate_release(revision) != digest:
                raise PipelineError('existing release digest mismatch')
            print('RELEASE_REUSED')
        else:
            built = builder.build(revision, digest, lifecycle_fd=lock)
            if built != received:
                raise PipelineError('builder result does not match received artifact')
            if controller.validate_release(revision) != digest:
                raise PipelineError('release marker does not match received artifact')
        state = store.load()
        if state['current'] == revision:
            if (controller.current_revision() != revision or not controller.no_service_jobs() or
                    not controller.health.healthy() or not controller.service_matches_current(revision) or
                    not controller.no_service_jobs()):
                raise PipelineError('already-current release is not healthy')
            print('ALREADY_DEPLOYED\nDEPLOY_OK')
            return
        controller.deploy(revision)
    finally:
        os.close(lock)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        print('ERROR: invalid pipeline invocation', file=sys.stderr)
        return 1
    try:
        run(0)
    except (PipelineError, controller.DeploymentError, controller.RestartUncertain,
            transaction.TransactionError, receiver.Rejected, receiver.ReceiveError,
            builder.BuildError, release_tree.UnsafeTree, OSError, ValueError,
            subprocess.SubprocessError) as error:
        print(f'ERROR: pipeline failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
