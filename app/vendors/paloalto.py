"""
Palo Alto Networks (PAN-OS) configuration parser.

Handles the three export flavors found in the wild (reference samples in
``files/``):

- PAN-OS XML device export (``<config version="...">`` root), minified or
  pretty-printed — objects live directly under the vsys entry in PAN-OS 11.x
  (``devices/entry/vsys/entry/address`` …) and under ``vsys/entry/objects``
  in older versions;
- app-generated ``<paloalto>`` documents (``<objects>`` wrapper);
- the set (``show``) format export (``.txt``, one ``set ...`` per line).

Normalized elements (same payload schema as the Fortinet parser):

    address, address_group, service, service_group, rule, interface, zone

Notes:

- In device exports a security rule's ``<from>``/``<to>`` hold the source /
  destination ZONES while ``<source>``/``<destination>`` hold the address
  objects; in app-generated documents the address lists live in
  ``<from>``/``<to>`` (zones are then empty).
- Zones: ``<network><layer3><member>`` entries under the vsys/zone (or
  device network/zone) element, i.e. interface units.
- Interfaces are parsed from ``network/interface/<type>/unit/entry`` when a
  full device export is provided (object-only exports carry an empty
  ``<interface>`` element and simply yield none).
- Set format: ``set address / address-group / service / service-group /
  rulebase security rules / zone / devices system <iface>`` lines are
  understood; ``no set`` lines and unknown fields are ignored.
"""

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

from .base import BaseVendorParser, ParsedConfig

INTERFACE_TYPES = ("ethernet", "virtual-wire", "vlan", "tunnel", "loopback")


class PaloAltoParser(BaseVendorParser):
    vendor_name = "paloalto"
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
    # Entry point
    # ------------------------------------------------------------------

    def parse_config(
        self,
        raw_data: str,
        selected_types: Optional[List[str]] = None,
    ) -> ParsedConfig:
        if not raw_data or not raw_data.strip():
            raise ValueError("Empty Palo Alto configuration provided.")

        stripped = raw_data.lstrip()
        if stripped.startswith("<"):
            objects, warnings = self._parse_xml(raw_data)
        elif self._looks_like_set_format(raw_data):
            objects, warnings = self._parse_set(raw_data)
        else:
            raise ValueError(
                "Input does not look like a Palo Alto configuration export "
                "(expected XML or set/show format)."
            )

        parsed = ParsedConfig(vendor=self.vendor_name)
        parsed.warnings.extend(warnings)

        requested_types = set(selected_types or self.supported_types)
        for obj_type in requested_types:
            if obj_type not in self.supported_types:
                parsed.warnings.append(
                    f"PaloAltoParser does not implement {obj_type} yet."
                )

        parsed.objects.extend(
            obj for obj in objects if obj["object_type"] in requested_types
        )
        return parsed

    @staticmethod
    def _looks_like_set_format(raw_data: str) -> bool:
        set_lines = 0
        other_lines = 0
        for line in raw_data.splitlines()[:500]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("set ") or line.startswith("no set "):
                set_lines += 1
            else:
                other_lines += 1
        return set_lines >= 1 and other_lines == 0

    # ------------------------------------------------------------------
    # Format dispatch: parse everything, filter by type in parse_config
    # ------------------------------------------------------------------

    def _parse_xml(self, raw_data: str) -> tuple:
        # Parse from bytes: str input that carries an XML declaration and
        # non-ASCII content makes ElementTree raise ValueError (not ParseError).
        try:
            root = ET.fromstring(raw_data.encode("utf-8"))
        except ET.ParseError as exc:
            raise ValueError(f"Invalid Palo Alto XML: {exc}") from exc

        if root.tag not in ("config", "paloalto") and not root.findall(".//vsys"):
            raise ValueError(
                "Input does not look like a Palo Alto configuration export."
            )

        objects: List[Dict] = []
        warnings: List[str] = []

        objects.extend(self._xml_addresses(root))
        group_objects, skipped_dynamic = self._xml_address_groups(root)
        objects.extend(group_objects)
        if skipped_dynamic:
            word = "group" if skipped_dynamic == 1 else "groups"
            warnings.append(
                f"Skipped {skipped_dynamic} dynamic address {word} "
                "(dynamic filters are not imported)."
            )
        objects.extend(self._xml_services(root))
        objects.extend(self._xml_service_groups(root))
        objects.extend(self._xml_rules(root))
        objects.extend(self._xml_interfaces(root))
        objects.extend(self._xml_zones(root))
        return objects, warnings

    # -- XML helpers -----------------------------------------------------

    @staticmethod
    def _text(element, path: str) -> str:
        value = element.findtext(path)
        if value is None:
            return ""
        return value.strip()

    @staticmethod
    def _member_texts(element, tag: str) -> List[str]:
        """All <member> texts under <tag> (direct child), stripped."""
        container = element.find(tag)
        if container is None:
            return []
        return [
            member.text.strip()
            for member in container.findall("member")
            if member.text and member.text.strip()
        ]

    def _xml_object_entries(self, root, tag: str) -> List:
        """
        Find the object container for `tag` across export styles and return
        the element objects to iterate (each carrying a `name` attribute):

        - PAN-OS 11.x device export:  vsys/entry/<tag>/entry
        - older device exports:       vsys/entry/objects/<tag>/entry
        - app-generated documents:    <objects> holding <tag name=...>
          children directly
        """
        for xpath in (f".//vsys/entry/{tag}", f".//vsys/entry/objects/{tag}"):
            entries = []
            for container in root.findall(xpath):
                entries.extend(container.findall("entry"))
            if entries:
                return entries

        named = []
        for container in root.findall(f".//objects/{tag}"):
            if container.get("name"):
                # App-generated documents: <objects><address name=\"...\">…
                named.append(container)
            else:
                # Older wrapped documents: <objects><tag><tag name=\"...\">…
                named.extend(child for child in container if child.get("name"))
        if named:
            return named
        return []

    def _xml_addresses(self, root) -> List[Dict]:
        objects: List[Dict] = []
        for element in self._xml_object_entries(root, "address"):
            name = element.get("name")
            if not name:
                continue

            value = (
                self._text(element, "ip-netmask")
                or self._text(element, "ip")
                or self._text(element, "ip-netrange")
                or self._text(element, "fqdn")
                or self._text(element, "interface")
            )
            if not value:
                continue

            if "/" in value:
                address_type = "cidr"
            elif re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value) or ":" in value:
                address_type = "ip"
            elif "-" in value:
                address_type = "iprange"
            elif "." in value:
                address_type = "fqdn"
            else:
                address_type = "other"

            description = self._text(element, "description")
            payload: Dict[str, Any] = {
                "address": value,
                "address_type": address_type,
            }
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "address",
                    "name": name,
                    "description": description or None,
                    "payload": payload,
                    "raw_excerpt": f'<address name="{xml_escape(name)}"/>',
                }
            )
        return objects

    def _xml_address_groups(self, root) -> tuple:
        objects: List[Dict] = []
        skipped_dynamic = 0

        for element in self._xml_object_entries(root, "address-group"):
            name = element.get("name")
            if not name:
                continue

            if element.find("dynamic") is not None:
                skipped_dynamic += 1
                continue

            members = self._member_texts(element, "static")
            if not members:
                # app-generated documents may use plain <member> children
                members = [
                    member.text.strip()
                    for member in element.findall("member")
                    if member.text and member.text.strip()
                ]
            if not members:
                continue

            description = self._text(element, "description")
            payload: Dict[str, Any] = {"members": members}
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "address_group",
                    "name": name,
                    "description": description or None,
                    "payload": payload,
                    "raw_excerpt": f'<addrgrp name="{xml_escape(name)}"/>',
                }
            )
        return objects, skipped_dynamic

    def _xml_services(self, root) -> List[Dict]:
        objects: List[Dict] = []

        for element in self._xml_object_entries(root, "service"):
            name = element.get("name")
            if not name:
                continue

            description = self._text(element, "description")
            protocols: List[str] = []
            ports: List[str] = []
            source_port: Optional[str] = None

            protocol_el = element.find("protocol")
            if protocol_el is not None and len(protocol_el):
                for proto_tag in ("tcp", "udp", "icmp", "ip"):
                    proto_el = protocol_el.find(proto_tag)
                    if proto_el is None:
                        continue
                    protocols.append(proto_tag)
                    port = self._text(proto_el, "port")
                    if port:
                        ports.append(self._normalize_port(port))
                    src = self._text(proto_el, "source-port")
                    if src:
                        source_port = self._normalize_port(src)
            else:
                # app-generated documents: flat <protocol>/<port> children
                protocol = self._text(element, "protocol") or "tcp"
                port = self._text(element, "port")
                protocols = [protocol]
                if port:
                    ports = [self._normalize_port(port)]
                source_port = self._text(element, "source-port") or None

            if not protocols:
                continue

            port_value = self._merge_ports(ports)
            payload: Dict[str, Any] = {
                "protocol": "+".join(protocols),
                "port": port_value,
            }
            if source_port:
                payload["source_port"] = source_port
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "service",
                    "name": name,
                    "description": description or None,
                    "payload": payload,
                    "raw_excerpt": f'<service name="{xml_escape(name)}"/>',
                }
            )
        return objects

    def _xml_service_groups(self, root) -> List[Dict]:
        objects: List[Dict] = []

        for element in self._xml_object_entries(root, "service-group"):
            name = element.get("name")
            if not name:
                continue

            members = self._member_texts(element, "members")
            if not members:
                # app-generated documents may use plain <member> children
                members = [
                    member.text.strip()
                    for member in element.findall("member")
                    if member.text and member.text.strip()
                ]
            if not members:
                continue

            description = self._text(element, "description")
            payload: Dict[str, Any] = {"members": members}
            if description:
                payload["description"] = description

            objects.append(
                {
                    "object_type": "service_group",
                    "name": name,
                    "description": description or None,
                    "payload": payload,
                    "raw_excerpt": f'<service-group name="{xml_escape(name)}"/>',
                }
            )
        return objects

    def _xml_rules(self, root) -> List[Dict]:
        objects: List[Dict] = []

        elements = root.findall(".//rulebase/security/rules/entry")
        if not elements:
            elements = root.findall(".//rulebase/rules/rule")
        if not elements:
            elements = [
                el
                for el in root.findall(".//rulebase/*/rules/entry")
                if el.get("name")
            ]

        for rule in elements:
            name = rule.get("name")
            if not name:
                continue

            action = self._text(rule, "action") or "allow"
            description = self._text(rule, "description")

            def members(tag: str) -> List[str]:
                return [
                    member.text.strip()
                    for member in rule.findall(f"./{tag}/member")
                    if member.text and member.text.strip()
                ]

            has_source = rule.find("source") is not None
            has_destination = rule.find("destination") is not None

            # In device exports <from>/<to> hold the source/destination
            # ZONES and <source>/<destination> the address objects; in
            # app-generated documents the address lists live in <from>/<to>.
            sources = members("source") or members("from")
            source_zones = members("from") if has_source else []
            destinations = members("destination") or members("to")
            destination_zones = members("to") if has_destination else []
            services = members("service")

            payload: Dict[str, Any] = {
                "action": action.lower(),
                "sources": sources,
                "destinations": destinations,
                "services": services,
                "source_zones": source_zones,
                "destination_zones": destination_zones,
            }

            if description:
                payload["description"] = description

            if self._text(rule, "disabled") == "yes":
                payload["disabled"] = True

            objects.append(
                {
                    "object_type": "rule",
                    "name": name,
                    "description": description or None,
                    "payload": payload,
                    "raw_excerpt": f'<rule name="{xml_escape(name)}"/>',
                }
            )
        return objects

    def _xml_interfaces(self, root) -> List[Dict]:
        objects: List[Dict] = []

        for if_type in INTERFACE_TYPES:
            for unit in root.findall(
                f".//network/interface/{if_type}/unit/entry"
            ):
                name = unit.get("name")
                if not name:
                    continue

                ip: Optional[str] = None
                ip_container = unit.find("ip")
                if ip_container is not None:
                    first = ip_container.find("entry")
                    if first is not None:
                        address = (first.findtext("address") or "").strip()
                        ip = address or None

                zone_el = unit.find("zone")
                zone = zone_el.get("name") if zone_el is not None else None

                description = self._text(unit, "description")

                payload: Dict[str, Any] = {"ip": ip, "type": if_type}
                if zone:
                    payload["zone"] = zone
                if description:
                    payload["description"] = description

                objects.append(
                    {
                        "object_type": "interface",
                        "name": name,
                        "description": description or None,
                        "payload": payload,
                        "raw_excerpt": (
                            f'<interface name="{xml_escape(name)}"/>'
                        ),
                    }
                )
        return objects

    def _xml_zones(self, root) -> List[Dict]:
        objects: List[Dict] = []
        seen: set = set()

        zone_entries: List = []

        for candidates in (
            root.findall(".//vsys/entry/zone/entry"),
            root.findall(".//network/zone/entry"),
            root.findall(".//objects/zone/entry"),
        ):
            zone_entries.extend(candidates)

        # App-generated documents: <objects><zone name=\"...\"><member>…
        # directly (the named element is the zone itself).
        for container in root.findall(".//objects/zone"):
            if container.get("name"):
                zone_entries.append(container)
            else:
                zone_entries.extend(container.findall("entry"))

        for zone in zone_entries:
            name = zone.get("name")
            if not name or name in seen:
                continue
            seen.add(name)

            members: List[str] = []
            for member in zone.findall(".//layer3/member"):
                text = (member.text or "").strip()
                if text and text not in members:
                    members.append(text)
            for member in zone.findall(".//layer2/member"):
                text = (member.text or "").strip()
                if text and text not in members:
                    members.append(text)
            if not members:
                members = [
                    member.text.strip()
                    for member in zone.findall("./member")
                    if member.text and member.text.strip()
                ]

            payload: Dict[str, Any] = {"members": members}
            objects.append(
                {
                    "object_type": "zone",
                    "name": name,
                    "description": None,
                    "payload": payload,
                    "raw_excerpt": f'<zone name="{xml_escape(name)}"/>',
                }
            )
        return objects

    # ------------------------------------------------------------------
    # Set (show) format
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize_set_line(line: str) -> List[Any]:
        """
        Tokenize one set-format line. Quoted strings stay single tokens
        (backslash escapes honored); ``[ a b ]`` becomes one list token.
        """
        tokens: List[Any] = []
        i, n = 0, len(line)

        while i < n:
            char = line[i]
            if char.isspace():
                i += 1
            elif char == "[":
                i += 1
                items: List[str] = []
                while i < n and line[i] != "]":
                    if line[i].isspace():
                        i += 1
                        continue
                    if line[i] == '"':
                        j, item = PaloAltoParser._read_quoted(line, i + 1)
                        items.append(item)
                        i = j
                    else:
                        j = i
                        while (
                            j < n
                            and not line[j].isspace()
                            and line[j] not in '"]'
                        ):
                            j += 1
                        items.append(line[i:j])
                        i = j
                i += 1  # skip ']'
                tokens.append(items)
            elif char == '"':
                j, item = PaloAltoParser._read_quoted(line, i + 1)
                tokens.append(item)
                i = j
            else:
                j = i
                while j < n and not line[j].isspace() and line[j] not in '"[':
                    j += 1
                tokens.append(line[i:j])
                i = j
        return tokens

    @staticmethod
    def _read_quoted(line: str, start: int) -> tuple:
        """Read a quoted string starting at `start` (after the opening quote)."""
        buf: List[str] = []
        i, n = start, len(line)
        while i < n and line[i] != '"':
            if line[i] == "\\" and i + 1 < n:
                buf.append(line[i + 1])
                i += 2
            else:
                buf.append(line[i])
                i += 1
        return i + 1, "".join(buf)

    @staticmethod
    def _normalize_port(port: str) -> str:
        port = (port or "").strip()
        if port.lower() == "any" or port == "1-65535":
            return "any"
        return port

    @staticmethod
    def _merge_ports(ports: List[str]) -> Optional[str]:
        parts: List[str] = []
        for port in ports:
            if port == "any":
                return "any"
            for part in port.split(","):
                if part not in parts:
                    parts.append(part)
        return ",".join(parts) if parts else None

    def _parse_set(self, raw_data: str) -> tuple:
        addresses: Dict[str, Dict[str, Any]] = {}
        address_groups: Dict[str, Dict[str, Any]] = {}
        services: Dict[str, Dict[str, Any]] = {}
        service_groups: Dict[str, Dict[str, Any]] = {}
        rules: Dict[str, Dict[str, Any]] = {}
        zones: Dict[str, List[str]] = {}
        interfaces: Dict[str, Dict[str, Any]] = {}
        warnings: List[str] = []

        for line in raw_data.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("no set "):
                continue  # negated statements: not imported
            if not line.startswith("set "):
                continue

            tokens = self._tokenize_set_line(line[4:])
            if not tokens:
                continue
            command = str(tokens[0])

            if command == "address" and len(tokens) >= 4:
                name = str(tokens[1])
                field = str(tokens[2])
                value = str(tokens[3]) if len(tokens) > 3 else ""
                entry = addresses.setdefault(name, {})
                if field in ("ip-netmask", "ip"):
                    entry["address"] = value
                elif field == "ip-netrange":
                    entry["address"] = value
                elif field == "fqdn":
                    entry["address"] = value
                elif field == "description":
                    entry["description"] = value

            elif command == "address-group" and len(tokens) >= 3:
                name = str(tokens[1])
                field = str(tokens[2])
                entry = address_groups.setdefault(name, {})
                if field == "static" and len(tokens) > 3:
                    members = tokens[3]
                    entry["members"] = (
                        list(members)
                        if isinstance(members, list)
                        else [str(members)]
                    )
                elif field == "description" and len(tokens) > 3:
                    entry["description"] = str(tokens[3])

            elif command == "service" and len(tokens) >= 3:
                name = str(tokens[1])
                field = str(tokens[2])
                entry = services.setdefault(name, {})
                if field == "protocol" and len(tokens) > 3:
                    proto = str(tokens[3]).lower()
                    protocols = entry.setdefault("protocols", [])
                    if proto not in protocols:
                        protocols.append(proto)
                    if proto in ("tcp", "udp") and len(tokens) > 4:
                        sub = str(tokens[4])
                        if sub == "port" and len(tokens) > 5:
                            entry.setdefault("ports", []).append(
                                self._normalize_port(str(tokens[5]))
                            )
                        elif sub == "source-port" and len(tokens) > 5:
                            entry["source_port"] = self._normalize_port(
                                str(tokens[5])
                            )
                elif field == "description" and len(tokens) > 3:
                    entry["description"] = str(tokens[3])

            elif command == "service-group" and len(tokens) >= 3:
                name = str(tokens[1])
                field = str(tokens[2])
                entry = service_groups.setdefault(name, {})
                if field == "members" and len(tokens) > 3:
                    members = tokens[3]
                    entry["members"] = (
                        list(members)
                        if isinstance(members, list)
                        else [str(members)]
                    )
                elif field == "description" and len(tokens) > 3:
                    entry["description"] = str(tokens[3])

            elif (
                command == "rulebase"
                and len(tokens) >= 5
                and str(tokens[1]) == "security"
                and str(tokens[2]) == "rules"
            ):
                name = str(tokens[3])
                field = str(tokens[4])
                rule = rules.setdefault(name, {})
                if field in ("from", "to", "source", "destination", "service"):
                    values = []
                    for item in tokens[5:]:
                        if isinstance(item, list):
                            values.extend(str(v) for v in item)
                        else:
                            values.append(str(item))
                    rule.setdefault(field, []).extend(values)
                elif field == "action":
                    rule["action"] = str(tokens[5])
                elif field == "description" and len(tokens) > 5:
                    rule["description"] = str(tokens[5])
                elif field == "disabled":
                    rule["disabled"] = str(tokens[5]).lower() == "yes"

            elif command == "zone" and len(tokens) >= 3:
                name = str(tokens[1])
                members = zones.setdefault(name, [])
                if str(tokens[2]) == "network" and len(tokens) > 3:
                    for item in tokens[3:]:
                        if isinstance(item, list):
                            members.extend(str(v) for v in item)
                        else:
                            members.append(str(item))

            elif command == "devices" and len(tokens) >= 4:
                # best-effort interface capture
                if str(tokens[1]) == "system" and str(tokens[2]) in INTERFACE_TYPES:
                    iface_name = str(tokens[3])
                    entry = interfaces.setdefault(iface_name, {"type": str(tokens[2])})
                    k = 4
                    while k < len(tokens) - 1:
                        key = str(tokens[k])
                        value = tokens[k + 1]
                        if key == "ip" and isinstance(value, str):
                            entry["ip"] = value
                        elif key == "description" and isinstance(value, str):
                            entry["description"] = value
                        k += 2

        objects: List[Dict] = []

        for name, data in addresses.items():
            value = data.get("address")
            if not value:
                continue
            if "/" in value:
                address_type = "cidr"
            elif re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", value) or ":" in value:
                address_type = "ip"
            elif "-" in value:
                address_type = "iprange"
            elif "." in value:
                address_type = "fqdn"
            else:
                address_type = "other"
            payload: Dict[str, Any] = {
                "address": value,
                "address_type": address_type,
            }
            if data.get("description"):
                payload["description"] = data["description"]
            objects.append(
                {
                    "object_type": "address",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set address {name}",
                }
            )

        for name, data in address_groups.items():
            members = data.get("members") or []
            if not members:
                continue
            payload = {"members": members}
            if data.get("description"):
                payload["description"] = data["description"]
            objects.append(
                {
                    "object_type": "address_group",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set address-group {name}",
                }
            )

        for name, data in services.items():
            protocols = data.get("protocols") or []
            if not protocols:
                continue
            payload = {
                "protocol": "+".join(protocols),
                "port": self._merge_ports(data.get("ports") or []),
            }
            if data.get("source_port"):
                payload["source_port"] = data["source_port"]
            if data.get("description"):
                payload["description"] = data["description"]
            objects.append(
                {
                    "object_type": "service",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set service {name}",
                }
            )

        for name, data in service_groups.items():
            members = data.get("members") or []
            if not members:
                continue
            payload = {"members": members}
            if data.get("description"):
                payload["description"] = data["description"]
            objects.append(
                {
                    "object_type": "service_group",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set service-group {name}",
                }
            )

        for name, data in rules.items():
            has_source = bool(data.get("source"))
            has_destination = bool(data.get("destination"))
            sources = data.get("source") or data.get("from") or []
            source_zones = data.get("from") or [] if has_source else []
            destinations = data.get("destination") or data.get("to") or []
            destination_zones = data.get("to") or [] if has_destination else []
            action = (data.get("action") or "allow").lower()
            if action == "accept":
                action = "allow"

            payload = {
                "action": action,
                "sources": sources,
                "destinations": destinations,
                "services": data.get("service") or [],
                "source_zones": source_zones,
                "destination_zones": destination_zones,
            }
            if data.get("description"):
                payload["description"] = data["description"]
            if data.get("disabled"):
                payload["disabled"] = True

            objects.append(
                {
                    "object_type": "rule",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set rulebase security rules {name}",
                }
            )

        for name, data in interfaces.items():
            payload = {"ip": data.get("ip"), "type": data.get("type")}
            if data.get("description"):
                payload["description"] = data["description"]
            objects.append(
                {
                    "object_type": "interface",
                    "name": name,
                    "description": data.get("description"),
                    "payload": payload,
                    "raw_excerpt": f"set devices system {data.get('type')} {name}",
                }
            )

        for name, members in zones.items():
            objects.append(
                {
                    "object_type": "zone",
                    "name": name,
                    "description": None,
                    "payload": {"members": members},
                    "raw_excerpt": f"set zone {name}",
                }
            )

        return objects, warnings

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def generate_config(
        self,
        objects: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
    ) -> str:
        fmt = (format or "xml").strip().lower()

        if fmt == "set":
            return self._generate_set(objects)

        addresses = [o for o in objects if o.get("object_type") == "address"]
        address_groups = [o for o in objects if o.get("object_type") == "address_group"]
        services = [o for o in objects if o.get("object_type") == "service"]
        service_groups = [o for o in objects if o.get("object_type") == "service_group"]
        rules = [o for o in objects if o.get("object_type") == "rule"]
        interfaces = [o for o in objects if o.get("object_type") == "interface"]
        zones = [o for o in objects if o.get("object_type") == "zone"]

        lines: List[str] = ['<?xml version="1.0" encoding="UTF-8"?><paloalto>']

        has_objects = bool(
            addresses
            or address_groups
            or services
            or service_groups
            or zones
            or interfaces
        )

        if has_objects:
            lines.append("  <objects>")

            for obj in addresses:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                value = payload.get("address")
                address_type = payload.get("address_type", "cidr")
                tag = {
                    "cidr": "ip-netmask",
                    "ip": "ip",
                    "iprange": "ip-netrange",
                    "fqdn": "fqdn",
                    "interface": "interface",
                }.get(address_type, "ip-netmask")

                lines.append(f'    <address name="{name}">')
                if value:
                    lines.append(f"      <{tag}>{xml_escape(value)}</{tag}>")
                if payload.get("description"):
                    lines.append(
                        f"      <description>{xml_escape(payload['description'])}</description>"
                    )
                lines.append("    </address>")

            for obj in address_groups:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                # Device exports wrap groups in <address-group> (11.x style);
                # the parser accepts either shape.
                lines.append(f'    <address-group name="{name}">')
                lines.append("      <static>")
                for member in payload.get("members", []):
                    lines.append(f"        <member>{xml_escape(member)}</member>")
                lines.append("      </static>")
                if payload.get("description"):
                    lines.append(
                        f"      <description>{xml_escape(payload['description'])}</description>"
                    )
                lines.append("    </address-group>")

            for obj in services:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                protocol = payload.get("protocol", "tcp")
                port = payload.get("port")

                lines.append(f'    <service name="{name}">')
                lines.append("      <protocol>")
                for proto in protocol.split("+"):
                    if proto in ("tcp", "udp"):
                        lines.append(f"        <{proto}>")
                        if port:
                            lines.append(f"          <port>{xml_escape(port)}</port>")
                        if payload.get("source_port"):
                            lines.append(
                                f"          <source-port>{xml_escape(payload['source_port'])}</source-port>"
                            )
                        lines.append(f"        </{proto}>")
                    elif proto in ("icmp", "ip"):
                        lines.append(f"        <{proto}></{proto}>")
                lines.append("      </protocol>")
                if payload.get("description"):
                    lines.append(
                        f"      <description>{xml_escape(payload['description'])}</description>"
                    )
                lines.append("    </service>")

            for obj in service_groups:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                lines.append(f'    <service-group name="{name}">')
                lines.append("      <members>")
                for member in payload.get("members", []):
                    lines.append(f"        <member>{xml_escape(member)}</member>")
                lines.append("      </members>")
                if payload.get("description"):
                    lines.append(
                        f"      <description>{xml_escape(payload['description'])}</description>"
                    )
                lines.append("    </service-group>")

            for obj in zones:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                lines.append(f'    <zone name="{name}">')
                for member in payload.get("members", []):
                    lines.append(f"      <member>{xml_escape(member)}</member>")
                lines.append("    </zone>")

            lines.append("  </objects>")

        if interfaces:
            lines.append("  <network><interface>")
            by_type: Dict[str, List[Dict]] = {}
            for obj in interfaces:
                if_type = (obj.get("payload") or {}).get("type") or "ethernet"
                by_type.setdefault(if_type, []).append(obj)
            for if_type, objs in by_type.items():
                lines.append(f"    <{if_type}><unit>")
                for obj in objs:
                    name = xml_escape(obj["name"])
                    payload = obj.get("payload") or {}
                    lines.append(f'      <entry name="{name}">')
                    if payload.get("ip"):
                        lines.append(
                            f"        <ip><entry name=\"primary\">"
                            f"<address>{xml_escape(payload['ip'])}</address>"
                            f"</entry></ip>"
                        )
                    if payload.get("zone"):
                        lines.append(
                            f'        <zone name="{xml_escape(payload["zone"])}"/>'
                        )
                    if payload.get("description"):
                        lines.append(
                            f"        <description>{xml_escape(payload['description'])}</description>"
                        )
                    lines.append("      </entry>")
                lines.append("    </unit></{0}>".format(if_type))
            lines.append("  </interface></network>")

        if rules:
            lines.append("  <rulebase><security><rules>")

            for obj in rules:
                name = xml_escape(obj["name"])
                payload = obj.get("payload") or {}
                action = payload.get("action", "allow")
                sources = payload.get("sources", [])
                destinations = payload.get("destinations", [])
                services_list = payload.get("services", [])
                source_zones = payload.get("source_zones", [])
                destination_zones = payload.get("destination_zones", [])
                description = payload.get("description")

                lines.append(f'    <entry name="{name}" uuid="">')

                for tag, members in (
                    ("from", source_zones or sources),
                    ("to", destination_zones or destinations),
                    ("source", sources if source_zones else []),
                    ("destination", destinations if destination_zones else []),
                    ("service", services_list),
                ):
                    if members:
                        lines.append(f"      <{tag}>")
                        for member in members:
                            lines.append(f"        <member>{xml_escape(member)}</member>")
                        lines.append(f"      </{tag}>")

                lines.append(f"      <action>{xml_escape(action)}</action>")

                if description:
                    lines.append(
                        f"      <description>{xml_escape(description)}</description>"
                    )

                if payload.get("disabled"):
                    lines.append("      <disabled>yes</disabled>")

                lines.append("    </entry>")

            lines.append("  </rules></security></rulebase>")

        lines.append("</paloalto>")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Set (show) format export
    # ------------------------------------------------------------------

    @staticmethod
    def _set_quote(value: Any) -> str:
        """Quote a set-format value (backslash escapes honored by the parser)."""
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @classmethod
    def _set_token(cls, value: Any) -> str:
        """One set-format token: quoted when the value carries spaces."""
        text = str(value)
        if any(char.isspace() for char in text):
            return cls._set_quote(text)
        return text

    def _generate_set(self, objects: List[Dict[str, Any]]) -> str:
        """Generate a set (``show``) format export — one ``set`` line per field.

        Line shapes mirror the reference sample in ``files/``
        (``set address``, ``set address-group … static``,
        ``set service … protocol``, ``set rulebase security rules …`` per
        field, ``set zone … network``, ``set devices system <type> <name>``)
        and round-trip through ``_parse_set``.
        """
        addresses = [o for o in objects if o.get("object_type") == "address"]
        address_groups = [o for o in objects if o.get("object_type") == "address_group"]
        services = [o for o in objects if o.get("object_type") == "service"]
        service_groups = [o for o in objects if o.get("object_type") == "service_group"]
        rules = [o for o in objects if o.get("object_type") == "rule"]
        interfaces = [o for o in objects if o.get("object_type") == "interface"]
        zones = [o for o in objects if o.get("object_type") == "zone"]

        def members_line(members: List[str]) -> str:
            if len(members) == 1:
                return self._set_token(members[0])
            return "[ " + " ".join(self._set_token(m) for m in members) + " ]"

        lines: List[str] = []

        for obj in addresses:
            name = obj["name"]
            payload = obj.get("payload") or {}
            value = str(payload.get("address") or "")
            if not value:
                continue
            address_type = payload.get("address_type", "cidr")
            if address_type == "iprange":
                # The device format is a single ``start-end`` token; the stored
                # value may carry spaces around the dash.
                value = value.replace(" -", "-").replace("- ", "-")
            field = {
                "cidr": "ip-netmask",
                "ip": "ip",
                "iprange": "ip-netrange",
                "fqdn": "fqdn",
                "interface": "interface",
            }.get(address_type, "ip-netmask")
            lines.append(f"set address {self._set_token(name)} {field} {value}")
            if payload.get("description"):
                lines.append(
                    f"set address {self._set_token(name)}"
                    f" description {self._set_quote(payload['description'])}"
                )

        for obj in address_groups:
            name = obj["name"]
            payload = obj.get("payload") or {}
            members = [str(m) for m in payload.get("members", [])]
            if not members:
                continue
            lines.append(
                f"set address-group {self._set_token(name)} static {members_line(members)}"
            )
            if payload.get("description"):
                lines.append(
                    f"set address-group {self._set_token(name)}"
                    f" description {self._set_quote(payload['description'])}"
                )

        for obj in services:
            name = obj["name"]
            payload = obj.get("payload") or {}
            protocol = str(payload.get("protocol") or "tcp")
            port = payload.get("port")
            source_port = payload.get("source_port")
            for proto in protocol.split("+"):
                proto = proto.strip()
                if not proto:
                    continue
                if proto in ("tcp", "udp"):
                    if port and str(port).lower() != "any":
                        lines.append(
                            f"set service {self._set_token(name)} protocol {proto} port {port}"
                        )
                    else:
                        lines.append(
                            f"set service {self._set_token(name)} protocol {proto}"
                        )
                    if source_port:
                        lines.append(
                            f"set service {self._set_token(name)} protocol {proto}"
                            f" source-port {source_port}"
                        )
                elif proto in ("icmp", "ip"):
                    lines.append(f"set service {self._set_token(name)} protocol {proto}")
            if payload.get("description"):
                lines.append(
                    f"set service {self._set_token(name)}"
                    f" description {self._set_quote(payload['description'])}"
                )

        for obj in service_groups:
            name = obj["name"]
            payload = obj.get("payload") or {}
            members = [str(m) for m in payload.get("members", [])]
            if not members:
                continue
            lines.append(
                f"set service-group {self._set_token(name)} members {members_line(members)}"
            )
            if payload.get("description"):
                lines.append(
                    f"set service-group {self._set_token(name)}"
                    f" description {self._set_quote(payload['description'])}"
                )

        for obj in rules:
            prefix = f"set rulebase security rules {self._set_token(obj['name'])}"
            payload = obj.get("payload") or {}
            if payload.get("source_zones"):
                lines.append(
                    f"{prefix} from {members_line([str(m) for m in payload['source_zones']])}"
                )
            if payload.get("destination_zones"):
                lines.append(
                    f"{prefix} to {members_line([str(m) for m in payload['destination_zones']])}"
                )
            if payload.get("sources"):
                lines.append(
                    f"{prefix} source {members_line([str(m) for m in payload['sources']])}"
                )
            if payload.get("destinations"):
                lines.append(
                    f"{prefix} destination"
                    f" {members_line([str(m) for m in payload['destinations']])}"
                )
            if payload.get("services"):
                lines.append(
                    f"{prefix} service {members_line([str(m) for m in payload['services']])}"
                )
            lines.append(f"{prefix} action {payload.get('action', 'allow')}")
            if payload.get("description"):
                lines.append(f"{prefix} description {self._set_quote(payload['description'])}")
            if payload.get("disabled"):
                lines.append(f"{prefix} disabled yes")

        for obj in zones:
            name = obj["name"]
            payload = obj.get("payload") or {}
            members = [str(m) for m in payload.get("members", [])]
            if members:
                lines.append(
                    f"set zone {self._set_token(name)} network {members_line(members)}"
                )
            else:
                # Member-less zones (round-trip: the set parser still creates
                # the zone from the bare ``network`` line).
                lines.append(f"set zone {self._set_token(name)} network")

        for obj in interfaces:
            name = self._set_token(obj["name"])
            payload = obj.get("payload") or {}
            if_type = payload.get("type") or "ethernet"
            prefix = f"set devices system {if_type} {name}"
            if payload.get("ip"):
                lines.append(f"{prefix} ip {payload['ip']}")
            if payload.get("description"):
                lines.append(f"{prefix} description {self._set_quote(payload['description'])}")

        return "\n".join(lines)
