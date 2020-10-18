import signal
from functools import partial

import structlog
import trio

from .platform import serve_tcp
from .service_loader import ServiceManager
from .tcp import tcp_handler_factory


async def handle_signals(nursery: trio.Nursery, log: structlog.BoundLogger):
    with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for sig in signals:
            log.info("shutdown requested", signal=sig)
            nursery.cancel_scope.cancel()


async def main():
    async with trio.open_nursery() as nursery:
        logger = structlog.get_logger()
        nursery.start_soon(handle_signals, nursery, logger)
        manager = ServiceManager(nursery=nursery, logger=logger)
        for service in manager.service_map.values():
            for port in service.ports:
                service_handler = tcp_handler_factory(service, port, logger)
                for ip in manager.ip_reverse_map[service.name]:
                    nursery.start_soon(
                        partial(serve_tcp, service_handler, port, host=ip)
                    )


if __name__ == "__main__":
    trio.run(main)
