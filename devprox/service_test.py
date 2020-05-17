import pytest
import trio

from . import service

async def test_service(nursery):
    s = service.Service(command=('sh', '-c', 'sleep 1; nc -lk ::1 $PORT_80'), ports=(80,), nursery=nursery)
    port_map = await s.start()
    stream = await trio.open_tcp_stream(host='::1', port=port_map[80])
    await stream.send_all(b'hi')
    await stream.aclose()
