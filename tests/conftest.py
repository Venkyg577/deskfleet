import os

# Set before any app module is imported so pydantic-settings picks them up.
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("STORE_API_OFFLINE", "1")
