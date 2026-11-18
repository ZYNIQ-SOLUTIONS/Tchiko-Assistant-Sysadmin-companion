---
name: nginx-tls-audit
description: Audit Nginx reverse-proxy configs, TLS 1.3, HSTS headers, and Certbot renewal status.
triggers: nginx, reverse proxy, certbot, ssl, hsts, 502 bad gateway
---
# Nginx & TLS Audit Runbook

1. Validate configuration syntax: `nginx -t` (never reload before checking syntax).
2. Inspect active sites in `/etc/nginx/sites-enabled/` with `<view_file>`.
3. Verify upstream sockets/ports with `<network_audit />` if seeing `502 Bad Gateway`.
4. Check TLS certificate expiry with `<tls host="<domain>" />` or `certbot certificates`.
5. Ensure modern security headers (`Strict-Transport-Security`, `TLSv1.2 TLSv1.3`) are present.
