"""Configuration models and loader for gcp-janitor."""

import importlib.resources
from pathlib import Path
import tomllib
from typing import Self

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KmsPolicy(BaseSettings):
    """Concrete policy defining retention thresholds and exclusion criteria."""

    disable_after_days: int = Field(
        default=14,
        ge=0,
        description="Days before disabling active versions (0 to disable)",
    )
    delete_after_days: int = Field(
        default=30,
        ge=0,
        description="Days before scheduling destruction (0 to disable)",
    )
    exclude_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Exact key-value label matches to exclude",
    )
    exclude_label_keys: list[str] = Field(
        default_factory=list,
        description="Label keys that exclude a key regardless of value",
    )

    def is_excluded(self, labels: dict[str, str]) -> bool:
        """
        Check if a resource with the given labels should be excluded from cleanup.

        Args:
            labels: Map of resource labels (e.g. from CryptoKey.labels).

        Returns:
            True if any exclusion criteria match, False otherwise.
        """
        # Exclude if resource contains any blocked label key
        for key in self.exclude_label_keys:
            if key in labels:
                return True

        # Exclude if resource matches any exact key-value label pair
        for key, value in self.exclude_labels.items():
            if labels.get(key) == value:
                return True

        return False


class KmsKeyringOverride(BaseSettings):
    """Optional overrides for a specific keyring. Unset fields fallback to default."""

    disable_after_days: int | None = Field(default=None, ge=0)
    soft_delete_after_days: int | None = Field(default=None, ge=0)
    hard_delete_empty_keyrings: bool | None = None
    exclude_labels: dict[str, str] | None = None
    exclude_label_keys: list[str] | None = None


class KmsConfig(BaseSettings):
    """KMS service configuration."""

    enabled: bool = True
    default: KmsPolicy = Field(default_factory=KmsPolicy)
    keyrings: dict[str, KmsKeyringOverride] = Field(default_factory=dict)

    def resolve_policy(self, keyring_name: str) -> KmsPolicy:
        """
        Return the effective policy for a given keyring, merging keyring-specific
        overrides into the base [kms.default] policy.

        Args:
            keyring_name: Either the simple keyring ID (e.g. 'my-ring') or the
                full resource path ('projects/.../locations/.../keyRings/my-ring').

        Returns:
            KmsPolicy: Merged effective policy.
        """
        # Support full resource paths or short IDs
        short_name = keyring_name.split("/")[-1]
        override = self.keyrings.get(short_name) or self.keyrings.get(keyring_name)

        if not override:
            return self.default

        # Merge base default with non-None override fields
        merged = self.default.model_dump()
        override_fields = {
            k: v for k, v in override.model_dump().items() if v is not None
        }
        merged.update(override_fields)

        # Merge label sets (union) rather than replacing
        if override.exclude_labels:
            merged["exclude_labels"] = {
                **self.default.exclude_labels,
                **override.exclude_labels,
            }
        if override.exclude_label_keys:
            merged["exclude_label_keys"] = sorted(
                set(self.default.exclude_label_keys) | set(override.exclude_label_keys)
            )

        return KmsPolicy.model_validate(merged)


class GeneralConfig(BaseSettings):
    """Daemon execution parameters."""

    project_id: str = Field(default="", description="GCP project ID")
    locations: list[str] = Field(default_factory=lambda: ["global", "us-central1"])
    dry_run: bool = Field(default=True, description="Dry-run safety switch")
    interval_seconds: int = Field(default=3600, gt=0)


class Config(BaseSettings):
    """Root configuration object matching default.config.toml."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    kms: KmsConfig = Field(default_factory=KmsConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Self:
        """
        Load configuration with fallback resolution:
        1. Explicit path (e.g. from CLI --config or K8s ConfigMap mount).
        2. Local config.toml in the working directory (if present).
        3. Packaged default.config.toml bundled inside the Python package.
        4. Pure in-memory defaults if no file is found.

        Args:
            path: Optional path to the TOML configuration file.

        Returns:
            Config: Validated configuration object.
        """
        # 1. Explicit path
        if path:
            target = Path(path)
            if not target.is_file():
                raise FileNotFoundError(f"Config file not found: {path}")
            with target.open("rb") as f:
                return cls.model_validate(tomllib.load(f))

        # 2. Local config.toml in current working directory
        local_cfg = Path("config.toml")
        if local_cfg.is_file():
            with local_cfg.open("rb") as f:
                return cls.model_validate(tomllib.load(f))

        # 3. Packaged default fallback via importlib.resources
        try:
            pkg_file = importlib.resources.files("gcp_janitor").joinpath(
                "default.config.toml"
            )
            if pkg_file.is_file():
                with pkg_file.open("rb") as f:
                    return cls.model_validate(tomllib.load(f))
        except (ModuleNotFoundError, TypeError):
            pass

        # 4. In-memory defaults
        return cls()
