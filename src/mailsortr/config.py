"""Configuration loading and validation for MailSortr AI."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import yaml
from platformdirs import user_config_path

APP_NAME = "mailsortr"
MAX_CATEGORIES = 15
MIN_CATEGORIES = 2
FALLBACK_ID = "UNSURE"
LANGUAGES = ("en", "fr")
ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,29}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"


class ConfigError(ValueError):
    """The configuration is invalid. The message says what to fix."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


@dataclass(frozen=True)
class Category:
    id: str            # stable key, stored in the database / clé stable, stockée dans la base de données
    name: str          # display name, used as the Gmail label: AI/<name> / nom affiché, utilisé comme étiquette Gmail : AI/<name>
    description: str   # tells the AI what belongs here / indique à l'IA ce qui appartient ici
    archive: bool = False  # True: mails of this category may leave the inbox / True : les mails de cette catégorie peuvent quitter la boîte de réception


@dataclass(frozen=True)
class LLMConfig:
    model: str = "qwen3:4b"          # any model available through Ollama / tout modèle disponible via Ollama
    base_url: str = DEFAULT_OLLAMA_URL
    timeout_seconds: int = 300


@dataclass(frozen=True)
class AppConfig:
    language: str = "en"
    label_prefix: str = "AI"
    max_mails: int = 50
    simulate: bool = True  # safe default: show what would happen, change nothing / par défaut sûr : montrer ce qui se passerait, ne rien changer
    llm: LLMConfig = field(default_factory=LLMConfig)
    categories: tuple[Category, ...] = ()

    @property
    def all_categories(self) -> tuple[Category, ...]:
        """User categories + the built-in fallback (not counted in the limit)."""
        fallback = Category(
            FALLBACK_ID, "Unsure", "Use only if the email truly cannot be classified.", False
        )
        return self.categories + (fallback,)

def _parse_category(raw: object, index: int) -> Category:
    where = f"categories[{index}]"
    _require(isinstance(raw, dict), f"{where}: must be a mapping")

    cid = str(raw.get("id") or "").strip().upper()
    _require(
        bool(ID_PATTERN.match(cid)),
        f"{where}: invalid id {cid!r} (A-Z, 0-9, _ ; 2-30 chars ; start with a letter)",
    )
    _require(cid != FALLBACK_ID, f"{where}: the id {FALLBACK_ID} is reserved")

    name = str(raw.get("name") or "").strip()
    _require(1 <= len(name) <= 40, f"{where}: name must be 1-40 characters")
    _require("/" not in name, f"{where}: name cannot contain '/'")

    description = str(raw.get("description") or "").strip()
    _require(
        5 <= len(description) <= 200,
        f"{where}: description must be 5-200 characters",
    )

    archive = raw.get("archive", False)
    _require(isinstance(archive, bool), f"{where}: archive must be true or false")

    return Category(cid, name, description, archive)


def _parse_llm(raw: object) -> LLMConfig:
    if raw is None:
        return LLMConfig()
    _require(isinstance(raw, dict), "llm: must be a mapping")

    model = str(raw.get("model") or "").strip()
    _require(bool(model), "llm.model is required")

    base_url = str(raw.get("base_url") or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    parsed = urlparse(base_url)
    _require(
        parsed.scheme in ("http", "https") and bool(parsed.hostname),
        "llm.base_url must be a valid http(s) address",
    )
    _require(
        parsed.hostname in LOCAL_HOSTS,
        "llm.base_url must point to this computer (localhost or 127.0.0.1): "
        "MailSortr AI only works with a local AI",
    )

    timeout = raw.get("timeout_seconds", 300)
    _require(
        isinstance(timeout, int) and not isinstance(timeout, bool) and 10 <= timeout <= 3600,
        "llm.timeout_seconds must be an integer between 10 and 3600",
    )

    return LLMConfig(model, base_url, timeout)


def parse_config(data: object) -> AppConfig:
    """Validate a dictionary (from YAML or from the UI) and build the config."""
    _require(isinstance(data, dict), "The configuration must be a mapping")

    language = str(data.get("language") or "en")
    _require(language in LANGUAGES, f"language must be one of {LANGUAGES}")

    prefix = str(data.get("label_prefix") or "AI").strip()
    _require(
        1 <= len(prefix) <= 20 and "/" not in prefix,
        "label_prefix must be 1-20 characters, without '/'",
    )

    max_mails = data.get("max_mails", 50)
    _require(
        isinstance(max_mails, int) and not isinstance(max_mails, bool) and 1 <= max_mails <= 1000,
        "max_mails must be an integer between 1 and 1000",
    )

    simulate = data.get("simulate", True)
    _require(isinstance(simulate, bool), "simulate must be true or false")

    raw_categories = data.get("categories")
    _require(isinstance(raw_categories, list), "categories must be a list")
    _require(
        MIN_CATEGORIES <= len(raw_categories) <= MAX_CATEGORIES,
        f"You need between {MIN_CATEGORIES} and {MAX_CATEGORIES} categories "
        f"(got {len(raw_categories)})",
    )
    categories = tuple(_parse_category(c, i) for i, c in enumerate(raw_categories))

    ids = [c.id for c in categories]
    names = [c.name.lower() for c in categories]
    _require(len(set(ids)) == len(ids), "Two categories share the same id")
    _require(len(set(names)) == len(names), "Two categories share the same name")
    _require("unsure" not in names, "The name 'Unsure' is reserved")

    return AppConfig(
        language=language,
        label_prefix=prefix,
        max_mails=max_mails,
        simulate=simulate,
        llm=_parse_llm(data.get("llm")),
        categories=categories,
    )


def default_config_path() -> Path:
    """~/.config/mailsortr/config.yaml on Linux, %APPDATA% equivalent on Windows."""
    return user_config_path(APP_NAME, appauthor=False) / "config.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or default_config_path()
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except FileNotFoundError as error:
        raise ConfigError(f"Configuration file not found: {path}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"Invalid YAML in {path}: {error}") from error
    return parse_config(data)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "language": config.language,
        "label_prefix": config.label_prefix,
        "max_mails": config.max_mails,
        "simulate": config.simulate,
        "llm": {
            "model": config.llm.model,
            "base_url": config.llm.base_url,
            "timeout_seconds": config.llm.timeout_seconds,
        },
        "categories": [
            {"id": c.id, "name": c.name, "description": c.description, "archive": c.archive}
            for c in config.categories
        ],
    }
    with open(path, "w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)