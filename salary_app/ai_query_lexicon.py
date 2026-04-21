"""
Multilingual substrings for NLU over user questions and AI table headers (RU / UK / EN).

Keeps recognition tokens out of view logic; wording for end-user markdown stays in ai_views.
"""

from __future__ import annotations

from typing import Final, List, Tuple

# --- Month names in free text (abbreviations and Latin) ---
MONTH_ALIASES: Final[Tuple[Tuple[int, Tuple[str, ...]], ...]] = (
    (1, ("янв", "jan")),
    (2, ("фев", "февр", "feb")),
    (3, ("мар", "mар", "берез", "mar")),
    (4, ("апр", "квіт", "apr")),
    (5, ("май", "мая", "мае", "трав", "may", "травень")),
    (6, ("июн", "черв", "jun")),
    (7, ("июл", "лип", "jul")),
    (8, ("авг", "серп", "aug")),
    (9, ("сен", "верес", "sep")),
    (10, ("окт", "жовт", "oct")),
    (11, ("нояб", "листоп", "nov")),
    (12, ("дек", "груд", "dec")),
)

# When a bare month number appears, require nearby context (e.g. "month 5", "5 and 11").
MONTH_NUMERIC_CONTEXT: Final[Tuple[str, ...]] = (
    "меся",
    "month",
    "міся",
    "/",
    "-",
    " и ",
    " vs ",
    "с ",
    "по ",
)

# --- Question intents (substring match on lowered text) ---
Q_MANAGER_HINTS: Final[Tuple[str, ...]] = ("менедж", "manager", "по менедж")
Q_SALES_HINTS: Final[Tuple[str, ...]] = ("продаж", "sales", "выруч", "revenue")
Q_SALES_HINTS_WIDE: Final[Tuple[str, ...]] = (
    "продаж",
    "sales",
    "выруч",
    "revenue",
    "объём",
    "обсяг",
)
Q_WHY: Final[Tuple[str, ...]] = ("почему", "чому", "why", "причин")
Q_DOWNTURN: Final[Tuple[str, ...]] = (
    "просел",
    "просели",
    "упал",
    "упали",
    "сниз",
    "паден",
    "decline",
    "drop",
    "fell",
)
Q_COMPARE_VERBS: Final[Tuple[str, ...]] = ("сравн", "порівня", "compare")

Q_SHOW_VERBS: Final[Tuple[str, ...]] = (
    "покажи",
    "показ",
    "show",
    "відобраз",
    "вивед",
    "display",
)

Q_PREVIOUS_TABLE: Final[Tuple[str, ...]] = (
    "по этим данным",
    "по этим цифрам",
    "по этой таблице",
    "за цими даними",
    "за цими цифрами",
    "за цією таблицею",
    "по этим показателям",
    "за цими показниками",
    "these data",
    "this table",
    "these numbers",
)

Q_EXPENSE_WORDS: Final[Tuple[str, ...]] = ("расход", "витрат", "expense", "expenses")
Q_EXPENSE_FOR_TYPE_RANKING: Final[Tuple[str, ...]] = (
    "расход",
    "витрат",
    "витрати",
    "expense",
    "затрат",
    "витрата",
)

Q_SALARY_TERMS: Final[Tuple[str, ...]] = (
    "зарплат",
    "salary",
    "salaries",
    "выплат",
    "виплат",
    "payout",
)
Q_SALARY_MONTHLY: Final[Tuple[str, ...]] = (
    "месяц",
    "месяцах",
    "по месяц",
    "monthly",
    "month",
)
Q_SALARY_MANAGER: Final[Tuple[str, ...]] = (
    "менедж",
    "manager",
    "у кого",
    "какого",
    "какой",
    "который",
    "which",
    "who",
    "в якого",
    "у якого",
    "який менеджер",
    "хто з менедж",
    "больше",
    "більше",
    "максим",
    "найбільш",
    "найбільша",
    "top",
    "highest",
    "biggest",
)

Q_ONE_MONTH_IMPLIED: Final[Tuple[str, ...]] = (
    "за месяц",
    "за місяць",
    "for the month",
    "for a month",
    "this month",
    "в этом месяце",
    "у цьому місяці",
    "per month",
)

# --- Table header column detection (lowercased header cells) ---
# Lists of tuple variants; all parts of a variant must appear in the header string.

TABLE_HEADER_MONTH: Final[List[Tuple[str, ...]]] = [
    ("меся",),
    ("month",),
    ("міся",),
]
TABLE_HEADER_MONTH_PERIOD: Final[List[Tuple[str, ...]]] = [
    ("month",),
    ("меся",),
    ("міся",),
    ("период",),
    ("період",),
]
TABLE_HEADER_TOTAL: Final[List[Tuple[str, ...]]] = [
    ("общ", "продаж"),
    ("total", "sale"),
    ("всього", "продаж"),
]
TABLE_HEADER_TOTAL_MGR_MONTH: Final[List[Tuple[str, ...]]] = [
    ("total", "sale"),
    ("общ", "продаж"),
    ("всього", "продаж"),
    ("сума", "продаж"),
]
TABLE_HEADER_DEALS: Final[List[Tuple[str, ...]]] = [
    ("колич", "сдел"),
    ("deals",),
    ("кільк", "угод"),
]
TABLE_HEADER_DEALS_MGR_MONTH: Final[List[Tuple[str, ...]]] = [
    ("deals", "count"),
    ("колич", "сдел"),
    ("кільк", "угод"),
    ("угод",),
]
TABLE_HEADER_AVG: Final[List[Tuple[str, ...]]] = [
    ("средн",),
    ("average",),
    ("середн",),
]
TABLE_HEADER_MAX: Final[List[Tuple[str, ...]]] = [
    ("макс",),
    ("max",),
    ("найб",),
]
TABLE_HEADER_MANAGER: Final[List[Tuple[str, ...]]] = [
    ("manager",),
    ("менедж",),
    ("керів",),
]

# Single-row month summary: try RU compound headers before EN.
HDR_MONTH_PRIMARY: Final[str] = "меся"
HDR_MONTH_FALLBACK: Final[str] = "month"
HDR_TOTAL_RU_PAIR: Final[Tuple[str, str]] = ("общ", "продаж")
HDR_DEALS_RU_PAIR: Final[Tuple[str, str]] = ("колич", "сдел")
HDR_AVG_RU_PAIR: Final[Tuple[str, str]] = ("средн", "сумм")
HDR_MAX_RU_PAIR: Final[Tuple[str, str]] = ("макс", "сумм")

HEADER_DEAL_MARKERS: Final[Tuple[str, ...]] = (
    "deal",
    "сдел",
    "угод",
    "record count",
    "кількість запис",
)
HEADER_SALE_MARKERS: Final[Tuple[str, ...]] = (
    "sale",
    "продаж",
    "выр",
    "revenue",
    "сума продаж",
    "sales",
)

MANAGER_HEADER_FRAGMENTS: Final[Tuple[str, ...]] = ("менедж", "manager")
COMPANY_HEADER_FRAGMENTS: Final[Tuple[str, ...]] = ("компан",)

# Salary-vs-sales table heuristic (joined lowercase headers).
SALESISH_HEADER_MARKERS: Final[Tuple[str, ...]] = ("sale", "продаж", "сдел", "deal")
PAYROLL_HEADER_MARKERS: Final[Tuple[str, ...]] = ("выплат", "payout", "зарплат")

# --- Follow-up / insights: deeper analysis vs plain compare ---
Q_INSIGHTS_DEEPER: Final[Tuple[str, ...]] = (
    "рекомендац",
    "рекомендации",
    "рекомендаций",
    "анализ",
    "выводы",
    "советы",
    "дай свои",
    "свои рекомендации",
    "проанализируй",
    "оцени",
    "что можно улучшить",
    "тенденции",
    "вывод",
    "совет",
    "почему",
    "разниц",
    "объясни",
    "объяснить",
    "чому",
    "різниц",
    "поясн",
    "why",
    "difference",
    "explain",
    "проблем",
    "улучш",
    "оціни",
    "ключев",
)

Q_INSIGHTS_KEYWORDS: Final[Tuple[str, ...]] = (
    "рекомендац",
    "рекомендации",
    "рекомендаций",
    "анализ",
    "выводы",
    "советы",
    "дай свои",
    "свои рекомендации",
    "проанализируй",
    "оцени",
    "что можно улучшить",
    "тенденции",
    "вывод",
    "совет",
    "почему",
    "разниц",
    "сравн",
    "объясни",
    "объяснить",
    "чем",
    "выше",
    "ниже",
    "чому",
    "різниц",
    "порівня",
    "поясн",
    "why",
    "difference",
    "compare",
    "explain",
)
