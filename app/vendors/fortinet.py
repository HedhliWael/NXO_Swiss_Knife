"""
FortiGate (FortiOS) configuration parser.

Parses a full FortiOS CLI export (the ``.conf`` format, e.g.
``files/FGT_CHATEAUDUN_2_7-2_1761_202610011359.conf``) and normalizes:

    - address          ``config firewall address`` / ``address6``
    - address_group    ``config firewall addrgrp``
    - service          ``config firewall service custom``
    - service_group    ``config firewall service group``
    - rule             ``config firewall policy``
    - interface        ``config system interface``
    - zone             ``config system zone`` (or, when that section is
                       absent, derived from the interfaces' ``set zone``)

Normalized payload schema (shared with the Palo Alto parser so objects are
comparable across vendors):

    address        {"address": "172.16.3.0/24" | "10.0.0.1" | "host.x"
                          | "10.0.0.1 - 10.0.0.254" | "<interface>",
                    "address_type": "cidr" | "ip" | "fqdn" | "iprange"
                                       | "interface" | "other",
                    "description": "..."}
    address_group  {"members": ["A", "B"], "description": "..."}
    service        {"protocol": "tcp" | "udp" | "tcp+udp" | "icmp"
                          | "icmpv6" | "ip",
                    "port": "443" | "88,464" | "1812-1813" | "any" | None,
                    "description": "..."}
    service_group  {"members": ["HTTP", "HTTPS"], "description": "..."}
    rule           {"action": "allow" | "deny" | "reject",
                    "sources": [...], "destinations": [...],
                    "services": [...],
                    "source_interfaces": [...], "destination_interfaces": [...],
                    "source_zones": [...], "destination_zones": [...],
                    "nat": bool, "log": bool, "schedule": "...",
                    "disabled": bool, "description": "..."}
    interface      {"ip": "37.58.190.24/28" | None,
                    "type": "physical" | "vlan" | ...,
                    "alias": "...", "role": "wan" | "lan" | ...,
                    "zone": "..." | None}
    zone           {"members": ["port1", "port2"]}

Notes:

- ``set subnet <ip> <mask>`` (FortiOS 6.x/7.x space form) and CIDR values are
  both normalized to CIDR.
- Address entries without an IP value (``all``, ``none``, iprange/fqdn are
  kept — only value-less entries are skipped) are counted in the warnings.
- Policy names: ``set name "..."`` when present, otherwise the policy id.
- When the export has no ``config system zone`` section, zones are derived
  from ``set zone "..."`` on the interfaces; an export with neither yields
  zero zone objects (rules then carry empty ``*_zones`` lists).
"""

import ipaddress
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseVendorParser, ParsedConfig

CONFIG_LINE = re.compile(r"^\s*config\s+(.+)$")
END_LINE = re.compile(r"^\s*end\s*$")
EDIT_LINE = re.compile(r'^\s+edit\s+(?:"(?P<q>.*?)"|(?P<bare>\S+))\s*$')
SET_LINE = re.compile(r"^\s+set\s+([A-Za-z0-9_-]+)\s+(?P<value>.*)$")
VALUE_TOKEN = re.compile(r'"(?P<quoted>.*?)"|(?P<bare>\S+)')


class FortinetParser(BaseVendorParser):
    vendor_name = "fortinet"
    supported_types = (
        "address",
        "address_group",
        "service",
        "service_group",
        "rule",
        "interface",
        "zone",
    )

    # ------------------------------------------------------------------
    # FortiOS CLI helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_section(lines: List[str], keywords: List[str]) -> Optional[List[str]]:
        """
        Return the lines of the ``config <keywords...>`` block (the ``end``
        line included), or None. Nested ``config``/``end`` pairs are tracked
        so a section ending at the right depth is found.

        Callers may include the leading ``config`` in `keywords`; it is
        dropped here because the match only captures what follows it.
        """
        if keywords and keywords[0] == "config":
            keywords = keywords[1:]

        for i, line in enumerate(lines):
            match = CONFIG_LINE.match(line)
            if match and match.group(1).split() == keywords:
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    if CONFIG_LINE.match(lines[j]):
                        depth += 1
                    elif END_LINE.match(lines[j]):
                        depth -= 1
                    j += 1
                return lines[i + 1 : j]
        return None

    @staticmethod
    def _iter_edits(section_lines: List[str]):
        """Yield (name, body_lines) for each first-level edit block."""
        name: Optional[str] = None
        body: List[str] = []
        for line in section_lines:
            match = EDIT_LINE.match(line)
            if match:
                if name is not None:
                    yield name, body
                name = match.group("q")
                if name is None:
                    name = match.group("bare")
                name = name.strip()
                body = []
            elif name is not None:
                if END_LINE.match(line):
                    # section-level or nested `end`: never part of a body
                    continue
                body.append(line)
        if name is not None:
            yield name, body

    @staticmethod
    def _set_value(body: List[str], key: str) -> Optional[str]:
        """Return the raw value of the first ``set <key>`` (quotes intact)."""
        for line in body:
            match = SET_LINE.match(line)
            if match and match.group(1) == key:
                return match.group("value").strip()
        return None

    @staticmethod
    def _split_values(value: Optional[str]) -> List[str]:
        """Split ``"A" B "C D"`` into ``["A", "B", "C D"]`` (quotes stripped)."""
        out: List[str] = []
        for match in VALUE_TOKEN.finditer(value or ""):
            if match.group("quoted") is not None:
                out.append(match.group("quoted"))
            else:
                out.append(match.group("bare"))
        return out

    @classmethod
    def _set_single(cls, body: List[str], key: str) -> Optional[str]:
        """First value token of a single-value ``set`` (unquoted)."""
        tokens = cls._split_values(cls._set_value(body, key))
        return tokens[0] if tokens else None

    # ------------------------------------------------------------------
    # Value normalizers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cidr(ip: str, mask: Optional[str]) -> Tuple[str, str]:
        """
        Return (value, address_type).

        - ``ip/prefix``              -> (``ip/prefix``, "cidr")
        - ``ip <netmask-or-length>`` -> (CIDR, "cidr")
        - bare ip                    -> (ip, "ip")
        Unparseable values are returned as-is with type "other".
        """
        if mask is None:
            if "/" in ip:
                try:
                    return ipaddress.ip_network(ip, strict=False).compressed, "cidr"
                except ValueError:
                    return ip, "other"
            try:
                ipaddress.ip_address(ip)
                return ip, "ip"
            except ValueError:
                return ip, "other"

        try:
            return ipaddress.ip_network(f"{ip}/{mask}", strict=False).compressed, "cidr"
        except ValueError:
            return f"{ip}/{mask}", "other"

    @staticmethod
    def _normalize_port(spec: str) -> str:
        """Normalize a FortiOS portrange spec: ``88 464`` -> ``88,464``."""
        parts = [p for p in spec.split() if p]
        if not parts:
            return "any"
        for part in parts:
            if part.lower() == "any" or part == "1-65535":
                return "any"
        return ",".join(parts)

    @staticmethod
    def _merge_ports(tcp: Optional[str], udp: Optional[str]) -> Optional[str]:
        """Union of two port specs (used for ``tcp+udp`` services)."""
        if not tcp and not udp:
            return None
        parts: List[str] = []
        for spec in (tcp, udp):
            if spec is None:
                continue
            norm = FortinetParser._normalize_port(spec)
            if norm == "any":
                return "any"
            for part in norm.split(","):
                if part not in parts:
                    parts.append(part)
        return ",".join(parts) if parts else None

    # ------------------------------------------------------------------
    # Section parsers — each returns a list of normalized object dicts
    # ------------------------------------------------------------------

    def _parse_addresses(self, lines: List[str]) -> Tuple[List[Dict], int]:
        objects: List[Dict] = []
        skipped = 0
        seen: set = set()

        for keywords in (
            ["config", "firewall", "address"],
            ["config", "firewall", "address6"],
        ):
            section = self._find_section(lines, keywords)
            if section is None:
                continue

            for name, body in self._iter_edits(section):
                if name in seen:
                    continue
                seen.add(name)

                if name.lower() in ("all", "none"):
                    # FortiOS sentinel objects ("any" / "no match") —
                    # not meaningful as stored address objects.
                    skipped += 1
                    continue

                value = (
                    self._set_value(body, "subnet")
                    or self._set_value(body, "ip")
                    or self._set_value(body, "ip6")
                )

                if value:
                    tokens = value.split()
                    ip_part = tokens[0]
                    mask_part = tokens[1] if len(tokens) > 1 else None
                    address, address_type = self._normalize_cidr(ip_part, mask_part)
                elif (
                    self._set_value(body, "start-ip")
                    and self._set_value(body, "end-ip")
                ):
                    address = f"{self._set_value(body, 'start-ip')} - {self._set_value(body, 'end-ip')}"
                    address_type = "iprange"
                elif (fqdn := self._set_single(body, "fqdn")):
                    address, address_type = fqdn, "fqdn"
                elif (wildcard := self._set_single(body, "wildcard-fqdn")):
                    address, address_type = wildcard, "fqdn"
                elif (iface := self._set_single(body, "associated-interface")):
                    address, address_type = iface, "interface"
                else:
                    # Value-less entries: "all", "none", FABRIC_DEVICE, ...
                    skipped += 1
                    continue

                description = self._set_single(body, "comment")
                payload: Dict[str, Any] = {
                    "address": address,
                    "address_type": address_type,
                }
                if description:
                    payload["description"] = description

                objects.append(
                    {
                        "object_type": "address",
                        "name": name,
                        "description": description,
                        "payload": payload,
                        "raw_excerpt": f'edit "{name}"',
                    }
                )

        return objects, skipped

    def _parse_address_groups(self, lines: List[str]) -> List[Dict]:
        section = self._find_section(lines, ["config", "firewall", "addrgrp"])
        if section is None:
            return []

        objects: List[Dict] = []
        for name, body in self._iter_edits(section):
            members = self._split_values(self._set_value(body, "member"))
            if not members:
                continue

            description = self._set_single(body, "comment")
            payload: Dict[str, Any] = {"members": members}
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "address_group",
                    "name": name,
                    "description": description,
                    "payload": payload,
                    "raw_excerpt": f'edit "{name}"',
                }
            )
        return objects

    def _parse_services(self, lines: List[str]) -> List[Dict]:
        section = self._find_section(
            lines, ["config", "firewall", "service", "custom"]
        )
        if section is None:
            return []

        objects: List[Dict] = []
        for name, body in self._iter_edits(section):
            tcp = self._set_value(body, "tcp-portrange")
            udp = self._set_value(body, "udp-portrange")
            protocol = self._set_single(body, "protocol")
            category = self._set_single(body, "category")

            if protocol:
                protocol = protocol.strip().lower()
                if protocol == "icmp6":
                    protocol = "icmpv6"
                if protocol in ("tcp", "udp", "icmp", "icmpv6", "ip"):
                    if tcp and udp:
                        protocol = "tcp+udp"
                    port = self._merge_ports(tcp, udp) if (tcp or udp) else (
                        "any" if protocol == "ip" else None
                    )
                else:
                    # unknown protocol keyword — keep it verbatim
                    port = self._merge_ports(tcp, udp)
            else:
                if tcp and udp:
                    protocol = "tcp+udp"
                    port = self._merge_ports(tcp, udp)
                elif tcp:
                    protocol = "tcp"
                    port = self._normalize_port(tcp)
                elif udp:
                    protocol = "udp"
                    port = self._normalize_port(udp)
                else:
                    continue  # service without protocol or ports

            payload: Dict[str, Any] = {"protocol": protocol, "port": port}
            if category:
                payload["description"] = category

            objects.append(
                {
                    "object_type": "service",
                    "name": name,
                    "description": category,
                    "payload": payload,
                    "raw_excerpt": f'edit "{name}"',
                }
            )
        return objects

    def _parse_service_groups(self, lines: List[str]) -> List[Dict]:
        section = self._find_section(
            lines, ["config", "firewall", "service", "group"]
        )
        if section is None:
            return []

        objects: List[Dict] = []
        for name, body in self._iter_edits(section):
            members = self._split_values(self._set_value(body, "member"))
            if not members:
                continue

            description = self._set_single(body, "comment")
            payload: Dict[str, Any] = {"members": members}
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "service_group",
                    "name": name,
                    "description": description,
                    "payload": payload,
                    "raw_excerpt": f'edit "{name}"',
                }
            )
        return objects

    def _parse_interfaces(self, lines: List[str]) -> List[Dict]:
        section = self._find_section(lines, ["config", "system", "interface"])
        if section is None:
            return []

        objects: List[Dict] = []
        for name, body in self._iter_edits(section):
            ip_value = self._set_value(body, "ip")
            ip = None
            if ip_value:
                tokens = ip_value.split()
                ip, _ = self._normalize_cidr(tokens[0], tokens[1] if len(tokens) > 1 else None)

            payload: Dict[str, Any] = {"ip": ip}

            for key in ("type", "alias", "role", "zone"):
                value = self._set_single(body, key)
                if value:
                    payload[key] = value

            objects.append(
                {
                    "object_type": "interface",
                    "name": name,
                    "description": payload.get("alias"),
                    "payload": payload,
                    "raw_excerpt": f'edit "{name}"',
                }
            )
        return objects

    def _parse_zones(
        self, lines: List[str], interfaces: List[Dict]
    ) -> List[Dict]:
        """
        Zones come from ``config system zone`` when the export has it;
        otherwise they are derived from the interfaces' ``set zone``.
        """
        zones: Dict[str, Dict[str, Any]] = {}

        section = self._find_section(lines, ["config", "system", "zone"])
        if section is not None:
            for name, body in self._iter_edits(section):
                zones[name] = {
                    "members": self._split_values(self._set_value(body, "member")),
                    "description": self._set_single(body, "comment"),
                }
        else:
            for obj in interfaces:
                zone_name = (obj.get("payload") or {}).get("zone")
                if zone_name:
                    zones.setdefault(zone_name, {"members": [], "description": None})
                    if obj["name"] not in zones[zone_name]["members"]:
                        zones[zone_name]["members"].append(obj["name"])

        objects: List[Dict] = []
        for name, data in zones.items():
            payload: Dict[str, Any] = {"members": data["members"]}
            if data.get("description"):
                payload["description"] = data["description"]

            objects.append(
                {
                    "object_type": "zone",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f'edit "{name}"',
                }
            )
        return objects

    def _parse_policies(
        self, lines: List[str], interface_zone_map: Dict[str, str]
    ) -> List[Dict]:
        section = self._find_section(lines, ["config", "firewall", "policy"])
        if section is None:
            return []

        objects: List[Dict] = []
        for name, body in self._iter_edits(section):
            rule_name = self._set_single(body, "name") or name

            source_interfaces = self._split_values(self._set_value(body, "srcintf"))
            destination_interfaces = self._split_values(
                self._set_value(body, "dstintf")
            )
            sources = self._split_values(self._set_value(body, "srcaddr"))
            destinations = self._split_values(self._set_value(body, "dstaddr"))
            services = self._split_values(self._set_value(body, "service"))

            action = (self._set_single(body, "action") or "accept").lower()
            if action == "accept":
                action = "allow"

            description = self._set_single(body, "comments")

            payload: Dict[str, Any] = {
                "action": action,
                "sources": sources,
                "destinations": destinations,
                "services": services,
                "source_interfaces": source_interfaces,
                "destination_interfaces": destination_interfaces,
                "source_zones": [
                    zone
                    for iface in source_interfaces
                    if (zone := interface_zone_map.get(iface))
                ],
                "destination_zones": [
                    zone
                    for iface in destination_interfaces
                    if (zone := interface_zone_map.get(iface))
                ],
            }

            nat_value = self._set_single(body, "nat")
            if nat_value is not None:
                payload["nat"] = nat_value.lower().startswith("enable")

            if (self._set_single(body, "logtraffic") or "").lower() == "all":
                payload["log"] = True

            if (self._set_single(body, "status") or "").lower() == "disable":
                payload["disabled"] = True

            schedule = self._set_single(body, "schedule")
            if schedule and schedule.lower() != "always":
                payload["schedule"] = schedule

            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "rule",
                    "name": rule_name,
                    "description": description,
                    "payload": payload,
                    "raw_excerpt": f"edit {name}",
                }
            )
        return objects

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def parse_config(
        self,
        raw_data: str,
        selected_types: Optional[List[str]] = None,
    ) -> ParsedConfig:
        if not raw_data or not raw_data.strip():
            raise ValueError("Empty FortiGate configuration provided.")

        lines = raw_data.splitlines()
        parsed = ParsedConfig(vendor=self.vendor_name)
        requested_types = set(selected_types or self.supported_types)

        for obj_type in requested_types:
            if obj_type not in self.supported_types:
                parsed.warnings.append(
                    f"FortinetParser does not implement {obj_type} yet."
                )

        # Interfaces are parsed first: zones (derived form) and policy
        # source/destination zone resolution both need the interface list.
        interfaces = self._parse_interfaces(lines)

        if "interface" in requested_types:
            parsed.objects.extend(interfaces)

        if "zone" in requested_types:
            parsed.objects.extend(self._parse_zones(lines, interfaces))

        if "address" in requested_types:
            addresses, skipped = self._parse_addresses(lines)
            parsed.objects.extend(addresses)
            if skipped:
                word = "entry" if skipped == 1 else "entries"
                parsed.warnings.append(
                    f"Skipped {skipped} address {word} without an IP value "
                    '(e.g. "all", "none").'
                )

        if "address_group" in requested_types:
            parsed.objects.extend(self._parse_address_groups(lines))

        if "service" in requested_types:
            parsed.objects.extend(self._parse_services(lines))

        if "service_group" in requested_types:
            parsed.objects.extend(self._parse_service_groups(lines))

        if "rule" in requested_types:
            interface_zone_map = {
                obj["name"]: (obj.get("payload") or {}).get("zone")
                for obj in interfaces
                if (obj.get("payload") or {}).get("zone")
            }
            parsed.objects.extend(self._parse_policies(lines, interface_zone_map))

        return parsed

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def generate_config(
        self,
        objects: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
    ) -> str:
        # Fortinet has a single ``show``-style format; ``format`` is accepted
        # for parser-signature compatibility and ignored here.
        chunks: List[str] = []

        def section(header: str, entries: List[str]) -> str:
            lines = [header]
            for entry in entries:
                lines.extend(entry.split("\n"))
            lines.append("end")
            return "\n".join(lines)

        def esc(value: Any) -> str:
            return str(value).replace("\\", "\\\\").replace('"', '\\"')

        addresses = [o for o in objects if o.get("object_type") == "address"]
        if addresses:
            entries = []
            for obj in addresses:
                payload = obj.get("payload") or {}
                value = payload.get("address") or ""
                address_type = payload.get("address_type", "cidr")
                parts = [f'    edit "{esc(obj["name"])}"']
                if address_type in ("cidr", "ip"):
                    parts.append(f"        set subnet {value}")
                elif address_type == "iprange":
                    start, _, end = value.partition(" - ")
                    parts.append("        set iprange")
                    parts.append(f"        set start-ip {start}")
                    parts.append(f"        set end-ip {end}")
                elif address_type == "fqdn":
                    parts.append(f'        set fqdn "{esc(value)}"')
                else:
                    parts.append(f"        set subnet {value}")
                if payload.get("description"):
                    parts.append(f'        set comment "{esc(payload["description"])}"')
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config firewall address", entries))

        address_groups = [
            o for o in objects if o.get("object_type") == "address_group"
        ]
        if address_groups:
            entries = []
            for obj in address_groups:
                payload = obj.get("payload") or {}
                parts = [f'    edit "{esc(obj["name"])}"']
                parts.append(
                    "        set member "
                    + " ".join(f'"{esc(m)}"' for m in payload.get("members", []))
                )
                if payload.get("description"):
                    parts.append(f'        set comment "{esc(payload["description"])}"')
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config firewall addrgrp", entries))

        services = [o for o in objects if o.get("object_type") == "service"]
        if services:
            entries = []
            for obj in services:
                payload = obj.get("payload") or {}
                protocol = payload.get("protocol", "tcp")
                port = payload.get("port") or "any"
                parts = [f'    edit "{esc(obj["name"])}"']
                if protocol in ("tcp", "tcp+udp"):
                    parts.append(f"        set tcp-portrange {port}")
                if protocol in ("udp", "tcp+udp"):
                    parts.append(f"        set udp-portrange {port}")
                if protocol in ("icmp", "icmpv6"):
                    parts.append(f"        set protocol {protocol.upper()}")
                if payload.get("description"):
                    parts.append(f'        set category "{esc(payload["description"])}"')
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config firewall service custom", entries))

        service_groups = [
            o for o in objects if o.get("object_type") == "service_group"
        ]
        if service_groups:
            entries = []
            for obj in service_groups:
                payload = obj.get("payload") or {}
                parts = [f'    edit "{esc(obj["name"])}"']
                parts.append(
                    "        set member "
                    + " ".join(f'"{esc(m)}"' for m in payload.get("members", []))
                )
                if payload.get("description"):
                    parts.append(f'        set comment "{esc(payload["description"])}"')
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config firewall service group", entries))

        rules = [o for o in objects if o.get("object_type") == "rule"]
        if rules:
            entries = []
            for index, obj in enumerate(rules, start=1):
                payload = obj.get("payload") or {}
                parts = [f"    edit {index}"]
                parts.append(f'        set name "{esc(obj["name"])}"')
                for key, label in (
                    ("source_interfaces", "srcintf"),
                    ("destination_interfaces", "dstintf"),
                    ("sources", "srcaddr"),
                    ("destinations", "dstaddr"),
                    ("services", "service"),
                ):
                    values = payload.get(key) or []
                    if values:
                        parts.append(
                            f"        set {label} "
                            + " ".join(f'"{esc(v)}"' for v in values)
                        )
                parts.append(f"        set action {payload.get('action', 'allow')}")
                if payload.get("nat"):
                    parts.append("        set nat enable")
                if payload.get("log"):
                    parts.append("        set logtraffic all")
                if payload.get("schedule"):
                    parts.append(f'        set schedule "{esc(payload["schedule"])}"')
                if payload.get("description"):
                    parts.append(f'        set comments "{esc(payload["description"])}"')
                if payload.get("disabled"):
                    parts.append("        set status disable")
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config firewall policy", entries))

        interfaces = [o for o in objects if o.get("object_type") == "interface"]
        if interfaces:
            entries = []
            for obj in interfaces:
                payload = obj.get("payload") or {}
                parts = [f'    edit "{esc(obj["name"])}"']
                if payload.get("type"):
                    parts.append(f"        set type {payload['type']}")
                if payload.get("ip"):
                    parts.append(f"        set ip {payload['ip']}")
                if payload.get("alias"):
                    parts.append(f'        set alias "{esc(payload["alias"])}"')
                if payload.get("role"):
                    parts.append(f"        set role {payload['role']}")
                if payload.get("zone"):
                    parts.append(f'        set zone "{esc(payload["zone"])}"')
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config system interface", entries))

        zones = [o for o in objects if o.get("object_type") == "zone"]
        if zones:
            entries = []
            for obj in zones:
                payload = obj.get("payload") or {}
                parts = [f'    edit "{esc(obj["name"])}"']
                if payload.get("members"):
                    parts.append(
                        "        set member "
                        + " ".join(f'"{esc(m)}"' for m in payload["members"])
                    )
                parts.append("    next")
                entries.append("\n".join(parts))
            chunks.append(section("config system zone", entries))

        if not chunks:
            return "# No supported FortiGate objects selected."

        return "\n\n".join(chunks)
