"""외부 주소 가져오기 전 IP 검사 (제목 미리보기 등, SSRF 방어).

`is_public_ip`가 True인 주소로만 연결한다. 거부하는 것:
- 사설(10/8, 172.16/12, 192.168/16, fc00::/7), 루프백, 링크로컬(169.254/16, fe80::/10),
  CGNAT 공유 대역(100.64/10), 멀티캐스트, 예약·문서용·벤치마크 대역, 미지정(0.0.0.0, ::),
  옛 site-local(fec0::/10)
- IPv6 안에 IPv4를 담는 형식은 안의 IPv4까지 검사한다: IPv4-mapped(::ffff:0:0/96),
  NAT64(64:ff9b::/96), 6to4(2002::/16). Teredo(2001::/32)는 통째로 거부한다.
- 그 밖의 IPv6는 전역 유니캐스트(2000::/3)만 받는다.
"""

import ipaddress
from ipaddress import IPv4Address, IPv6Address

_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_GLOBAL_UNICAST_V6 = ipaddress.IPv6Network("2000::/3")


def is_public_ip(ip: IPv4Address | IPv6Address) -> bool:
    if isinstance(ip, IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip in _NAT64:
            return is_public_ip(IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour is not None and not is_public_ip(ip.sixtofour):
            return False
        if ip.teredo is not None or ip.scope_id or ip.is_site_local:
            return False
        if ip not in _GLOBAL_UNICAST_V6:
            return False
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None
