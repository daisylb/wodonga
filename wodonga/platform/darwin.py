# # Platform-specific code for Darwin (macOS)
import trio
from signal import Signals
from structlog import BoundLogger
from os import killpg
from signal import SIGINT, SIGKILL, SIGTERM

TIMEOUT_LEADER_CANCEL = 3
TIMEOUT_ORPHAN_CANCEL = 3
TIMEOUT_CANCEL = TIMEOUT_LEADER_CANCEL + TIMEOUT_ORPHAN_CANCEL + 1

# ## Cleaning up after a dead process
# We need to handle two situations here:
#
# 1. The process exits, either because it was terminated by `.exit()` or because it stopped unexpectedly, or
# 2. The Trio cancel scope we're running in gets cancelled (e.g. because we got a `SIGINT` or `SIGTERM` ourselves), in which case the process is still running.
def cleanup_dead_process(process: trio.Process, *, signal: Signals, logger: BoundLogger):
    with trio.move_on_after(TIMEOUT_CANCEL) as scope:
        logger.debug(
            "cleaning up",
            pid=process.pid,
            returncode=process.returncode,
        )
        scope.shield = True
        # In that second case, we kill the process. We ask it nicely by sending it the configured signal, and give it a few seconds.
        if process.returncode is None:
            logger.debug(
                "politely asking process to quit",
                pid=process.pid,
                signal=signal,
            )
            process.send_signal(signal)
            with trio.move_on_after(TIMEOUT_LEADER_CANCEL):
                await process.wait()
        
        # If the process is _still_ running, we send it SIGKILL (which halts it immediately).
        if process.returncode is None:
            logger.debug("forcing process to quit")
            process.send_signal(SIGKILL)
            await process.wait()

        # The process in question might have spawned subprocesses (e.g. something like [modd](https://github.com/cortesi/modd), or Django in auto-reload mode). If both the parent and child process aren't handling signals properly, the child process could still be running as an orphan; we handle that by sending `SIGTERM` to its process group.
        #
        # You might read that when a parent process leaves orphans, those orphans are reparented to PID 1 _and_ have their process group reset when the parent is reaped. The behaviour in Darwin seems to be that they're reparented _as soon as the parent exits_, but the process group ID is never touched.
        try:
            await killpg_no_zombie(process.pid, SIGTERM, logger)
        # `ProcessLookupError` just means that there aren't any processes in that group in which case hooray, there weren't any orphans!
        except ProcessLookupError:
            pass
        # If there _were_ orphans, we can't wait on a process group, so we just poll `killpg` until they all exit or we hit a timeout.
        else:
            logger.warn("process left orphans")
            try:
                with trio.move_on_after(TIMEOUT_ORPHAN_CANCEL):
                    while True:
                        # `killpg`-ing a process group with a signal of 0 doesn't actually signal any processes, but does look up whether the process group exists, so it's a handy way to check if there's any processes left.
                        await killpg_no_zombie(process.pid, 0, logger)
                        await trio.sleep(0.1)
                await killpg_no_zombie(process.pid, SIGKILL, logger)
            # We're catching the `ProcessLookupError` _outside_ the loop, so that the loop stops running once all the orphans exit.
            except ProcessLookupError:
                logger.debug("all orphans exited")
            # If we reach the end without getting a `ProcessLookupError`, we had to send `SIGKILL` to at least one orphan, so we log that. The actual signal is sent from within the `try` block because it's possible the last child exits in the 100ms between the last `killpg(pid, 0)` and the `killpg(pid, SIGKILL)`.
            else:
                logger.debug("forcibly killed orphans")

# ## Wrapping `killpg`
# macOS has this fun\*\*\* little quirk where if you try to `killpg` a process group, and there's a process in that group that's died but not been reaped, you get a `PermissionError`. Since we're dealing with orphan processes, they get reaped by launchd, leading to a fun little race condition.
async def killpg_no_zombie(pgid, signal, logger):
    for i in range(9, -1, -1):
        try:
            return killpg(pgid, signal)
        # ...So if we get `PermissionError`, we just try again.
        except PermissionError:
            logger.debug(
                "got PermissionError trying to killpg",
                pgid=pgid,
                signal=signal,
                remaining_tries=i,
            )
            # There are other circumstances that raise `PermissionError` too, though&mdash;for instance, if there's a process in the group that we don't own&mdash;so we only do this up to ten times, to avoid an infinite loop.
            if i == 0:
                raise
        await trio.sleep(0.05)

