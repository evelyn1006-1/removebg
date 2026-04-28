server {
    server_name removebg.princessevelyn.com;
    client_max_body_size 10m;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # Block dotfiles except Let's Encrypt well-known
    location ~* ^/\.(?!well-known/) {
        return 404;
    }

    # Block any direct PHP endpoint probes
    location ~* \.php($|/) {
        return 404;
    }

    # Block WP-related endpoints
    location ~* ^/(?:[^/]+/)?wp-(?:login\.php|admin/|content/|includes/) {
        return 404;
    }

    location ~* ^/(wp-admin|wp-login\.php|administrator|admin\.php|admin/login|adminpanel|phpmyadmin|pma|mysql|myadmin) {
        return 404;
    }

    # Block admin and API probes
    location = /admin {
        return 404;
    }
    location /admin/ {
        return 404;
    }
    location = /api {
        return 404;
    }
    location /api/ {
        return 404;
    }

    location / {
        proxy_pass http://127.0.0.1:8004;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/removebg.princessevelyn.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/removebg.princessevelyn.com/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}

server {
    if ($host = removebg.princessevelyn.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    server_name removebg.princessevelyn.com;
    listen 80;
    return 404; # managed by Certbot

}
