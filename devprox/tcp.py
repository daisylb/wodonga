import trio
import re
import structlog

REDIR_RE = re.compile(r'([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\]')

log = structlog.get_logger()

async def tcp_connection_handler(stream):
    logger = structlog.get_logger(connection_id=f'{trio.current_time()}.{id(stream)}')
    peer_ip, peer_port, *_ = stream.socket.getpeername()
    self_ip, self_port, *_ = stream.socket.getsockname()

    process = await trio.run_process(('sudo', 'pfctl', '-s', 'state'), capture_stdout=True)
    for match in REDIR_RE.finditer(process.stdout.decode('utf8')):
        m_self_ip, m_self_port, m_target_ip, m_target_port, m_peer_ip, m_peer_port = match.groups()
        if m_self_ip == self_ip and int(m_self_port) == self_port and m_peer_ip == peer_ip and int(m_peer_port) == peer_port:
            await stream.send_all(f'{m_target_ip=}, {m_target_port=}\n'.encode('utf8'))
            break
    else:
        await stream.aclose()
        logger.error('not found in redirect table', self_ip=self_ip, self_port=self_port, peer_ip=peer_ip, peer_port=peer_port)
    
    target_ip = m_target_ip
    target_port = int(m_target_port)
    logger.debug('found in redirect table', target_ip=target_ip, target_port=target_port)

    # TODO: dispatch to service pool
    

async def main():
    await trio.serve_tcp(tcp_connection_handler, 55555, host='::1')

if __name__ == "__main__":
    trio.run(main)