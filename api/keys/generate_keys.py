from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = Path(__file__).parent

private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

public_key = private_key.public_key()

private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)

public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

if __name__ == "__main__":
    private_path = KEYS_DIR / "private.pem"
    public_path = KEYS_DIR / "public.pem"

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)

    print(f"Private Key: {private_path}")
    print(f"Public Key : {public_path}")
