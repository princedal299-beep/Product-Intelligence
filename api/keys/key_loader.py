from pathlib import Path

KEYS_DIR = Path(__file__).parent

PRIVATE_KEY: bytes = (KEYS_DIR / "private.pem").read_bytes()
PUBLIC_KEY: bytes = (KEYS_DIR / "public.pem").read_bytes()
