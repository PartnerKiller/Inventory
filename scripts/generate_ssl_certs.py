import os
import datetime
import ipaddress
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert(cert_dir):
    os.makedirs(cert_dir, exist_ok=True)
    key_file = os.path.join(cert_dir, "server.key")
    cert_file = os.path.join(cert_dir, "server.crt")

    # Generate RSA private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Texas"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Austin"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AuraStock Enterprise"),
        x509.NameAttribute(NameOID.COMMON_NAME, "192.168.0.11"),
    ])

    alt_names = [
        x509.IPAddress(ipaddress.IPv4Address("192.168.0.11")),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.DNSName("localhost"),
        x509.DNSName("aurastock.local"),
        x509.DNSName("api.aurastock.production"),
    ]

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)) # 10 years
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    # Write key
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Write cert
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"[OK] Generated Production SSL Certificate:\n  Key:  {key_file}\n  Cert: {cert_file}")

if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "deploy", "ssl"))
    generate_self_signed_cert(base_dir)
