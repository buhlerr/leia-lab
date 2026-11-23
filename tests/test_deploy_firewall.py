"""O firewall do admin nunca deixa as portas 8000/8080 abertas para a LAN, nem durante a troca (VIT-33).

O script roda contra um ``iptables``/``iptables-restore`` falso no PATH: este mesmo arquivo, executado como
programa, guarda as cadeias num JSON e grava um retrato depois de cada mudanca efetivada. O teste avalia um
pacote da LAN em cada retrato, como o kernel faria entre duas chamadas.
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "firewall" / "leia-admin-firewall.sh"
PORTS = ("8000", "8080")
LAN = {"src": "192.168.0.50", "iface": "eth0"}
DOCKER_DEFAULT = [["-j", "RETURN"]]
BUILTIN_TARGETS = {"ACCEPT", "DROP", "RETURN"}


class IptablesError(Exception):
    pass


def _target(rule):
    return rule[rule.index("-j") + 1] if "-j" in rule else None


def _require(chains, name):
    if name not in chains:
        raise IptablesError(f"No chain/target/match by that name: {name}")


def _check_target(chains, rule):
    target = _target(rule)
    if target is not None and target not in BUILTIN_TARGETS:
        _require(chains, target)


def apply(chains, args):
    op, chain, rule = args[0], args[1], args[2:]
    if op == "-N":
        if chain in chains:
            raise IptablesError("Chain already exists.")
        chains[chain] = []
        return
    _require(chains, chain)
    if op == "-F":
        chains[chain] = []
    elif op in ("-A", "-I"):
        if op == "-I" and rule and rule[0].isdigit():
            pos, rule = int(rule[0]) - 1, rule[1:]
        else:
            pos = len(chains[chain]) if op == "-A" else 0
        _check_target(chains, rule)
        chains[chain].insert(pos, rule)
    elif op == "-R":
        _check_target(chains, rule[1:])
        chains[chain][int(rule[0]) - 1] = rule[1:]
    elif op in ("-C", "-D"):
        if rule not in chains[chain]:
            raise IptablesError("Bad rule (does a matching rule exist in that chain?).")
        if op == "-D":
            chains[chain].remove(rule)
    elif op == "-X":
        if chains[chain] or any(_target(r) == chain for rules in chains.values() for r in rules):
            raise IptablesError("Directory not empty / chain in use")
        del chains[chain]
    elif op == "-E":
        chains[rule[0]] = chains.pop(chain)
        for rules in chains.values():
            for r in rules:
                if _target(r) == chain:
                    r[r.index("-j") + 1] = rule[0]
    else:
        raise IptablesError(f"fake iptables does not model {op}")


def restore(chains, text, noflush):
    work = {k: [list(r) for r in v] for k, v in chains.items()} if noflush else {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "*filter":
            continue
        if line.startswith("*"):
            raise IptablesError(f"fake iptables-restore only models the filter table: {line}")
        if line == "COMMIT":
            return work
        if line.startswith(":"):
            work[line[1:].split()[0]] = []
            continue
        apply(work, shlex.split(line))
    raise IptablesError("missing COMMIT")


def fake_main(prog, argv):
    state_path = Path(os.environ["FAKE_IPTABLES_STATE"])
    state = json.loads(state_path.read_text())
    try:
        if prog == "iptables-restore":
            chains = restore(state["chains"], sys.stdin.read(), "--noflush" in argv or "-n" in argv)
        else:
            chains = {k: [list(r) for r in v] for k, v in state["chains"].items()}
            apply(chains, [a for a in argv if a != "-w"])
            if argv[0] == "-C":
                return 0
    except IptablesError as e:
        print(f"{prog}: {e}", file=sys.stderr)
        return 1
    state["chains"] = chains
    state["history"].append(chains)
    state_path.write_text(json.dumps(state))
    return 0


def _matches(rule, packet):
    it = iter(rule)
    for tok in it:
        if tok == "-s" and next(it).removesuffix("/32") != packet["src"]:
            return False
        if tok == "-i":
            iface = next(it)
            if not (packet["iface"].startswith(iface[:-1]) if iface.endswith("+") else packet["iface"] == iface):
                return False
        if tok == "--ctorigdstport" and next(it) != packet["dport"]:
            return False
    return True


def verdict(chains, chain, packet):
    for rule in chains[chain]:
        if not _matches(rule, packet):
            continue
        target = _target(rule)
        if target == "RETURN":
            return None
        if target in ("ACCEPT", "DROP"):
            return target
        if target is not None and (v := verdict(chains, target, packet)) is not None:
            return v
    return None


def lan_dropped(chains, port):
    return verdict(chains, "DOCKER-USER", {**LAN, "dport": port}) == "DROP"


@pytest.fixture
def firewall(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"chains": {"DOCKER-USER": DOCKER_DEFAULT}, "history": []}))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for prog in ("iptables", "iptables-restore"):
        shim = bindir / prog
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" {prog} "$@"\n')
        shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_IPTABLES_STATE": str(state)}

    def run():
        subprocess.run(["sh", str(SCRIPT)], env=env, check=True, capture_output=True, text=True)
        return json.loads(state.read_text())

    return run


def test_reaplicar_nunca_deixa_a_lan_alcancar_as_portas(firewall):
    first = firewall()
    assert all(lan_dropped(first["chains"], p) for p in PORTS)

    second = firewall()
    during = second["history"][len(first["history"]) :]
    assert during, "a segunda execucao nao chamou o iptables"
    for i, chains in enumerate(during):
        for port in PORTS:
            assert lan_dropped(chains, port), f"porta {port} aberta para a LAN no passo {i}: {chains}"


def test_estado_final_libera_so_newt_e_docker_e_e_idempotente(firewall):
    firewall()
    chains = firewall()["chains"]

    for port in PORTS:
        assert lan_dropped(chains, port)
        for src, iface in (("192.168.0.9", "eth0"), ("192.168.0.128", "eth0"), ("172.18.0.5", "br-1a2b")):
            assert verdict(chains, "DOCKER-USER", {"src": src, "iface": iface, "dport": port}) is None
    assert verdict(chains, "DOCKER-USER", {**LAN, "dport": "5432"}) is None
    assert chains["DOCKER-USER"][-1] == DOCKER_DEFAULT[0], "a regra RETURN do Docker sumiu"
    assert len(chains["DOCKER-USER"]) == len(PORTS) + 1, chains["DOCKER-USER"]


if __name__ == "__main__":
    sys.exit(fake_main(sys.argv[1], sys.argv[2:]))
