import trio
import re

REDIR_RE = re.compile(r'([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\]')

async def tcp_connection_handler(stream):
    peer_ip, peer_port, *_ = stream.socket.getpeername()
    self_ip, self_port, *_ = stream.socket.getsockname()
    await stream.send_all(f'{peer_ip=}, {peer_port=}, {self_ip=}, {self_port=}\n'.encode('utf8'))

    process = await trio.run_process(('sudo', 'pfctl', '-s', 'state'), capture_stdout=True)
    for match in REDIR_RE.finditer(process.stdout.decode('utf8')):
        m_self_ip, m_self_port, m_target_ip, m_target_port, m_peer_ip, m_peer_port = match.groups()
        if m_self_ip == self_ip and int(m_self_port) == self_port and m_peer_ip == peer_ip and int(m_peer_port) == peer_port:
            await stream.send_all(f'{m_target_ip=}, {m_target_port=}\n'.encode('utf8'))
            break
    else:
        await stream.send_all(f'not found'.encode('utf8'))
    

async def main():
    await trio.serve_tcp(tcp_connection_handler, 55555, host='::1')

if __name__ == "__main__":
    trio.run(main)