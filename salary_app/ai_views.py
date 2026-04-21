"""Views for working with the AI model GPT-OSS-120B."""
import json
import re
from collections import defaultdict, Counter
from typing import List, Optional, Tuple
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from functools import wraps
from django.db.models import Sum, Count, Avg, Max
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings

from .models import Sale, SalaryPayment, ProductionExpense, CrmUser, Company, Employee, ExpenseType, AIAnalysisHistory
from .llm_service import get_llm_service
from .ai_tools import TOOL_DEFINITIONS, AnalysisToolSession, _cell_str
from .ai_query_lexicon import (
    COMPANY_HEADER_FRAGMENTS,
    HEADER_DEAL_MARKERS,
    HEADER_SALE_MARKERS,
    HDR_AVG_RU_PAIR,
    HDR_DEALS_RU_PAIR,
    HDR_MAX_RU_PAIR,
    HDR_MONTH_FALLBACK,
    HDR_MONTH_PRIMARY,
    HDR_TOTAL_RU_PAIR,
    MANAGER_HEADER_FRAGMENTS,
    MONTH_ALIASES,
    MONTH_NUMERIC_CONTEXT,
    PAYROLL_HEADER_MARKERS,
    Q_COMPARE_VERBS,
    Q_DOWNTURN,
    Q_EXPENSE_FOR_TYPE_RANKING,
    Q_EXPENSE_WORDS,
    Q_INSIGHTS_DEEPER,
    Q_INSIGHTS_KEYWORDS,
    Q_MANAGER_HINTS,
    Q_ONE_MONTH_IMPLIED,
    Q_PREVIOUS_TABLE,
    Q_SALARY_MANAGER,
    Q_SALARY_MONTHLY,
    Q_SALARY_TERMS,
    Q_SALES_HINTS,
    Q_SALES_HINTS_WIDE,
    Q_SHOW_VERBS,
    Q_WHY,
    SALESISH_HEADER_MARKERS,
    TABLE_HEADER_AVG,
    TABLE_HEADER_DEALS,
    TABLE_HEADER_DEALS_MGR_MONTH,
    TABLE_HEADER_MANAGER,
    TABLE_HEADER_MAX,
    TABLE_HEADER_MONTH,
    TABLE_HEADER_MONTH_PERIOD,
    TABLE_HEADER_TOTAL,
    TABLE_HEADER_TOTAL_MGR_MONTH,
)
from .utils import (
    get_current_crm_user,
    get_months,
    get_month_date_range,
    normalize_executor_result_for_table,
    prune_sparse_ai_table_rows,
    fill_compare_placeholders_in_text,
    apply_table_grounded_analysis_for_compare,
    apply_table_grounded_analysis_for_manager_compare,
    question_requires_code_execution,
    apply_dashboard_filters,
    compare_question_suggests_multiple_months,
    table_data_supports_manager_month_compare,
    _is_compare_intent_question,
    _is_manager_breakdown_requested,
)
from django.conf import settings
from django.utils.translation import (
    gettext as _,
    gettext_lazy,
    ngettext,
    override,
    pgettext,
)
import logging

logger = logging.getLogger(__name__)


def _detect_question_lang(question: str) -> str:
    """Lightweight language detection for question text: ru / uk / en."""
    q = (question or "").strip()
    if not q:
        return "ru"
    if re.search(r"[іїєґІЇЄҐ]", q):
        return "uk"
    cyr = len(re.findall(r"[А-Яа-яЁё]", q))
    lat = len(re.findall(r"[A-Za-z]", q))
    return "ru" if cyr > lat else "en"


def _grounded_response_lang(code: str) -> str:
    c = (code or "ru").split("-")[0].lower()
    return c if c in ("ru", "uk", "en") else "ru"


def _chunk_looks_like_llm_error(chunk: str) -> bool:
    """Detect error chunks from the model (any active UI language)."""
    s = (chunk or "").lstrip()
    return any(s.startswith(p) for p in ("Error:", "Ошибка:", "Помилка:"))


def _resolve_response_lang(request, question: str) -> str:
    """Prefer question language, fallback to active Django locale."""
    q_lang = _detect_question_lang(question)
    if q_lang in ("ru", "uk", "en"):
        return q_lang
    req_lang = getattr(request, "LANGUAGE_CODE", None) or "ru"
    req_lang = (req_lang or "ru").split("-")[0].lower()
    return req_lang if req_lang in ("ru", "uk", "en") else "ru"


def _grounded_text_pack(question: str) -> dict:
    """Language-specific phrases for deterministic grounded summaries."""
    lang = _grounded_response_lang(_detect_question_lang(question))
    if lang == "uk":
        return {
            "analysis_h3": "### Аналіз",
            "facts": "Лише факти з таблиці (без вигаданих менеджерів або сум).",
            "facts_short": "Лише факти з таблиці.",
            "total_sales": "загальна сума продажів становить",
            "deals_count": "Кількість угод становить",
            "avg_deal": "Середня сума угоди становить",
            "max_deal": "Максимальна сума угоди становить",
            "deals_are": "кількість угод",
            "avg_is": "середня угода",
            "change_total": "Зміна загальної суми продажів",
            "change_deals": "Зміна кількості угод",
            "total_payout": "Загальна сума виплат",
        }
    if lang == "en":
        return {
            "analysis_h3": "### Analysis",
            "facts": "Only facts from the table (no made-up managers or amounts).",
            "facts_short": "Only facts from the table.",
            "total_sales": "total sales amount is",
            "deals_count": "Number of deals is",
            "avg_deal": "Average deal amount is",
            "max_deal": "Maximum deal amount is",
            "deals_are": "deals are",
            "avg_is": "average deal is",
            "change_total": "Change in total sales amount",
            "change_deals": "Change in number of deals",
            "total_payout": "Total payout amount",
        }
    return {
        "analysis_h3": "### Анализ",
        "facts": "Только факты из таблицы (без выдуманных менеджеров или сумм).",
        "facts_short": "Только факты из таблицы.",
        "total_sales": "общая сумма продаж составляет",
        "deals_count": "Количество сделок составляет",
        "avg_deal": "Средняя сумма сделки составляет",
        "max_deal": "Максимальная сумма сделки составляет",
        "deals_are": "количество сделок",
        "avg_is": "средняя сделка",
        "change_total": "Изменение общей суммы продаж",
        "change_deals": "Изменение количества сделок",
        "total_payout": "Общая сумма выплат",
    }


def _fmt_money_for_lang(value: float, lang: str) -> str:
    if lang == "en":
        return f"{value:,.2f}"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def save_analysis_to_history(manager, question, answer, table_data=None, token_usage=None, conversation_history=None, history_id=None):
    """Save a request and response into the analysis history log."""
    try:
        if not manager:
            logger.warning("Failed to save history entry: manager not found")
            return None
            
        if history_id:
            try:
                entry = AIAnalysisHistory.objects.get(id=history_id, manager=manager)
                # Update with latest data for preview, but keep the original question as the dialog title
                entry.answer = answer[:100000] if answer and len(answer) > 100000 else answer
                entry.table_data = table_data
                if token_usage:
                    entry.token_usage = token_usage
                entry.conversation_history = conversation_history
                entry.save()
                logger.info(f"History entry updated: ID={entry.id}, manager={manager}")  # type: ignore[reportAttributeAccessIssue]
                return entry
            except AIAnalysisHistory.DoesNotExist:
                logger.warning(f"History entry with ID={history_id} not found. Creating a new one.")
                pass
        
        history_entry = AIAnalysisHistory.objects.create(
            manager=manager,
            question=question,
            answer=answer[:100000] if answer and len(answer) > 100000 else answer,  # Limit answer length
            table_data=table_data,
            token_usage=token_usage,
            conversation_history=conversation_history
        )
        logger.info(f"History entry saved: ID={history_entry.id}, manager={manager}")  # type: ignore[reportAttributeAccessIssue]
        return history_entry
    except Exception as e:
        logger.exception(f"Error while saving history entry: {e}")
        return None


def _merge_ai_token_usage(primary: dict, secondary: dict) -> dict:
    """Sum token fields from two LLM responses (e.g. main + repair retry)."""
    a = primary or {}
    b = secondary or {}
    out = dict(a)
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        out[k] = int(a.get(k) or 0) + int(b.get(k) or 0)
    return out


def _repair_missing_code_user_message(lang: str) -> str:
    with override(_grounded_response_lang(lang)):
        return _(
            "Your reply had no ```python``` block setting `result`. "
            "Repeat: FIRST only ```python``` (assign result = list of dicts from "
            "sales_queryset / ORM), "
            "then at most 3 sentences with names and amounts from result. "
            'Do not start with an "Analysis:" paragraph before the code.'
        )



def _repair_empty_table_user_message(lang: str) -> str:
    with override(_grounded_response_lang(lang)):
        return _(
            "Your code ran but `result` stayed empty (0 table rows). "
            "Send again: start with one ```python``` block where result is a non-empty list of dicts from the DB. "
            "Fill result in a loop with result.append(...) or a list comprehension. "
            "Use sales_queryset and closing_date for month/year filters. "
            "Do not truncate before result is filled."
        )


def _repair_code_error_user_message(lang: str, error_text: str) -> str:
    err = (error_text or "").strip()
    with override(_grounded_response_lang(lang)):
        return _(
            "Your code failed with a runtime error. Error: %(error)s. "
            "Send again only one valid ```python``` block with no undefined variables. "
            "Use sales_queryset and build result as a list of dicts."
        ) % {"error": err}


def _maybe_retry_analysis_for_code_error(
    *,
    llm_service,
    data_summary,
    question,
    conversation_history,
    lang,
    accumulated,
    token_usage,
    error_text,
):
    if not question_requires_code_execution(question or ""):
        return accumulated, token_usage
    retry_history = list(conversation_history or [])
    acc = str(accumulated or "")
    preview = acc[:3500] + ("…" if len(acc) > 3500 else "")
    if preview.strip():
        retry_history.append({"role": "assistant", "content": preview})
    retry_history.append({"role": "user", "content": _repair_code_error_user_message(lang, error_text)})
    try:
        llm_res = llm_service.analyze_data(
            data_summary,
            question,
            use_streaming=False,
            conversation_history=retry_history,
            lang=lang,
        )
        if isinstance(llm_res, dict):
            text = llm_res.get("text", "")
            new_usage = llm_res.get("usage", {})
        else:
            text = llm_res
            new_usage = {}
        merged = _merge_ai_token_usage(token_usage, new_usage)
        if text and str(text).strip():
            return str(text).strip(), merged
    except Exception as e:
        logger.exception("Repair retry for code error failed: %s", e)
    return accumulated, token_usage


def _maybe_retry_analysis_for_empty_table(
    *,
    llm_service,
    data_summary,
    question,
    conversation_history,
    lang,
    accumulated,
    token_usage,
):
    if not question_requires_code_execution(question or ""):
        return accumulated, token_usage
    logger.warning("Analysis code returned an empty table; retrying once with repair prompt")
    retry_history = list(conversation_history or [])
    acc = str(accumulated)
    preview = acc[:3500] + ("…" if len(acc) > 3500 else "")
    if preview.strip():
        retry_history.append({"role": "assistant", "content": preview})
    retry_history.append({"role": "user", "content": _repair_empty_table_user_message(lang)})
    try:
        llm_res = llm_service.analyze_data(
            data_summary,
            question,
            use_streaming=False,
            conversation_history=retry_history,
            lang=lang,
        )
        if isinstance(llm_res, dict):
            text = llm_res.get("text", "")
            new_usage = llm_res.get("usage", {})
        else:
            text = llm_res
            new_usage = {}
        merged = _merge_ai_token_usage(token_usage, new_usage)
        if text and str(text).strip():
            return str(text).strip(), merged
    except Exception as e:
        logger.exception("Repair retry for empty table failed: %s", e)
    return accumulated, token_usage


def _is_nonempty_executor_payload(v) -> bool:
    if v is None:
        return False
    if isinstance(v, list) and len(v) == 0:
        return False
    if isinstance(v, dict) and len(v) == 0:
        return False
    return True


def _extract_month_numbers_from_question(question: str):
    q = (question or "").lower()
    found = []
    for month_num, keys in MONTH_ALIASES:
        pos = min((q.find(k) for k in keys if k in q), default=-1)
        if pos >= 0:
            found.append((pos, month_num))

    # Numeric month references: "5 and 11", "05/11", "month 11", etc.
    num_re = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])(?!\d)")
    for m in num_re.finditer(q):
        try:
            month_num = int(m.group(1))
        except (TypeError, ValueError):
            continue
        ctx_start = max(0, m.start() - 12)
        ctx_end = min(len(q), m.end() + 12)
        ctx = q[ctx_start:ctx_end]
        if any(k in ctx for k in MONTH_NUMERIC_CONTEXT):
            found.append((m.start(), month_num))

    found.sort(key=lambda x: x[0])
    ordered = []
    seen = set()
    for _, month_num in found:
        if month_num not in seen:
            seen.add(month_num)
            ordered.append(month_num)
    # Inclusive month range when Cyrillic/Latin range markers match (see regexes below).
    if (
        len(ordered) >= 2
        and (
            re.search(r"\bс\b.+\bпо\b", q)
            or re.search(r"\bfrom\b.+\bto\b", q)
            or re.search(r"\bвід\b.+\bдо\b", q)
        )
    ):
        start_m = ordered[0]
        end_m = ordered[-1]
        if start_m <= end_m:
            return list(range(start_m, end_m + 1))
        # Cross-year phrasing (e.g. "from November to February")
        return list(range(start_m, 13)) + list(range(1, end_m + 1))
    return ordered


def _extract_year_numbers_from_question(question: str):
    q = str(question or "")
    years = []
    for m in re.finditer(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", q):
        try:
            y = int(m.group(1))
        except (TypeError, ValueError):
            continue
        if 1900 <= y <= 2100 and y not in years:
            years.append(y)
    return years


def _is_single_month_total_question(question: str) -> bool:
    q = (question or "").lower()
    months = _extract_month_numbers_from_question(question)
    if len(months) != 1:
        return False
    if _is_compare_intent_question(question):
        return False
    if any(k in q for k in Q_MANAGER_HINTS):
        return False
    return any(k in q for k in Q_SALES_HINTS)


def _build_single_month_grounded_text(table_data: dict, question: str) -> str:
    if not table_data or not isinstance(table_data, dict):
        return ""
    if not _is_single_month_total_question(question):
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]
    rows = table_data.get("rows") or []
    if len(rows) != 1:
        return ""

    def idx_contains(*keys):
        for i, h in enumerate(headers):
            if all(k in h for k in keys):
                return i
        return None

    month_i = (
        idx_contains(HDR_MONTH_PRIMARY)
        if idx_contains(HDR_MONTH_PRIMARY) is not None
        else idx_contains(HDR_MONTH_FALLBACK)
    )
    total_i = (
        idx_contains(*HDR_TOTAL_RU_PAIR)
        if idx_contains(*HDR_TOTAL_RU_PAIR) is not None
        else idx_contains("total", "sale")
    )
    deals_i = (
        idx_contains(*HDR_DEALS_RU_PAIR)
        if idx_contains(*HDR_DEALS_RU_PAIR) is not None
        else idx_contains("deal")
    )
    avg_i = (
        idx_contains(*HDR_AVG_RU_PAIR)
        if idx_contains(*HDR_AVG_RU_PAIR) is not None
        else idx_contains("average")
    )
    max_i = (
        idx_contains(*HDR_MAX_RU_PAIR)
        if idx_contains(*HDR_MAX_RU_PAIR) is not None
        else idx_contains("max")
    )

    row = rows[0]
    if total_i is None or deals_i is None:
        return ""

    def cell(i):
        if i is None or i >= len(row):
            return ""
        return str(row[i])

    month_label = cell(month_i) or "Period"
    total = cell(total_i)
    deals = cell(deals_i)
    avg = cell(avg_i)
    maxv = cell(max_i)

    tr = _grounded_text_pack(question)
    return (
        f"{tr['analysis_h3']}\n\n"
        f"{tr['facts']}\n"
        f"- **{month_label}**: {tr['total_sales']} **{total}**.\n"
        f"- {tr['deals_count']} **{deals}**.\n"
        f"- {tr['avg_deal']} **{avg}**.\n"
        f"- {tr['max_deal']} **{maxv}**.\n"
    )


def _to_float_safe(v) -> float:
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return 0.0


def _safe_table_row_count(table_data) -> int:
    """Return len(rows) for normalized AI table_data; malformed rows are ignored."""
    if not isinstance(table_data, dict):
        return 0
    rows = table_data.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _pct_change(from_v: float, to_v: float) -> str:
    if abs(from_v) < 1e-9:
        return "N/A"
    return f"{((to_v - from_v) / from_v) * 100.0:.2f}%"


def _is_compare_why_question(question: str) -> bool:
    q = (question or "").lower()
    return _is_compare_intent_question(question) and any(k in q for k in Q_WHY)


def _is_downturn_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in Q_DOWNTURN)


def _build_two_month_compare_grounded_text(table_data: dict, question: str) -> str:
    if not table_data or not isinstance(table_data, dict):
        return ""
    if not _is_compare_intent_question(question):
        return ""
    if _is_manager_breakdown_requested(question):
        return ""
    rows = table_data.get("rows") or []
    if len(rows) != 2:
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]

    def idx_any(parts_list):
        for i, h in enumerate(headers):
            for parts in parts_list:
                if all(p in h for p in parts):
                    return i
        return None

    month_i = idx_any(TABLE_HEADER_MONTH)
    total_i = idx_any(TABLE_HEADER_TOTAL)
    deals_i = idx_any(TABLE_HEADER_DEALS)
    avg_i = idx_any(TABLE_HEADER_AVG)

    if month_i is None or total_i is None or deals_i is None:
        return ""

    def c(row, i):
        return str(row[i]) if i is not None and i < len(row) else ""

    r0, r1 = rows[0], rows[1]
    m0, m1 = c(r0, month_i), c(r1, month_i)
    t0, t1 = c(r0, total_i), c(r1, total_i)
    d0, d1 = c(r0, deals_i), c(r1, deals_i)
    a0, a1 = c(r0, avg_i), c(r1, avg_i)
    ft0, ft1 = _to_float_safe(t0), _to_float_safe(t1)
    fd0, fd1 = _to_float_safe(d0), _to_float_safe(d1)
    pct_total = _pct_change(ft0, ft1)
    pct_deals = _pct_change(fd0, fd1)

    tr = _grounded_text_pack(question)
    text = (
        f"{tr['analysis_h3']}\n\n"
        f"{tr['facts_short']}\n"
        f"- **{m0}**: {tr['total_sales']} **{t0}**, {tr['deals_are']} **{d0}**"
    )
    if a0:
        text += f", {tr['avg_is']} **{a0}**"
    text += ".\n"
    text += f"- **{m1}**: {tr['total_sales']} **{t1}**, {tr['deals_are']} **{d1}**"
    if a1:
        text += f", {tr['avg_is']} **{a1}**"
    text += ".\n"
    text += (
        f"- {tr['change_total']} ({m1} vs {m0}) — **{pct_total}**.\n"
        f"- {tr['change_deals']} ({m1} vs {m0}) — **{pct_deals}**.\n"
    )
    return text


def _is_sales_related_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in Q_SALES_HINTS_WIDE)


def _build_multi_month_sales_compare_grounded_text(table_data: dict, question: str) -> str:
    """
    Grounded "### Analysis" block for compare + sales + month summary tables with 3+ rows (no managers).
    Fills the gap where compare_only skips the second LLM and two-row handlers do not apply.
    """
    if not table_data or not isinstance(table_data, dict):
        return ""
    if not _is_compare_intent_question(question):
        return ""
    if _is_manager_breakdown_requested(question):
        return ""
    if not _is_sales_related_question(question):
        return ""
    rows = table_data.get("rows") or []
    if len(rows) < 3:
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]

    def idx_any(parts_list):
        for i, h in enumerate(headers):
            for parts in parts_list:
                if all(p in h for p in parts):
                    return i
        return None

    month_i = idx_any(TABLE_HEADER_MONTH)
    total_i = idx_any(TABLE_HEADER_TOTAL)
    deals_i = idx_any(TABLE_HEADER_DEALS)
    avg_i = idx_any(TABLE_HEADER_AVG)
    max_i = idx_any(TABLE_HEADER_MAX)
    if month_i is None or total_i is None or deals_i is None:
        return ""

    def c(row, i):
        return str(row[i]) if i is not None and i < len(row) else ""

    q_lang = _grounded_response_lang(_detect_question_lang(question))
    first_lbl = c(rows[0], month_i)
    last_lbl = c(rows[-1], month_i)
    totals_f = [_to_float_safe(c(r, total_i)) for r in rows]
    deals_f = [_to_float_safe(c(r, deals_i)) for r in rows]
    pct_total = _pct_change(totals_f[0], totals_f[-1])
    pct_deals = _pct_change(deals_f[0], deals_f[-1])
    best_idx = max(range(len(totals_f)), key=lambda i: totals_f[i])
    worst_idx = min(range(len(totals_f)), key=lambda i: totals_f[i])
    nmonths = len(rows)
    with override(q_lang):
        months_label = ngettext(
            "%(num)d month", "%(num)d months", nmonths
        ) % {"num": nmonths}
        lines = [
            pgettext("ai_grounded", "### Analysis"),
            "",
            _("Only facts from the monthly table."),
            _(
                "- Table period: **%(first)s** through **%(last)s** (%(months)s)."
            )
            % {"first": first_lbl, "last": last_lbl, "months": months_label},
        ]
        for r in rows:
            ml = c(r, month_i)
            part = _(
                "- **%(month)s**: total sales **%(total)s**, deals **%(deals)s**"
            ) % {
                "month": ml,
                "total": c(r, total_i),
                "deals": c(r, deals_i),
            }
            if avg_i is not None and c(r, avg_i):
                part += _(", average deal **%(avg)s**") % {"avg": c(r, avg_i)}
            if max_i is not None and c(r, max_i):
                part += _(", largest deal **%(mx)s**") % {"mx": c(r, max_i)}
            lines.append(part + ".")
        lines.append(
            _(
                "- Total sales change (**%(last)s** vs **%(first)s**): **%(pct)s**."
            )
            % {"last": last_lbl, "first": first_lbl, "pct": pct_total}
        )
        lines.append(
            _(
                "- Deals count change (**%(last)s** vs **%(first)s**): **%(pct)s**."
            )
            % {"last": last_lbl, "first": first_lbl, "pct": pct_deals}
        )
        lines.append(
            _(
                "- Highest monthly sales in the table: **%(month)s** — **%(total)s**."
            )
            % {
                "month": c(rows[best_idx], month_i),
                "total": c(rows[best_idx], total_i),
            }
        )
        lines.append(
            _(
                "- Lowest monthly sales in the table: **%(month)s** — **%(total)s**."
            )
            % {
                "month": c(rows[worst_idx], month_i),
                "total": c(rows[worst_idx], total_i),
            }
        )
    return "\n".join(lines) + "\n"


def _build_month_summary_grounded_text(table_data: dict, lang: str) -> str:
    if not isinstance(table_data, dict):
        return ""
    rows = table_data.get("rows") or []
    if len(rows) not in (1, 2):
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]

    def idx_any(parts_list):
        for i, h in enumerate(headers):
            for parts in parts_list:
                if all(p in h for p in parts):
                    return i
        return None

    month_i = idx_any(TABLE_HEADER_MONTH)
    total_i = idx_any(TABLE_HEADER_TOTAL)
    deals_i = idx_any(TABLE_HEADER_DEALS)
    avg_i = idx_any(TABLE_HEADER_AVG)
    max_i = idx_any(TABLE_HEADER_MAX)
    if month_i is None or total_i is None or deals_i is None:
        return ""

    def c(row, i):
        return str(row[i]) if i is not None and i < len(row) else ""

    lang = _grounded_response_lang(lang)
    with override(lang):
        lines = [
            pgettext("ai_grounded", "### Analysis"),
            "",
            pgettext("ai_grounded", "Only facts from the table."),
        ]
        for row in rows:
            m = c(row, month_i) or _("Period")
            t = c(row, total_i)
            d = c(row, deals_i)
            line = _(
                "- **%(month)s**: total sales amount is **%(total)s**, deals are **%(deals)s**"
            ) % {"month": m, "total": t, "deals": d}
            a = c(row, avg_i)
            if a:
                line += _(", average deal is **%(avg)s**") % {"avg": a}
            mx = c(row, max_i)
            if mx:
                line += _(", maximum deal is **%(mx)s**") % {"mx": mx}
            line += "."
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def _build_expense_type_ranking_grounded_text(
    table_data: dict, question: str, lang: str
) -> str:
    """
    Localized bullet summary for CRM expense-type tables (expense type + total_amount, multiple rows).
    Replaces English-only model prose while tool headers stay in English (EXPENSE TYPE …).
    """
    if not isinstance(table_data, dict):
        return ""
    rows = table_data.get("rows") or []
    headers_raw = table_data.get("headers") or []
    if len(rows) < 1 or len(headers_raw) < 2:
        return ""

    headers = [str(h or "").strip().lower() for h in headers_raw]
    exp_i = None
    tot_i = None
    for i, h in enumerate(headers):
        if exp_i is None:
            if "expense_type" in h or ("expense" in h and "type" in h):
                exp_i = i
            elif "вид" in h and ("расход" in h or "витрат" in h or "витрати" in h):
                exp_i = i
            elif "тип" in h and ("расход" in h or "витрат" in h):
                exp_i = i
        if tot_i is None:
            if ("total" in h and "amount" in h) or ("общ" in h and "сумм" in h):
                tot_i = i
            elif "всього" in h and "сума" in h:
                tot_i = i
            elif "загальн" in h and "сума" in h:
                tot_i = i
    if exp_i is None or tot_i is None or exp_i == tot_i:
        return ""
    if any(any(m in h for m in MANAGER_HEADER_FRAGMENTS) for h in headers):
        return ""
    if any(
        any(c in h for c in COMPANY_HEADER_FRAGMENTS) or h.strip() == "company"
        for h in headers
    ):
        return ""

    qlow = (question or "").lower()
    if not any(w in qlow for w in Q_EXPENSE_FOR_TYPE_RANKING):
        return ""

    parsed: List[Tuple[str, float]] = []
    for r in rows[:250]:
        if not isinstance(r, (list, tuple)) or len(r) <= max(exp_i, tot_i):
            continue
        name = str(r[exp_i]).strip()
        val = _to_float_safe(r[tot_i])
        if name:
            parsed.append((name, val))
    if len(parsed) < 1:
        return ""

    parsed.sort(key=lambda x: x[1], reverse=True)
    winner = parsed[0]
    lang_n = _grounded_response_lang(lang)
    top_n = min(len(parsed), 6)
    with override(lang_n):
        amt0 = f"{winner[1]:.2f}"
        lines = [
            pgettext("ai_grounded", "### Analysis"),
            "",
            pgettext("ai_grounded", "Only facts from the table."),
            _(
                "- Largest expense type: **%(name)s** — **%(amount)s**."
            )
            % {"name": winner[0], "amount": amt0},
        ]
        for name, val in parsed[1:top_n]:
            lines.append(
                _("- **%(name)s**: **%(amount)s**.") % {
                    "name": name,
                    "amount": f"{val:.2f}",
                }
            )
        lines.append("")
    return "\n".join(lines)


def _build_one_row_table_grounded_text(table_data: dict, question: str) -> str:
    if not isinstance(table_data, dict):
        return ""
    # Keep specialized handlers first; this is a generic fallback.
    if _is_single_month_total_question(question) or _is_compare_intent_question(question):
        return ""
    rows = table_data.get("rows") or []
    headers = table_data.get("headers") or []
    if len(rows) != 1 or len(headers) < 2:
        return ""
    row = rows[0]
    if not isinstance(row, (list, tuple)):
        return ""
    cells = []
    for i, h in enumerate(headers[:8]):
        if i >= len(row):
            continue
        hv = str(h or "").strip()
        cv = str(row[i]).strip()
        if not hv or not cv:
            continue
        cells.append((hv, cv))
    if not cells:
        return ""
    tr = _grounded_text_pack(question)
    lines = [tr["analysis_h3"], "", tr["facts_short"]]
    # Prefer first label as period/category and the rest as metrics.
    first_h, first_v = cells[0]
    if len(cells) == 2:
        second_h, second_v = cells[1]
        lines.append(f"- **{first_h} {first_v}**: **{second_h} = {second_v}**.")
    else:
        lines.append(f"- **{first_h}**: **{first_v}**.")
        for h, v in cells[1:]:
            lines.append(f"- **{h}**: **{v}**.")
    lines.append("")
    return "\n".join(lines)


def _company_breakdown_for_sales_compare(question: str, executor) -> list:
    """
    Top companies by revenue per month on the filtered sales queryset (same slice as table).
    Returns list of dicts: {"month_label", "items": [{"title", "sales", "deals"}, ...]}.
    """
    qsets = getattr(executor, "querysets", None) or {}
    sales_qs = qsets.get("sales_queryset")
    if sales_qs is None:
        return []
    months_use = _extract_month_numbers_from_question(question)
    months_use = sorted({m for m in months_use if isinstance(m, int) and 1 <= m <= 12})
    if len(months_use) < 2:
        return []
    years = _extract_year_numbers_from_question(question)
    year_f = years[0] if years else None
    month_names = get_months()
    out = []
    for m in months_use:
        qs = sales_qs.filter(closing_date__isnull=False, closing_date__month=m)
        if year_f is not None:
            qs = qs.filter(closing_date__year=year_f)
        rows_agg = (
            qs.values("company__title")
            .annotate(total_sale=Sum("sale"), deal_cnt=Count("id"))
            .order_by("-total_sale")[:5]
        )
        items = []
        for r in rows_agg:
            title = (r.get("company__title") or "").strip() or "—"
            items.append(
                {
                    "title": title,
                    "sales": float(r.get("total_sale") or 0),
                    "deals": int(r.get("deal_cnt") or 0),
                }
            )
        if items:
            out.append(
                {
                    "month_label": str(month_names.get(m, m)),
                    "items": items,
                }
            )
    return out


def _build_manager_compare_grounded_text(
    table_data: dict, question: str, executor=None, lang: str = "ru"
) -> str:
    if not isinstance(table_data, dict):
        return ""
    if not (_is_compare_intent_question(question) and _is_manager_breakdown_requested(question)):
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]
    rows = table_data.get("rows") or []
    if not rows:
        return ""
    if len(headers) < 5:
        return ""

    # Expected compare schema:
    # [manager, sales_m0, deals_m0, sales_m1, deals_m1]
    # Do not force this on single-period tables like:
    # [manager, total amount, record count, avg amount, max amount].
    manager_i = 0
    sales_like = []
    deals_like = []
    for i, h in enumerate(headers):
        if i == manager_i:
            continue
        hs = str(h or "").strip().lower()
        if any(k in hs for k in HEADER_DEAL_MARKERS):
            deals_like.append(i)
            continue
        if any(k in hs for k in HEADER_SALE_MARKERS):
            sales_like.append(i)
            continue

    if len(sales_like) < 2 or len(deals_like) < 2:
        return ""

    s_idxs = sorted(sales_like)
    d_idxs = sorted(deals_like)

    def f(v):
        return _to_float_safe(v)

    # Multi-month manager pivot: build per-month metrics from ALL sales/deals columns.
    if len(s_idxs) >= 3 and len(d_idxs) >= 3:
        ql = _grounded_response_lang(lang)
        month_labels = [str(headers[i]).strip() for i in s_idxs]
        totals = [sum(f(r[i]) for r in rows if len(r) > i) for i in s_idxs]
        deals_totals = [int(sum(f(r[i]) for r in rows if len(r) > i)) for i in d_idxs]
        top_names = []
        top_vals = []
        for si in s_idxs:
            top_row = max(rows, key=lambda r: f(r[si]) if len(r) > si else -1)
            top_names.append(str(top_row[manager_i]) if len(top_row) > manager_i else "N/A")
            top_vals.append(f(top_row[si]) if len(top_row) > si else 0.0)

        first_lbl, last_lbl = month_labels[0], month_labels[-1]
        first_total, last_total = totals[0], totals[-1]
        first_deals, last_deals = deals_totals[0], deals_totals[-1]
        pct_total = _pct_change(first_total, last_total)
        pct_deals = _pct_change(float(first_deals), float(last_deals))

        best_month_idx = max(range(len(totals)), key=lambda i: totals[i])
        worst_month_idx = min(range(len(totals)), key=lambda i: totals[i])
        peak_v = totals[best_month_idx]
        trough_v = totals[worst_month_idx]
        peak_to_trough_pct = _pct_change(peak_v, trough_v) if peak_v else "0%"

        mom_sales = [_pct_change(totals[i], totals[i + 1]) for i in range(len(totals) - 1)]
        mom_deals = [
            _pct_change(float(deals_totals[i]), float(deals_totals[i + 1]))
            for i in range(len(deals_totals) - 1)
        ]
        avg_sales = sum(totals) / len(totals) if totals else 0.0
        avg_deals_f = sum(deals_totals) / len(deals_totals) if deals_totals else 0.0
        vol_rows = []
        for r in rows:
            vals = [f(r[si]) if len(r) > si else 0.0 for si in s_idxs]
            spread = (max(vals) - min(vals)) if vals else 0.0
            nm = str(r[manager_i]) if len(r) > manager_i else "—"
            vol_rows.append((nm, spread))
        vol_rows.sort(key=lambda x: -x[1])
        top_vol = [(nm, sp) for nm, sp in vol_rows[:3] if sp > 0]
        lead_counts = Counter(top_names)
        repeat_leaders = sorted(
            [(n, k) for n, k in lead_counts.items() if k >= 2], key=lambda x: -x[1]
        )
        company_blocks = _company_breakdown_for_sales_compare(question, executor)

        def _mom_chain(labels: List[str], pcts: List[str], arrow: str) -> str:
            return "; ".join(
                f"{labels[i]}{arrow}{labels[i + 1]}: **{pcts[i]}**"
                for i in range(len(pcts))
            )

        nmonths = len(month_labels)
        with override(ql):
            months_label = ngettext("%(num)d month", "%(num)d months", nmonths) % {
                "num": nmonths
            }
            lines: List[str] = [
                pgettext("ai_grounded", "### Analysis"),
                "",
                _(
                    "Only facts from the manager table and company slice "
                    "(same CRM filters as the table)."
                ),
                _(
                    "- Table period: from **%(first)s** to **%(last)s** (%(months)s)."
                )
                % {
                    "first": first_lbl,
                    "last": last_lbl,
                    "months": months_label,
                },
            ]
            for i in range(len(month_labels)):
                lines.append(
                    _(
                        "- **%(month)s**: sales — **%(sales)s**, deals — **%(deals)s**; "
                        "top manager — **%(top_name)s** (**%(top_val)s**)."
                    )
                    % {
                        "month": month_labels[i],
                        "sales": f"{totals[i]:.2f}",
                        "deals": str(deals_totals[i]),
                        "top_name": top_names[i],
                        "top_val": f"{top_vals[i]:.2f}",
                    }
                )
            lines.append(
                _("- **Month-over-month (total sales, all managers):** %(chain)s.")
                % {"chain": _mom_chain(month_labels, mom_sales, " → ")}
            )
            lines.append(
                _("- **Month-over-month (deal counts):** %(chain)s.")
                % {"chain": _mom_chain(month_labels, mom_deals, " → ")}
            )
            lines.append(
                _(
                    "- **Peak vs trough (all managers):** highest — **%(best_m)s** (**%(peak)s**), "
                    "lowest — **%(worst_m)s** (**%(trough)s**); "
                    "gap **%(gap)s** (**%(gap_pct)s** from peak to lowest month)."
                )
                % {
                    "best_m": month_labels[best_month_idx],
                    "peak": f"{peak_v:.2f}",
                    "worst_m": month_labels[worst_month_idx],
                    "trough": f"{trough_v:.2f}",
                    "gap": f"{peak_v - trough_v:.2f}",
                    "gap_pct": peak_to_trough_pct,
                }
            )
            lines.append(
                _("- **Per-month averages:** sales **%(avg_sales)s**, deals **%(avg_deals)s**.")
                % {"avg_sales": f"{avg_sales:.2f}", "avg_deals": f"{avg_deals_f:.1f}"}
            )
            if top_vol:
                vol_detail = "; ".join(
                    f"**{nm}** — **{sp:.2f}**" for nm, sp in top_vol
                )
                lines.append(
                    _(
                        "- **Largest month-to-month spread (max−min per manager row):** "
                        "%(details)s."
                    )
                    % {"details": vol_detail}
                )
            if repeat_leaders:
                rdet = "; ".join(f"**{n}** — {k}×" for n, k in repeat_leaders)
                lines.append(
                    _(
                        "- **Times each manager was #1 by sales in a month:** %(details)s."
                    )
                    % {"details": rdet}
                )
            lines.append(
                _(
                    "- **Interval endpoints only (%(first)s vs %(last)s), not the full trend:** "
                    "sales **%(pct_tot)s**, deals **%(pct_deal)s**."
                )
                % {
                    "first": first_lbl,
                    "last": last_lbl,
                    "pct_tot": pct_total,
                    "pct_deal": pct_deals,
                }
            )
            if company_blocks:
                lines.append(
                    _("- **Top companies by revenue per month (up to 5, from CRM):**")
                )
                for blk in company_blocks:
                    parts = ", ".join(
                        _("**%(title)s** — %(sales)s (%(deals)d deals)")
                        % {
                            "title": it["title"],
                            "sales": f"{it['sales']:.2f}",
                            "deals": it["deals"],
                        }
                        for it in blk["items"]
                    )
                    lines.append(
                        _("  - **%(month_label)s:** %(parts)s.")
                        % {"month_label": blk["month_label"], "parts": parts}
                    )
        return "\n".join(lines) + "\n"
    s0_i, s1_i = s_idxs[0], s_idxs[1]
    d0_i, d1_i = d_idxs[0], d_idxs[1]

    total0 = sum(f(r[s0_i]) for r in rows if len(r) > s0_i)
    total1 = sum(f(r[s1_i]) for r in rows if len(r) > s1_i)
    deals0 = int(sum(f(r[d0_i]) for r in rows if len(r) > d0_i))
    deals1 = int(sum(f(r[d1_i]) for r in rows if len(r) > d1_i))

    top0 = max(rows, key=lambda r: f(r[s0_i]) if len(r) > s0_i else -1)
    top1 = max(rows, key=lambda r: f(r[s1_i]) if len(r) > s1_i else -1)
    top0_name = str(top0[manager_i]) if len(top0) > manager_i else "N/A"
    top1_name = str(top1[manager_i]) if len(top1) > manager_i else "N/A"
    top0_val = f(top0[s0_i]) if len(top0) > s0_i else 0.0
    top1_val = f(top1[s1_i]) if len(top1) > s1_i else 0.0
    pct_total = _pct_change(total0, total1)
    pct_deals = _pct_change(float(deals0), float(deals1))

    months = _extract_month_numbers_from_question(question)
    years = _extract_year_numbers_from_question(question)
    year_label = str(years[0]) if years else ""
    month_names = get_months()

    ql = _grounded_response_lang(lang)
    if len(months) >= 2:
        m0 = str(month_names.get(months[0], months[0]))
        m1 = str(month_names.get(months[1], months[1]))
    else:
        h0 = str(headers[s0_i]).strip()
        h1 = str(headers[s1_i]).strip()
        with override(ql):
            m0 = h0 or _("Period 1")
            m1 = h1 or _("Period 2")
    if year_label:
        m0 = f"{m0} {year_label}"
        m1 = f"{m1} {year_label}"

    with override(ql):
        lines = [
            pgettext("ai_grounded", "### Analysis"),
            "",
            _("Only facts from the manager table."),
            _(
                "- Total sales: **%(m0)s** — **%(t0)s**, **%(m1)s** — **%(t1)s**."
            )
            % {
                "m0": m0,
                "t0": f"{total0:.2f}",
                "m1": m1,
                "t1": f"{total1:.2f}",
            },
            _(
                "- Deals: **%(m0)s** — **%(d0)s**, **%(m1)s** — **%(d1)s**."
            )
            % {"m0": m0, "d0": str(deals0), "m1": m1, "d1": str(deals1)},
            _(
                "- Sales amount change (%(m1)s vs %(m0)s): **%(pct)s**."
            )
            % {"m0": m0, "m1": m1, "pct": pct_total},
            _(
                "- Deals count change (%(m1)s vs %(m0)s): **%(pct)s**."
            )
            % {"m0": m0, "m1": m1, "pct": pct_deals},
            _(
                "- Top performer in **%(m)s**: **%(name)s** (**%(val)s**)."
            )
            % {"m": m0, "name": top0_name, "val": f"{top0_val:.2f}"},
            _(
                "- Top performer in **%(m)s**: **%(name)s** (**%(val)s**)."
            )
            % {"m": m1, "name": top1_name, "val": f"{top1_val:.2f}"},
        ]
    return "\n".join(lines) + "\n"


def _build_manager_month_list_grounded_text(table_data: dict, question: str, lang: str) -> str:
    """
    Grounded summary for manager-by-month table:
    [Month, Manager, Total sales, Deals count].
    """
    if not isinstance(table_data, dict):
        return ""
    q = (question or "").lower()
    if not any(k in q for k in Q_SHOW_VERBS):
        return ""

    headers_src = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if not headers_src or not rows:
        return ""
    headers = [str(h or "").strip().lower() for h in headers_src]

    def idx_any(parts_list):
        for i, h in enumerate(headers):
            for parts in parts_list:
                if all(p in h for p in parts):
                    return i
        return None

    month_i = idx_any(TABLE_HEADER_MONTH_PERIOD)
    manager_i = idx_any(TABLE_HEADER_MANAGER)
    total_i = idx_any(TABLE_HEADER_TOTAL_MGR_MONTH)
    deals_i = idx_any(TABLE_HEADER_DEALS_MGR_MONTH)
    if None in (month_i, manager_i, total_i, deals_i):
        return ""
    assert month_i is not None
    assert manager_i is not None
    assert total_i is not None
    assert deals_i is not None
    month_idx = int(month_i)
    manager_idx = int(manager_i)
    total_idx = int(total_i)
    deals_idx = int(deals_i)

    monthly = {}
    order = []
    for r in rows:
        if not isinstance(r, (list, tuple)):
            continue
        if len(r) <= max(month_idx, manager_idx, total_idx, deals_idx):
            continue
        m = str(r[month_idx]).strip()
        mgr = str(r[manager_idx]).strip()
        total = _to_float_safe(r[total_idx])
        deals = int(round(_to_float_safe(r[deals_idx])))
        if not m:
            continue
        if m not in monthly:
            monthly[m] = {"total": 0.0, "deals": 0, "leader_name": "", "leader_total": -1.0}
            order.append(m)
        monthly[m]["total"] += total
        monthly[m]["deals"] += deals
        if total > monthly[m]["leader_total"]:
            monthly[m]["leader_total"] = total
            monthly[m]["leader_name"] = mgr or "—"

    if len(order) < 1:
        return ""

    ql = _grounded_response_lang(lang)
    with override(ql):
        lines = [
            pgettext("ai_grounded", "### Analysis"),
            "",
            pgettext("ai_grounded", "Only facts from the table."),
        ]
        for m in order[:6]:
            item = monthly[m]
            total_s = _fmt_money_for_lang(float(item["total"]), ql)
            leader_total_s = _fmt_money_for_lang(float(item["leader_total"]), ql)
            lines.append(
                _(
                    "- **%(month)s**: total sales amount is **%(total)s**, deals are **%(deals)s**; "
                    "top manager by sales is **%(leader)s** (**%(leader_total)s**)."
                )
                % {
                    "month": m,
                    "total": total_s,
                    "deals": str(item["deals"]),
                    "leader": item["leader_name"],
                    "leader_total": leader_total_s,
                }
            )
        if len(order) == 2:
            a, b = order[0], order[1]
            delta = monthly[b]["total"] - monthly[a]["total"]
            delta_s = _fmt_money_for_lang(float(delta), ql)
            lines.append(
                _(
                    "- Total sales difference (**%(b)s** vs **%(a)s**) is **%(delta)s**."
                )
                % {"a": a, "b": b, "delta": delta_s}
            )
        lines.append("")
    return "\n".join(lines)


def _build_compare_why_grounded_text_from_db(question: str, executor) -> str:
    if not _is_compare_why_question(question):
        return ""
    months = _extract_month_numbers_from_question(question)
    if len(months) < 2:
        return ""
    years = _extract_year_numbers_from_question(question)
    year_for_filter = years[0] if years else None
    querysets = getattr(executor, "querysets", None) or {}
    sales_qs = querysets.get("sales_queryset")
    if sales_qs is None:
        return ""
    m0, m1 = months[0], months[1]
    month_names = get_months()

    def month_qs(m):
        q = sales_qs.filter(closing_date__isnull=False, closing_date__month=m)
        if year_for_filter is not None:
            q = q.filter(closing_date__year=year_for_filter)
        return q

    qs0 = month_qs(m0)
    qs1 = month_qs(m1)
    t0 = float(qs0.aggregate(v=Sum("sale")).get("v") or 0)
    t1 = float(qs1.aggregate(v=Sum("sale")).get("v") or 0)
    c0 = int(qs0.aggregate(v=Count("id")).get("v") or 0)
    c1 = int(qs1.aggregate(v=Count("id")).get("v") or 0)

    mgr0 = {
        (str(r.get("manager__last_name") or "").strip(), str(r.get("manager__name") or "").strip()): (
            float(r.get("total") or 0),
            int(r.get("cnt") or 0),
        )
        for r in qs0.values("manager__last_name", "manager__name").annotate(total=Sum("sale"), cnt=Count("id"))
    }
    mgr1 = {
        (str(r.get("manager__last_name") or "").strip(), str(r.get("manager__name") or "").strip()): (
            float(r.get("total") or 0),
            int(r.get("cnt") or 0),
        )
        for r in qs1.values("manager__last_name", "manager__name").annotate(total=Sum("sale"), cnt=Count("id"))
    }
    cmp0 = {
        str(r.get("company__title") or "").strip(): (float(r.get("total") or 0), int(r.get("cnt") or 0))
        for r in qs0.values("company__title").annotate(total=Sum("sale"), cnt=Count("id"))
    }
    cmp1 = {
        str(r.get("company__title") or "").strip(): (float(r.get("total") or 0), int(r.get("cnt") or 0))
        for r in qs1.values("company__title").annotate(total=Sum("sale"), cnt=Count("id"))
    }

    def top_drops(left: dict, right: dict, top_n=3):
        names = set(left.keys()) | set(right.keys())
        rows = []
        for n in names:
            s0, c0n = left.get(n, (0.0, 0))
            s1, c1n = right.get(n, (0.0, 0))
            rows.append((n, s1 - s0, c1n - c0n, s0, s1, c0n, c1n))
        rows.sort(key=lambda x: x[1])  # biggest negative first
        return rows[:top_n]

    # Normalize comparison direction for "decline" questions: stronger month -> weaker month.
    base_m, base_t, base_c, base_mgr, base_cmp = m0, t0, c0, mgr0, cmp0
    target_m, target_t, target_c, target_mgr, target_cmp = m1, t1, c1, mgr1, cmp1
    if _is_downturn_question(question) and t0 < t1:
        base_m, base_t, base_c, base_mgr, base_cmp = m1, t1, c1, mgr1, cmp1
        target_m, target_t, target_c, target_mgr, target_cmp = m0, t0, c0, mgr0, cmp0

    top_mgr = top_drops(base_mgr, target_mgr, top_n=3)
    top_cmp = top_drops(base_cmp, target_cmp, top_n=3)

    base_label = f"{month_names.get(base_m, base_m)} {year_for_filter}" if year_for_filter else str(month_names.get(base_m, base_m))
    target_label = f"{month_names.get(target_m, target_m)} {year_for_filter}" if year_for_filter else str(month_names.get(target_m, target_m))
    lines = [
        "### Reason Analysis",
        "",
        "Only facts from the DB (via table and aggregates):",
        f"- Total amount: **{base_label} = {base_t:.2f}**, **{target_label} = {target_t:.2f}** (change **{_pct_change(base_t, target_t)}**).",
        f"- Number of deals: **{base_label} = {base_c}**, **{target_label} = {target_c}** (change **{_pct_change(float(base_c), float(target_c))}**).",
    ]
    if top_mgr:
        lines.append("- Biggest contribution to the decline by managers:")
        for n, ds, dc, s0, s1, c0n, c1n in top_mgr:
            name = " ".join([x for x in n if x]).strip() or "N/A"
            lines.append(f"  - {name}: {s0:.2f} -> {s1:.2f} (change {ds:.2f}), deals {c0n} -> {c1n} (change {dc}).")
    if top_cmp:
        lines.append("- Biggest contribution to the decline by companies:")
        for n, ds, dc, s0, s1, c0n, c1n in top_cmp:
            cname = n or "N/A"
            lines.append(f"  - {cname}: {s0:.2f} -> {s1:.2f} (change {ds:.2f}), deals {c0n} -> {c1n} (change {dc}).")
    lines.append("")
    return "\n".join(lines)


def _question_refs_previous_data(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in Q_PREVIOUS_TABLE)


def _is_expenses_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in Q_EXPENSE_WORDS)


def _is_salary_and_expenses_question(question: str) -> bool:
    """True when the question asks about salary/payouts and expenses together."""
    return _is_salary_question(question) and _is_expenses_question(question)


def _build_salary_expenses_combo_table(
    question: str, executor, lang: str = "ru"
) -> Optional[dict]:
    """
    Two rows: SalaryPayment payouts and ProductionExpense rows for the year from the question
    (same dashboard filters as executor querysets).
    """
    if not _is_salary_and_expenses_question(question):
        return None
    qsets = getattr(executor, "querysets", None) or {}
    pay_qs = qsets.get("salary_payments_queryset")
    exp_qs = qsets.get("expenses_queryset")

    years = _extract_year_numbers_from_question(question)
    year_f = years[0] if years else None

    def agg_amount(qs, date_field: str) -> Tuple[float, int, float, float]:
        if qs is None:
            return 0.0, 0, 0.0, 0.0
        qs = qs.filter(**{f"{date_field}__isnull": False})
        if year_f is not None:
            qs = qs.filter(**{f"{date_field}__year": int(year_f)})
        a = qs.aggregate(
            total=Sum("amount"),
            cnt=Count("id"),
            avg=Avg("amount"),
            mx=Max("amount"),
        )
        return (
            float(a["total"] or 0),
            int(a["cnt"] or 0),
            float(a["avg"] or 0),
            float(a["mx"] or 0),
        )

    st = agg_amount(pay_qs, "payment_datetime")
    et = agg_amount(exp_qs, "expense_date")

    lang_u = (lang or "ru").split("-")[0].lower()
    if lang_u not in ("ru", "uk", "en"):
        lang_u = "ru"
    with override(lang_u):
        cat_pay = str(_("Salary payments"))
        cat_exp = str(_("Expenses"))
        headers = [
            str(_("Category")),
            str(_("Total amount")),
            str(_("Record count")),
            str(_("Average amount")),
            str(_("Max amount")),
        ]
    return {
        "headers": headers,
        "rows": [
            [
                cat_pay,
                round(st[0], 2),
                st[1],
                round(st[2], 6) if st[2] else 0.0,
                round(st[3], 2),
            ],
            [
                cat_exp,
                round(et[0], 2),
                et[1],
                round(et[2], 6) if et[2] else 0.0,
                round(et[3], 2),
            ],
        ],
        "type": "dict_list",
        "_combo_salary_expenses": True,
    }


def _ensure_salary_expenses_combo_table(
    table_data, question: str, executor, lang: str = "ru"
):
    """For combined salary+expense questions, always inject the two-row DB summary table."""
    if not _is_salary_and_expenses_question(question or ""):
        return table_data
    built = _build_salary_expenses_combo_table(question or "", executor, lang=lang)
    if not built:
        return table_data
    return built


def _build_salary_expenses_combo_grounded_text(
    table_data: dict, question: str, lang: str
) -> str:
    if not isinstance(table_data, dict) or not table_data.get("_combo_salary_expenses"):
        return ""
    rows = table_data.get("rows") or []
    if len(rows) != 2:
        return ""

    r0, r1 = rows[0], rows[1]
    lang_u = _grounded_response_lang(lang)

    def cells(r):
        return str(r[0]), r[1], r[2], r[3], r[4]

    c0 = cells(r0)
    c1 = cells(r1)

    with override(lang_u):
        intro = _(
            "Only facts from the table (salary payouts and expenses for the selected period/year)."
        )
        row_tmpl = _(
            "- **%(cat)s**: total **%(tot)s**, records **%(rec)s**, average **%(avg)s**, max **%(mx)s**."
        )
        body = (
            pgettext("ai_grounded", "### Analysis")
            + "\n\n"
            + intro
            + "\n"
            + row_tmpl
            % {
                "cat": c0[0],
                "tot": c0[1],
                "rec": c0[2],
                "avg": c0[3],
                "mx": c0[4],
            }
            + "\n"
            + row_tmpl
            % {
                "cat": c1[0],
                "tot": c1[1],
                "rec": c1[2],
                "avg": c1[3],
                "mx": c1[4],
            }
            + "\n"
        )
    return body


def _is_salary_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in Q_SALARY_TERMS)


def _is_salary_monthly_question(question: str) -> bool:
    q = (question or "").lower()
    if not _is_salary_question(question):
        return False
    return any(k in q for k in Q_SALARY_MONTHLY)


def _is_salary_manager_question(question: str) -> bool:
    """Salary/payout question tied to managers (not a sales rollup)."""
    if not _is_salary_question(question):
        return False
    q = (question or "").lower()
    return any(k in q for k in Q_SALARY_MANAGER)


def _question_implies_one_calendar_month_no_explicit_month(question: str) -> bool:
    """Phrases like 'per month' with no explicit month name/number — treat as one calendar month."""
    if _extract_month_numbers_from_question(question):
        return False
    q = (question or "").lower()
    return any(k in q for k in Q_ONE_MONTH_IMPLIED)


def _salary_fallback_year_month(question: str, executor) -> Tuple[Optional[int], Optional[int]]:
    """
    Year/month for extra filtering in salary fallbacks: explicit values from the question by default.
    For 'per month' without a month number, resolve month (dashboard or current) and year (effective_year or current).
    """
    years_q = _extract_year_numbers_from_question(question)
    months_q = _extract_month_numbers_from_question(question)
    year_f: Optional[int] = years_q[0] if years_q else None
    month_f: Optional[int] = months_q[0] if len(months_q) == 1 else None

    meta = getattr(executor, "filter_meta", None)
    if meta is None:
        qsd = getattr(executor, "querysets", None) or {}
        if isinstance(qsd, dict):
            meta = qsd.get("filter_meta")

    implied_month = False
    if month_f is None and _question_implies_one_calendar_month_no_explicit_month(question):
        implied_month = True
        fm = (meta or {}).get("month")
        if fm not in (None, ""):
            try:
                month_f = int(str(fm))
            except (ValueError, TypeError):
                month_f = timezone.now().month
        else:
            month_f = timezone.now().month

    if implied_month and year_f is None:
        ey = (meta or {}).get("effective_year")
        if ey not in (None, ""):
            try:
                year_f = int(str(ey))
            except (ValueError, TypeError):
                year_f = timezone.now().year
        else:
            year_f = timezone.now().year

    return year_f, month_f


def _build_expenses_year_fallback_table(question: str, executor):
    if not _is_expenses_question(question):
        return None
    querysets = getattr(executor, "querysets", None) or {}
    expenses_qs = querysets.get("expenses_queryset")
    if expenses_qs is None:
        return None
    years = _extract_year_numbers_from_question(question)
    year_for_filter = years[0] if years else None
    qs = expenses_qs.filter(expense_date__isnull=False)
    if year_for_filter is not None:
        qs = qs.filter(expense_date__year=year_for_filter)
    by_month = defaultdict(float)
    count_by_month = defaultdict(int)
    for e in qs.only("expense_date", "amount"):
        if not getattr(e, "expense_date", None):
            continue
        m = int(e.expense_date.month)
        by_month[m] += float(e.amount or 0)
        count_by_month[m] += 1
    if not by_month:
        return None
    month_names = get_months()
    rows = []
    for m in sorted(by_month.keys()):
        rows.append([
            str(month_names.get(m, m)),
            round(by_month[m], 2),
            int(count_by_month[m]),
        ])
    return {
        "headers": ["Month", "Total expenses", "Operations count"],
        "rows": rows,
        "type": "dict_list",
    }


def _build_salary_manager_grounded_text(table_data: dict, question: str) -> str:
    if not _is_salary_question(question):
        return ""
    if not isinstance(table_data, dict):
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]
    rows = table_data.get("rows") or []
    if len(rows) < 1 or len(headers) < 2:
        return ""
    mgr_i = None
    sum_i = None
    for i, h in enumerate(headers):
        if mgr_i is None and any(m in h for m in MANAGER_HEADER_FRAGMENTS):
            mgr_i = i
        if sum_i is None:
            if ("зарплат" in h) or (
                "salary" in h and ("total" in h or "общ" in h or "amount" in h or "sum" in h)
            ):
                sum_i = i
            elif ("выплат" in h and "сумм" in h) or ("payout" in h and "amount" in h):
                sum_i = i
    if mgr_i is None or sum_i is None:
        return ""

    hdrs_raw = table_data.get("headers") or []
    sum_header_raw = str(hdrs_raw[sum_i] if sum_i < len(hdrs_raw) else "").strip().lower()
    is_payout_col = "payout" in sum_header_raw or (
        "выплат" in sum_header_raw and "зарплат" not in sum_header_raw
    )

    parsed = []
    total = 0.0
    for r in rows[:500]:
        if not isinstance(r, (list, tuple)) or len(r) <= max(mgr_i, sum_i):
            continue
        name = str(r[mgr_i]).strip() or "N/A"
        val = _to_float_safe(r[sum_i])
        parsed.append((name, val))
        total += val
    if not parsed:
        return ""
    parsed.sort(key=lambda x: x[1], reverse=True)
    winner = parsed[0]
    tr = _grounded_text_pack(question)
    lang = _grounded_response_lang(_detect_question_lang(question))
    if lang == "uk":
        top_line = f"- Менеджер з найбільшою сумою в таблиці: **{winner[0]}** (**{winner[1]:.2f}**)."
        payout_line = f"- Загальна сума виплат (сума рядків): **{total:.2f}**."
        accrued_line = f"- Нарахована зарплата з угод у таблиці (поле salary по угоді, сума рядків): **{total:.2f}**."
    elif lang == "en":
        top_line = f"- Manager with the highest amount in the table: **{winner[0]}** (**{winner[1]:.2f}**)."
        payout_line = f"- Total payout amount (sum of rows): **{total:.2f}**."
        accrued_line = f"- Accrued salary from deals in the table (field salary per sale, sum of rows): **{total:.2f}**."
    else:
        top_line = f"- Менеджер с наибольшей суммой в таблице: **{winner[0]}** (**{winner[1]:.2f}**)."
        payout_line = f"- Общая сумма выплат (сумма строк): **{total:.2f}**."
        accrued_line = f"- Начисленная зарплата по сделкам в таблице (поле salary по сделке, сумма строк): **{total:.2f}**."

    lines = [tr["analysis_h3"], "", tr["facts_short"], top_line]
    if is_payout_col:
        lines.append(payout_line)
    else:
        lines.append(accrued_line)
    for name, val in parsed[1:3]:
        lines.append(f"- {name}: **{val:.2f}**.")
    lines.append("")
    return "\n".join(lines)


def _build_salary_monthly_grounded_text(table_data: dict, question: str) -> str:
    if not _is_salary_monthly_question(question):
        return ""
    if not isinstance(table_data, dict):
        return ""
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]
    rows = table_data.get("rows") or []
    if len(rows) < 1 or len(headers) < 2:
        return ""
    month_i = None
    sum_i = None
    for i, h in enumerate(headers):
        if month_i is None and ("меся" in h or "month" in h):
            month_i = i
        if sum_i is None:
            if ("сумм" in h and "выплат" in h) or ("payout" in h and "amount" in h):
                sum_i = i
            elif "salary" in h and "sale" not in h:
                sum_i = i
            elif "зарплат" in h:
                sum_i = i
    if month_i is None or sum_i is None:
        return ""
    pairs = []
    total = 0.0
    for r in rows[:120]:
        if not isinstance(r, (list, tuple)) or len(r) <= max(month_i, sum_i):
            continue
        m = str(r[month_i]).strip()
        v = _to_float_safe(r[sum_i])
        if not m:
            continue
        pairs.append((m, v))
        total += v
    if not pairs:
        return ""
    tr = _grounded_text_pack(question)
    lines = [tr["analysis_h3"], "", tr["facts_short"], f"- {tr['total_payout']}: **{total:.2f}**."]
    for m, v in pairs:
        lines.append(f"- {m}: **{v:.2f}**.")
    lines.append("")
    return "\n".join(lines)


def _build_salary_monthly_fallback_table(question: str, executor):
    if not _is_salary_monthly_question(question):
        return None
    querysets = getattr(executor, "querysets", None) or {}
    pay_qs = querysets.get("salary_payments_queryset")
    if pay_qs is None:
        return None

    # Optional manager hint: last two Cyrillic tokens (surname + given name pattern).
    mgr_last = None
    mgr_first = None
    m = re.search(r"([А-Яа-яІіЇїЄєҐґ]+)\s+([А-Яа-яІіЇїЄєҐґ]+)\s*$", str(question or "").strip())
    if m:
        mgr_last, mgr_first = m.group(1), m.group(2)

    qs = pay_qs
    if mgr_last and mgr_first:
        qs = qs.filter(manager__last_name__iexact=mgr_last, manager__name__iexact=mgr_first)

    years = _extract_year_numbers_from_question(question)
    year_for_filter = years[0] if years else None
    if year_for_filter is not None:
        qs = qs.filter(payment_datetime__year=year_for_filter)

    by_month = defaultdict(float)
    for p in qs:
        dt = getattr(p, "payment_datetime", None)
        if not dt:
            continue
        key = f"{dt.year:04d}-{dt.month:02d}"
        by_month[key] += float(p.amount or 0)
    if not by_month:
        return None
    rows = [[k, round(by_month[k], 2)] for k in sorted(by_month.keys())]
    return {
        "headers": ["Month", "Payout amount"],
        "rows": rows,
        "type": "dict_list",
    }


def _build_salary_managers_totals_fallback_table(question: str, executor):
    """
    Per-manager totals for the period (dashboard filters + optional year/month from the question).
    Prefer SalaryPayment rows; if none, accrued salary from Sale.salary.
    """
    if not _is_salary_question(question):
        return None
    querysets = getattr(executor, "querysets", None) or {}
    pay_qs = querysets.get("salary_payments_queryset")
    sales_qs = querysets.get("sales_queryset")

    year_f, month_f = _salary_fallback_year_month(question, executor)

    def _manager_name_from_agg_row(r: dict) -> str:
        last = str(r.get("manager__last_name") or "").strip()
        first = str(r.get("manager__name") or "").strip()
        return f"{last} {first}".strip() or "N/A"

    rows_out = []
    header_amount = "Payout amount"

    if pay_qs is not None:
        qs = pay_qs.filter(payment_datetime__isnull=False)
        if year_f is not None:
            qs = qs.filter(payment_datetime__year=int(year_f))
        if month_f is not None:
            qs = qs.filter(payment_datetime__month=int(month_f))
        agg = (
            qs.values("manager_id", "manager__last_name", "manager__name")
            .annotate(total=Sum("amount"))
            .filter(total__gt=0)
            .order_by("-total")
        )
        for r in agg:
            rows_out.append([_manager_name_from_agg_row(r), float(r.get("total") or 0)])

    if not rows_out and sales_qs is not None:
        sq = sales_qs.filter(closing_date__isnull=False).filter(manager__isnull=False)
        if year_f is not None:
            sq = sq.filter(closing_date__year=int(year_f))
        if month_f is not None:
            sq = sq.filter(closing_date__month=int(month_f))
        agg = (
            sq.values("manager_id", "manager__last_name", "manager__name")
            .annotate(total=Sum("salary"))
            .filter(total__gt=0)
            .order_by("-total")
        )
        for r in agg:
            rows_out.append([_manager_name_from_agg_row(r), float(r.get("total") or 0)])
        if rows_out:
            header_amount = "Total salary"

    if not rows_out:
        return None
    return {
        "headers": ["Manager", header_amount],
        "rows": rows_out,
        "type": "dict_list",
    }


def _apply_ai_table_fallbacks(table_data, question: str, executor):
    """Inject a DB-built table when the model returns empty; never substitute sales for salary questions."""
    td = table_data
    if _is_compare_intent_question(question or "") and _is_manager_breakdown_requested(question or ""):
        mgr_fallback = _build_manager_month_compare_fallback_table(question, executor)
        if mgr_fallback and len(mgr_fallback.get("rows") or []) > 0:
            td = mgr_fallback

    if len((td or {}).get("rows") or []) == 0:
        try:
            qs = (getattr(executor, "querysets", None) or {}).get("sales_queryset")
            if qs is not None:
                logger.info(
                    "Empty AI table; trying fallbacks; sales_queryset.count()=%s",
                    qs.count(),
                )
        except Exception:
            logger.debug("Could not log sales_queryset count for empty table case", exc_info=True)

        if _is_salary_question(question or ""):
            if _is_salary_manager_question(question or ""):
                sm = _build_salary_managers_totals_fallback_table(question, executor)
                if sm and len(sm.get("rows") or []) > 0:
                    td = sm
                    logger.info(
                        "Built salary-by-manager fallback: %s rows",
                        len(sm.get("rows") or []),
                    )
            if len((td or {}).get("rows") or []) == 0 and _is_salary_monthly_question(question or ""):
                salary_monthly = _build_salary_monthly_fallback_table(question, executor)
                if salary_monthly and len(salary_monthly.get("rows") or []) > 0:
                    td = salary_monthly
                    logger.info(
                        "Built salary monthly fallback: %s rows",
                        len((td or {}).get("rows") or []),
                    )

        if len((td or {}).get("rows") or []) == 0 and not _is_salary_question(question or ""):
            fallback_table = _build_month_compare_fallback_table(question, executor)
            if fallback_table:
                td = fallback_table
                logger.info(
                    "Built fallback month-comparison table from sales_queryset: %s rows",
                    len((td or {}).get("rows") or []),
                )

        if len((td or {}).get("rows") or []) == 0 and not _is_salary_question(question or ""):
            exp_fallback = _build_expenses_year_fallback_table(question, executor)
            if exp_fallback and len(exp_fallback.get("rows") or []) > 0:
                td = exp_fallback
    elif _is_single_month_total_question(question) and not _is_salary_question(question):
        forced_table = _build_month_compare_fallback_table(question, executor)
        if forced_table and len(forced_table.get("rows") or []) >= 1:
            td = forced_table

    return td


def _maybe_replace_sales_table_for_salary_question(table_data, question: str, executor):
    """If the model returned a sales-shaped table but the question is about salary, replace it."""
    if not table_data or not _is_salary_question(question or ""):
        return table_data
    headers = [str(h or "").strip().lower() for h in (table_data.get("headers") or [])]
    hjoin = " ".join(headers)
    looks_sales = any(x in hjoin for x in SALESISH_HEADER_MARKERS) and not any(
        x in hjoin for x in PAYROLL_HEADER_MARKERS
    )
    if not looks_sales:
        return table_data
    if _is_salary_manager_question(question or ""):
        sm = _build_salary_managers_totals_fallback_table(question, executor)
        if sm and len(sm.get("rows") or []) > 0:
            return sm
    if _is_salary_monthly_question(question or ""):
        sm = _build_salary_monthly_fallback_table(question, executor)
        if sm and len(sm.get("rows") or []) > 0:
            return sm
    return table_data


def _table_looks_all_zero(table_data) -> bool:
    if not isinstance(table_data, dict):
        return False
    rows = table_data.get("rows") or []
    if not rows:
        return False
    has_numeric = False
    for row in rows[:100]:
        for cell in row:
            s = str(cell).strip().replace(",", ".")
            try:
                v = float(s)
            except Exception:
                continue
            has_numeric = True
            if abs(v) > 1e-9:
                return False
    return has_numeric


def _table_has_nonzero(table_data) -> bool:
    if not isinstance(table_data, dict):
        return False
    rows = table_data.get("rows") or []
    for row in rows[:200]:
        for cell in row:
            s = str(cell).strip().replace(",", ".")
            try:
                v = float(s)
            except Exception:
                continue
            if abs(v) > 1e-9:
                return True
    return False


def _should_reuse_previous_table(question: str, current_table, previous_table) -> bool:
    rows = (current_table or {}).get("rows") if isinstance(current_table, dict) else None
    current_table_is_empty = not rows
    # Reuse context not only for all-zero outputs, but also when the current turn
    # produced no table at all (typical follow-up "why the difference?" question).
    if not current_table_is_empty and not _table_looks_all_zero(current_table):
        return False
    if not _table_has_nonzero(previous_table):
        return False
    if _question_refs_previous_data(question):
        return True
    # Follow-up "why difference?" questions often omit month names in the second turn.
    # Reuse previous non-zero table to keep context from the immediately preceding answer.
    if _is_compare_why_question(question or "") and not _extract_month_numbers_from_question(question or ""):
        return True
    # Implicit follow-up: compare question with multiple months, no explicit year.
    if (
        _is_compare_intent_question(question or "")
        and compare_question_suggests_multiple_months(question or "")
        and not _extract_year_numbers_from_question(question or "")
    ):
        return True
    return False


def _get_previous_table_from_history(current_user, history_id):
    if not current_user or not history_id:
        return None
    try:
        entry = AIAnalysisHistory.objects.filter(id=history_id, manager=current_user).first()
        if entry and isinstance(entry.table_data, dict):
            return entry.table_data
    except Exception:
        logger.exception("Failed to load previous table from history")
    return None


def _build_month_compare_fallback_table(question: str, executor):
    """
    Fallback for month-comparison questions when model code returns empty result.
    Uses already-filtered sales_queryset from executor context.
    """
    if not question:
        return None
    querysets = getattr(executor, "querysets", None) or {}
    sales_qs = querysets.get("sales_queryset")
    if sales_qs is None:
        return None

    months = _extract_month_numbers_from_question(question)
    if len(months) < 1:
        return None
    years = _extract_year_numbers_from_question(question)
    year_for_filter = years[0] if years else None

    month_names = get_months()
    rows = []
    for month_num in months[:6]:
        month_qs = sales_qs.filter(closing_date__isnull=False, closing_date__month=month_num)
        if year_for_filter is not None:
            month_qs = month_qs.filter(closing_date__year=year_for_filter)
        agg = month_qs.aggregate(
            total=Sum("sale"),
            deals=Count("id"),
            avg=Avg("sale"),
            max_deal=Max("sale"),
        )
        deals = int(agg.get("deals") or 0)
        if deals <= 0:
            continue
        rows.append(
            [
                str(month_names.get(month_num, month_num)),
                float(agg.get("total") or 0),
                deals,
                float(agg.get("avg") or 0),
                float(agg.get("max_deal") or 0),
            ]
        )

    if len(rows) < 1:
        return None
    lang = _grounded_response_lang(_detect_question_lang(question))
    if lang == "uk":
        headers = [
            "Місяць",
            "Загальна сума продажів",
            "Кількість угод",
            "Середня сума угоди",
            "Максимальна сума угоди",
        ]
    elif lang == "en":
        headers = [
            "Month",
            "Total sales amount",
            "Deals count",
            "Average deal amount",
            "Maximum deal amount",
        ]
    else:
        headers = [
            "Месяц",
            "Общая сумма продаж",
            "Количество сделок",
            "Средняя сумма сделки",
            "Максимальная сумма сделки",
        ]

    return {
        "headers": headers,
        "rows": rows,
        "type": "dict_list",
    }


def _build_manager_month_compare_fallback_table(question: str, executor):
    querysets = getattr(executor, "querysets", None) or {}
    sales_qs = querysets.get("sales_queryset")
    if sales_qs is None:
        return None
    months = _extract_month_numbers_from_question(question)
    if len(months) < 2:
        return None
    years = _extract_year_numbers_from_question(question)
    year_for_filter = years[0] if years else None
    months_use = sorted({m for m in months if isinstance(m, int) and 1 <= m <= 12})
    if len(months_use) < 2:
        return None
    month_names = get_months()

    def by_manager(month_num):
        qs = sales_qs.filter(closing_date__isnull=False, closing_date__month=month_num)
        if year_for_filter is not None:
            qs = qs.filter(closing_date__year=year_for_filter)
        rows = qs.values("manager__last_name", "manager__name").annotate(
            total=Sum("sale"),
            cnt=Count("id"),
        )
        out = {}
        for r in rows:
            last = str(r.get("manager__last_name") or "").strip()
            first = str(r.get("manager__name") or "").strip()
            name = f"{last} {first}".strip() or "N/A"
            out[name] = {
                "sales": float(r.get("total") or 0),
                "deals": int(r.get("cnt") or 0),
            }
        return out

    by_month = {m: by_manager(m) for m in months_use}
    all_names = sorted({nm for mm in by_month.values() for nm in mm.keys()})
    if not all_names:
        return None

    rows = []
    for name in all_names:
        row = [name]
        for m in months_use:
            cell = by_month.get(m, {}).get(name, {"sales": 0.0, "deals": 0})
            row.extend([cell["sales"], cell["deals"]])
        rows.append(row)

    headers = [_("Manager")]
    for m in months_use:
        ml = month_names.get(m, m)
        headers.append(f"{_('Sales')} {ml}")
        headers.append(f"{_('Deals')} {ml}")
    return {
        "headers": headers,
        "rows": rows,
        "type": "dict_list",
    }


def _coerce_manager_compare_table_if_needed(table_data, question, executor):
    """
    When the model returns a merged multi-month manager rollup, swap in a per-month column layout
    so deterministic "### Analysis" grounding can run.
    """
    if not (
        table_data
        and _safe_table_row_count(table_data) > 0
        and _is_compare_intent_question(question or "")
        and _is_manager_breakdown_requested(question or "")
        and len(_extract_month_numbers_from_question(question or "")) >= 2
        and not table_data_supports_manager_month_compare(table_data)
    ):
        return table_data
    mgr_fb = _build_manager_month_compare_fallback_table(question, executor)
    if mgr_fb and _safe_table_row_count(mgr_fb) > 0:
        return mgr_fb
    return table_data



def _question_asks_for_insights(question):
    """Check whether the question asks for insights/recommendations/analysis."""
    if not question or not question.strip():
        return False
    q = question.lower().strip()
    # Plain "compare/show A and B" without deeper analysis → skip second LLM to avoid duplicate walls of text.
    compare_only = any(k in q for k in Q_COMPARE_VERBS) and not any(
        k in q for k in Q_INSIGHTS_DEEPER
    )
    if compare_only:
        return False
    return any(k in q for k in Q_INSIGHTS_KEYWORDS)


def _append_insights_if_requested(text, table_data, question, llm_service, *, non_streaming=False):
    """Append insights text when the question explicitly asks for analysis."""
    if not table_data or not _question_asks_for_insights(question):
        return text
    try:
        insights_table = _prepare_table_for_insights(table_data)
        insights = llm_service.generate_insights(insights_table, question)
        if insights and isinstance(insights, str) and insights.strip():
            if not isinstance(text, str):
                text = str(text)
            text = (text.rstrip() + "\n\n" + insights.strip()).strip()
            if non_streaming:
                logger.info(
                    "Insights and recommendations (non‑streaming) appended to answer: %s characters",
                    len(insights),
                )
            else:
                logger.info(
                    "Insights and recommendations appended to answer: %s characters",
                    len(insights),
                )
    except Exception as e:
        logger.exception("Error while generating insights: %s", e)
    return text


def _apply_grounded_overrides(text, table_data, question, executor, lang):
    """Apply deterministic grounded overrides for compare/follow-up queries."""
    if not table_data:
        return text
    
    text = text or ""
    text = fill_compare_placeholders_in_text(text, table_data)
    text = apply_table_grounded_analysis_for_compare(text, table_data, question)
    text = apply_table_grounded_analysis_for_manager_compare(
        text, table_data, question, lang=lang
    )
    grounded_manager = _build_manager_compare_grounded_text(
        table_data, question, executor, lang=lang
    )
    if grounded_manager:
        text = grounded_manager
    grounded_two_month = _build_two_month_compare_grounded_text(table_data, question)
    if grounded_two_month:
        text = grounded_two_month
    grounded_multi_month_sales = _build_multi_month_sales_compare_grounded_text(
        table_data, question
    )
    if grounded_multi_month_sales:
        text = grounded_multi_month_sales
    grounded_single_month = _build_single_month_grounded_text(table_data, question)
    if grounded_single_month:
        text = grounded_single_month
    if _question_refs_previous_data(question):
        grounded_followup = _build_month_summary_grounded_text(table_data, lang)
        if grounded_followup:
            text = grounded_followup
    grounded_one_row = _build_one_row_table_grounded_text(table_data, question)
    if grounded_one_row:
        text = grounded_one_row
    grounded_manager_month_list = _build_manager_month_list_grounded_text(
        table_data, question, lang
    )
    if grounded_manager_month_list:
        text = grounded_manager_month_list
    grounded_why = _build_compare_why_grounded_text_from_db(question, executor)
    if grounded_why:
        text = grounded_why
    grounded_salary = _build_salary_manager_grounded_text(table_data, question)
    if grounded_salary:
        text = grounded_salary
    grounded_salary_monthly = _build_salary_monthly_grounded_text(table_data, question)
    if grounded_salary_monthly:
        text = grounded_salary_monthly
    grounded_combo_se = _build_salary_expenses_combo_grounded_text(
        table_data, question, lang
    )
    if grounded_combo_se:
        text = grounded_combo_se
    grounded_expense_types = _build_expense_type_ranking_grounded_text(
        table_data, question, lang
    )
    if grounded_expense_types:
        text = grounded_expense_types
    text = _localize_grounded_output_text(text, lang)
    return text


def _localize_grounded_output_text(text: str, lang: str) -> str:
    """
    Some deterministic grounded builders still output English templates.
    Localize fixed phrases via Django locale dictionaries (.po files).
    """
    if not isinstance(text, str) or not text.strip():
        return text
    lang = (lang or "ru").split("-")[0].lower()
    if lang not in ("ru", "uk", "en"):
        return text

    msgids = (
        "### Reason Analysis",
        "Only facts from the DB (via table and aggregates):",
        "Only facts from the manager table.",
        "Only facts from the table (no made-up managers or amounts).",
        "Only facts from the table (no made-up numbers).",
        "- Change in total sales amount",
        "- Change in number of deals",
        "- Total payout amount",
        "- Total payout amount (sum of rows): ",
        "- Manager with the highest amount in the table: ",
        "- Accrued salary from deals in the table (field salary per sale, sum of rows): ",
        ": total sales amount is ",
        ", deals are ",
        ", average deal is ",
        " is **",
        "(change ",
        "deals ",
        "Biggest contribution to the decline by managers",
        "Biggest contribution to the decline by companies",
    )

    out = text
    with override(lang):
        out = out.replace(
            "### Analysis",
            pgettext("ai_grounded", "### Analysis"),
        )
        out = out.replace(
            "Only facts from the table.",
            pgettext("ai_grounded", "Only facts from the table."),
        )
        for src in msgids:
            out = out.replace(src, _(src))
    return out


class DummyExecutor:
    def __init__(self, querysets):
        self.querysets = querysets or {}
        self.filter_meta = (
            self.querysets.get("filter_meta")
            if isinstance(self.querysets, dict)
            else None
        )

def _build_code_executor(data_summary, filtered_querysets):
    """(Deprecated) Build dummy executor for backward-compatible fallback logic."""
    return DummyExecutor(filtered_querysets)

def _normalize_tool_dispatch_table(raw: Optional[dict]) -> Optional[dict]:
    """Turn a tool dispatch dict into frontend table_data (headers + list rows)."""
    if not raw or not isinstance(raw, dict):
        return None
    table_data = dict(raw)
    if "summaries" in table_data:
        table_data = {**table_data, "rows": table_data.pop("summaries")}
    rows = table_data.get("rows", [])
    if not rows:
        return None
    if "headers" not in table_data and isinstance(rows[0], dict):
        keys = list(rows[0].keys())
        table_data["headers"] = [str(k).replace("_", " ").upper() for k in keys]
        table_data["rows"] = [
            [_cell_str(row.get(k, "")) for k in keys] for row in rows
        ]
    elif isinstance(rows[0], list):
        table_data["rows"] = [[_cell_str(c) for c in r] for r in rows]
    return table_data


def _run_analysis_tools(tool_calls, filtered_querysets):
    """
    Execute every tool call in one assistant turn; return OpenAI ``tool`` payloads
    and the last non-empty normalized table for the UI.

    Returns:
        (list of {"id", "content"}, table_data | None)
    """
    if not tool_calls:
        return [], None

    logger.info("Executing %s analysis tool call(s)", len(tool_calls))
    max_chars = int(getattr(settings, "AI_MAX_TOOL_RESULT_CHARS", 120_000))
    session = AnalysisToolSession(filtered_querysets)
    tool_messages = []
    table_data = None

    for tc in tool_calls:
        fname = tc.get("function", {}).get("name")
        fargs_str = tc.get("function", {}).get("arguments", "{}")
        tid = tc.get("id") or ""
        try:
            fargs = (
                json.loads(fargs_str)
                if isinstance(fargs_str, str)
                else (fargs_str if isinstance(fargs_str, dict) else {})
            )
        except json.JSONDecodeError:
            fargs = {}
        try:
            logger.info("Tool %s with args %s", fname, fargs)
            raw = session.dispatch(fname, fargs)
        except Exception as e:
            logger.exception("Tool %s failed: %s", fname, e)
            raw = {"ok": False, "error": str(e)}

        try:
            payload = json.dumps(raw, ensure_ascii=False, default=str)
        except TypeError:
            payload = json.dumps(
                {"ok": False, "error": "serialization_failed"}, ensure_ascii=False
            )
        if len(payload) > max_chars:
            payload = (
                payload[:max_chars]
                + "\n...(truncated: increase AI_MAX_TOOL_RESULT_CHARS if needed)"
            )
        tool_messages.append({"id": tid, "content": payload})

        td = _normalize_tool_dispatch_table(raw if isinstance(raw, dict) else None)
        if td:
            table_data = td

    return tool_messages, table_data


def _analysis_tool_executor(filtered_querysets):
    """Build closure for ``LLMService.analyze_data(..., tool_executor=...)``."""

    def _exec(serial_tool_calls):
        return _run_analysis_tools(serial_tool_calls, filtered_querysets)

    return _exec


def _execute_tool_calls(tool_calls, filtered_querysets):
    """Backward-compatible: run all tools; return the last non-empty table for the UI."""
    _, table_data = _run_analysis_tools(tool_calls, filtered_querysets)
    return table_data


def _persist_analysis_history(
    current_user,
    question,
    answer_text,
    serializable_table_data,
    token_usage,
    conversation_history,
    history_id,
):
    """Persist assistant response and table data to history."""
    if not (current_user and answer_text):
        return None
    full_history = list(conversation_history) if conversation_history else []
    full_history.append({'role': 'user', 'content': question})

    assistant_msg = {'role': 'assistant', 'content': answer_text}
    if serializable_table_data:
        assistant_msg['table_data'] = serializable_table_data
    full_history.append(assistant_msg)

    return save_analysis_to_history(
        manager=current_user,
        question=question,
        answer=answer_text,
        table_data=serializable_table_data,
        token_usage=token_usage,
        conversation_history=full_history,
        history_id=history_id,
    )


def _ensure_total_tokens(token_usage):
    """Populate total_tokens from prompt/completion tokens when missing."""
    if "total_tokens" in token_usage:
        return token_usage
    prompt_tokens = token_usage.get("prompt_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0)
    if prompt_tokens or completion_tokens:
        token_usage["total_tokens"] = prompt_tokens + completion_tokens
    return token_usage


def _prepare_table_for_insights(table_data):
    """
    Reduce mixed tables to a stable summary slice for insights.
    LLM-generated result tables often contain several logical sections in one list;
    this helper keeps only month-level summary rows when possible to avoid double counting.
    """
    if not table_data or not isinstance(table_data, dict):
        return table_data
    headers = table_data.get('headers') or []
    rows = table_data.get('rows') or []
    if not headers or not rows:
        return table_data

    # Candidate column names in RU/UK/EN.
    month_candidates = {'месяц', 'month'}
    total_candidates = {'общая сумма продаж', 'total sales', 'всього продажів'}
    deals_candidates = {'количество сделок', 'deals count', 'кількість угод'}
    avg_candidates = {'средняя сумма сделки', 'average deal', 'середня угода', 'средняя сделка'}
    max_candidates = {'максимальная сумма сделки', 'max deal', 'максимальна угода', 'наибольшая сделка'}

    def normalize(h):
        return str(h or '').strip().lower()

    normalized_headers = [normalize(h) for h in headers]

    def find_idx(candidates):
        for i, h in enumerate(normalized_headers):
            if h in candidates:
                return i
        return None

    month_idx = find_idx(month_candidates)
    total_idx = find_idx(total_candidates)
    deals_idx = find_idx(deals_candidates)
    avg_idx = find_idx(avg_candidates)
    max_idx = find_idx(max_candidates)

    # If key summary columns are not present, keep original.
    if month_idx is None or total_idx is None or deals_idx is None:
        return table_data

    def non_empty(cell):
        return str(cell if cell is not None else '').strip() != ''

    # Keep rows that look like month-level totals.
    filtered_rows = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        if len(row) <= max(month_idx, total_idx, deals_idx):
            continue
        if not (non_empty(row[month_idx]) and non_empty(row[total_idx]) and non_empty(row[deals_idx])):
            continue
        # If avg/max columns exist in this schema, require them to be present too
        # (helps exclude manager-level lines that may share month+total+count fields).
        if avg_idx is not None and (len(row) <= avg_idx or not non_empty(row[avg_idx])):
            continue
        if max_idx is not None and (len(row) <= max_idx or not non_empty(row[max_idx])):
            continue
        filtered_rows.append(list(row))

    # Only use filtered slice if we have at least 2 summary rows (e.g., two compared months).
    if len(filtered_rows) >= 2:
        return {
            'headers': headers,
            'rows': filtered_rows,
            'type': table_data.get('type', 'dict_list')
        }
    return table_data


def json_serialize_dates(obj):
    """
    Recursively convert values for JSON (SSE, history): date/datetime → ISO str, Decimal → float.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: json_serialize_dates(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [json_serialize_dates(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(json_serialize_dates(item) for item in obj)
    return obj


def json_response_on_error(view_func):
    """Decorator to handle exceptions and return JSON responses."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Unhandled exception in {view_func.__name__}: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Internal server error: %(error)s") % {"error": str(e)},
            }, status=500)
    return wrapper


@login_required
@ensure_csrf_cookie
def ai_analysis_view(request):
    """Main page for working with AI analysis."""
    current_user, is_admin = get_current_crm_user(request)
    # Get data for analysis
    data_summary = _get_data_summary(request, current_user, is_admin)
    
    context = {
        'data_summary': data_summary,
        'is_admin': is_admin,
    }
    
    return render(request, 'salary/ai_analysis.html', context)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_analyze_data(request):
    """API endpoint for analyzing data via AI."""
    try:
        # Parse JSON from the request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON format in request'
            }, status=400)
        
        question = data.get('question', '')
        use_streaming = data.get('streaming', True)  # Use streaming mode by default
        conversation_history = data.get('conversation_history')  # list [{role, content}] to continue the dialog
        history_id = data.get('history_id')
        body_filters = data.get('filters')
        if body_filters is not None and not isinstance(body_filters, dict):
            body_filters = None
        if conversation_history is not None and not isinstance(conversation_history, list):
            conversation_history = None
        current_user, is_admin = get_current_crm_user(request)
        # Get data summary and filtered QuerySets for executing generated code
        try:
            data_summary = _get_data_summary(
                request, current_user, is_admin, question=question, extra_filters=body_filters
            )
            filtered_querysets = _get_filtered_querysets(
                request, current_user, is_admin, question=question, extra_filters=body_filters
            )
        except Exception as e:
            logger.exception(f"Error while getting data summary: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while getting data: %(error)s") % {"error": str(e)},
            }, status=500)
        
        # Get the LLM service
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Error while getting LLM service: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while initializing LLM service: %(error)s") % {"error": str(e)},
            }, status=500)
        
        # If streaming is enabled
        if use_streaming:
            def generate_stream():
                try:
                    logger.info(f"Starting streaming data analysis via AI. Model type: {llm_service.model_type}")
                    logger.info(f"User question: {question[:100] if question else 'No question'}")
                    accumulated = ""
                    token_usage = {}
                    chunk_count = 0
                    has_data = False
                    
                    lang = _resolve_response_lang(request, question)

                    tool_calls = None
                    agent_table_data = None
                    tool_ex = _analysis_tool_executor(filtered_querysets)
                    for chunk_data in llm_service.analyze_data(
                        data_summary,
                        question,
                        use_streaming=True,
                        conversation_history=conversation_history,
                        lang=lang,
                        tools=TOOL_DEFINITIONS,
                        tool_executor=tool_ex,
                    ):
                        chunk_count += 1
                        if isinstance(chunk_data, dict):
                            chunk = chunk_data.get('chunk', '')
                            if 'tool_calls' in chunk_data:
                                tool_calls = chunk_data['tool_calls']
                            if chunk_data.get('agent_table_data') is not None:
                                agent_table_data = chunk_data['agent_table_data']
                            if 'usage' in chunk_data:
                                token_usage = chunk_data['usage']
                        else:
                            # For backward compatibility
                            chunk = chunk_data
                        
                        # Check whether the chunk is an error message
                        if chunk and _chunk_looks_like_llm_error(chunk):
                            # If this is an error, send it as error
                            logger.error(f"Error received from the model: {chunk}")
                            yield f"data: {json.dumps({'error': chunk}, ensure_ascii=False)}\n\n"
                            break
                        
                        if chunk:
                            has_data = True
                            accumulated += chunk
                            # Send chunk in JSON format for SSE
                            yield f"data: {json.dumps({'chunk': chunk, 'accumulated': accumulated, 'usage': token_usage}, ensure_ascii=False)}\n\n"
                    
                    # Check whether at least one chunk was received
                    logger.info(f"Streaming finished. Chunks received: {chunk_count}, accumulated text length: {len(accumulated)} characters")
                    
                    # If accumulated text is empty but there was no error, this is a problem
                    if not accumulated and not has_data and not tool_calls and chunk_count > 0:
                        logger.warning("Model returned an empty answer without errors. Trying non‑streaming mode...")
                        # Try non‑streaming mode as a fallback
                        try:
                            logger.info("Trying non‑streaming mode as a fallback")
                            result = llm_service.analyze_data(
                                data_summary,
                                question,
                                use_streaming=False,
                                conversation_history=conversation_history,
                                lang=lang,
                                tools=TOOL_DEFINITIONS,
                                tool_executor=tool_ex,
                            )
                            if isinstance(result, dict):
                                analysis = result.get('text', '')
                                if 'tool_calls' in result:
                                    tool_calls = result['tool_calls']
                                token_usage = result.get('usage', {})
                            else:
                                analysis = result
                                token_usage = {}

                            # Ensure analysis is a string before using string methods
                            if analysis is not None and not isinstance(analysis, str):
                                analysis = str(analysis)
                            
                            if analysis and analysis.strip():
                                logger.info(f"Non‑streaming fallback successfully generated an answer: {len(analysis)} characters")
                                accumulated = analysis
                            else:
                                logger.error("Non-streaming mode also returned an empty answer")
                                error_msg = "The model did not generate an answer in either mode. The prompt may be too large, or the model cannot process the request."
                                yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
                                return
                        except Exception as fallback_error:
                            logger.exception(f"Error during fallback to non-streaming mode: {fallback_error}")
                            error_msg = "The model did not generate an answer. The prompt may be too large, or the model cannot process the request."
                            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
                            return
                    
                    # Send a final message with token usage
                    # Compute total_tokens if not provided
                    token_usage = _ensure_total_tokens(token_usage)
                    
                    logger.info(f"Final answer: {len(accumulated)} characters, tokens: {token_usage}")
                    
                    # Check if model returned tool calls
                    table_data = None
                    code_result = None
                    executor = None
                    try:
                        executor = _build_code_executor(data_summary, filtered_querysets)
                        if agent_table_data is not None:
                            table_data = agent_table_data
                        elif tool_calls:
                            table_data = _execute_tool_calls(tool_calls, filtered_querysets)

                        table_data = _apply_ai_table_fallbacks(table_data, question, executor)
                        table_data = _maybe_replace_sales_table_for_salary_question(
                            table_data, question, executor
                        )
                        table_data = _ensure_salary_expenses_combo_table(
                            table_data, question, executor, lang=lang
                        )

                        table_data = _coerce_manager_compare_table_if_needed(
                            table_data, question, executor
                        )

                        prev_table = _get_previous_table_from_history(current_user, history_id)
                        if _should_reuse_previous_table(question, table_data, prev_table):
                            table_data = prev_table
                    except Exception as e:
                        logger.exception(f"Error while executing tool logic: {e}")
                        # Do not stop execution, just log the error
                    
                    if not accumulated.strip() and table_data and _safe_table_row_count(table_data) > 0:
                        with override(_grounded_response_lang(lang)):
                            accumulated = _("Here is the data found for your request:")

                    accumulated = _append_insights_if_requested(
                        accumulated, table_data, question, llm_service
                    )
                    accumulated = _apply_grounded_overrides(
                        accumulated, table_data, question, executor, lang
                    )
                    
                    # Convert dates to strings before JSON serialization
                    serializable_table_data = json_serialize_dates(table_data) if table_data else None
                    serializable_code_result = json_serialize_dates(code_result) if code_result else None
                    history_entry = None
                    
                    # Save to history after streaming is finished
                    history_entry = _persist_analysis_history(
                        current_user=current_user,
                        question=question,
                        answer_text=accumulated,
                        serializable_table_data=serializable_table_data,
                        token_usage=token_usage,
                        conversation_history=conversation_history,
                        history_id=history_id,
                    )
                    
                    yield f"data: {json.dumps({'done': True, 'full_text': accumulated, 'usage': token_usage, 'table_data': serializable_table_data, 'code_result': serializable_code_result, 'history_id': history_entry.id if history_entry else None}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.exception(f"Error during streaming data analysis via AI: {e}")
                    error_msg = str(e)
                    yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
            
            response = StreamingHttpResponse(generate_stream(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        else:
            # Regular non‑streaming mode
            try:
                logger.info(f"Starting data analysis via AI. Model type: {llm_service.model_type}")
                # Prefer Django active language (set by LocaleMiddleware); fallback to ru.
                lang = _resolve_response_lang(request, question)

                tool_ex = _analysis_tool_executor(filtered_querysets)
                result = llm_service.analyze_data(
                    data_summary,
                    question,
                    use_streaming=False,
                    conversation_history=conversation_history,
                    lang=lang,
                    tools=TOOL_DEFINITIONS,
                    tool_executor=tool_ex,
                )
                
                tool_calls = None
                # Handle the new return format (dict with 'text' and 'usage')
                if isinstance(result, dict):
                    analysis = result.get('text', '')
                    if 'tool_calls' in result:
                        tool_calls = result['tool_calls']
                    token_usage = result.get('usage', {})
                    pref_table = result.get('table_data')
                else:
                    # For backward compatibility
                    analysis = result
                    token_usage = {}
                    pref_table = None
                
                # Ensure analysis is a string for further processing
                if analysis is not None and not isinstance(analysis, str):
                    analysis = str(analysis)

                logger.info(f"Data analysis completed successfully. Answer length: {len(analysis) if analysis else 0}")
                
                # Compute total_tokens if not provided
                token_usage = _ensure_total_tokens(token_usage)
                
                # Check if model returned tool calls
                table_data = None
                code_result = None
                executor = None
                try:
                    executor = _build_code_executor(data_summary, filtered_querysets)
                    if pref_table is not None:
                        table_data = pref_table
                    elif tool_calls:
                        table_data = _execute_tool_calls(tool_calls, filtered_querysets)

                    table_data = _apply_ai_table_fallbacks(table_data, question, executor)
                    table_data = _maybe_replace_sales_table_for_salary_question(
                        table_data, question, executor
                    )
                    table_data = _ensure_salary_expenses_combo_table(
                        table_data, question, executor, lang=lang
                    )

                    table_data = _coerce_manager_compare_table_if_needed(
                        table_data, question, executor
                    )

                    prev_table = _get_previous_table_from_history(current_user, history_id)
                    if _should_reuse_previous_table(question, table_data, prev_table):
                        table_data = prev_table
                except Exception as e:
                    logger.exception("Error while executing tool logic: %s", e)
                    # Do not stop execution, just log the error
                
                if not analysis.strip() and table_data and _safe_table_row_count(table_data) > 0:
                    with override(_grounded_response_lang(lang)):
                        analysis = _("Here is the data found for your request:")

                analysis = _append_insights_if_requested(
                    analysis, table_data, question, llm_service, non_streaming=True
                )
                analysis = _apply_grounded_overrides(
                    analysis, table_data, question, executor, lang
                )
                
                # Convert dates to strings before JSON serialization
                serializable_table_data = json_serialize_dates(table_data) if table_data else None
                serializable_code_result = json_serialize_dates(code_result) if code_result else None
                serializable_data_summary = json_serialize_dates(data_summary) if data_summary else None
                history_entry = None
                
                # Save to history after receiving the answer
                history_entry = _persist_analysis_history(
                    current_user=current_user,
                    question=question,
                    answer_text=analysis,
                    serializable_table_data=serializable_table_data,
                    token_usage=token_usage,
                    conversation_history=conversation_history,
                    history_id=history_id,
                )
                
                return JsonResponse({
                    'success': True,
                    'analysis': analysis,
                    'usage': token_usage,
                    'data_summary': serializable_data_summary,
                    'table_data': serializable_table_data,
                    'code_result': serializable_code_result,
                    'history_id': history_entry.id if history_entry and current_user and analysis else None
                })
            except Exception as e:
                logger.exception(f"Error while analyzing data via AI: {e}")
                error_msg = str(e)
                # Check whether the error is related to API connectivity
                if 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                    error_msg = gettext_lazy("Could not connect to ChatGPT API. Check OPENAI_API_KEY settings and Internet availability.")
                return JsonResponse({
                    'success': False,
                    'error': gettext_lazy("Error while analyzing data: %(error)s") % {"error": error_msg},
                }, status=500)
        
    except Exception as e:
        logger.exception(f"Unexpected error while analyzing data via AI: {e}")
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("Unexpected error: %(error)s") % {"error": str(e)},
        }, status=500)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_generate_insights(request):
    """API endpoint for generating insights and recommendations based on table data."""
    try:
        # Parse JSON from the request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Invalid JSON format in request"),
            }, status=400)
        
        table_data = data.get('table_data', {})
        question = data.get('question', '')
        
        if not table_data or not table_data.get('headers') or not table_data.get('rows'):
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Table data was not provided"),
            }, status=400)
        
        # Get the LLM service
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Error while getting LLM service: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while initializing LLM service: %(error)s") % {"error": str(e)},
            }, status=500)
        
        # Generate insights and recommendations
        try:
            insights = llm_service.generate_insights(table_data, question)
            
            # Ensure that insights is a string
            if not isinstance(insights, str):
                logger.warning(f"generate_insights returned non-string: {type(insights)}, converting to string")
                if insights is None:
                    insights = gettext_lazy("Failed to generate insights. Please try again.")
                else:
                    insights = str(insights)
            
            return JsonResponse({
                'success': True,
                'insights': insights
            })
        except Exception as e:
            logger.exception(f"Error while generating insights: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while generating insights: %(error)s") % {"error": str(e)},
            }, status=500)
    
    except Exception as e:
        logger.exception(f"Unexpected error while generating insights: {e}")
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("Internal server error: %(error)s") % {"error": str(e)},
        }, status=500)


@login_required
@require_http_methods(["POST"])
@json_response_on_error
def ai_generate_chart(request):
    """API endpoint for generating a chart suggestion via AI."""
    try:
        # Parse JSON from the request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Invalid JSON format in request"),
            }, status=400)
        
        body_filters = data.get('filters')
        if body_filters is not None and not isinstance(body_filters, dict):
            body_filters = None

        current_user, is_admin = get_current_crm_user(request)
        # Get data summary
        try:
            data_summary = _get_data_summary(
                request, current_user, is_admin, extra_filters=body_filters
            )
        except Exception as e:
            logger.exception(f"Error while getting data summary: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while getting data: %(error)s") % {"error": str(e)},
            }, status=500)
        
        # Get the LLM service
        try:
            llm_service = get_llm_service()
        except Exception as e:
            logger.exception(f"Error while getting LLM service: {e}")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while initializing LLM service: %(error)s") % {"error": str(e)},
            }, status=500)
        
        # Generate a chart suggestion
        try:
            # Prefer Django active language (set by LocaleMiddleware); fallback to ru.
            lang = getattr(request, "LANGUAGE_CODE", None) or "ru"
            lang = (lang or "ru").split("-")[0].lower()
            if lang not in ("ru", "uk", "en"):
                lang = "ru"
            chart_suggestion = llm_service.generate_chart_suggestion(data_summary, lang=lang)
        except Exception as e:
            logger.exception(f"Error while generating chart via AI: {e}")
            error_msg = str(e)
            # Check whether the error is related to API connectivity
            if 'connection' in error_msg.lower() or 'timeout' in error_msg.lower():
                error_msg = gettext_lazy("Could not connect to ChatGPT API. Check OPENAI_API_KEY settings and Internet availability.")
            return JsonResponse({
                'success': False,
                'error': gettext_lazy("Error while generating chart: %(error)s") % {"error": error_msg},
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'chart': chart_suggestion
        })
        
    except Exception as e:
        logger.exception(f"Unexpected error while generating chart via AI: {e}")
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("Unexpected error: %(error)s") % {"error": str(e)},
        }, status=500)


@login_required
@ensure_csrf_cookie
@require_http_methods(["GET"])
def get_csrf_token(request):
    """Get CSRF token for AJAX requests."""
    from django.middleware.csrf import get_token
    token = get_token(request)
    return JsonResponse({'csrf_token': token})


@login_required
def ai_analysis_history(request):
    """Page for viewing the ChatGPT analysis history."""
    current_user, _ = get_current_crm_user(request)
    if not current_user:
        return render(request, 'salary/error_simple.html', {
            'error_message': gettext_lazy("User not found"),
        }, status=404)
    
    # Get analysis history for the current manager
    history = AIAnalysisHistory.objects.filter(manager=current_user).order_by('-created_at')
    
    # Pagination (20 entries per page)
    from django.core.paginator import Paginator
    paginator = Paginator(history, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'salary/ai_analysis_history.html', {
        'history': page_obj,
        'current_user': current_user,
    })


@login_required
@require_http_methods(["GET"])
def ai_get_history_entry(request, entry_id):
    """API endpoint to get details of a history entry."""
    current_user, _ = get_current_crm_user(request)
    if not current_user:
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("User not found"),
        }, status=404)
    try:
        entry = AIAnalysisHistory.objects.get(id=entry_id, manager=current_user)
    except AIAnalysisHistory.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("Entry not found"),
        }, status=404)
    
    # Convert dates to strings
    serializable_table_data = json_serialize_dates(entry.table_data) if entry.table_data else None
    
    return JsonResponse({
        'success': True,
        'id': entry.id,  # type: ignore[reportAttributeAccessIssue]
        'question': entry.question,
        'answer': entry.answer,
        'table_data': serializable_table_data,
        'token_usage': entry.token_usage,
        'conversation_history': entry.conversation_history,
        'created_at': entry.created_at.strftime('%d.%m.%Y %H:%M:%S')
    })


@login_required
@require_http_methods(["DELETE", "POST"])
def ai_delete_history_entry(request, entry_id):
    """API endpoint to delete a history entry."""
    current_user, _ = get_current_crm_user(request)
    if not current_user:
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("User not found"),
        }, status=404)
    try:
        entry = AIAnalysisHistory.objects.get(id=entry_id, manager=current_user)
    except AIAnalysisHistory.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': gettext_lazy("Entry not found"),
        }, status=404)
    
    # Delete the entry
    entry.delete()
    logger.info("History entry deleted: ID=%s, manager=%s", entry_id, current_user)
    
    return JsonResponse({
        'success': True,
        'message': gettext_lazy("Entry has been deleted successfully."),
    })


@login_required
@require_http_methods(["GET"])
def ai_check_model_status(request):
    """Check the status of the ChatGPT model."""
    try:
        llm_service = get_llm_service()
        
        # Check whether API key is configured
        if not llm_service.api_key:
            return JsonResponse({
                'status': 'not_configured',
                'message': gettext_lazy("ChatGPT is not configured. Set OPENAI_API_KEY in the environment (.env file)."),
            })
        
        # Initialize the model if it is not initialized yet
        if not llm_service._initialized:
            initialized = llm_service.initialize()
            if not initialized:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("Could not initialize ChatGPT. Check OPENAI_API_KEY settings."),
                })
        
        # Perform a simple test request to check API availability
        try:
            # Ensure client is initialized
            client = llm_service.client
            if client is None:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("ChatGPT client is not initialized. Check OPENAI_API_KEY settings."),
                })

            # Determine which parameter to use for token limit
            completion_params = {}
            models_using_max_completion_tokens = ['o1', 'o1-preview', 'o1-mini', 'o1-mini-preview']
            if any(model in llm_service.model_name.lower() for model in models_using_max_completion_tokens):
                completion_params['max_completion_tokens'] = 1
            else:
                completion_params['max_tokens'] = 1
            
            client.chat.completions.create(
                model=llm_service.model_name,
                messages=[{"role": "user", "content": "test"}],
                **completion_params
            )
            
            response_data = {
                'status': 'ready',
                'message': gettext_lazy("ChatGPT is ready."),
                'model_type': llm_service.model_type,
                'model_name': llm_service.model_name,
            }
            
            return JsonResponse(response_data)
        except Exception as e:
            logger.warning(f"Error while checking ChatGPT API availability: {e}")
            error_msg = str(e).lower()
            
            if 'api key' in error_msg or 'authentication' in error_msg:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("Invalid API key. Check OPENAI_API_KEY settings."),
                })
            elif 'rate limit' in error_msg:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("Rate limit exceeded for ChatGPT API. Please try again later."),
                })
            elif 'connection' in error_msg or 'timeout' in error_msg:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("Could not connect to ChatGPT API. Check Internet availability."),
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': gettext_lazy("Error while checking ChatGPT: %(error)s") % {"error": str(e)},
                })
        
    except Exception as e:
        logger.exception(f"Error while checking model status: {e}")
        return JsonResponse({
            'status': 'error',
            'message': gettext_lazy("Error: %(error)s") % {"error": str(e)},
        }, status=500)


def _ai_request_filter_params(request, extra_filters=None):
    """
    Merge filters from the page query string and the /api/ai/analyze/ JSON body
    (same keys as the dashboard: year, month, filter_type, date_from, date_to, manager).
    """
    bf = extra_filters if isinstance(extra_filters, dict) else {}

    def pick(key, default=None):
        v = bf.get(key)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
        got = request.GET.get(key, default)
        if got is not None and str(got).strip() != "":
            return str(got).strip()
        return None

    return {
        "month": pick("month"),
        "year_param": pick("year"),
        "date_from": pick("date_from"),
        "date_to": pick("date_to"),
        "filter_type": pick("filter_type", "month") or "month",
        "manager_id": pick("manager"),
    }


def _effective_month_for_ai_question(fp, question):
    """When the question mentions >=2 months, widen a narrow single-month slice to full-year context."""
    eff_month = fp["month"]
    if (
        question
        and compare_question_suggests_multiple_months(question)
        and eff_month
    ):
        return None, True
    return eff_month, False


def _effective_year_for_ai_question(fp, question, compare_widened):
    """
    For multi-month compare questions without explicit year,
    disable "current year by default" filter in AI pipeline.
    """
    year_param = fp["year_param"]
    parsed_years = _extract_year_numbers_from_question(question)
    if (year_param is None or str(year_param).strip() == "") and parsed_years:
        return str(parsed_years[0])
    if (
        (year_param is None or str(year_param).strip() == "")
        and _is_salary_monthly_question(question or "")
    ):
        # For "in which months salary was paid" questions without explicit year,
        # avoid clipping by current year default.
        return ""
    if (
        (year_param is None or str(year_param).strip() == "")
        and compare_question_suggests_multiple_months(question or "")
    ):
        # For compare questions like "November vs May" without explicit year in request,
        # avoid implicit current-year clipping.
        return ""
    if compare_widened and (year_param is None or str(year_param).strip() == ""):
        return ""
    return year_param


def _get_filtered_querysets(request, current_user, is_admin, question="", extra_filters=None):
    """
    QuerySets for CodeExecutor: same slice as the main dashboard (sales_list), plus chat JSON filters.
    """
    fp = _ai_request_filter_params(request, extra_filters)
    eff_month, compare_widened = _effective_month_for_ai_question(fp, question)
    eff_year = _effective_year_for_ai_question(fp, question, compare_widened)

    sales = Sale.objects.select_related('manager', 'company').all()
    salary_payments = SalaryPayment.objects.select_related('manager').all()
    expenses = ProductionExpense.objects.select_related('employee', 'expense_type').all()

    sales, salary_payments, expenses, meta = apply_dashboard_filters(
        sales,
        salary_payments,
        expenses,
        is_admin=is_admin,
        current_user=current_user,
        manager_id=fp["manager_id"],
        month=eff_month,
        year_param=eff_year,
        date_from=fp["date_from"],
        date_to=fp["date_to"],
        filter_type=fp["filter_type"],
    )

    return {
        'sales_queryset': sales,
        'salary_payments_queryset': salary_payments,
        'expenses_queryset': expenses,
        'filter_meta': meta,
    }


def _get_data_summary(request, current_user, is_admin, question="", extra_filters=None):
    """Aggregated prompt summary using the same filters as the dashboard; see apply_dashboard_filters."""
    fp = _ai_request_filter_params(request, extra_filters)
    eff_month, compare_widened = _effective_month_for_ai_question(fp, question)
    eff_year = _effective_year_for_ai_question(fp, question, compare_widened)

    sales = Sale.objects.select_related('manager', 'company').all()
    salary_payments = SalaryPayment.objects.select_related('manager').all()
    expenses = ProductionExpense.objects.select_related('employee', 'expense_type').all()

    sales, salary_payments, expenses, meta = apply_dashboard_filters(
        sales,
        salary_payments,
        expenses,
        is_admin=is_admin,
        current_user=current_user,
        manager_id=fp["manager_id"],
        month=eff_month,
        year_param=eff_year,
        date_from=fp["date_from"],
        date_to=fp["date_to"],
        filter_type=fp["filter_type"],
    )

    # Aggregate data
    total_sales = sales.aggregate(total=Sum('sale'))['total'] or 0
    total_salary = sales.aggregate(total=Sum('salary'))['total'] or 0
    total_salary_paid = salary_payments.aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or 0
    sales_count = sales.count()
    payments_count = salary_payments.count()
    expenses_count = expenses.count()
    
    # Average values
    avg_sale = sales.aggregate(avg=Avg('sale'))['avg'] or 0
    avg_salary = sales.aggregate(avg=Avg('salary'))['avg'] or 0
    avg_expense = expenses.aggregate(avg=Avg('amount'))['avg'] or 0
    
    # Data by managers
    manager_stats = sales.values('manager__name', 'manager__last_name').annotate(
        total_sales=Sum('sale'),
        total_salary=Sum('salary'),
        count=Count('id')
    ).order_by('-total_sales')[:10]
    
    manager_data = [
        {
            'name': f"{m.get('manager__last_name', '')} {m.get('manager__name', '')}",
            'total_sales': float(m['total_sales'] or 0),
            'total_salary': float(m['total_salary'] or 0),
            'count': m['count']
        }
        for m in manager_stats
    ]
    
    # Data by months (only records with valid dates)
    # Use Python for grouping to avoid DB timezone issues
    monthly_sales = sales.filter(closing_date__isnull=False).select_related('manager', 'company')
    monthly_dict = {}
    for sale in monthly_sales:
        try:
            if sale.closing_date:
                month_key = sale.closing_date.strftime('%Y-%m')
                if month_key not in monthly_dict:
                    monthly_dict[month_key] = {
                        'total_sales': 0,
                        'total_salary': 0,
                        'count': 0
                    }
                monthly_dict[month_key]['total_sales'] += float(sale.sale or 0)
                monthly_dict[month_key]['total_salary'] += float(sale.salary or 0)
                monthly_dict[month_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    monthly_data = [
        {
            'month': month_key,
            'total_sales': float(data['total_sales']),
            'total_salary': float(data['total_salary']),
            'count': data['count']
        }
        for month_key, data in sorted(monthly_dict.items())[:12]
    ]
    
    # Data by expense types
    expense_type_stats = expenses.values('expense_type__name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:10]
    
    expense_type_data = [
        {
            'type': e['expense_type__name'],
            'total': float(e['total'] or 0),
            'count': e['count']
        }
        for e in expense_type_stats
    ]
    
    # Expense data by months (only records with valid dates)
    # Use Python for grouping to avoid DB timezone issues
    expense_monthly_list = expenses.filter(expense_date__isnull=False).select_related('employee', 'expense_type')
    expense_monthly_dict = {}
    for expense in expense_monthly_list:
        try:
            if expense.expense_date:
                month_key = expense.expense_date.strftime('%Y-%m')
                if month_key not in expense_monthly_dict:
                    expense_monthly_dict[month_key] = {
                        'total': 0,
                        'count': 0
                    }
                expense_monthly_dict[month_key]['total'] += float(expense.amount or 0)
                expense_monthly_dict[month_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    expense_monthly_data = [
        {
            'month': month_key,
            'total': float(data['total']),
            'count': data['count']
        }
        for month_key, data in sorted(expense_monthly_dict.items())[:12]
    ]
    
    # Expense data by employees
    expense_employee_stats = expenses.values('employee__name').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')[:10]
    
    expense_employee_data = [
        {
            'employee': e['employee__name'],
            'total': float(e['total'] or 0),
            'count': e['count']
        }
        for e in expense_employee_stats
    ]
    
    # Data by companies (ALL companies, without limits)
    company_stats = sales.values('company__title').annotate(
        total_sales=Sum('sale'),
        total_salary=Sum('salary'),
        count=Count('id')
    ).order_by('-total_sales')  # All companies by total sales
    
    company_data = [
        {
            'company': c['company__title'] or gettext_lazy("No company"),
            'total_sales': float(c['total_sales'] or 0),
            'total_salary': float(c['total_salary'] or 0),
            'count': c['count']
        }
        for c in company_stats
    ]
    
    # Also sort by deal count (top 10 for quick access)
    company_by_count = sorted(company_data, key=lambda x: x['count'], reverse=True)[:10]
    
    # Detailed sales data by managers and months (for answering specific questions)
    month_names_ru = get_months()
    # Data by managers and months (using Python for grouping)
    manager_monthly_sales = sales.filter(closing_date__isnull=False).select_related('manager', 'company')
    manager_monthly_dict = {}
    for sale in manager_monthly_sales:
        try:
            if sale.closing_date and sale.manager:
                manager_name = f"{sale.manager.last_name or ''} {sale.manager.name or ''}".strip()
                month_key = sale.closing_date.strftime('%Y-%m')
                dict_key = f"{manager_name}|{month_key}"
                
                if dict_key not in manager_monthly_dict:
                    manager_monthly_dict[dict_key] = {
                        'manager': manager_name,
                        'month': month_key,
                        'month_name_ru': f"{month_names_ru.get(sale.closing_date.month, '')} {sale.closing_date.year}".strip(),
                        'total_sales': 0,
                        'total_salary': 0,
                        'count': 0
                    }
                manager_monthly_dict[dict_key]['total_sales'] += float(sale.sale or 0)
                manager_monthly_dict[dict_key]['total_salary'] += float(sale.salary or 0)
                manager_monthly_dict[dict_key]['count'] += 1
        except (AttributeError, ValueError, TypeError):
            continue
    
    # Sort by manager and month
    manager_monthly_data = [
        {
            'manager': data['manager'],
            'month': data['month'],
            'month_name_ru': data['month_name_ru'],
            'total_sales': float(data['total_sales']),
            'total_salary': float(data['total_salary']),
            'count': data['count']
        }
        for dict_key, data in sorted(manager_monthly_dict.items(), key=lambda x: (x[1]['manager'], x[1]['month']))
    ]
    
    # Detailed sales data (limited to 50 to avoid prompt overload)
    detailed_sales = sales.select_related('manager', 'company').order_by('-closing_date', '-id')[:50]
    detailed_sales_data = []
    for sale in detailed_sales:
        sale_data = {
            'id': sale.id,  # type: ignore[reportAttributeAccessIssue]
            'id_number': sale.id_number,  # Invoice (ID number)
            'manager': f"{sale.manager.last_name if sale.manager else ''} {sale.manager.name if sale.manager else ''}".strip(),
            'manager_id': sale.manager.user_id if sale.manager else None,
            'company': sale.company.title if sale.company else '',
            'company_id': sale.company.company_id if sale.company else None,
            'sale': float(sale.sale or 0),  # Sale amount
            'salary': float(sale.salary or 0),  # Salary
            'account_number': sale.account_number,  # Account number
            'closing_date': sale.closing_date.strftime('%Y-%m-%d') if sale.closing_date else '',
            'closing_date_formatted': sale.closing_date.strftime('%d.%m.%Y') if sale.closing_date else '',  # Example: "15.07.2025"
            'title': sale.title  # Deal title
        }
        # Add Russian month name for better matching
        if sale.closing_date:
            month_ru = month_names_ru.get(sale.closing_date.month, '')
            sale_data['month_name_ru'] = f"{month_ru} {sale.closing_date.year}" if month_ru else ''
            sale_data['month'] = sale.closing_date.strftime('%Y-%m')
        else:
            sale_data['month_name_ru'] = ''
            sale_data['month'] = ''
        detailed_sales_data.append(sale_data)
    
    # All managers with all fields
    all_managers = CrmUser.objects.all()
    all_managers_data = []
    for manager in all_managers:
        all_managers_data.append({
            'id': manager.id,  # type: ignore[reportAttributeAccessIssue]
            'user_id': manager.user_id,
            'name': manager.name,
            'last_name': manager.last_name,
            'full_name': f"{manager.last_name} {manager.name}".strip(),
            'is_admin': manager.is_admin
        })
    
    # All companies with all fields
    all_companies = Company.objects.all()
    all_companies_data = []
    for company in all_companies:
        all_companies_data.append({
            'id': company.id,  # type: ignore[reportAttributeAccessIssue]
            'company_id': company.company_id,
            'title': company.title
        })
    
    # All salary payments (detailed data, limited to 50)
    all_salary_payments = salary_payments.select_related('manager').order_by('-payment_datetime')[:50]
    all_salary_payments_data = []
    for payment in all_salary_payments:
        try:
            if payment.payment_datetime:
                payment_datetime_str = payment.payment_datetime.strftime('%Y-%m-%d %H:%M:%S')
                payment_date_str = payment.payment_datetime.strftime('%Y-%m-%d')
                payment_date_formatted_str = payment.payment_datetime.strftime('%d.%m.%Y')
                year = payment.payment_datetime.year
                month = payment.payment_datetime.month
                month_name_ru = month_names_ru.get(month, '')
            else:
                payment_datetime_str = ''
                payment_date_str = ''
                payment_date_formatted_str = ''
                year = None
                month = None
                month_name_ru = ''
        except (AttributeError, ValueError, TypeError):
            payment_datetime_str = ''
            payment_date_str = ''
            payment_date_formatted_str = ''
            year = None
            month = None
            month_name_ru = ''
        
        all_salary_payments_data.append({
            'id': payment.id,  # type: ignore[reportAttributeAccessIssue]
            'manager': f"{payment.manager.last_name if payment.manager else ''} {payment.manager.name if payment.manager else ''}".strip(),
            'manager_id': payment.manager.user_id if payment.manager else None,
            'amount': float(payment.amount or 0),
            'payment_datetime': payment_datetime_str,
            'payment_date': payment_date_str,
            'payment_date_formatted': payment_date_formatted_str,
            'year': year,
            'month': month,
            'month_name_ru': month_name_ru
        })
    
    # All expenses (detailed data, limited to 50, only with valid dates)
    all_expenses = expenses.filter(
        expense_date__isnull=False
    ).select_related('employee', 'expense_type').order_by('-expense_date')[:50]
    all_expenses_data = []
    for expense in all_expenses:
        try:
            if expense.expense_date:
                expense_date_str = expense.expense_date.strftime('%Y-%m-%d %H:%M:%S')
                expense_date_formatted_str = expense.expense_date.strftime('%d.%m.%Y')
                year = expense.expense_date.year
                month = expense.expense_date.month
                month_name_ru = month_names_ru.get(month, '')
            else:
                expense_date_str = ''
                expense_date_formatted_str = ''
                year = None
                month = None
                month_name_ru = ''
        except (AttributeError, ValueError, TypeError):
            expense_date_str = ''
            expense_date_formatted_str = ''
            year = None
            month = None
            month_name_ru = ''
        
        all_expenses_data.append({
            'id': expense.id,  # type: ignore[reportAttributeAccessIssue]
            'employee': expense.employee.name if expense.employee else '',
            'expense_type': expense.expense_type.name if expense.expense_type else '',
            'amount': float(expense.amount or 0),
            'expense_date': expense_date_str,
            'expense_date_formatted': expense_date_formatted_str,
            'year': year,
            'month': month,
            'month_name_ru': month_name_ru,
            'comment': expense.comment or ''
        })
    
    # All employees
    all_employees = Employee.objects.all()
    all_employees_data = [{'id': emp.id,  # type: ignore[reportAttributeAccessIssue]
                           'name': emp.name} for emp in all_employees]
    
    # All expense types
    all_expense_types = ExpenseType.objects.all()
    all_expense_types_data = [{'id': et.id,  # type: ignore[reportAttributeAccessIssue]
                               'name': et.name} for et in all_expense_types]
    
    # Build the summary
    summary = {
        'summary': {
            'total_sales': float(total_sales),
            'total_salary': float(total_salary),
            'total_salary_paid': float(total_salary_paid),
            'salary_left': float(total_salary - total_salary_paid),
            'total_expenses': float(total_expenses),
            'sales_count': sales_count,
            'payments_count': payments_count,
            'expenses_count': expenses_count,
            'avg_sale': float(avg_sale),
            'avg_salary': float(avg_salary),
            'avg_expense': float(avg_expense),
            'expenses_to_sales_ratio': float(total_expenses / total_sales * 100) if total_sales > 0 else 0,
        },
        'managers': manager_data,  # Top managers by sales
        'all_managers': all_managers_data,  # ALL managers with all fields (id, user_id, name, last_name, is_admin)
        'monthly': monthly_data,
        'manager_monthly': manager_monthly_data,  # Detailed data by managers and months
        'detailed_sales': detailed_sales_data,  # Detailed sales data (id, id_number, account_number, title, etc.)
        'expense_types': expense_type_data,  # Top expense types
        'expense_monthly': expense_monthly_data,  # Expenses by months
        'expense_employees': expense_employee_data,  # Expenses by employees
        'all_expense_types': all_expense_types_data,  # ALL expense types
        'companies': company_data,  # Top companies by total sales
        'companies_by_count': company_by_count,  # Top companies by number of deals
        'all_companies': all_companies_data,  # ALL companies with all fields (id, company_id, title)
        'all_salary_payments': all_salary_payments_data,  # ALL salary payments (id, manager, amount, payment_datetime)
        'all_expenses': all_expenses_data,  # ALL expenses (id, employee, expense_type, amount, expense_date, comment)
        'all_employees': all_employees_data,  # ALL employees
        'period': {
            'filter_type': fp['filter_type'],
            'year': fp['year_param'],
            'effective_year': meta.get('effective_year'),
            'month': eff_month,
            'month_from_request': fp['month'],
            'compare_widened_month_to_full_year': compare_widened,
            'date_from': fp['date_from'],
            'date_to': fp['date_to'],
            'manager_id': fp['manager_id'],
        }
    }
    
    return summary
