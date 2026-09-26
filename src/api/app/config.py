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
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_sync_interval_seconds: int = 3600
    auth_allow_demo: bool = True
    seed_on_startup: bool = True

    @property
    def entra_graph_configured(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id and self.entra_client_secret)


settings = Settings()
