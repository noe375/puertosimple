"""Datos disponibles en TODAS las plantillas (menú lateral)."""
from .models import AlertaStock, Venta


def datos_globales(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and hasattr(user, "perfil"):
        perfil = user.perfil
        return {
            "comercio": perfil.comercio,
            "es_admin": perfil.rol == "admin",
            "n_alertas": AlertaStock.objects.filter(producto__comercio=perfil.comercio, estado="activa").count(),
            "n_pendientes": Venta.objects.filter(comercio=perfil.comercio, estado="pendiente").count(),
        }
    return {}
