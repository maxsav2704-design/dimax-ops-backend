"""Apply the same production policy to direct ASGI and container startup."""
import os

from scripts.validate_production_env import validate_runtime_environment


def validate_startup(settings, *, factory_email_key: str = "") -> bool:
    production = os.environ.get("APP_ENV", "development").lower() == "production"
    if production:
        env = {key: str(value) for key, value in settings.model_dump().items() if value is not None}
        env["FACTORY_APPROVAL_EMAIL_KEY"] = factory_email_key
        errors, _ = validate_runtime_environment(env)
        if errors:
            raise RuntimeError("Production configuration rejected: " + "; ".join(errors))
    return production
