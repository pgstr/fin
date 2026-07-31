#!/bin/sh
set -eu

# Fin has no runtime network dependencies. Permit loopback health checks and
# replies to ingress connections, but reject every connection initiated by a
# compromised demo process.
iptables -C OUTPUT -o lo -j ACCEPT 2>/dev/null \
    || iptables -A OUTPUT -o lo -j ACCEPT
iptables -C OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null \
    || iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -P OUTPUT DROP

ip6tables -C OUTPUT -o lo -j ACCEPT 2>/dev/null \
    || ip6tables -A OUTPUT -o lo -j ACCEPT
ip6tables -C OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null \
    || ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -P OUTPUT DROP

exec /usr/local/bin/finanzplaner-entrypoint "$@"
