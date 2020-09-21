use pnet::datalink;
use pnet::ipnetwork::{IpNetwork, Ipv6Network};
use std::net::Ipv6Addr;


fn main() {
    let LINK_LOCAL = Ipv6Network::new(Ipv6Addr::new(0xfe80, 0, 0, 0, 0, 0, 0, 0), 10).unwrap();
    for iface in datalink::interfaces() {
        for ip in iface.ips {
            if let IpNetwork::V6(ip6) = ip {
                if !ip6.is_subnet_of(LINK_LOCAL){
                    let name = &iface.name;
                    let addr = ip6.ip().to_string();
                    let subnet = ip6.to_string();
                    println!("rdr pass on {} inet6 proto tcp from any to fd7f:1fa7:68ca:202f:f34a:65d7::/96 port 1:65535 -> {} port 55555", name, addr);
                }
            }
        }
    }
}
