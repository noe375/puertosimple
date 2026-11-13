from django import template

register = template.Library()


@register.filter
def pesos(valor):
    """24970 -> $24.970"""
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return "$0"
    texto = f"{abs(n):,}".replace(",", ".")
    return ("-$" if n < 0 else "$") + texto
