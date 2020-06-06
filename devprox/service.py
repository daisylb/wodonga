import trio
import typing as t
from socket import AF_INET6
from errno import ECONNREFUSED, errorcode
from contextlib import asynccontextmanager
from structlog import BoundLogger
from signal import SIGINT, SIGKILL, SIGTERM
from os import killpg

TIMEOUT_LEADER_CANCEL = 3
TIMEOUT_ORPHAN_CANCEL = 3
TIMEOUT_CANCEL = TIMEOUT_LEADER_CANCEL + TIMEOUT_ORPHAN_CANCEL + 1

class Service:
    _service_wanted: trio.Event
    _service_started: trio.Event
    _process: t.Optional[trio.Process] = None
    _port_map: t.Optional[t.Mapping[int, int]] = None
    _users = 0
    _nursery: trio.Nursery
    _log: BoundLogger
    signal: int

    def __init__(self, *, command, ports, nursery, logger: BoundLogger, env={}, signal=SIGINT):
        self.command = command
        self.env = env
        self.ports = ports
        self.signal = signal
        self._nursery = nursery
        self._service_wanted = trio.Event()
        self._service_started = trio.Event()
        self._log = logger
        nursery.start_soon(self._run_loop)

    # ## Run loop
    #
    # This task is responsible for managing the subprocess that runs the
    # actual service.
    # It starts up in `__init__`, and should stay running for the
    # lifetime of the server.
    #
    # It runs a loop that waits for the service to be requested, starts it up,
    # waits for it to exit, cleans up, and repeats.
    async def _run_loop(self):
        while True:
            await self._service_wanted.wait()

            # TODO: flapping detection / exponential backoff

            # We start off by constructing a mapping between the ports we're
            # listening on, and the ports we're expecting the service to
            # listen on for us to proxy to.
            self._port_map = {}
            # Trio doesn't give us a way to call `nursery.start_soon()` and
            # then access the result, so we can't call `get_free_port()`
            # directly.
            # Instead, we define an async closure that awaits on it and
            # assigns the result to `self._port_map()`, and call that.
            async def get_port(port_to_map):
                self._port_map[port_to_map] = await get_free_port()
            async with trio.open_nursery() as nursery:
                for port in self.ports:
                    nursery.start_soon(get_port, port)

            # The mapping is communicated to our subprocess via environment
            # variables.
            env = {
                **self.env,
                **{f'PORT_{port}': str(alloc_port) for port, alloc_port in self._port_map.items()}
            }

            # We then start up the process, wait for it to listen on all of
            # the ports we're expecting, and fire the `_service_started` event.
            try:
                self._process = await trio.open_process(
                    self.command,
                    env=env,
                    start_new_session=True,
                )
                
                async with trio.open_nursery() as nursery:
                    for port in self._port_map.values():
                        nursery.start_soon(wait_for_port, port)

                self._service_started.set()

                # With the service started, we wait for it to stop, and clean up.
                #
                # Note that we _don't_ reset `self._service_wanted` here! If the
                # service was killed by the shutdown timer, it would have reset
                # `_service_wanted` itself. If the service crashed, we want to
                # restart it straight away.
                await self._process.wait()
            finally:
                with trio.move_on_after(TIMEOUT_CANCEL) as scope:
                    scope.shield = True
                    if self._process.returncode is None:
                        self._log.debug('politely asking leader to quit', pid=self._process.pid, signal=self.signal)
                        self._process.send_signal(self.signal)
                        with trio.move_on_after(TIMEOUT_LEADER_CANCEL):
                            await self._process.wait()
                    if self._process.returncode is None:
                        self._log.debug('forcing leader to quit')
                        self._process.send_signal(SIGKILL)
                        await self._process.wait()
                    self._log.debug('going to try terminating any orphans', pgid=self._process.pid, signal=SIGTERM)
                    try:
                        killpg(self._process.pid, SIGTERM)
                        with trio.move_on_after(TIMEOUT_ORPHAN_CANCEL):
                            while True:
                                killpg(self._process.pid, 0)
                                await trio.sleep(0.1)
                        killpg(self._process.pid, SIGKILL)
                    except ProcessLookupError:
                        self._log.debug('process left no orphans')
                        pass
                    else:
                        self._log.debug('killed at least one orphan')
            self._process = None
            self._service_started = trio.Event()
    
    # ## Shutdown timer
    #
    # This task is started when the service is running, but there are no open
    # connections; it's responsible for terminating the task after an idle
    # timeout.
    async def _shutdown_timer(self, task_status):
        self._log.debug('shutdown timer started')
        task_status.started()
        self._service_wanted = trio.Event()

        # If the service gets used while we're waiting for the timeout to expire, `self._service_wanted` will fire, and this task stops.
        with trio.move_on_after(600):
            await self._service_wanted.wait()
            self._log.debug('shutdown timer stopped because service was wanted')
            return
        
        # Otherwise, we shut down the process.
        self._log.debug('shutting down')
        await self.stop()
    
    @asynccontextmanager
    async def use(self):
        self._log.debug('use entered', existing_users=self._users)
        self._service_wanted.set()
        await self._service_started.wait()
        self._users += 1
        try:
            yield self._port_map
        finally:
            self._users -= 1
            self._log.debug('use exited', existing_users=self._users)
            if not self._users:
                # We're using start here, instead of start_soon, because we
                # want self._shutdown_timer to initialise synchronously. If
                # we'd used start_soon, another task could have entered a
                # use() context between us launching it and it
                # unsetting _service_wanted.
                await self._nursery.start(self._shutdown_timer)
    
    async def stop(self):
        """Shut down the service, if it is running."""
        if self._process is not None:
            with trio.move_on_after(5):
                self._log.debug('politely asking process to stop')
                self._process.send_signal(self.signal)
                exit_code = await self._process.wait()
                self._log.debug('process stopped', exit_code=exit_code)
                return
            self._log.debug('slightly less politely asking OS to stop process')
            self._process.kill()
            exit_code = await self._process.wait()
            self._log.debug('process stopped', exit_code=exit_code)
    

async def get_free_port():
    s = trio.socket.socket(family=AF_INET6)
    await s.bind(('::1', 0, 0, 0))
    _, alloc_port, _, _ = s.getsockname()
    s.close()
    return alloc_port

async def wait_for_port(port):
    while True:
        try:
            stream = await trio.open_tcp_stream(host='::1', port=port)
        except OSError as e:
            pass
        else:
            await stream.aclose()
            break
        await trio.sleep(0.1)