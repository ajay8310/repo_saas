"""Generate RSA key pair for JWT signing and write to files."""
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

priv_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

pub_pem = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

with open("/keys/private.pem", "w") as f:
    f.write(priv_pem)
with open("/keys/public.pem", "w") as f:
    f.write(pub_pem)

print("Keys generated successfully")
