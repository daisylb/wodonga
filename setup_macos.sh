#!/bin/sh
route add -inet6 fd7f:1fa7:68ca:202f:4b5c:aef6::/96 ::1
echo "rdr pass inet6 proto tcp from any to fd7f:1fa7:68ca:202f:4b5c:aef6::/96 port 1:65535 -> ::1 port 55555" | pfctl -a "com.apple/250.wodonga" -Ef -
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
