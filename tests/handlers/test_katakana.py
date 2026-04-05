import json
from pathlib import Path

from handlers.katakana import E2KConverter, Romaji


def _write_json(tmp_path: Path, obj, name="romaji.json") -> Path:
    p: Path = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _write_dict(tmp_path: Path, lines, name="e2kata.dic") -> Path:
    p: Path = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def teardown_function(_) -> None:
    # Clear state per test to avoid side effects.
    Romaji.tree.clear()
    Romaji.max_unit_len = 0
    E2KConverter.clear()


def test_romaji_load_empty(tmp_path: Path) -> None:
    p: Path = _write_json(tmp_path, {})
    Romaji.load(p)
    assert Romaji.tree == {}
    assert Romaji.max_unit_len == 0


def test_get_kana_bounds() -> None:
    assert Romaji.get_kana("a", 1) == ""
    assert Romaji.get_kana("a", -1) == ""


def test_konnichiwa_and_kitte(tmp_path: Path) -> None:
    # Use a minimal dictionary to validate hatsuon and sokuon behavior.
    mapping: dict[str, str] = {
        "ko": "コ",
        "ni": "ニ",
        "chi": "チ",
        "wa": "ワ",
        "ki": "キ",
        "te": "テ",
    }
    p: Path = _write_json(tmp_path, mapping)
    Romaji.load(p)

    assert Romaji.romanize("konnichiwa") == "コンニチワ"
    assert Romaji.romanize("kitte") == "キッテ"


def test_hatsuon_and_sokuon_rules() -> None:
    # Hatsuon rules.
    assert Romaji.is_hatsuon("n", 0) is True  # Trailing n -> ン.
    assert Romaji.is_hatsuon("na", 0) is False  # n before a vowel is not hatsuon.
    assert Romaji.is_hatsuon("mb", 0) is True  # m before b -> ン.

    # Sokuon rules.
    assert Romaji.is_sokuon("kk", 0) is True
    assert Romaji.is_sokuon("nn", 0) is False  # n is not sokuon.
    assert Romaji.is_sokuon("kt", 0) is False


def test_katakanaise_to_kana_with_dict_and_special_chars(tmp_path: Path) -> None:
    lines: list[str] = ["hello ハロー", "EBAY イーベイ"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    # Verify direct replacements and that an unknown single 'x' becomes 'クス'.
    src = "hello EBAY x "
    out: str = E2KConverter.katakanaize(src)
    assert out == "ハロー イーベイ クス "


def test_camelcase_with_space(tmp_path: Path) -> None:
    lines: list[str] = ["EBAY イーベイ", "SERVER サーバー"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    src = "eBay Server"
    out: str = E2KConverter.katakanaize(src)
    # When CamelCase starts with a single letter, it is treated as romaji and some characters remain.
    # Lock in the expected behavior.
    assert out == "eブaイー サーバー"


def test_abbreviation_uppercase(tmp_path: Path) -> None:
    lines: list[str] = ["NASA ナサ"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    src = "We use NASA."
    out: str = E2KConverter.katakanaize(src)
    # Without English word detection, English text is romaji-processed (caller must avoid this).
    assert out == "ウe uスe ナサ."


def test_apostrophe_hatsuon(tmp_path: Path) -> None:
    mapping: dict[str, str] = {"ko": "コ", "ni": "ニ", "chi": "チ", "wa": "ワ"}
    p: Path = _write_json(tmp_path, mapping)
    Romaji.load(p)

    # Apostrophes currently remain (potential improvement).
    assert Romaji.romanize("kon'nichiwa") == "コン'ニチワ"


def test_n_end_and_m_before_bp(tmp_path: Path) -> None:
    mapping: dict[str, str] = {"ca": "カ", "la": "ラ", "ba": "バ"}
    p: Path = _write_json(tmp_path, mapping)
    Romaji.load(p)

    assert Romaji.romanize("can") == "カン"
    assert Romaji.romanize("lamba") == "ランバ"


def test_load_bep_and_user_merge() -> None:
    # Clear first, then load.
    E2KConverter.clear()
    root: Path = Path(__file__).resolve().parents[2]
    bep: Path = root / "dic" / "bep-eng.dic"
    user: Path = root / "dic" / "user.dic"

    E2KConverter.load(bep)
    # Ensure entries from bep-eng.dic are loaded.
    assert "NASA" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["NASA"] == "ナサ"

    E2KConverter.load(user)
    # Ensure entries from user.dic are loaded.
    assert "VOICEVOX" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["VOICEVOX"] == "ボイスボックス"
    # Ensure short entries from user.dic are loaded.
    assert "A" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["A"] == "ア"

    # Existing bep entries remain.
    assert "NASA" in E2KConverter.e2kata_dict


def test_load_user_override(tmp_path: Path) -> None:
    # Confirm user dictionary entries override earlier ones.
    E2KConverter.clear()
    root: Path = Path(__file__).resolve().parents[2]
    bep: Path = root / "dic" / "bep-eng.dic"
    E2KConverter.load(bep)

    assert E2KConverter.e2kata_dict.get("NASA") == "ナサ"

    override: Path = tmp_path / "user_override.dic"
    override.write_text("NASA ナサ_OVERRIDE\n", encoding="utf-8")

    E2KConverter.load(override)
    assert E2KConverter.e2kata_dict.get("NASA") == "ナサ_OVERRIDE"
