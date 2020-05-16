import asyncio
import re
from subprocess import PIPE

REDIR_RE = re.compile(r'([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\] <- ([0-9a-f\:]+)\[([0-9]+)\]')

async def tcp_connection_handler(reader, writer):
    peer_ip, peer_port, *_ = writer.get_extra_info('peername')
    self_ip, self_port, *_ = writer.get_extra_info('sockname')
    writer.write(f'{peer_ip=}, {peer_port=}, {self_ip=}, {self_port=}\n'.encode('utf8'))

    process = await asyncio.create_subprocess_exec('sudo', 'pfctl', '-s', 'state', stdout=PIPE)
    out, _ = await process.communicate()
    print(out)
    for match in REDIR_RE.finditer(out.decode('utf8')):
        m_self_ip, m_self_port, m_target_ip, m_target_port, m_peer_ip, m_peer_port = match.groups()
        if m_self_ip == self_ip and int(m_self_port) == self_port and m_peer_ip == peer_ip and int(m_peer_port) == peer_port:
            writer.write(f'{m_target_ip=}, {m_target_port=}\n'.encode('utf8'))
            break
    else:
        writer.write(f'not found'.encode('utf8'))
    

async def main():
    server = await asyncio.start_server(tcp_connection_handler, host='::1', port=55555)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())