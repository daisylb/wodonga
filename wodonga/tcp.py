import trio
import re
import structlog
import errno

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
        print(stream.socket.getpeername(), stream.socket.getsockname())
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

        async with service.use() as port_map:
            try:
                mapped_port = port_map[target_port]
            except KeyError:
                logger.error('service doesn\'t use port', service=service, port=target_port)
                await stream.aclose()
                return
            try: 
               await proxy(stream, '::1', mapped_port)
            except OSError:
                logger.error('Error connecting to service', service=service, port=target_port, mapped_port=mapped_port, exc_info=True)
    return tcp_connection_handler


async def one_way_proxy(source: trio.abc.ReceiveStream, sink: trio.abc.SendStream, cancel_scope: trio.CancelScope):
        try:
            while True:
                data = await source.receive_some()
                if data == b'':
                    break
                await sink.send_all(data)
        except trio.BrokenResourceError:
            print('broken pipe')
        cancel_scope.cancel()


async def proxy(incoming: trio.SocketStream, target_host: str, target_port: int):
    raise_after = trio.current_time() + 20
    while True:
        try:
            outgoing = await trio.open_tcp_stream(target_host, target_port)
        except OSError as e:
            if not isinstance(e.__cause__, ConnectionRefusedError):
                raise
            if trio.current_time() > raise_after:
                raise
        else:
            break
        await trio.sleep(0.1)



    async with trio.open_nursery() as nursery:
        nursery.start_soon(one_way_proxy, incoming, outgoing, nursery.cancel_scope)
        nursery.start_soon(one_way_proxy, outgoing, incoming, nursery.cancel_scope)
