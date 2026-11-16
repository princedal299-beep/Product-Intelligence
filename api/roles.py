SHOPPER = "Shopper"
MERCHANDISER = "Merchandiser"
ADMIN = "ADMIN"

UserRole = str  


def scopes_for_role(role: str) -> tuple[str, ...]:
    clean = str(role or "").strip().upper()
    if clean == "SHOPPER":
        return ("catalog:read",)
    if clean == "MERCHANDISER":
        return ("catalog:read", "catalog:analytics")
    if clean == "ADMIN":
        return ("catalog:read", "catalog:analytics")
    raise ValueError(f"Unknown user role: {role}")