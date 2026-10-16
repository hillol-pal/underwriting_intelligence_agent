"""Application logs. Claim text is included. Secrets are not."""
import logging

_SECRET_NAMES = ("api_key", "authorization", "password", "secret", "token")


def event(logger: logging.Logger, name: str, **fields) -> None:
    """One info line. Values are logged in full except secret field names."""
    parts = [name]
    for key, value in fields.items():
        if any(secret in key.lower() for secret in _SECRET_NAMES):
            parts.append(f"{key}=[redacted]")
            continue
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))
