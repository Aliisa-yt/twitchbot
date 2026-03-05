"""Load Google Cloud STT V2 location/model metadata from a text table."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class STTLanguageInfo(TypedDict):
    """Metadata for one BCP-47 language key."""

    location: str
    models: tuple[str, ...]
    default_model: str


@dataclass(slots=True)
class _MutableLanguageInfo:
    """Mutable accumulator used while building the final index."""

    location_to_models: dict[str, list[str]] = field(default_factory=dict)


_MODEL_PRIORITY: dict[str, int] = {
    "chirp_3": 0,
    "chirp_2": 1,
    "chirp": 2,
    "chirp_telephony": 3,
    "long": 4,
    "short": 5,
    "telephony": 6,
    "telephony_short": 7,
    "medical_conversation": 8,
    "medical_dictation": 9,
}

STABLE_LOCATIONS: frozenset[str] = frozenset({"global", "us", "eu", "us-central1"})


def normalize_bcp47(code: str) -> str:
    """Normalize a BCP-47 language code for stable dictionary lookup.

    Args:
        code: Raw language code from INI or source data.

    Returns:
        Normalized BCP-47 string.
    """
    raw = code.strip()
    if not raw:
        return raw

    parts = raw.split("-")
    normalized: list[str] = []

    for index, part in enumerate(parts):
        if not part:
            continue
        if index == 0:
            normalized.append(part.lower())
            continue
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
            continue
        if (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
            continue
        normalized.append(part)

    return "-".join(normalized)


def load_stt_language_index(
    file_path: str | Path,
    preferred_locations: tuple[str, ...] | None = ("global", "us", "eu", "us-central1"),
    allowed_locations: frozenset[str] | None = None,
) -> dict[str, STTLanguageInfo]:
    """Load table data and build a BCP-47 keyed index.

    Args:
        file_path: Path to the table text file.
        preferred_locations: Location priority for choosing one location per language.
            When None, the first-seen location in the source file is used.
        allowed_locations: Optional allow-list for locations.
            When provided, rows outside this set are ignored.

    Returns:
        Dictionary keyed by normalized BCP-47.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If a non-comment data line cannot be parsed.
    """
    source_path = Path(file_path)
    if not source_path.exists():
        msg = f"STT metadata file was not found: {source_path}"
        raise FileNotFoundError(msg)

    temp_index = _build_temp_index(source_path, allowed_locations)

    final_index: dict[str, STTLanguageInfo] = {}
    for key, info in temp_index.items():
        selected_location = _select_location(info.location_to_models, preferred_locations)
        if selected_location is None:
            continue

        sorted_models = tuple(sorted(info.location_to_models[selected_location], key=_model_sort_key))
        if not sorted_models:
            msg = f"No model found for BCP-47 key: {key}"
            raise ValueError(msg)

        final_index[key] = {
            "location": selected_location,
            "models": sorted_models,
            "default_model": sorted_models[0],
        }

    return final_index


def _build_temp_index(source_path: Path, allowed_locations: frozenset[str] | None) -> dict[str, _MutableLanguageInfo]:
    """Build a mutable index from source rows."""
    temp_index: dict[str, _MutableLanguageInfo] = {}

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if _is_skippable_line(line):
                continue

            columns = _split_table_line(line)
            if columns is None:
                msg = f"Could not parse line {line_number}: {raw_line.rstrip()}"
                raise ValueError(msg)

            location, _name, bcp47_code, model = columns
            if allowed_locations is not None and location not in allowed_locations:
                continue

            key = normalize_bcp47(bcp47_code)
            info = temp_index.setdefault(key, _MutableLanguageInfo())
            models = info.location_to_models.setdefault(location, [])
            if model not in models:
                models.append(model)

    return temp_index


def _is_skippable_line(line: str) -> bool:
    """Return True when a source line should be ignored."""
    if not line:
        return True
    return bool(line.startswith("#"))


def get_stt_language_info(index: Mapping[str, STTLanguageInfo], bcp47_code: str) -> STTLanguageInfo | None:
    """Get one language record with normalized BCP-47 lookup.

    Args:
        index: BCP-47 keyed metadata index.
        bcp47_code: Requested language code.

    Returns:
        Metadata dictionary, or None when not found.
    """
    key = normalize_bcp47(bcp47_code)
    return index.get(key)


def _split_table_line(line: str) -> tuple[str, str, str, str] | None:
    """Split one table row into 4 columns.

    Args:
        line: One non-empty, non-comment row.

    Returns:
        (location, name, bcp47, model) or None when parsing fails.
    """
    tab_parts = [part.strip() for part in line.split("\t") if part.strip()]
    if len(tab_parts) >= 4:
        return tab_parts[0], tab_parts[1], tab_parts[2], tab_parts[3]

    normalized = " ".join(line.split())
    parts = normalized.split(" ")
    if len(parts) < 4:
        return None

    location = parts[0]
    model = parts[-1]
    bcp47_code = parts[-2]
    name = " ".join(parts[1:-2])
    if not name:
        return None

    return location, name, bcp47_code, model


def _model_sort_key(model_name: str) -> tuple[int, str]:
    """Sort models by preferred priority and stable name order."""
    return _MODEL_PRIORITY.get(model_name, 999), model_name


def _select_location(
    location_to_models: dict[str, list[str]], preferred_locations: tuple[str, ...] | None
) -> str | None:
    """Select one location for a language according to the configured policy."""
    if not location_to_models:
        return None

    if preferred_locations is None:
        return next(iter(location_to_models))

    for location in preferred_locations:
        if location in location_to_models:
            return location

    return next(iter(location_to_models))
