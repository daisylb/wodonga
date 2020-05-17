#!/bin/sh
route add -inet6 fd7f:1fa7:68ca:202f:4b5c:aef6::/96 ::1
echo -e "rdr pass proto tcp from any to fd7f:1fa7:68ca:202f:4b5c:aef6::/96 -> ::1 port 2000" | pfctl -a "com.apple/250.devprox" -Ef -