from django import template

register = template.Library()


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
        # Split into integer and fractional parts
        parts = f"{number:,.2f}".split('.')
        integer_part = parts[0].replace(",", " ")  # replace commas with spaces
        return f"{integer_part}.{parts[1]}"
    except (ValueError, TypeError):
        return value