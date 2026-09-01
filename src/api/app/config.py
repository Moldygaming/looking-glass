from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_secret: str = "change-me"
    internal_api_key: str = "change-me-internal-key"
    database_url: str = (
        "postgresql+asyncpg://lookingglass:lookingglass@localhost:5432/lookingglass"
    )
    web_origin: str = "http://localhost:3000"
    blob_endpoint: str = ""
    blob_account: str = ""
    blob_key: str = ""
    blob_container: str = "cost-exports"
    entra_admin_role: str = "PlatformAdmin"
    auth_allow_demo: bool = True
    seed_on_startup: bool = True


settings = Settings()
