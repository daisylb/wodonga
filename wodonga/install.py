import sys
from appdirs import user_log_dir
from pathlib import Path
import os
from shutil import chown
from subprocess import check_call
from ipaddress import IPv6Network
from cityhash import CityHash32

DARWIN_LAUNCH_DAEMON = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>au.net.leigh.wodonga.{dns_prefix}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string><![CDATA[
sysctl -w net.inet.ip.forwarding=1
sysctl -w net.inet6.ip6.forwarding=1
route add -inet6 {network_cidr} ::1
echo "rdr pass inet6 proto tcp from any to {network_cidr} port 1:65535 -> ::1 port {server_port}" | pfctl -a "com.apple/250.wodonga.{dns_prefix}" -Ef -
ifconfig feth99 create
ifconfig feth99 inet6 fd77:1fa7:202f:acab::1 prefixlen 128
scutil <<EOI
d.init
d.add Addresses * fd77:1fa7:202f:acab::1
d.add DestAddresses * fd77:1fa7:202f:acab::1
d.add Flags * 0 0
d.add InterfaceName feth99
d.add PrefixLength 128
set State:/Network/Service/wodonga-dummy-feth/IPv6
set Setup:/Network/Service/wodonga-dummy-feth/IPv6
EOI
        ]]></string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""

DARWIN_LAUNCH_AGENT = """
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>au.net.leigh.wodonga.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>-m</string>
        <string>wodonga</string>
    </array>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>

"""

GLOBAL_NETWORK = IPv6Network('fd7f:1fa7:68ca:202f::/64')

def install_darwin():
    dns_prefix = input("DNS prefix: ")
    network = IPv6Network((GLOBAL_NETWORK[CityHash32(dns_prefix) << 32], 96))
    network_cidr = str(network)
    context = {
        "dns_prefix": dns_prefix,
        "network_cidr": network_cidr,
        "server_port": '55555',
        "python_bin": sys.executable,
        "log_path": user_log_dir("Wodonga", "Leigh Brenecki") + '/server.log',
    }

    launch_daemon_text = DARWIN_LAUNCH_DAEMON.format(**context)
    launch_agent_text = DARWIN_LAUNCH_AGENT.format(**context)
    home = Path('~' + os.environ['SUDO_USER']).expanduser()
    launch_agent_path = home / 'Library' / 'LaunchAgents' / 'au.net.leigh.wodonga.server.plist'
    launch_daemon_path = Path('/Library/LaunchDaemons') / f'au.net.leigh.wodonga.{dns_prefix}.plist'

    with launch_daemon_path.open('x') as f:
        f.write(launch_daemon_text)
    
    with launch_agent_path.open('x') as f:
        f.write(launch_agent_text)
    
    chown(launch_agent_path, user=os.environ['SUDO_USER'])
    check_call(('launchctl', 'bootstrap', 'system', launch_daemon_path))
    check_call(('launchctl', 'bootstrap', f'gui/{os.environ["SUDO_UID"]}', launch_agent_path))
    
if __name__ == "__main__":
    install_darwin()