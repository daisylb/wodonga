import trio
import typing as t
from socket import AF_INET6
from errno import ECONNREFUSED, errorcode
from contextlib import asynccontextmanager
from structlog import BoundLogger

class Service:
    _service_wanted: trio.Event
    _service_started: trio.Event
    _process: t.Optional[trio.Process] = None
    _port_map: t.Optional[t.Mapping[int, int]] = None
    _users = 0
    _nursery: trio.Nursery
    _log: BoundLogger

    def __init__(self, *, command, ports, nursery, logger: BoundLogger, env={}):
        self.command = command
        self.env = env
        self.ports = ports
        self._nursery = nursery
        self._service_wanted = trio.Event()
        self._service_started = trio.Event()
        self._log = logger.bind(service=self)
        nursery.start_soon(self._run_loop)

    async def _run_loop(self):
        while True:
            await self._service_wanted.wait()

            # TODO: flapping detection / exponential backoff

            self._port_map = {}
            for port in self.ports:
                # TODO: do this concurrently
                s = trio.socket.socket(family=AF_INET6)
                await s.bind(('::1', 0, 0, 0))
                _, alloc_port, _, _ = s.getsockname()
                s.close()
                self._port_map[port] = alloc_port
            
            env = {**self.env, **{f'PORT_{port}': f'{alloc_port}' for port, alloc_port in self._port_map.items()}}

            self._process = await trio.open_process(self.command, env=env)
            
            for port in self._port_map.values():
                while True:
                    try:
                        stream = await trio.open_tcp_stream(host='::1', port=port)
                    except OSError as e:
                        pass
                    else:
                        await stream.aclose()
                        break
                    await trio.sleep(0.1)

            self._service_started.set()
            await self._process.wait()
            self._process = None

            # We don't reset _service_wanted; if the service is idle it would
            # have been reset at the start of the idle time by _shutdown_timer.
            self._service_started = trio.Event()
    
    async def _shutdown_timer(self, task_status):
        self._log.debug('shutdown timer started')
        task_status.started()
        self._service_wanted = trio.Event()

        with trio.move_on_after(600):
            await self._service_wanted.wait()
            self._log.debug('shutdown timer stopped because service was wanted')
            return
        
        self._log.debug('shutting down')
        await self.stop()
    
    async def start(self):
        """Ensure the service has started and is ready to connect to.

        If you await on this function, the service will almost certainly be
        running and ready to connect to when it returns. (There are
        unavoidable but rare circumstances where it might not if it just so
        happens to crash at the exact right moment.)
        """
        self._service_wanted.set()
        await self._service_started.wait()
        return self._port_map
    
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
            self._process.terminate()
            # TODO: block until process is actually shut down
            # TODO: forcibly kill process if needed after a timeout
    