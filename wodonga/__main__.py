import trio
import structlog
import signal
from .service_loader import ServiceManager
from .tcp import tcp_handler_factory


async def handle_signals(nursery: trio.Nursery, log: structlog.BoundLogger):
    with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for sig in signals:
            log.info('shutdown requested', signal=sig)
            nursery.cancel_scope.cancel()

async def main():
    async with trio.open_nursery() as nursery:
        logger = structlog.get_logger()
        nursery.start_soon(handle_signals, nursery, logger)
        manager = ServiceManager(nursery=nursery, logger=logger)
        handler = tcp_handler_factory(manager)
        logger.info('starting up', port=55555)
        await trio.serve_tcp(handler, 55555, host='::1')

if __name__ == "__main__":
    trio.run(main)