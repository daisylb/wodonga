use pnet::datalink;
use pnet::ipnetwork::{IpNetwork, Ipv6Network};
use std::net::Ipv6Addr;
use std::process::exit;
use std::env::args;
use std::process::{Command, Stdio};
use std::io::Write;


fn main() {
    let arguments: Vec<String> = args().collect();

    let incoming_addr: Ipv6Addr = arguments.get(1).expect("no incoming addr provided").parse().expect("incoming addr not a valid ipv6");
    let incoming_port: u16 = arguments.get(2).expect("no incoming port provided").parse().expect("incoming port not a valid u16");
    let outgoing_port: u16 = arguments.get(3).expect("no outgoing port provided").parse().expect("outgoing port not a valid u16");

    let target_net = Ipv6Network::new(Ipv6Addr::new(0xfd7f, 0x1fa7, 0x68ca, 0x202f, 0, 0, 0, 0), 64).unwrap();
    let link_local = Ipv6Network::new(Ipv6Addr::new(0xfe80, 0, 0, 0, 0, 0, 0, 0), 10).unwrap();

    if !target_net.contains(incoming_addr){
        panic!("incoming addr not a socket garden addr");
    }
    
    let anchor = format!("com.apple/250.socket-garden.{:x}.{:x}", u128::from(incoming_addr), incoming_port);
    
    println!("Writing to anchor {}", anchor);
    
    let mut pf = Command::new("/sbin/pfctl").env_clear().arg("-a").arg(anchor).arg("-Ef").arg("-").stdin(Stdio::piped()).spawn().expect("Couldn't run pf");
    let stdin = pf.stdin.as_mut().expect("Failed to open stdin");

    for iface in datalink::interfaces() {
        for ip in iface.ips {
            if let IpNetwork::V6(ip6) = ip {
                if !ip6.is_subnet_of(link_local){
                    let if_name = &iface.name;
                    let outgoing_addr = ip6.ip().to_string();
                    write!(stdin, "rdr pass on {} inet6 proto tcp from any to {} port {} -> {} port {}\n", if_name, incoming_addr, incoming_port, outgoing_addr, outgoing_port).unwrap();
                }
            }
        }
    }
}
