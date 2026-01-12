from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    query = context['request'].GET.copy()
    for k, v in kwargs.items():
        query[k] = v
    return query.urlencode()

@register.filter
def to_range(start, end):
    """Генерирует диапазон чисел: {% for i in 1|to_range:13 %} — 1 до 12"""
    return range(start, end)

@register.filter
def sum(values, attr):
    total = 0
    for obj in values:
        if isinstance(obj, dict):
            value = obj.get(attr, 0)
        else:
            value = getattr(obj, attr, 0)
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
    return total



@register.filter
def dict_get(d, key):
    return d.get(key, '')

@register.filter
def spaced_number(value):
    try:
        number = float(value)
        # Разбиваем на целую и дробную части
        parts = f"{number:,.2f}".split('.')
        integer_part = parts[0].replace(",", " ")  # заменяем запятые на пробелы
        return f"{integer_part}.{parts[1]}"
    except (ValueError, TypeError):
        return value