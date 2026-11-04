# dns/dns_providers.py
"""
Список DNS провайдеров для UI
"""

DNS_PROVIDERS = {
    "Обход блокировок": {
        "Comss DNS": {
            "ipv4": ["83.220.169.155", "212.109.195.93"],
            "ipv6": [],
            "desc": "Доступ к зарубежным сервисам",
            "icon": "fa5s.brain",
            "color": "#673ab7",
            "doh": "https://dns.comss.one/dns-query"
        },
    },
    "Обычные": {
        "Cloudflare": {
            "ipv4": ["1.1.1.1", "1.0.0.1"],
            "ipv6": ["2606:4700:4700::1111", "2606:4700:4700::1001"],
            "desc": "Быстрый, без фильтрации",
            "icon": "fa5s.bolt",
            "color": "#f48120",
            "doh": "https://cloudflare-dns.com/dns-query"
        },
        "Google DNS": {
            "ipv4": ["8.8.8.8", "8.8.4.4"],
            "ipv6": ["2001:4860:4860::8888", "2001:4860:4860::8844"],
            "desc": "Надёжный, без фильтрации",
            "icon": "fa5b.google",
            "color": "#4285f4",
            "doh": "https://dns.google/dns-query"
        },
        "Quad9": {
            "ipv4": ["9.9.9.9", "149.112.112.112"],
            "ipv6": ["2620:fe::fe", "2620:fe::9"],
            "desc": "С защитой от вредоносных сайтов",
            "icon": "fa5s.shield-alt",
            "color": "#d6006c",
            "doh": "https://dns.quad9.net/dns-query"
        },
    },
}
