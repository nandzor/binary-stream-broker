#!/bin/bash
# Generate self-signed certificate for development/testing
# For production, use certificates from a trusted CA (Let's Encrypt, etc.)

mkdir -p certs

# Generate private key
openssl genrsa -out certs/server.key 2048

# Generate certificate signing request
openssl req -new -key certs/server.key -out certs/server.csr \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in certs/server.csr -signkey certs/server.key \
    -out certs/server.crt

# Clean up CSR
rm certs/server.csr

echo "Certificate generated successfully!"
echo "  Certificate: certs/server.crt"
echo "  Private Key: certs/server.key"
echo ""
echo "Note: This is a self-signed certificate for development only."
echo "For production, use certificates from a trusted CA."

