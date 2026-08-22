from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?")
CHINESE_PERCENT_RE = re.compile(r"百分之([零〇一二两三四五六七八九十百千万]+)")
CHINESE_COUNT_RE = re.compile(
    r"([零〇一二两三四五六七八九十百千万]+)"
    r"(?=\s*(?:个|项|名|人|次|家|所|年|月|天|周|倍))"
)
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

PROTECTED_TERMS = {
    "星云科技", "产品实习生", "高级产品经理", "OpenAI API", "Python", "Java",
    "Kubernetes", "某某大学", "清华大学", "信息管理与信息系统", "计算机专业",
    "国家级一等奖", "校级优秀结项", "英语母语水平", "商业智能问答公司",
}


@dataclass(frozen=True)
class FactCheckResult:
    allowed: bool
    violations: tuple[str, ...]


def _canonical_arabic(value: str) -> str:
    suffix = "%" if value.endswith("%") else ""
    number = value.removesuffix("%")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    number = number.lstrip("0") or "0"
    return f"{number}{suffix}"


def _chinese_number(value: str) -> int:
    if not any(character in CHINESE_UNITS for character in value):
        return int("".join(str(CHINESE_DIGITS[character]) for character in value))
    total = 0
    section = 0
    digit = 0
    for character in value:
        if character in CHINESE_DIGITS:
            digit = CHINESE_DIGITS[character]
            continue
        unit = CHINESE_UNITS[character]
        if unit == 10000:
            total += (section + digit) * unit
            section = 0
        else:
            section += (digit or 1) * unit
        digit = 0
    return total + section + digit


def numeric_facts(text: str) -> set[str]:
    facts = {_canonical_arabic(value) for value in NUMBER_RE.findall(text)}
    for value in CHINESE_PERCENT_RE.findall(text):
        facts.add(f"{_chinese_number(value)}%")
    for value in CHINESE_COUNT_RE.findall(text):
        facts.add(str(_chinese_number(value)))
    return facts


def explain_violations(violations: tuple[str, ...] | list[str]) -> str:
    messages = []
    for violation in sorted(set(violations)):
        kind, _, value = violation.partition(":")
        if kind == "unsupported_number":
            messages.append(f"生成内容中的数字“{value}”没有出现在用户资料或当前原文中")
        elif kind == "unsupported_term":
            messages.append(f"生成内容中的事实“{value}”没有出现在用户资料或当前原文中")
        else:
            messages.append(violation)
    return "；".join(messages)


def check_hard_facts(source_texts: list[str], generated: str) -> FactCheckResult:
    source = "\n".join(source_texts)
    violations: list[str] = []
    source_numbers = numeric_facts(source)
    for number in numeric_facts(generated):
        if number not in source_numbers:
            violations.append(f"unsupported_number:{number}")
    for term in PROTECTED_TERMS:
        if term in generated and term not in source:
            violations.append(f"unsupported_term:{term}")
    return FactCheckResult(allowed=not violations, violations=tuple(sorted(set(violations))))

