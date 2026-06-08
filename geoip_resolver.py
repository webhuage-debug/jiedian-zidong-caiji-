#!/usr/bin/env python3
"""Resolve IP country codes from Xray geoip.dat without external APIs."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple


def read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    shift = 0
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def read_messages(data: bytes, expected_field: int) -> List[bytes]:
    offset = 0
    messages = []
    while offset < len(data):
        key, offset = read_varint(data, offset)
        field = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            _, offset = read_varint(data, offset)
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            payload = data[offset:offset + length]
            offset += length
            if field == expected_field:
                messages.append(payload)
        elif wire_type == 5:
            offset += 4
        else:
            raise ValueError("unsupported protobuf wire type: " + str(wire_type))
    return messages


def parse_geoip_entry(payload: bytes) -> Tuple[str, List[Tuple[ipaddress._BaseNetwork, str]]]:
    offset = 0
    country = ""
    cidr_payloads: List[bytes] = []
    while offset < len(payload):
        key, offset = read_varint(payload, offset)
        field = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            _, offset = read_varint(payload, offset)
        elif wire_type == 2:
            length, offset = read_varint(payload, offset)
            value = payload[offset:offset + length]
            offset += length
            if field == 1:
                country = value.decode("utf-8", errors="replace").upper()
            elif field == 2:
                cidr_payloads.append(value)
        elif wire_type == 5:
            offset += 4
        elif wire_type == 1:
            offset += 8
        else:
            raise ValueError("unsupported protobuf wire type: " + str(wire_type))

    networks: List[Tuple[ipaddress._BaseNetwork, str]] = []
    if not country:
        return country, networks
    for cidr_payload in cidr_payloads:
        ip_bytes = b""
        prefix = None
        offset = 0
        while offset < len(cidr_payload):
            key, offset = read_varint(cidr_payload, offset)
            field = key >> 3
            wire_type = key & 7
            if wire_type == 0:
                value, offset = read_varint(cidr_payload, offset)
                if field == 2:
                    prefix = value
            elif wire_type == 2:
                length, offset = read_varint(cidr_payload, offset)
                value = cidr_payload[offset:offset + length]
                offset += length
                if field == 1:
                    ip_bytes = value
            elif wire_type == 5:
                offset += 4
            elif wire_type == 1:
                offset += 8
            else:
                raise ValueError("unsupported protobuf wire type: " + str(wire_type))
        if ip_bytes and prefix is not None:
            address = ipaddress.ip_address(ip_bytes)
            networks.append((ipaddress.ip_network((address, prefix), strict=False), country))
    return country, networks


class GeoIPResolver:
    def __init__(self, path: Path = Path("tools/xray/geoip.dat")):
        self.path = path
        self.ipv4: List[Tuple[ipaddress._BaseNetwork, str]] = []
        self.ipv6: List[Tuple[ipaddress._BaseNetwork, str]] = []
        self.load()

    def load(self) -> None:
        data = self.path.read_bytes()
        for entry in read_messages(data, 1):
            country, networks = parse_geoip_entry(entry)
            if len(country) != 2:
                continue
            for network, country in networks:
                if network.version == 4:
                    self.ipv4.append((network, country))
                else:
                    self.ipv6.append((network, country))

    @lru_cache(maxsize=4096)
    def country_for_ip(self, value: str) -> str:
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            return ""
        networks = self.ipv4 if address.version == 4 else self.ipv6
        best_prefix = -1
        best_country = ""
        for network, country in networks:
            if network.prefixlen <= best_prefix:
                continue
            if address in network:
                best_prefix = network.prefixlen
                best_country = country
        return best_country

    def country_for_ips(self, values: str) -> str:
        countries = []
        seen = set()
        for item in values.split(","):
            country = self.country_for_ip(item)
            if country and country not in seen:
                countries.append(country)
                seen.add(country)
        return ",".join(countries)


if __name__ == "__main__":
    resolver = GeoIPResolver()
    for sample in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"):
        print(sample + " " + (resolver.country_for_ip(sample) or "未知"))
