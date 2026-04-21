"""
Server-side analytics tools for AI analysis (OpenAI-style function calling).

All queries run on the filtered QuerySets passed from the dashboard — the same
slice as _get_data_summary / _get_filtered_querysets.
"""
from __future__ import annotations

import calendar
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Avg, Count, Max, QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils.translation import gettext as _

from .utils import get_months

logger = logging.getLogger(__name__)

MAX_AGG_GROUPS = 200
MAX_LIST_ROWS = 100
MAX_TOP_DEALS = 30


def _serialize_row(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (date, datetime)):
            out[k] = v.isoformat() if v else ""
        elif v is None:
            out[k] = ""
        else:
            out[k] = v
    return out


def format_data_as_table(data: Any) -> Dict[str, Any]:
    """Format tool / list-of-dicts output for the frontend (same contract as CodeExecutor)."""
    if data is None:
        return {"headers": [], "rows": [], "type": "empty"}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        headers = list(data[0].keys())
        rows = []
        for row in data:
            rows.append([_cell_str(row.get(h, "")) for h in headers])
        return {"headers": headers, "rows": rows, "type": "dict_list"}
    if isinstance(data, dict) and "headers" in data and "rows" in data:
        rows = data.get("rows") or []
        if rows and isinstance(rows[0], list):
            rows = [[_cell_str(c) for c in r] for r in rows]
        return {
            "headers": list(data.get("headers", [])),
            "rows": rows,
            "type": "structured",
        }
    return {
        "headers": ["Result"],
        "rows": [[_cell_str(data)]],
        "type": "simple",
    }


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{float(value):.2f}"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _dataset_qs(
    dataset: str, querysets: Dict[str, QuerySet]
) -> Tuple[Optional[QuerySet], Optional[str]]:
    key_map = {
        "sales": "sales_queryset",
        "expenses": "expenses_queryset",
        "salary_payments": "salary_payments_queryset",
    }
    qk = key_map.get(dataset)
    if not qk:
        return None, f"Unknown dataset: {dataset}"
    qs = querysets.get(qk)
    if qs is None:
        return None, "QuerySet not available"
    return qs, None


def _date_amount_fields(dataset: str) -> Tuple[str, str, bool]:
    if dataset == "sales":
        return "closing_date", "sale", False
    if dataset == "expenses":
        return "expense_date", "amount", False
    return "payment_datetime", "amount", True


def _resolve_sales_amount_field(raw: Optional[str]) -> str:
    """Which numeric column on Sale to aggregate: deal amount or per-deal salary/commission."""
    s = (raw or "sale").strip().lower()
    if s in ("salary", "deal_salary", "commission", "комис"):
        return "salary"
    return "sale"


def _apply_sales_company_filter(
    qs: QuerySet, dataset: str, company_name_contains: Optional[str]
) -> QuerySet:
    if dataset != "sales":
        return qs
    needle = (company_name_contains or "").strip()
    if not needle:
        return qs
    return qs.filter(company__title__icontains=needle)


def _apply_year_month(
    qs: QuerySet, date_field: str, year: Optional[int], months: Optional[List[int]], is_dt: bool
) -> QuerySet:
    if year is not None:
        qs = qs.filter(**{f"{date_field}__year": year})
    if months:
        m = [x for x in months if isinstance(x, int) and 1 <= x <= 12]
        if m:
            qs = qs.filter(**{f"{date_field}__month__in": m})
    return qs


def _parse_year_month_str(raw: Any) -> Optional[Tuple[int, List[int]]]:
    """Parse 'YYYY-MM', 'YYYY-M', or 'YYYYMM' → (year, [month])."""
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})\b", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1900 <= y <= 2100 and 1 <= mo <= 12:
            return (y, [mo])
    m2 = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m2:
        y, mo = int(m2.group(1)), int(m2.group(2))
        if 1900 <= y <= 2100 and 1 <= mo <= 12:
            return (y, [mo])
    return None


def _manager_label(row: Dict[str, Any]) -> str:
    ln = (row.get("manager__last_name") or "").strip()
    fn = (row.get("manager__name") or "").strip()
    return f"{ln} {fn}".strip() or "—"


class AnalysisToolSession:
    """Executes CRM analytics tools on filtered filter_querysets."""

    def __init__(self, querysets: Dict[str, Any]):
        self.querysets = querysets or {}

    def dispatch(self, name: str, arguments: Any) -> Dict[str, Any]:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as e:
                return {"ok": False, "error": f"Invalid JSON arguments: {e}"}
        if not isinstance(arguments, dict):
            arguments = {}

        handlers = {
            "crm_analytics_aggregate": self._aggregate,
            "crm_analytics_list": self._list_records,
            "crm_analytics_compare_months": self._compare_months,
        }
        fn = handlers.get(name)
        if not fn:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            out = fn(**arguments)
            return out
        except Exception as e:
            logger.exception("Tool %s failed: %s", name, e)
            return {"ok": False, "error": str(e)}

    def _aggregate(
        self,
        dataset: str,
        group_by: str = "none",
        year: Optional[int] = None,
        months: Optional[List[int]] = None,
        year_month: Optional[Any] = None,
        limit_groups: int = 100,
        company_name_contains: Optional[str] = None,
        sales_amount_field: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if kwargs:
            logger.debug(
                "crm_analytics_aggregate: ignoring extra parameters: %s",
                sorted(kwargs.keys()),
            )
        if year_month is not None:
            parsed = _parse_year_month_str(year_month)
            if parsed:
                year, months = parsed[0], list(parsed[1])

        qs, err = _dataset_qs(dataset, self.querysets)
        if err:
            return {"ok": False, "error": err, "rows": []}
        assert qs is not None
        date_field, amount_field, is_dt = _date_amount_fields(dataset)
        if dataset == "sales":
            amount_field = _resolve_sales_amount_field(sales_amount_field)
        qs = _apply_sales_company_filter(qs, dataset, company_name_contains)
        qs = _apply_year_month(qs, date_field, year, months, is_dt)

        lim = max(1, min(int(limit_groups or 100), MAX_AGG_GROUPS))

        if group_by == "none":
            qs2 = qs
            agg = qs2.aggregate(
                total_amount=Sum(amount_field),
                record_count=Count("id"),
                avg_amount=Avg(amount_field),
                max_amount=Max(amount_field),
            )
            row = {
                "total_amount": float(agg["total_amount"] or 0),
                "record_count": agg["record_count"],
                "avg_amount": float(agg["avg_amount"] or 0),
                "max_amount": float(agg["max_amount"] or 0),
            }
            return {"ok": True, "rows": [_serialize_row(row)]}

        if group_by == "year_month":
            qs2 = qs.filter(**{f"{date_field}__isnull": False})
            trunc = TruncMonth(date_field)
            grouped = (
                qs2.annotate(period=trunc)
                .values("period")
                .annotate(
                    total_amount=Sum(amount_field),
                    record_count=Count("id"),
                    avg_amount=Avg(amount_field),
                    max_amount=Max(amount_field),
                )
                .order_by("period")[:lim]
            )
            rows = []
            for g in grouped:
                p = g.get("period")
                label = p.strftime("%Y-%m") if p else ""
                rows.append(
                    _serialize_row(
                        {
                            "year_month": label,
                            "total_amount": float(g.get("total_amount") or 0),
                            "record_count": g.get("record_count", 0),
                            "avg_amount": float(g.get("avg_amount") or 0),
                            "max_amount": float(g.get("max_amount") or 0),
                        }
                    )
                )
            return {"ok": True, "rows": rows}

        if group_by == "manager" and dataset in ("sales", "salary_payments"):
            month_list = sorted(
                {x for x in (months or []) if isinstance(x, int) and 1 <= x <= 12}
            )
            # Two or more months + managers: cannot fold into one row — need a per-period pivot/summary.
            if dataset == "sales" and len(month_list) >= 2:
                return self._aggregate_sales_managers_pivot_months(
                    qs, date_field, amount_field, month_list, lim
                )

            qs2 = qs.filter(manager__isnull=False)
            grouped = (
                qs2.values("manager__last_name", "manager__name")
                .annotate(
                    total_amount=Sum(amount_field),
                    record_count=Count("id"),
                    avg_amount=Avg(amount_field),
                    max_amount=Max(amount_field),
                )
                .order_by("-total_amount")[:lim]
            )
            rows = []
            for g in grouped:
                rows.append(
                    _serialize_row(
                        {
                            "manager": _manager_label(g),
                            "total_amount": float(g.get("total_amount") or 0),
                            "record_count": g.get("record_count", 0),
                            "avg_amount": float(g.get("avg_amount") or 0),
                            "max_amount": float(g.get("max_amount") or 0),
                        }
                    )
                )
            return {"ok": True, "rows": rows}

        if group_by == "company" and dataset == "sales":
            grouped = (
                qs.filter(company__isnull=False)
                .values("company__title")
                .annotate(
                    total_amount=Sum(amount_field),
                    record_count=Count("id"),
                    avg_amount=Avg(amount_field),
                    max_amount=Max(amount_field),
                )
                .order_by("-total_amount")[:lim]
            )
            rows = []
            for g in grouped:
                rows.append(
                    _serialize_row(
                        {
                            "company": g.get("company__title") or "—",
                            "total_amount": float(g.get("total_amount") or 0),
                            "record_count": g.get("record_count", 0),
                            "avg_amount": float(g.get("avg_amount") or 0),
                            "max_amount": float(g.get("max_amount") or 0),
                        }
                    )
                )
            return {"ok": True, "rows": rows}

        if group_by == "expense_type" and dataset == "expenses":
            grouped = (
                qs.filter(expense_type__isnull=False)
                .values("expense_type__name")
                .annotate(
                    total_amount=Sum(amount_field),
                    record_count=Count("id"),
                    avg_amount=Avg(amount_field),
                    max_amount=Max(amount_field),
                )
                .order_by("-total_amount")[:lim]
            )
            rows = []
            for g in grouped:
                rows.append(
                    _serialize_row(
                        {
                            "expense_type": g.get("expense_type__name") or "—",
                            "total_amount": float(g.get("total_amount") or 0),
                            "record_count": g.get("record_count", 0),
                            "avg_amount": float(g.get("avg_amount") or 0),
                            "max_amount": float(g.get("max_amount") or 0),
                        }
                    )
                )
            return {"ok": True, "rows": rows}

        if group_by == "employee" and dataset == "expenses":
            grouped = (
                qs.filter(employee__isnull=False)
                .values("employee__name")
                .annotate(
                    total_amount=Sum(amount_field),
                    record_count=Count("id"),
                    avg_amount=Avg(amount_field),
                    max_amount=Max(amount_field),
                )
                .order_by("-total_amount")[:lim]
            )
            rows = []
            for g in grouped:
                rows.append(
                    _serialize_row(
                        {
                            "employee": g.get("employee__name") or "—",
                            "total_amount": float(g.get("total_amount") or 0),
                            "record_count": g.get("record_count", 0),
                            "avg_amount": float(g.get("avg_amount") or 0),
                            "max_amount": float(g.get("max_amount") or 0),
                        }
                    )
                )
            return {"ok": True, "rows": rows}

        return {"ok": False, "error": f"group_by '{group_by}' is not valid for dataset '{dataset}'", "rows": []}

    def _aggregate_sales_managers_pivot_months(
        self,
        qs: QuerySet,
        date_field: str,
        amount_field: str,
        months_use: List[int],
        lim: int,
    ) -> Dict[str, Any]:
        """Per-manager summary with separate sales/deal-count columns for each requested month."""
        months_sorted = sorted({m for m in months_use if isinstance(m, int) and 1 <= m <= 12})
        if len(months_sorted) < 2:
            return {"ok": False, "error": "sales manager pivot requires two month numbers", "rows": []}
        month_names = get_months()
        buckets: Dict[str, Dict[int, Dict[str, Any]]] = {}

        for m in months_sorted:
            mqs = (
                qs.filter(**{f"{date_field}__isnull": False})
                .filter(manager__isnull=False)
                .filter(**{f"{date_field}__month": m})
            )
            grouped = mqs.values("manager__last_name", "manager__name").annotate(
                total_amount=Sum(amount_field),
                record_count=Count("id"),
            )
            for g in grouped:
                name = _manager_label(g)
                buckets.setdefault(name, {})
                buckets[name][m] = {
                    "total_amount": float(g.get("total_amount") or 0),
                    "record_count": int(g.get("record_count") or 0),
                }

        def combined_total(nm: str) -> float:
            return sum(
                buckets[nm].get(mi, {}).get("total_amount", 0.0) or 0.0
                for mi in months_sorted
            )

        names = sorted(buckets.keys(), key=lambda n: -combined_total(n))[:lim]
        rows_out: List[Dict[str, Any]] = []
        sales_label = _("Salary") if amount_field == "salary" else _("Sales")
        deals_label = _("Deals")
        for name in names:
            row_d: Dict[str, Any] = {"manager": name}
            for m in months_sorted:
                lbl = str(month_names.get(m, m))
                cell = buckets[name].get(
                    m, {"total_amount": 0.0, "record_count": 0}
                )
                row_d[f"{sales_label} {lbl}"] = float(cell.get("total_amount") or 0)
                row_d[f"{deals_label} {lbl}"] = int(cell.get("record_count") or 0)
            rows_out.append(_serialize_row(row_d))
        return {"ok": True, "rows": rows_out}

    def _list_records(
        self,
        dataset: str,
        limit: int = 25,
        sort: str = "date_desc",
        year: Optional[int] = None,
        months: Optional[List[int]] = None,
        year_month: Optional[Any] = None,
        company_name_contains: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if kwargs:
            logger.debug(
                "crm_analytics_list: ignoring extra parameters: %s",
                sorted(kwargs.keys()),
            )
        if year_month is not None:
            parsed = _parse_year_month_str(year_month)
            if parsed:
                year, months = parsed[0], list(parsed[1])

        qs, err = _dataset_qs(dataset, self.querysets)
        if err:
            return {"ok": False, "error": err, "rows": []}
        assert qs is not None
        date_field, amount_field, is_dt = _date_amount_fields(dataset)
        qs = _apply_sales_company_filter(qs, dataset, company_name_contains)
        qs = _apply_year_month(qs, date_field, year, months, is_dt)
        lim = max(1, min(int(limit or 25), MAX_LIST_ROWS))

        if sort == "amount_desc":
            qs = qs.order_by(f"-{amount_field}")
        else:
            qs = qs.order_by(f"-{date_field}")

        rows: List[Dict[str, Any]] = []
        if dataset == "sales":
            qs = qs.select_related("manager", "company")[:lim]
            for s in qs:
                rows.append(
                    _serialize_row(
                        {
                            "id_number": s.id_number,
                            "title": s.title,
                            "manager": f"{s.manager.last_name or ''} {s.manager.name or ''}".strip(),
                            "company": s.company.title if s.company else "",
                            "sale_amount": float(s.sale or 0),
                            "salary": float(s.salary or 0),
                            "closing_date": s.closing_date,
                            "account_number": s.account_number,
                        }
                    )
                )
        elif dataset == "expenses":
            qs = qs.select_related("employee", "expense_type")[:lim]
            for e in qs:
                rows.append(
                    _serialize_row(
                        {
                            "employee": e.employee.name if e.employee else "",
                            "expense_type": e.expense_type.name if e.expense_type else "",
                            "amount": float(e.amount or 0),
                            "expense_date": e.expense_date,
                            "comment": (e.comment or "")[:200],
                        }
                    )
                )
        else:
            qs = qs.select_related("manager")[:lim]
            for p in qs:
                rows.append(
                    _serialize_row(
                        {
                            "manager": f"{p.manager.last_name or ''} {p.manager.name or ''}".strip(),
                            "amount": float(p.amount or 0),
                            "payment_datetime": p.payment_datetime,
                        }
                    )
                )
        return {"ok": True, "rows": rows}

    def _compare_months(
        self,
        year: int,
        months: List[int],
        top_deals_per_month: int = 5,
        company_name_contains: Optional[str] = None,
        sales_amount_field: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Totals per month + top deals; UI shows only summaries, model gets full JSON."""
        if kwargs:
            logger.debug(
                "crm_analytics_compare_months: ignoring extra parameters: %s",
                sorted(kwargs.keys()),
            )
        qs, err = _dataset_qs("sales", self.querysets)
        if err:
            return {"ok": False, "error": err, "summaries": [], "top_deals_by_month": []}
        assert qs is not None
        date_field, amount_field, _ = _date_amount_fields("sales")
        amount_field = _resolve_sales_amount_field(sales_amount_field)
        qs = _apply_sales_company_filter(qs, "sales", company_name_contains)
        top_n = max(1, min(int(top_deals_per_month or 5), MAX_TOP_DEALS))
        months_clean = sorted({m for m in months if isinstance(m, int) and 1 <= m <= 12})
        if not months_clean:
            return {"ok": False, "error": "months must contain 1..12", "summaries": [], "top_deals_by_month": []}

        summaries: List[Dict[str, Any]] = []
        top_deals_by_month: List[Dict[str, Any]] = []
        for m in months_clean:
            mqs = qs.filter(**{f"{date_field}__year": year, f"{date_field}__month": m})
            mqs = mqs.filter(**{f"{date_field}__isnull": False})
            agg = mqs.aggregate(
                total_amount=Sum(amount_field),
                record_count=Count("id"),
                avg_amount=Avg(amount_field),
                max_amount=Max(amount_field),
            )
            label = f"{calendar.month_name[m]} {year}"
            summaries.append(
                _serialize_row(
                    {
                        "Month": label,
                        "Total Sales": float(agg["total_amount"] or 0),
                        "Deals Count": agg["record_count"],
                        "Average Deal": float(agg["avg_amount"] or 0),
                        "Max Deal": float(agg["max_amount"] or 0),
                    }
                )
            )
            top = mqs.select_related("manager", "company").order_by(f"-{amount_field}")[:top_n]
            deals: List[Dict[str, Any]] = []
            rank = 0
            for s in top:
                rank += 1
                deals.append(
                    _serialize_row(
                        {
                            "rank": rank,
                            "id_number": s.id_number,
                            "title": s.title,
                            "manager": f"{s.manager.last_name or ''} {s.manager.name or ''}".strip(),
                            "company": s.company.title if s.company else "",
                            "sale_amount": float(s.sale or 0),
                            "salary": float(s.salary or 0),
                            "closing_date": s.closing_date,
                        }
                    )
                )
            top_deals_by_month.append({"month": m, "month_label": label, "top_deals": deals})
        return {"ok": True, "summaries": summaries, "top_deals_by_month": top_deals_by_month}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "crm_analytics_aggregate",
            "description": (
                "Aggregate sales, expenses, or salary payments on the CURRENT dashboard data slice "
                "(already filtered by period and manager permissions). Use this for totals, sums by month, "
                "by manager, company, expense type, or employee. "
                "For per-deal manager compensation (commission/salary on deals), use dataset sales with "
                "sales_amount_field='salary' — not salary_payments (that table is separate payout transfers)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": ["sales", "expenses", "salary_payments"],
                        "description": "Which dataset to query.",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            "none",
                            "year_month",
                            "manager",
                            "company",
                            "expense_type",
                            "employee",
                        ],
                        "description": "Grouping dimension. 'company', 'expense_type', 'employee' only apply to their datasets.",
                    },
                    "year": {
                        "type": "integer",
                        "description": "Optional further filter: calendar year (e.g. 2025).",
                    },
                    "months": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1, "maximum": 12},
                        "description": (
                            "Optional month filter 1-12. For sales with group_by=manager, "
                            "two months (e.g. [5,11]) return a pivot: each manager gets Sales/Deals columns per month, "
                            "not one combined total."
                        ),
                    },
                    "year_month": {
                        "type": "string",
                        "description": (
                            "Optional single period as YYYY-MM (e.g. 2025-05). "
                            "If set, overrides year/months for filtering. Same slice as dashboard + this period."
                        ),
                    },
                    "limit_groups": {
                        "type": "integer",
                        "description": "Max number of groups to return when group_by is not none (default 100, max 200).",
                    },
                    "company_name_contains": {
                        "type": "string",
                        "description": (
                            "Only for dataset=sales: keep deals whose customer company title contains this text "
                            "(case-insensitive substring, e.g. 'Еталон' or 'Etalon')."
                        ),
                    },
                    "sales_amount_field": {
                        "type": "string",
                        "enum": ["sale", "salary"],
                        "description": (
                            "Only for dataset=sales: which amount to sum — sale=deal revenue (default), "
                            "salary=per-deal manager salary/commission (Sale.salary field)."
                        ),
                    },
                },
                "required": ["dataset", "group_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_analytics_list",
            "description": (
                "List individual sales, expense rows, or salary payment rows with amounts and dates. "
                "Use for detailed line items (e.g. all deals in October)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": ["sales", "expenses", "salary_payments"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Row count 1-100 (default 25).",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["amount_desc", "date_desc"],
                        "description": "Sort order (default date_desc).",
                    },
                    "year": {"type": "integer"},
                    "months": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1, "maximum": 12},
                    },
                    "year_month": {
                        "type": "string",
                        "description": "Optional YYYY-MM; overrides year and months when provided.",
                    },
                    "company_name_contains": {
                        "type": "string",
                        "description": "Only for dataset=sales: filter by customer company title (substring, case-insensitive).",
                    },
                },
                "required": ["dataset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_analytics_compare_months",
            "description": (
                "Compare SALES across months in one year. Response JSON includes `summaries` (one row per month) "
                "and `top_deals_by_month` (largest deals). Use for month-vs-month questions. "
                "Use sales_amount_field=salary to compare per-deal compensation totals instead of deal amounts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Calendar year, e.g. 2025."},
                    "months": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1, "maximum": 12},
                        "description": "Months to compare, e.g. [5, 11].",
                    },
                    "top_deals_per_month": {
                        "type": "integer",
                        "description": "Top N deals per month by amount (default 5, max 30).",
                    },
                    "company_name_contains": {
                        "type": "string",
                        "description": "Only include deals for companies whose title contains this substring.",
                    },
                    "sales_amount_field": {
                        "type": "string",
                        "enum": ["sale", "salary"],
                        "description": "Metric for monthly totals and for ranking top deals: sale (default) or salary.",
                    },
                },
                "required": ["year", "months"],
            },
        },
    },
]
