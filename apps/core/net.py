"""Utilidades de red: IP pública del cliente detrás de proxies (CloudFront / ALB / Nginx)."""
import ipaddress

from django.conf import settings


def get_client_ip(request):
    """
    IP pública del visitante.

    Con TRUSTED_PROXY_COUNT = N se toma la N-ésima IP desde el final de X-Forwarded-For
    (cada proxy de confianza agrega una). Así un cliente no puede falsificar su IP
    enviando su propio X-Forwarded-For. Con N = 0 se usa REMOTE_ADDR.
    """
    proxies = settings.TRUSTED_PROXY_COUNT
    ip = request.META.get("REMOTE_ADDR", "")
    if proxies > 0:
        chain = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(chain) >= proxies:
            ip = chain[-proxies]
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def ip_in_list(ip, networks):
    """True si la IP está en alguna de las IPs/redes CIDR dadas (ej. '181.50.1.10', '10.0.0.0/8')."""
    if not ip:
        return False
    addr = ipaddress.ip_address(ip)
    for net in networks:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False
