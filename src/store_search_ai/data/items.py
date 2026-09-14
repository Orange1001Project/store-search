from __future__ import annotations

import html
import re
import pandas as pd


PLACEHOLDERS = {
    "",
    "-",
    ".",
    "없음",
}


LOW_INFORMATION = {
    "기타",
    "서비스",
    "서비스업",
    "제품",
    "판매",
    "소매",
}


SPACE_RE = re.compile(r"\s+")


def clean_item_text(value: object) -> str | None:

    if value is None or pd.isna(value):
        return None

    text = str(value)

    # &amp; 등의 HTML entity 먼저 복원
    text = html.unescape(text)

    text = text.replace("\xa0", " ")

    text = SPACE_RE.sub(
        " ",
        text,
    ).strip()

    if text in PLACEHOLDERS:
        return None

    return text or None


def split_outside_parentheses(
    text: str,
) -> list[str]:

    tokens = []

    buffer = []

    depth = 0

    separators = {
        ",",
        ";",
        "/",
        "|",
    }

    for char in text:

        if char == "(":
            depth += 1

        elif char == ")" and depth > 0:
            depth -= 1

        if (
            char in separators
            and depth == 0
        ):

            token = "".join(buffer).strip()

            if token:
                tokens.append(token)

            buffer = []

        else:
            buffer.append(char)

    token = "".join(buffer).strip()

    if token:
        tokens.append(token)

    return tokens


def parse_item_tokens(
    value: object,
) -> list[str]:

    text = clean_item_text(value)

    if text is None:
        return []

    return split_outside_parentheses(text)


def item_has_unbalanced_parentheses(
    value: object,
) -> bool:

    text = clean_item_text(value)

    if text is None:
        return False

    return (
        text.count("(")
        != text.count(")")
    )


def item_is_low_information(
    value: object,
) -> bool:

    text = clean_item_text(value)

    if text is None:
        return True

    return text in LOW_INFORMATION

def has_ambiguous_suffix(
    value: object,
) -> bool:
    """
    '주방용품외', '과일 등'처럼
    범위가 불명확한 표현인지 표시하기 위한 quality flag.
    """

    text = clean_item_text(value)

    if text is None:
        return False

    return bool(
        re.search(
            r"(외|등)\s*$",
            text
        )
    )