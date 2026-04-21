"""
Shared helpers for salary_app: months, current CRM user, amount normalization.
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from django.utils import timezone
from django.utils.translation import gettext as _

from django.db.models import QuerySet

from .models import CrmUser
from .ai_query_lexicon import MONTH_ALIASES


def get_months():
    """Map month number -> localized name (via Django gettext)."""
    return {
        1: _('Январь'), 2: _('Февраль'), 3: _('Март'), 4: _('Апрель'),
        5: _('Май'), 6: _('Июнь'), 7: _('Июль'), 8: _('Август'),
        9: _('Сентябрь'), 10: _('Октябрь'), 11: _('Ноябрь'), 12: _('Декабрь'),
    }


def get_current_crm_user(request):
    """
    Return (current_user, is_admin) for request.user.
    current_user is CrmUser or None; is_admin is bool.
    """
    if not request.user.is_authenticated:
        return None, False
    try:
        current_user = CrmUser.objects.get(django_user=request.user)
        return current_user, bool(current_user.is_admin)
    except CrmUser.DoesNotExist:
        return None, False


def normalize_amount(value):
    """
    Normalize amount string: strip spaces (incl. NBSP), comma -> decimal point.
    """
    if value is None or not isinstance(value, str):
        return value
    return (
        value.replace(' ', '')
        .replace('\xa0', '')
        .replace('\u00a0', '')
        .replace('\u202f', '')
        .replace(',', '.')
    )

def get_month_date_range(year, month):
    """Return (start_date, end_date) for year/month in the active timezone."""
    tz = timezone.get_current_timezone()
    start_date = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end_date = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end_date = datetime(year, month + 1, 1, tzinfo=tz)
    return start_date, end_date

def parse_date_range(date_from: Optional[str], date_to: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not date_from or not date_to:
        return None, None
    try:
        date_start_naive = datetime.strptime(date_from, "%Y-%m-%d")
        date_end_naive = datetime.strptime(date_to, "%Y-%m-%d")
        tz = timezone.get_current_timezone()
        date_start = timezone.make_aware(date_start_naive, tz)
        date_end = timezone.make_aware(
            datetime.combine(date_end_naive, datetime.max.time()), tz
        )
        return date_start, date_end
    except ValueError:
        return None, None


def compare_question_suggests_multiple_months(question: str) -> bool:
    """True if the question names at least two distinct months (RU/UK/EN) — widens the date slice."""
    if not (question or "").strip():
        return False
    q = question.lower()
    found: set[int] = set()
    for num, keys in MONTH_ALIASES:
        if any(k in q for k in keys):
            found.add(num)
    return len(found) >= 2


def apply_dashboard_filters(
    sales: QuerySet,
    salary_qs: QuerySet,
    expenses_qs: QuerySet,
    *,
    is_admin: bool,
    current_user: Optional[CrmUser],
    manager_id: Optional[str],
    month: Optional[str],
    year_param: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    filter_type: str,
) -> Tuple[QuerySet, QuerySet, QuerySet, Dict[str, Any]]:
    """
    Same manager/date filters as the main dashboard (sales_list):
    staff see only their sales/payouts; admins see all or the selected manager_id;
    default year is current if year is omitted.
    """
    if not is_admin and current_user:
        sales = sales.filter(manager=current_user)
        salary_qs = salary_qs.filter(manager=current_user)
    elif manager_id:
        sales = sales.filter(manager_id=manager_id)
        salary_qs = salary_qs.filter(manager_id=manager_id)

    current_year = timezone.now().year
    selected_year = year_param
    if year_param is None:
        selected_year = str(current_year)

    meta: Dict[str, Any] = {
        "filter_type": filter_type,
        "year_request": year_param,
        "effective_year": selected_year,
        "month": month,
        "date_from": date_from,
        "date_to": date_to,
        "manager_id": manager_id,
    }

    if filter_type == "date_range":
        date_start, date_end = parse_date_range(date_from, date_to)
        if date_start and date_end:
            sales = sales.filter(closing_date__range=(date_start.date(), date_end.date()))
            salary_qs = salary_qs.filter(
                payment_datetime__gte=date_start,
                payment_datetime__lte=date_end,
            )
    else:
        if selected_year:
            try:
                year_int = int(selected_year)
                sales = sales.filter(closing_date__year=year_int)
                if month:
                    month_int = int(month)
                    sales = sales.filter(closing_date__month=month_int)
                    start_date, end_date = get_month_date_range(year_int, month_int)
                    salary_qs = salary_qs.filter(
                        payment_datetime__gte=start_date,
                        payment_datetime__lt=end_date,
                    )
                else:
                    salary_qs = salary_qs.filter(payment_datetime__year=year_int)
            except (ValueError, TypeError):
                selected_year = ""
                meta["effective_year"] = ""
        elif month:
            try:
                month_int = int(month)
                sales = sales.filter(closing_date__month=month_int)
                salary_qs = salary_qs.filter(payment_datetime__month=month_int)
            except (ValueError, TypeError):
                pass

    expenses_qs = expenses_qs.filter(expense_date__isnull=False)
    if filter_type == "date_range":
        date_start, date_end = parse_date_range(date_from, date_to)
        if date_start and date_end:
            expenses_qs = expenses_qs.filter(
                expense_date__gte=date_start,
                expense_date__lte=date_end,
            )
    else:
        if selected_year:
            try:
                year_int = int(selected_year)
                if month:
                    month_int = int(month)
                    start_date, end_date = get_month_date_range(year_int, month_int)
                    expenses_qs = expenses_qs.filter(
                        expense_date__gte=start_date,
                        expense_date__lt=end_date,
                    )
                else:
                    expenses_qs = expenses_qs.filter(expense_date__year=year_int)
            except (ValueError, TypeError):
                pass
        elif month:
            try:
                month_int = int(month)
                expenses_qs = expenses_qs.filter(expense_date__month=month_int)
            except (ValueError, TypeError):
                pass

    meta["effective_year"] = selected_year
    return sales, salary_qs, expenses_qs, meta


def _norm_header(h: Any) -> str:
    return str(h or "").strip().lower()


def _is_list_of_dicts(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def normalize_executor_result_for_table(data: Any) -> Any:
    """
    If the LLM puts a sectioned dict in ``result`` (monthly_totals, top_deals, …),
    ``format_data_as_table`` would otherwise emit Key/Value repr rows and break the UI.
    For month compares, return the summary list of dicts instead.
    """
    if not isinstance(data, dict):
        return data
    if "headers" in data and "rows" in data:
        return data

    preferred_keys = (
        "monthly_totals",
        "summaries",
        "month_summaries",
        "compare_summary",
        "summary",
        "totals_by_month",
        "rows",
        "data",
        "items",
        "result",
    )
    for key in preferred_keys:
        v = data.get(key)
        if _is_list_of_dicts(v):
            return v

    for _k, v in data.items():
        if _is_list_of_dicts(v):
            return v

    return data


def _metric_column_indices(headers: List[Any]) -> Dict[str, Optional[int]]:
    """Column indices for two-month compare summary (RU/UK/EN header text)."""
    out: Dict[str, Optional[int]] = {"total": None, "deals": None, "avg": None, "max": None}
    for i, h in enumerate(headers):
        s = _norm_header(h)
        if out["total"] is None and (
            ("общ" in s and "продаж" in s)
            or ("объем" in s and "продаж" in s)
            or ("об'єм" in s and "продаж" in s)
            or ("total" in s and "sale" in s)
            or ("всього" in s and "продаж" in s)
            or ("загальн" in s and "продаж" in s)
        ):
            out["total"] = i
        if out["deals"] is None and (
            ("количество" in s and "сдел" in s)
            or ("кількість" in s and "угод" in s)
            or ("deals" in s and "count" in s)
            or ("deal_count" in s.replace(" ", ""))
        ):
            out["deals"] = i
        if out["avg"] is None and (
            ("средн" in s and "сдел" in s)
            or ("average" in s and "deal" in s)
            or ("середн" in s)
        ):
            out["avg"] = i
        if out["max"] is None and (
            ("макс" in s and "сдел" in s)
            or ("max" in s and "deal" in s)
            or ("найбільш" in s)
        ):
            out["max"] = i
    return out


def prune_sparse_ai_table_rows(table_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Drop rows that are mostly empty (common junk in month compares: month label only, no figures).
    """
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if not headers or not rows:
        return table_data
    n = len(headers)
    need = max(2, (n * 3 + 3) // 4)  # ceil(0.75 * n); e.g. n=5 -> 4
    new_rows: List[List[Any]] = []
    for row in rows[:500]:
        cells = list(row)[:n] + [""] * (n - len(row))
        non_empty = sum(1 for c in cells if str(c).strip() != "")
        if non_empty >= need:
            new_rows.append(cells)
    if not new_rows:
        return table_data
    out = dict(table_data)
    out["rows"] = new_rows
    return out


def _two_row_compare_metrics_for_placeholders(table_data: Dict[str, Any]) -> Optional[Tuple[str, ...]]:
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if len(rows) < 2:
        return None
    idx = _metric_column_indices(headers)
    if idx["total"] is None or idx["deals"] is None:
        return None

    def cell(row: List[Any], col: Optional[int]) -> str:
        if col is None or col >= len(row):
            return ""
        return str(row[col]).strip()

    r0, r1 = rows[0], rows[1]
    tot_i, dea_i = idx["total"], idx["deals"]
    av_i, mx_i = idx["avg"], idx["max"]
    return (
        cell(r0, tot_i),
        cell(r1, tot_i),
        cell(r0, dea_i),
        cell(r1, dea_i),
        cell(r0, av_i),
        cell(r1, av_i),
        cell(r0, mx_i),
        cell(r1, mx_i),
    )


# Placeholder letters in the usual two-month-summary order.
_PLACEHOLDER_LETTERS = "XYABCDEF"


def _fill_one_month_metric_blanks(s: str, total: str, deals: str, avg: str, maxd: str) -> str:
    """Fill one RU compare block (total / deals / avg / max) when values were left blank."""
    s = re.sub(r"(составила)\s*,", rf"\1 {total},", s, count=1, flags=re.I)
    s = re.sub(r"(количество\s+сделок\s*[—–-])\s*,", rf"\1 {deals},", s, count=1, flags=re.I)
    s = re.sub(r"(средняя\s+сделка\s*[—–-])\s*,", rf"\1 {avg},", s, count=1, flags=re.I)
    s = re.sub(r"(максимальная\s+сделка\s*[—–-])\s*\.", rf"\1 {maxd}.", s, count=1, flags=re.I)
    return s


def _fill_empty_russian_compare_slots(text: str, vals: Tuple[str, ...]) -> str:
    """Insert numbers when the model left blanks after typical RU compare phrases."""
    if len(vals) < 8:
        return text
    t0, t1, d0, d1, a0, a1, m0, m1 = vals
    out = _fill_one_month_metric_blanks(text, t0, d0, a0, m0)
    out = _fill_one_month_metric_blanks(out, t1, d1, a1, m1)
    return out


def _fill_square_bracket_metric_labels(text: str, vals: Tuple[str, ...]) -> str:
    """
    Replace patterns like [Total sales May], [Deals count November], … with values
    from the first two summary rows (typical order: earlier month then later month).
    """
    if len(vals) < 8 or "[" not in text:
        return text
    t0, t1, d0, d1, a0, a1, m0, m1 = vals
    # First month row 0, second row 1 (models often say May / November).
    month_a = r"(?:May|май|Май|мая|MAY)"
    month_b = r"(?:November|ноябр|Ноябр|NOV|Nov)"
    pairs: List[Tuple[str, str]] = [
        (rf"\[\s*Total sales[^\]]*?{month_a}[^\]]*?\]", t0),
        (rf"\[\s*Deals count[^\]]*?{month_a}[^\]]*?\]", d0),
        (rf"\[\s*Average deal[^\]]*?{month_a}[^\]]*?\]", a0),
        (rf"\[\s*Max deal[^\]]*?{month_a}[^\]]*?\]", m0),
        (rf"\[\s*Total sales[^\]]*?{month_b}[^\]]*?\]", t1),
        (rf"\[\s*Deals count[^\]]*?{month_b}[^\]]*?\]", d1),
        (rf"\[\s*Average deal[^\]]*?{month_b}[^\]]*?\]", a1),
        (rf"\[\s*Max deal[^\]]*?{month_b}[^\]]*?\]", m1),
    ]
    out = text
    for pat, val in pairs:
        if not val:
            continue
        out = re.sub(pat, val, out, flags=re.I)
    return out


def _fill_vstavyty_ua_placeholders(text: str, vals: Tuple[str, ...]) -> str:
    """
    UA editor placeholders, often in pairs per month:
    [вставити значення], [вставити кількість] → total/deals for row0, then row1.
    """
    if len(vals) < 4 or "[" not in text:
        return text
    t0, t1, d0, d1 = vals[0], vals[1], vals[2], vals[3]
    value_pat = re.compile(
        r"\[\s*вставити\s+значенн\w*\s*\]"
        r"|\[\s*insert\s+value\s*\]",
        flags=re.I,
    )
    count_pat = re.compile(
        r"\[\s*вставити\s+кількість\w*\s*\]"
        r"|\[\s*insert\s+(?:the\s+)?(?:deal\s+)?count\s*\]",
        flags=re.I,
    )
    out = text
    if value_pat.search(out):
        vi = iter([t0, t1])
        out = value_pat.sub(lambda m: next(vi, m.group(0)), out)
    if count_pat.search(out):
        ci = iter([d0, d1])
        out = count_pat.sub(lambda m: next(ci, m.group(0)), out)
    return out


def _fill_db_value_placeholders(text: str, vals: Tuple[str, ...]) -> str:
    """
    Fill [value from database]-style placeholders (RU/UK) in model text.
    Usually four placeholders: total/deals for each of two months.
    """
    if len(vals) < 8:
        return text
    # Full and truncated forms: RU/UK «value from DB» bracket placeholders.
    generic_placeholder_re = re.compile(
        r"\[\s*знач[^\]\s]*(?:\s+[^\]\s]+){0,4}\s*\]",
        flags=re.I,
    )
    matches = [
        m
        for m in generic_placeholder_re.finditer(text)
        if re.search(r"\b(?:из|з)\b", m.group(0), flags=re.I)
    ]
    if not matches:
        return text

    t0, t1, d0, d1, a0, a1, m0, m1 = vals
    replacement_seq: List[str]
    if len(matches) == 4:
        replacement_seq = [t0, d0, t1, d1]
    elif len(matches) == 8:
        replacement_seq = [t0, d0, a0, m0, t1, d1, a1, m1]
    else:
        replacement_seq = [t0, d0, a0, m0, t1, d1, a1, m1]

    out_parts: List[str] = []
    pos = 0
    for i, m in enumerate(matches):
        out_parts.append(text[pos:m.start()])
        val = replacement_seq[i] if i < len(replacement_seq) else replacement_seq[-1]
        out_parts.append(val)
        pos = m.end()
    out_parts.append(text[pos:])
    return "".join(out_parts)


def fill_compare_placeholders_in_text(text: str, table_data: Optional[Dict[str, Any]]) -> str:
    """
    Replace X,Y,… placeholder letters with numbers from the first two table rows when columns match.
    Also fills typical RU/UK compare prose blanks and bracket placeholders.
    """
    if not text or not table_data:
        return text
    vals = _two_row_compare_metrics_for_placeholders(table_data)
    if not vals:
        return text
    out = text
    if re.search(
        r"(?<![A-Za-zА-Яа-яІіЇїЄєҐґ])([XYABCDEF])(?![A-Za-z0-9А-Яа-яІіЇїЄєҐґ])",
        text,
    ):
        for letter, val in zip(_PLACEHOLDER_LETTERS, vals):
            if not val:
                continue
            out = re.sub(
                rf"(?<![A-Za-zА-Яа-яІіЇїЄєҐґ]){letter}(?![A-Za-z0-9А-Яа-яІіЇїЄєҐґ])",
                val,
                out,
                count=1,
            )
    out = _fill_empty_russian_compare_slots(out, vals)
    out = _fill_square_bracket_metric_labels(out, vals)
    out = _fill_db_value_placeholders(out, vals)
    out = _fill_vstavyty_ua_placeholders(out, vals)
    return out


def _is_compare_intent_question(question: str) -> bool:
    q = (question or "").lower()
    keys = (
        "сравн",
        "порівня",
        "compare",
        "comparison",
        " vs ",
        " vs.",
        "проти",
        "різниц",
        "разниц",
    )
    return any(q.find(k) >= 0 for k in keys)


def _is_manager_breakdown_requested(question: str) -> bool:
    """User asked for per-manager breakdown — do not replace with a 2-row month-only summary."""
    q = (question or "").lower()
    return any(
        k in q
        for k in (
            "менеджер",
            "по менедж",
            "manager",
            "managers",
            "кожним менедж",
            "співробітник",
        )
    )


def question_requires_code_execution(question: str) -> bool:
    """
    Questions that should be answered with executable ```python``` returning ORM ``result``.
    If the model returns prose only, callers may retry once with a stronger reminder.
    """
    q = (question or "").lower().strip()
    if not q:
        return False
    conceptual_only = (
        ("что такое" in q or "що таке" in q or "what is " in q[:50] or "define " in q[:50])
        and not _is_compare_intent_question(question)
        and not _is_manager_breakdown_requested(question)
        and not any(
            k in q
            for k in (
                "продаж",
                "sale",
                "сдел",
                "deal",
                "выручк",
                "менеджер",
                "manager",
            )
        )
    )
    if conceptual_only:
        return False
    if _is_compare_intent_question(question):
        return True
    if _is_manager_breakdown_requested(question):
        return True
    data_keys = (
        "продаж",
        "sale",
        "сделок",
        "сделк",
        "deal",
        "выручк",
        "revenue",
        "сколько",
        "сумм",
        "total",
        "топ",
        "рейтинг",
        "rating",
        "по компан",
        "by company",
        "количеств",
        "кількість",
        "aggreg",
        "групп",
        "розбив",
        "breakdown",
    )
    return any(k in q for k in data_keys)


def _month_label_column_index(headers: List[Any]) -> int:
    for i, h in enumerate(headers):
        s = _norm_header(h)
        if "месяц" in s or "month" in s or "місяць" in s:
            return i
    return 0


def _parse_scalar_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = normalize_amount(s) if isinstance(s, str) else s
    if not isinstance(s, str):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _build_ru_grounded_compare_analysis(table_data: Dict[str, Any], vals: Tuple[str, ...]) -> str:
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if len(rows) < 2 or len(vals) < 8:
        return ""
    mi = _month_label_column_index(headers)
    l0 = str(rows[0][mi]).strip() if mi < len(rows[0]) else ""
    l1 = str(rows[1][mi]).strip() if mi < len(rows[1]) else ""
    if not l0:
        l0 = "Период 1"
    if not l1:
        l1 = "Период 2"
    t0, t1, d0, d1, a0, a1, m0, m1 = vals
    f0, f1 = _parse_scalar_float(t0), _parse_scalar_float(t1)
    trend = ""
    if f0 is not None and f1 is not None:
        if abs(f1) < 1e-9:
            trend = "Второй период в таблице имеет нулевую (или почти нулевую) сумму — процентное сравнение не считаем."
        else:
            diff = f0 - f1
            pct = (diff / f1) * 100.0
            if diff > 1e-6:
                trend = (
                    f"**Итог по объёму продаж:** за **{l0}** выручка **выше**, чем за **{l1}**, "
                    f"на **{abs(diff):,.2f}** (~**{abs(pct):.1f}%** от объёма второго периода)."
                )
            elif diff < -1e-6:
                trend = (
                    f"**Итог по объёму продаж:** за **{l0}** выручка **ниже**, чем за **{l1}**, "
                    f"на **{abs(diff):,.2f}** (~**{abs(pct):.1f}%** от объёма второго периода)."
                )
            else:
                trend = "**Итог по объёму продаж:** суммы за оба периода в таблице совпадают."
    def period_line(label: str, t: str, d: str, a: str, mx: str) -> str:
        parts = [f"общий объём продаж **{t}**", f"сделок — **{d}**"]
        if str(a).strip():
            parts.append(f"средняя сделка — **{a}**")
        if str(mx).strip():
            parts.append(f"макс. — **{mx}**")
        return f"- **{label}**: " + "; ".join(parts) + "."

    body = (
        f"Ниже — только значения из **таблицы** (без выводов модели с произвольными числами).\n\n"
        f"{period_line(l0, t0, d0, a0, m0)}\n"
        f"{period_line(l1, t1, d1, a1, m1)}\n\n"
        f"{trend}"
    )
    return body.strip()


def apply_table_grounded_analysis_for_compare(
    text: str,
    table_data: Optional[Dict[str, Any]],
    question: str,
) -> str:
    """
    For compare-style questions with exactly two summary rows: replace the model reply
    with a single grounded analysis markdown block (table-sourced figures only).
    """
    if not text or not table_data or not question:
        return text
    if not _is_compare_intent_question(question):
        return text
    if _is_manager_breakdown_requested(question):
        return text
    if len(table_data.get("rows") or []) != 2:
        return text
    vals = _two_row_compare_metrics_for_placeholders(table_data)
    if not vals:
        return text
    grounded = _build_ru_grounded_compare_analysis(table_data, vals)
    if not grounded:
        return text
    return f"### Анализ\n\n{grounded.strip()}\n"


def _manager_column_index(headers: List[Any]) -> int:
    for i, h in enumerate(headers):
        s = _norm_header(h)
        if "менедж" in s or "manager" in s or "керівник" in s:
            return i
    return 0


def table_data_supports_manager_month_compare(table_data: Optional[Dict[str, Any]]) -> bool:
    """Table has manager rows and sales/deal columns for two periods (e.g. May vs November)."""
    if not isinstance(table_data, dict):
        return False
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if len(headers) < 3 or len(rows) < 1:
        return False
    mgr_i = _manager_column_index(headers)
    return _resolve_manager_compare_column_map(headers, mgr_i) is not None


def _header_period_key(header: Any) -> Optional[str]:
    """Map column header substrings to compare period p0 or p1."""
    s = _norm_header(header)
    p0_markers = (
        "май",
        "мая",
        "має",
        "мае",
        "трав",
        "may",
        "2025-05",
        "-05-",
        ".05.",
        " за 5 ",
        " 05 ",
    )
    p1_markers = (
        "нояб",
        "листоп",
        "nov",
        "2025-11",
        "-11-",
        ".11.",
        " за 11 ",
        " 11 ",
    )
    if any(m in s for m in p0_markers):
        return "p0"
    if any(m in s for m in p1_markers):
        return "p1"
    return None


def _header_metric_kind(header: Any) -> str:
    s = _norm_header(header)
    if any(
        x in s
        for x in (
            "продаж",
            "sale",
            "выруч",
            "revenue",
            "объем",
            "об'єм",
            "обсяг",
            "volume",
        )
    ):
        return "sales"
    if any(
        x in s
        for x in (
            "сдел",
            "deal",
            "угод",
            "угід",
            "кільк",
            "count",
        )
    ):
        return "deals"
    return "unknown"


def _resolve_manager_compare_column_map(
    headers: List[Any], mgr_idx: int
) -> Optional[Dict[str, int]]:
    """Map p0_sales, p0_deals, p1_sales, p1_deals -> column indices."""
    mapping: Dict[str, int] = {}
    for j in range(len(headers)):
        if j == mgr_idx:
            continue
        period = _header_period_key(headers[j])
        kind = _header_metric_kind(headers[j])
        if period and kind in ("sales", "deals"):
            key = f"{period}_{kind}"
            if key not in mapping:
                mapping[key] = j
    required = ("p0_sales", "p0_deals", "p1_sales", "p1_deals")
    if all(k in mapping for k in required):
        return {k: mapping[k] for k in required}
    return None


def _fmt_grounded_money(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")





def _build_manager_compare_grounded_prose(table_data: Dict[str, Any], lang: str) -> str:
    """
    Short narrative derived only from table cells (manager rows, two periods).
    """
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if len(headers) < 3 or len(rows) < 1:
        return ""
    lang = (lang or "ru").split("-")[0].lower()
    if lang not in ("ru", "uk", "en"):
        lang = "ru"

    mgr_i = _manager_column_index(headers)
    cmap = _resolve_manager_compare_column_map(headers, mgr_i)
    if not cmap:
        return ""

    parsed: List[Tuple[str, float, int, float, int]] = []
    max_ci = max(cmap.values())
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) <= max_ci:
            continue
        name = str(row[mgr_i]).strip() or "—"
        s0 = _parse_scalar_float(row[cmap["p0_sales"]]) or 0.0
        d0f = _parse_scalar_float(row[cmap["p0_deals"]])
        s1 = _parse_scalar_float(row[cmap["p1_sales"]]) or 0.0
        d1f = _parse_scalar_float(row[cmap["p1_deals"]])
        d0 = int(round(d0f)) if d0f is not None else 0
        d1 = int(round(d1f)) if d1f is not None else 0
        parsed.append((name, s0, d0, s1, d1))

    if not parsed:
        return ""

    lbl0 = str(headers[cmap["p0_sales"]] or "").strip() or "Период 1"
    lbl1 = str(headers[cmap["p1_sales"]] or "").strip() or "Период 2"

    tot0 = sum(p[1] for p in parsed)
    tot1 = sum(p[3] for p in parsed)
    cnt0 = sum(p[2] for p in parsed)
    cnt1 = sum(p[4] for p in parsed)

    leader0 = max(parsed, key=lambda x: x[1])
    leader1 = max(parsed, key=lambda x: x[3])

    zero_second = [p[0] for p in parsed if p[1] > 0 and p[3] == 0.0]
    drops = [(p[0], p[1] - p[3]) for p in parsed if p[1] > 0]
    best_drop = max(drops, key=lambda t: t[1]) if drops else None

    lines: List[str] = []
    if lang == "en":
        lines.append("Facts taken only from the table (names and numbers match the columns above).")
        lines.append(
            f"- **Total sales (all managers):** {lbl0} — **{_fmt_grounded_money(tot0)}**; "
            f"{lbl1} — **{_fmt_grounded_money(tot1)}**."
        )
        lines.append(f"- **Deals (all managers):** {lbl0} — **{cnt0}**; {lbl1} — **{cnt1}**.")
        lines.append(
            f"- **Top by sales in the first period:** **{leader0[0]}** — **{_fmt_grounded_money(leader0[1])}** "
            f"({leader0[2]} deals)."
        )
        lines.append(
            f"- **Top by sales in the second period:** **{leader1[0]}** — **{_fmt_grounded_money(leader1[3])}** "
            f"({leader1[4]} deals)."
        )
        if zero_second:
            lines.append(
                f"- **Managers with sales in the first period but 0 in the second:** "
                f"{', '.join(zero_second)}."
            )
        if best_drop and best_drop[1] > 0:
            lines.append(
                f"- **Largest drop (first minus second period, by table):** **{best_drop[0]}** "
                f"— **{_fmt_grounded_money(best_drop[1])}**."
            )
        if tot0 > tot1 + 1e-6:
            lines.append(
                f"- **Total sales in the table are lower in the second period than in the first** "
                f"(by **{_fmt_grounded_money(tot0 - tot1)}**)."
            )
        elif tot1 > tot0 + 1e-6:
            lines.append(
                f"- **Total sales in the table are higher in the second period than in the first** "
                f"(by **{_fmt_grounded_money(tot1 - tot0)}**)."
            )
        else:
            lines.append("- **Total sales for both periods in the table are equal (within rounding).**")
        return "\n".join(lines)

    if lang == "uk":
        lines.append("Лише факти з таблиці (прізвища та суми збігаються з колонками вище).")
        lines.append(
            f"- **Сума продажів (усі менеджери):** {lbl0} — **{_fmt_grounded_money(tot0)}**; "
            f"{lbl1} — **{_fmt_grounded_money(tot1)}**."
        )
        lines.append(f"- **Угод загалом:** {lbl0} — **{cnt0}**; {lbl1} — **{cnt1}**.")
        lines.append(
            f"- **Максимум продажів у першому періоді:** **{leader0[0]}** — **{_fmt_grounded_money(leader0[1])}** "
            f"({leader0[2]} угод)."
        )
        lines.append(
            f"- **Максимум продажів у другому періоді:** **{leader1[0]}** — **{_fmt_grounded_money(leader1[3])}** "
            f"({leader1[4]} угод)."
        )
        if zero_second:
            lines.append(
                f"- Менеджери з продажами в першому періоді та нулем у другому: "
                f"{', '.join('**' + n + '**' for n in zero_second)}."
            )
        if best_drop and best_drop[1] > 0:
            lines.append(
                f"- **Найбільше падіння продажів (перший мінус другий період за таблицею):** **{best_drop[0]}** "
                f"— **{_fmt_grounded_money(best_drop[1])}**."
            )
        if tot0 > tot1 + 1e-6:
            lines.append(
                f"- **Загальна сума продажів у таблиці в другому періоді нижча**, ніж у першому "
                f"(на **{_fmt_grounded_money(tot0 - tot1)}**)."
            )
        elif tot1 > tot0 + 1e-6:
            lines.append(
                f"- **Загальна сума продажів у таблиці в другому періоді вища**, ніж у першому "
                f"(на **{_fmt_grounded_money(tot1 - tot0)}**)."
            )
        else:
            lines.append("- **Загальні суми продажів за обидва періоди в таблиці збігаються (з урахуванням округлення).**")
        return "\n".join(lines)

    # ru
    lines.append("Только факты из таблицы (имена и суммы совпадают с колонками выше).")
    lines.append(
        f"- **Сумма продаж (все менеджеры):** {lbl0} — **{_fmt_grounded_money(tot0)}**; "
        f"{lbl1} — **{_fmt_grounded_money(tot1)}**."
    )
    lines.append(f"- **Сделок всего:** {lbl0} — **{cnt0}**; {lbl1} — **{cnt1}**.")
    lines.append(
        f"- **Максимум продаж в первом периоде:** **{leader0[0]}** — **{_fmt_grounded_money(leader0[1])}** "
        f"({leader0[2]} сделок)."
    )
    lines.append(
        f"- **Максимум продаж во втором периоде:** **{leader1[0]}** — **{_fmt_grounded_money(leader1[3])}** "
        f"({leader1[4]} сделок)."
    )
    if zero_second:
        lines.append(
            f"- Менеджеры с продажами в первом периоде и нулём во втором: "
            f"{', '.join('**' + n + '**' for n in zero_second)}."
        )
    if best_drop and best_drop[1] > 0:
        lines.append(
            f"- **Наибольшее падение продаж (первый минус второй период по таблице):** **{best_drop[0]}** "
            f"— **{_fmt_grounded_money(best_drop[1])}**."
        )
    if tot0 > tot1 + 1e-6:
        lines.append(
            f"- **Совокупные продажи по таблице во втором периоде ниже**, чем в первом "
            f"(на **{_fmt_grounded_money(tot0 - tot1)}**)."
        )
    elif tot1 > tot0 + 1e-6:
        lines.append(
            f"- **Совокупные продажи по таблице во втором периоде выше**, чем в первом "
            f"(на **{_fmt_grounded_money(tot1 - tot0)}**)."
        )
    else:
        lines.append("- **Совокупные суммы продаж за оба периода в таблице совпадают (с учётом округления).**")
    return "\n".join(lines)


def apply_table_grounded_analysis_for_manager_compare(
    text: str,
    table_data: Optional[Dict[str, Any]],
    question: str,
    lang: str = "ru",
) -> str:
    """
    For compare + per-manager breakdown: drop hallucinated prose under the table;
    replace with a short analysis where every figure comes from table rows.
    """
    if not text or not table_data or not question:
        return text
    if not _is_compare_intent_question(question) or not _is_manager_breakdown_requested(question):
        return text
    rows = table_data.get("rows") or []
    if len(rows) < 1:
        return text
    grounded = _build_manager_compare_grounded_prose(table_data, lang)
    if not grounded:
        # If we cannot confidently map a real two-period schema, keep model text
        # instead of producing a misleading "period 1/2" grounded summary.
        return text
    return f"### Анализ\n\n{grounded.strip()}\n"
