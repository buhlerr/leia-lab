#!/bin/sh
# Admin (8000) e API (8080) da Leia so via Pangolin: as portas aceitam apenas os conectores Newt do
# site "proxmox" (host pve 192.168.0.9 e CT 103 192.168.0.128) e os containers da propria stack
# (redes internas do Docker, interfaces br-*: o admin chama a API por http://leia-api:8080).
# A LAN entra por eth0 e continua barrada. Idempotente, e a troca e um unico commit do
# iptables-restore: nao ha instante em que a cadeia exista sem o DROP (VIT-33).
set -e
rules='*filter
:LEIA-ADMIN - [0:0]
-A LEIA-ADMIN -s 192.168.0.9 -j RETURN
-A LEIA-ADMIN -s 192.168.0.128 -j RETURN
-A LEIA-ADMIN -i br-+ -j RETURN
-A LEIA-ADMIN -j DROP
'
for port in 8000 8080; do
  jump="DOCKER-USER -p tcp -m conntrack --ctorigdstport $port --ctdir ORIGINAL -j LEIA-ADMIN"
  iptables -C $jump 2>/dev/null || rules="$rules-I $jump
"
done
printf '%sCOMMIT\n' "$rules" | iptables-restore --noflush
