#!/bin/sh
# Admin da Leia so via Pangolin: a porta 8000 aceita apenas os conectores Newt do site "proxmox"
# (host pve 192.168.0.9 e CT 103 192.168.0.128). Idempotente.
set -e
iptables -N LEIA-ADMIN 2>/dev/null || iptables -F LEIA-ADMIN
iptables -A LEIA-ADMIN -s 192.168.0.9 -j RETURN
iptables -A LEIA-ADMIN -s 192.168.0.128 -j RETURN
iptables -A LEIA-ADMIN -j DROP
iptables -C DOCKER-USER -p tcp -m conntrack --ctorigdstport 8000 --ctdir ORIGINAL -j LEIA-ADMIN 2>/dev/null \
  || iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8000 --ctdir ORIGINAL -j LEIA-ADMIN
