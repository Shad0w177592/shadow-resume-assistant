from __future__ import annotations

import re
from dataclasses import dataclass

NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?")
PROTECTED_TERMS = {
    "星云科技", "产品实习生", "高级产品经理", "OpenAI API", "Python", "Java",
    "Kubernetes", "某某大学", "清华大学", "信息管理与信息系统", "计算机专业",
    "国家级一等奖", "校级优秀结项", "英语母语水平", "商业智能问答公司",
}


@dataclass(frozen=True)
class FactCheckResult:
    allowed: bool
    violations: tuple[str, ...]


def check_hard_facts(source_texts: list[str], generated: str) -> FactCheckResult:
    source = "\n".join(source_texts)
    violations: list[str] = []
    source_numbers = set(NUMBER_RE.findall(source))
    for number in NUMBER_RE.findall(generated):
        if number not in source_numbers:
            violations.append(f"unsupported_number:{number}")
    for term in PROTECTED_TERMS:
        if term in generated and term not in source:
            violations.append(f"unsupported_term:{term}")
    return FactCheckResult(allowed=not violations, violations=tuple(sorted(set(violations))))

