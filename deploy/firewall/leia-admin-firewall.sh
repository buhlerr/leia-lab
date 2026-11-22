#!/bin/sh
# Admin (8000) e API (8080) da Leia so via Pangolin: as portas aceitam apenas os conectores Newt do
# site "proxmox" (host pve 192.168.0.9 e CT 103 192.168.0.128) e os containers da propria stack
# (redes internas do Docker, interfaces br-*: o admin chama a API por http://leia-api:8080).
# A LAN entra por eth0 e continua barrada. Idempotente.
set -e
iptables -N LEIA-ADMIN 2>/dev/null || iptables -F LEIA-ADMIN
iptables -A LEIA-ADMIN -s 192.168.0.9 -j RETURN
iptables -A LEIA-ADMIN -s 192.168.0.128 -j RETURN
iptables -A LEIA-ADMIN -i br-+ -j RETURN
iptables -A LEIA-ADMIN -j DROP
for port in 8000 8080; do
  iptables -C DOCKER-USER -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -j LEIA-ADMIN 2>/dev/null \
    || iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport "$port" --ctdir ORIGINAL -j LEIA-ADMIN
done
