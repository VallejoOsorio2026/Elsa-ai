"""Configuración de la aplicación.

Toda la configuración entra por variables de entorno con prefijo ``ELSA_``
(ver ``.env.example`` y ``docs/environment-variables.md``). La carga es tipada
y se valida al arranque: si falta una variable obligatoria o un valor es
inválido, la aplicación falla de forma clara con ``ConfigurationError`` antes
de aceptar tráfico.

Los valores secretos (secreto simétrico del JWT, cadena de conexión de la
base de ELSA, token de bootstrap) se declaran como ``SecretStr``: no se
imprimen al representar la configuración ni aparecen en los logs.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# Algoritmos de firma aceptables. `none` y cualquier algoritmo fuera de esta
# lista se rechazan en la configuración, antes de que llegue un token.
_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})
_SYMMETRIC_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_SUPPORTED_ALGORITHMS = _ASYMMETRIC_ALGORITHMS | _SYMMETRIC_ALGORITHMS


class Environment(StrEnum):
    """Ambientes lógicos del proyecto (regla 13 de CLAUDE.md)."""

    DEV = "DEV"
    TEST = "TEST"


class AuthProvider(StrEnum):
    """Origen de la verificación de identidad."""

    SUPABASE = "supabase"
    """Verificación real contra el Supabase de Materiales."""

    FAKE = "fake"
    """Adaptador determinista en memoria. Solo permitido en DEV."""


class PermissionsBackend(StrEnum):
    """Almacén del modelo de autorización de ELSA."""

    POSTGRES = "postgres"
    """Supabase ELSA a través de la credencial de servicio del backend."""

    MEMORY = "memory"
    """Almacén en memoria, no persistente. Solo permitido en DEV."""


class ArtifactStorageBackend(StrEnum):
    """Dónde viven los bytes de los archivos originales y sus derivados."""

    LOCAL = "local"
    """Sistema de archivos privado, fuera del repositorio."""

    MEMORY = "memory"
    """En memoria, no persistente. Solo permitido en DEV."""


class ConfigurationError(RuntimeError):
    """Configuración ausente o inválida detectada al arranque."""


class Settings(BaseSettings):
    """Configuración validada de ELSA.

    Campos sin valor por defecto son obligatorios: su ausencia impide el
    arranque.
    """

    model_config = SettingsConfigDict(
        env_prefix="ELSA_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------
    # Generales
    # ---------------------------------------------------------------

    env: Environment
    """Selector de ambiente lógico: DEV o TEST. Obligatorio."""

    cors_origins: Annotated[list[str], NoDecode]
    """Orígenes CORS permitidos, separados por coma. Explícitos, sin comodines."""

    log_level: str = "INFO"
    """Nivel de log de la aplicación."""

    debug: bool = False
    """Sube la verbosidad de logs. Prohibido fuera de DEV; nunca expone trazas."""

    # ---------------------------------------------------------------
    # Identidad (Materiales)
    # ---------------------------------------------------------------

    auth_provider: AuthProvider = AuthProvider.FAKE
    """Adaptador del puerto ``auth``. ``fake`` solo es válido en DEV."""

    materials_supabase_url: str | None = None
    """URL del proyecto Supabase de Materiales, p. ej. ``https://<ref>.supabase.co``."""

    materials_api_key: str | None = None
    """Clave publicable (``sb_publishable_...`` o ``anon``) de Materiales.

    Es pública por diseño: por sí sola no da acceso a nada, porque las
    políticas RLS de Materiales exigen una sesión válida. Se necesita como
    cabecera ``apikey`` para hablar con PostgREST.
    """

    auth_jwt_algorithms: Annotated[list[str], NoDecode] = ["ES256", "RS256"]
    """Algoritmos de firma aceptados. Cualquier otro se rechaza."""

    auth_jwt_audience: str | None = "authenticated"
    """Audiencia esperada (``aud``). Vacío desactiva la comprobación."""

    auth_jwt_issuer: str | None = None
    """Emisor esperado. Por defecto ``<materials_supabase_url>/auth/v1``."""

    auth_jwks_url: str | None = None
    """URL del JWKS. Por defecto la del proyecto de Materiales."""

    auth_jwt_secret: SecretStr | None = None
    """Secreto simétrico. Obligatorio solo si se acepta algún algoritmo HS*."""

    auth_jwt_leeway_seconds: int = 10
    """Tolerancia de reloj al comprobar ``exp`` / ``iat``."""

    auth_timeout_seconds: float = 5.0
    """Timeout de las llamadas al proveedor de identidad."""

    auth_jwks_cache_seconds: int = 600
    """Vigencia del JWKS en caché."""

    auth_jwks_min_refresh_seconds: int = 60
    """Espera mínima entre refrescos del JWKS ante un ``kid`` desconocido.

    Evita que un token forjado con un ``kid`` inventado provoque una
    descarga del JWKS por petición.
    """

    # ---------------------------------------------------------------
    # Autorización (Supabase ELSA)
    # ---------------------------------------------------------------

    permissions_backend: PermissionsBackend = PermissionsBackend.MEMORY
    """Almacén de permisos. ``memory`` solo es válido en DEV."""

    database_url: SecretStr | None = None
    """Cadena de conexión a Supabase ELSA. Credencial exclusiva del servidor."""

    database_pool_min_size: int = 1
    database_pool_max_size: int = 10

    bootstrap_admin_token: SecretStr | None = None
    """Token del bootstrap del primer administrador. Sin él, queda deshabilitado."""

    # ---------------------------------------------------------------
    # Almacenamiento privado de artefactos e ingesta
    # ---------------------------------------------------------------

    artifact_storage_backend: ArtifactStorageBackend = ArtifactStorageBackend.MEMORY
    """Adaptador del puerto ``artifact_storage``. ``memory`` solo es válido en DEV."""

    artifact_storage_root: Path | None = None
    """Directorio privado de artefactos. Obligatorio con el backend ``local``.

    Debe estar **fuera del repositorio**: guarda archivos internos de planta
    (XLSX de Ingeniería, exportes de SAP, imágenes de plano) que nunca pueden
    entrar en Git ni quedar expuestos por un servidor web.
    """

    ingestion_max_upload_bytes: int = 25 * 1024 * 1024
    """Tamaño máximo aceptado de un archivo subido."""

    ingestion_max_uncompressed_bytes: int = 200 * 1024 * 1024
    """Tamaño máximo al que puede expandirse un XLSX (bomba de descompresión)."""

    ingestion_max_archive_entries: int = 5_000
    """Número máximo de entradas dentro del paquete XLSX."""

    # ---------------------------------------------------------------
    # Interfaz web y demostración (Bloque 3)
    # ---------------------------------------------------------------

    web_ui_enabled: bool = True
    """Sirve la interfaz web estática desde el propio backend.

    El piloto no tiene proceso de compilación: son archivos estáticos que
    FastAPI publica en la raíz. Se puede apagar para exponer solo la API.
    """

    demo_seed: bool = False
    """Siembra datos **sintéticos** al arrancar. Solo válido en DEV.

    Los datos no proceden de la planta. La siembra además se niega a
    escribir sobre cualquier almacén que no sea el de memoria: datos de
    demostración dentro de una base real serían indistinguibles de datos
    reales al día siguiente.
    """

    contribution_max_attachments: int = 5
    """Máximo de adjuntos por aporte o por mensaje de chat."""

    contribution_max_attachment_bytes: int = 50 * 1024 * 1024
    """Tamaño máximo sumado de los adjuntos de un aporte o mensaje."""

    contribution_max_audio_seconds: int = 300
    """Duración máxima de una nota de voz. El navegador además se autodetiene."""

    # ---------------------------------------------------------------
    # Control de abuso
    # ---------------------------------------------------------------

    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60
    """Máximo de solicitudes por usuario y minuto. 0 = sin límite."""

    rate_limit_max_concurrent_requests: int = 5
    """Máximo de solicitudes simultáneas por usuario. 0 = sin límite."""

    max_sessions_per_user: int = 0
    """Máximo de sesiones ELSA simultáneas por usuario. 0 = sin límite.

    Solo es aplicable si el JWT trae un identificador de sesión fiable; ver
    la limitación documentada en ``docs/security.md``.
    """

    session_idle_timeout_seconds: int = 1800
    """Inactividad tras la cual una sesión deja de contar como activa."""

    # ---------------------------------------------------------------
    # Validadores
    # ---------------------------------------------------------------

    @field_validator("cors_origins", "auth_jwt_algorithms", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _forbid_wildcard_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("at least one explicit origin is required")
        for origin in origins:
            if "*" in origin:
                raise ValueError(f"wildcard origins are not allowed: {origin!r}")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"origin must include an http(s) scheme: {origin!r}")
        return origins

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"log level must be one of {sorted(_LOG_LEVELS)}, got {value!r}")
        return level

    @field_validator("auth_jwt_algorithms")
    @classmethod
    def _validate_algorithms(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("at least one signing algorithm must be accepted")
        normalized = [value.strip().upper() for value in values]
        for algorithm in normalized:
            if algorithm not in _SUPPORTED_ALGORITHMS:
                raise ValueError(
                    f"unsupported signing algorithm {algorithm!r}; "
                    f"allowed: {sorted(_SUPPORTED_ALGORITHMS)}"
                )
        return normalized

    @field_validator("materials_supabase_url", "auth_jwks_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        """Valida una URL opcional, tolerando la variable declarada sin valor.

        Copiar ``.env.example`` a ``.env`` deja líneas como
        ``ELSA_AUTH_JWKS_URL=``. Eso significa «no configurada», no «URL
        vacía»: se interpreta como ausencia para que el valor derivado de
        ``ELSA_MATERIALS_SUPABASE_URL`` tome el relevo. Una URL no vacía y
        malformada se sigue rechazando.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        url = stripped.rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"must include an http(s) scheme: {value!r}")
        return url

    @field_validator("auth_jwt_audience", "auth_jwt_issuer", "materials_api_key")
    @classmethod
    def _empty_string_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("auth_jwt_secret", "database_url", "bootstrap_admin_token")
    @classmethod
    def _empty_secret_is_none(cls, value: SecretStr | None) -> SecretStr | None:
        """Un secreto declarado sin valor es un secreto ausente.

        Es la diferencia entre «no hay token» y «el token es la cadena
        vacía». Sin esto, ``ELSA_BOOTSTRAP_ADMIN_TOKEN=`` —la línea que trae
        la plantilla— habilitaría el bootstrap y una comparación contra una
        cabecera ausente daría verdadera.

        Solo se descarta el valor si es vacío o son espacios; un secreto real
        se conserva tal cual, sin recortarlo.
        """
        if value is None:
            return None
        if not value.get_secret_value().strip():
            return None
        return value

    @field_validator("artifact_storage_root", mode="before")
    @classmethod
    def _empty_path_is_none(cls, value: object) -> object:
        """``ELSA_ARTIFACT_STORAGE_ROOT=`` significa «no configurada»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "ingestion_max_upload_bytes",
        "ingestion_max_uncompressed_bytes",
        "ingestion_max_archive_entries",
        "contribution_max_attachments",
        "contribution_max_attachment_bytes",
        "contribution_max_audio_seconds",
    )
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator(
        "auth_jwt_leeway_seconds",
        "auth_jwks_cache_seconds",
        "auth_jwks_min_refresh_seconds",
        "rate_limit_requests_per_minute",
        "rate_limit_max_concurrent_requests",
        "max_sessions_per_user",
        "session_idle_timeout_seconds",
    )
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must not be negative")
        return value

    @model_validator(mode="after")
    def _validate_combinations(self) -> "Settings":
        is_dev = self.env is Environment.DEV

        if self.debug and not is_dev:
            raise ValueError("debug mode is only allowed in the DEV environment")

        if self.demo_seed and not is_dev:
            raise ValueError("the synthetic demo seed is only allowed in the DEV environment")

        if self.auth_provider is AuthProvider.FAKE and not is_dev:
            raise ValueError(
                "the fake authentication provider is only allowed in the DEV environment; "
                "set ELSA_AUTH_PROVIDER=supabase"
            )

        if self.permissions_backend is PermissionsBackend.MEMORY and not is_dev:
            raise ValueError(
                "the in-memory permissions backend is only allowed in the DEV environment; "
                "set ELSA_PERMISSIONS_BACKEND=postgres"
            )

        if self.auth_provider is AuthProvider.SUPABASE:
            self._validate_supabase_auth(is_dev=is_dev)

        if self.permissions_backend is PermissionsBackend.POSTGRES and self.database_url is None:
            raise ValueError(
                "ELSA_DATABASE_URL is required when the permissions backend is postgres"
            )

        if self.auth_timeout_seconds <= 0:
            raise ValueError("must be greater than zero")

        if self.artifact_storage_backend is ArtifactStorageBackend.MEMORY and not is_dev:
            raise ValueError(
                "the in-memory artifact storage is only allowed in the DEV environment; "
                "set ELSA_ARTIFACT_STORAGE_BACKEND=local"
            )
        if (
            self.artifact_storage_backend is ArtifactStorageBackend.LOCAL
            and self.artifact_storage_root is None
        ):
            raise ValueError(
                "ELSA_ARTIFACT_STORAGE_ROOT is required when the artifact storage is local"
            )
        if self.ingestion_max_uncompressed_bytes < self.ingestion_max_upload_bytes:
            raise ValueError(
                "ELSA_INGESTION_MAX_UNCOMPRESSED_BYTES cannot be smaller than "
                "ELSA_INGESTION_MAX_UPLOAD_BYTES"
            )

        return self

    def _validate_supabase_auth(self, *, is_dev: bool) -> None:
        if self.materials_supabase_url is None and (
            self.auth_jwks_url is None or self.auth_jwt_issuer is None
        ):
            raise ValueError(
                "ELSA_MATERIALS_SUPABASE_URL is required (or set both ELSA_AUTH_JWKS_URL "
                "and ELSA_AUTH_JWT_ISSUER explicitly)"
            )
        if self.materials_supabase_url is not None and not is_dev:
            if not self.materials_supabase_url.startswith("https://"):
                raise ValueError("must use https outside the DEV environment")
        if self.materials_api_key is None:
            raise ValueError(
                "ELSA_MATERIALS_API_KEY is required to check the user profile in Materiales"
            )
        algorithms = set(self.auth_jwt_algorithms)
        if algorithms & _SYMMETRIC_ALGORITHMS and self.auth_jwt_secret is None:
            raise ValueError(
                "ELSA_AUTH_JWT_SECRET is required when a symmetric algorithm (HS*) is accepted"
            )
        if algorithms & _ASYMMETRIC_ALGORITHMS and self.jwks_url is None:
            raise ValueError(
                "ELSA_AUTH_JWKS_URL (or ELSA_MATERIALS_SUPABASE_URL) is required for "
                "asymmetric verification"
            )

    # ---------------------------------------------------------------
    # Valores derivados
    # ---------------------------------------------------------------

    @property
    def jwks_url(self) -> str | None:
        """URL efectiva del JWKS de Materiales."""
        if self.auth_jwks_url is not None:
            return self.auth_jwks_url
        if self.materials_supabase_url is None:
            return None
        return f"{self.materials_supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str | None:
        """Emisor esperado en el claim ``iss``."""
        if self.auth_jwt_issuer is not None:
            return self.auth_jwt_issuer
        if self.materials_supabase_url is None:
            return None
        return f"{self.materials_supabase_url}/auth/v1"

    @property
    def materials_profiles_url(self) -> str | None:
        """Endpoint PostgREST de la tabla ``perfiles`` de Materiales."""
        if self.materials_supabase_url is None:
            return None
        return f"{self.materials_supabase_url}/rest/v1/perfiles"


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Carga y valida la configuración.

    Las variables de entorno reales tienen prioridad sobre ``env_file``.
    Lanza :class:`ConfigurationError` con un mensaje legible (una línea por
    variable afectada) si la configuración es inválida.
    """
    try:
        # `_env_file` es un kwarg de runtime de BaseSettings que la firma
        # sintetizada por mypy no declara.
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from None


def _format_validation_error(exc: ValidationError) -> str:
    prefix = Settings.model_config.get("env_prefix", "")
    lines = ["Invalid application configuration:"]
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "settings"
        variable = f"{prefix}{loc}".upper()
        lines.append(f"  - {variable}: {error['msg']}")
    lines.append("See .env.example and docs/environment-variables.md.")
    return "\n".join(lines)
