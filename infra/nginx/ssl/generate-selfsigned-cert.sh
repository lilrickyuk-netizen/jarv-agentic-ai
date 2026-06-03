#!/bin/bash
# Generate self-signed SSL certificate for development/testing
# For production, use Let's Encrypt or your certificate provider

CERT_DIR="$(dirname "$0")"
DOMAIN="${DOMAIN:-localhost}"
DAYS="${DAYS:-365}"

echo "Generating self-signed SSL certificate for $DOMAIN..."

openssl req -x509 -nodes -days $DAYS -newkey rsa:2048 \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -subj "/C=US/ST=State/L=City/O=JARV/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:*.${DOMAIN},DNS:localhost"

chmod 600 "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"

echo "SSL certificate generated successfully!"
echo "Certificate: $CERT_DIR/cert.pem"
echo "Private Key: $CERT_DIR/key.pem"
echo ""
echo "WARNING: This is a self-signed certificate for development only."
echo "For production, use Let's Encrypt or a trusted certificate authority."
