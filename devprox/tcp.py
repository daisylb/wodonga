import trio
import re
import structlog
from os import environ

from .service import Service

REDIR_RE = re.compile(r'([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\]')

log = structlog.get_logger()

async def get_real_target(stream: trio.SocketStream, logger):
    peer_ip, peer_port, *_ = stream.socket.getpeername()
    self_ip, self_port, *_ = stream.socket.getsockname()

    process = await trio.run_process(('sudo', 'pfctl', '-s', 'state'), capture_stdout=True)
    for match in REDIR_RE.finditer(process.stdout.decode('utf8')):
        m_self_ip, m_self_port, m_target_ip, m_target_port, m_peer_ip, m_peer_port = match.groups()
        if m_self_ip == self_ip and int(m_self_port) == self_port and m_peer_ip == peer_ip and int(m_peer_port) == peer_port:
            break
    else:
        logger.error('not found in redirect table', self_ip=self_ip, self_port=self_port, peer_ip=peer_ip, peer_port=peer_port)
        raise ValueError("Connection not found in redirect table")
    
    return m_target_ip, int(m_target_port)




def tcp_handler_factory(service_dict):
    async def tcp_connection_handler(stream):
        logger = structlog.get_logger(connection_id=f'{trio.current_time()}.{id(stream)}')
        try:
            target_ip, target_port = await get_real_target(stream, logger)
        except ValueError:
            logger.error('not found in lookup table')
            await stream.aclose()
            return
        
        try:
            service = service_dict[target_ip]
        except KeyError:
            logger.error('no registered service', ip=target_ip)
            await stream.aclose()
            return

        port_map = await service.start()

        async with service.use() as port_map:
            try:
                mapped_port = port_map[target_port]
            except KeyError:
                logger.error('service doesn\'t use port', service=service, port=target_port)
                await stream.aclose()
                return
                
            await proxy(stream, '::1', mapped_port)
    return tcp_connection_handler


async def one_way_proxy(source: trio.abc.ReceiveStream, sink: trio.abc.SendStream):
        while True:
            data = await source.receive_some()
            if data == b'':
                break
            await sink.send_all(data)


async def proxy(incoming: trio.SocketStream, target_host: str, target_port: int):
    outgoing = await trio.open_tcp_stream(target_host, target_port)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(one_way_proxy, incoming, outgoing)
        nursery.start_soon(one_way_proxy, outgoing, incoming)
    

async def main():
    async with trio.open_nursery() as nursery:
        services = {
            'fd7f:1fa7:68ca:202f:4b5c:aef6:fc98:c103':
                Service(
                    command=('sh', '-c', 'cd ~/Projects/home/dist && python -m http.server --bind ::1 $PORT_80'),
                    ports=(80,),
                    nursery=nursery,
                    env=environ,
                    logger=structlog.get_logger(),
                )
        }
        handler = tcp_handler_factory(services)
        await trio.serve_tcp(handler, 55555, host='::1')

if __name__ == "__main__":
    trio.run(main)