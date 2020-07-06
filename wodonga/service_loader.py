from .service import Service
from pathlib import Path
from appdirs import user_data_dir
import typing as t
from ipaddress import IPv6Address, IPv6Network
import tomlkit
import trio
from structlog import BoundLogger
from cityhash import CityHash32

default_dir = user_data_dir("Wodonga", "Leigh Brenecki")
network = IPv6Network('fd7f:1fa7:68ca:202f:4b5c:aef6::/96')

class ServiceManager:
    service_map: t.Dict[str, Service]
    ip_map: t.Dict[IPv6Address, str]
    _log: BoundLogger

    def __init__(self, config_dir=default_dir, *, nursery: trio.Nursery, logger: BoundLogger):
        self.service_map = {}
        self.ip_map = {}
        self._log = logger.bind(manager=self)

        config_path = Path(config_dir)
        self._log.info('loading configs', config_path=config_path)
        for conf in config_path.glob('*.toml'):
            with conf.open() as f:
                data = tomlkit.loads(f.read())
            
            name = conf.stem
            ip = network[CityHash32(name)]
            if 'alias-of' in data:
                self.ip_map[ip] = data['alias-of']
            else:
                name = conf.stem
                service = Service(
                    command=data['command'],
                    workdir=Path(data.get('workdir', '~')).expanduser(),
                    ports=data['ports'] if 'ports' in data else [data['port']],
                    nursery=nursery,
                    logger=logger.bind(service=name),
                    env=data['env'],
                )
                self.service_map[name] = service
                self.ip_map[ip] = name
                self._log.debug('service mapped', name=name, ip=ip)

    def __getitem__(self, key):
        ip = IPv6Address(key)
        return self.service_map[self.ip_map[ip]]