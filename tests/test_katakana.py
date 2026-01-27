import json
from pathlib import Path

from handlers.katakana import E2KConverter, Romaji


def _write_json(tmp_path, obj, name="romaji.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _write_dict(tmp_path, lines, name="e2kata.dic") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def teardown_function(_) -> None:
    # テストごとに状態をクリアして副作用を防ぐ
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
    # 最小限の辞書を用意して、撥音・促音の挙動を確認する
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
    # 撥音の判定
    assert Romaji.is_hatsuon("n", 0) is True  # 末尾の n -> ン
    assert Romaji.is_hatsuon("na", 0) is False  # 母音の前の n は撥音ではない
    assert Romaji.is_hatsuon("mb", 0) is True  # m の後に b -> ン

    # 促音の判定
    assert Romaji.is_sokuon("kk", 0) is True
    assert Romaji.is_sokuon("nn", 0) is False  # n は促音ではない
    assert Romaji.is_sokuon("kt", 0) is False


def test_katakanaise_to_kana_with_dict_and_special_chars(tmp_path: Path) -> None:
    lines: list[str] = ["hello ハロー", "EBAY イーベイ"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    # 単純置換と、辞書にない単文字 x が内部置換で 'クス' になることを検証
    src = "hello EBAY x "
    out: str = E2KConverter.katakanaize(src)
    assert out == "ハロー イーベイ クス "


def test_camelcase_with_space(tmp_path: Path) -> None:
    lines: list[str] = ["EBAY イーベイ", "SERVER サーバー"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    src = "eBay Server"
    out: str = E2KConverter.katakanaize(src)
    # 実装では CamelCase の先頭が単文字の場合にはローマ字扱いとなり、部分的に非変換文字の置換が走る
    # 期待の振る舞いを固定して検証する
    assert out == "eブaイー サーバー"


def test_abbreviation_uppercase(tmp_path: Path) -> None:
    lines: list[str] = ["NASA ナサ"]
    p: Path = _write_dict(tmp_path, lines)
    E2KConverter.load(p)

    src = "We use NASA."
    out: str = E2KConverter.katakanaize(src)
    # 実装では英単語の判定がないため、英語部分もローマ字処理される（回避は呼び出し側で行う）
    assert out == "ウe uスe ナサ."


def test_apostrophe_hatsuon(tmp_path: Path) -> None:
    mapping: dict[str, str] = {"ko": "コ", "ni": "ニ", "chi": "チ", "wa": "ワ"}
    p: Path = _write_json(tmp_path, mapping)
    Romaji.load(p)

    # 現状ではアポストロフィは残る（改修候補）
    assert Romaji.romanize("kon'nichiwa") == "コン'ニチワ"


def test_n_end_and_m_before_bp(tmp_path: Path) -> None:
    mapping: dict[str, str] = {"ca": "カ", "la": "ラ", "ba": "バ"}
    p: Path = _write_json(tmp_path, mapping)
    Romaji.load(p)

    assert Romaji.romanize("can") == "カン"
    assert Romaji.romanize("lamba") == "ランバ"


def test_load_bep_and_user_merge() -> None:
    # 事前にクリアしてから読み込む
    E2KConverter.clear()
    root: Path = Path(__file__).resolve().parents[1]
    bep: Path = root / "dic" / "bep-eng.dic"
    user: Path = root / "dic" / "user.dic"

    E2KConverter.load(bep)
    # bep-eng.dic 由来の単語が読み込まれている
    assert "NASA" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["NASA"] == "ナサ"

    E2KConverter.load(user)
    # user.dic 由来の単語が読み込まれている
    assert "VOICEVOX" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["VOICEVOX"] == "ボイスボックス"
    # user.dic に定義されている小語も読み込まれる
    assert "A" in E2KConverter.e2kata_dict
    assert E2KConverter.e2kata_dict["A"] == "ア"

    # 既存の bep の項目は残っている
    assert "NASA" in E2KConverter.e2kata_dict


def test_load_user_override(tmp_path: Path) -> None:
    # ユーザ辞書の後読み込みで上書きされることを確認
    E2KConverter.clear()
    root: Path = Path(__file__).resolve().parents[1]
    bep: Path = root / "dic" / "bep-eng.dic"
    E2KConverter.load(bep)

    assert E2KConverter.e2kata_dict.get("NASA") == "ナサ"

    override: Path = tmp_path / "user_override.dic"
    override.write_text("NASA ナサ_OVERRIDE\n", encoding="utf-8")

    E2KConverter.load(override)
    assert E2KConverter.e2kata_dict.get("NASA") == "ナサ_OVERRIDE"
