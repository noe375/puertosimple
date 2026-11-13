"""Lógica del negocio: ventas, stock, alertas, informes. Las vistas llaman a estas funciones."""
import json
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from .models import (AlertaStock, DetalleVenta, MovimientoInventario, Producto, Venta)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


class ErrorNegocio(Exception):
    """Error que se le muestra a la persona usuaria (siempre en español)."""


# ---------------------------------------------------------------- stock y alertas
def revisar_alerta(producto):
    """Crea una alerta si el stock quedó bajo el mínimo y la resuelve si ya se repuso."""
    activa = producto.alertas.filter(estado="activa").first()
    if producto.stock_actual < producto.stock_minimo:
        if activa is None:
            AlertaStock.objects.create(producto=producto, stock_actual=producto.stock_actual,
                                       stock_minimo=producto.stock_minimo)
        else:
            activa.stock_actual = producto.stock_actual
            activa.stock_minimo = producto.stock_minimo
            activa.save()
    elif activa is not None:
        activa.estado = "resuelta"
        activa.fecha_resolucion = timezone.now()
        activa.save()


def mover_stock(producto, cantidad, tipo, usuario=None, costo=0, nota=""):
    """Suma (o resta si es negativa) unidades, deja el movimiento registrado y revisa la alerta."""
    if producto.stock_actual + cantidad < 0:
        raise ErrorNegocio(f"Stock insuficiente de {producto.nombre}: quedan {producto.stock_actual}.")
    producto.stock_actual += cantidad
    producto.save(update_fields=["stock_actual"])
    MovimientoInventario.objects.create(producto=producto, tipo=tipo, cantidad=cantidad,
                                        stock_resultante=producto.stock_actual, costo_unitario=costo,
                                        nota=nota, usuario=usuario)
    revisar_alerta(producto)


# ---------------------------------------------------------------------- ventas
def _descontar(venta, usuario):
    for d in venta.detalles.all():
        p = Producto.objects.select_for_update().get(pk=d.producto_id)
        if d.cantidad > p.stock_actual:
            raise ErrorNegocio(f"Stock insuficiente de {p.nombre}: quedan {p.stock_actual} y se pidieron "
                               f"{d.cantidad}. No se descontó nada.")
        mover_stock(p, -d.cantidad, "venta", usuario, d.costo_unitario, f"Venta #{venta.id}")


@transaction.atomic
def registrar_venta(comercio, usuario, items, canal="presencial", metodo_pago="efectivo",
                    cliente="", contacto="", estado="completada"):
    """items = lista de (id_producto, cantidad). Si algo falla, no se guarda NADA."""
    pedido = defaultdict(int)
    for id_producto, cantidad in items:
        if int(cantidad) > 0:
            pedido[int(id_producto)] += int(cantidad)
    if not pedido:
        raise ErrorNegocio("Agrega al menos un producto con cantidad mayor a 0.")
    productos = {p.id: p for p in comercio.productos.filter(activo=True, id__in=pedido.keys())}
    venta = Venta.objects.create(comercio=comercio, usuario=usuario, canal=canal, estado=estado,
                                 metodo_pago=metodo_pago, cliente=cliente, contacto=contacto)
    total = costo_total = 0
    for id_producto, cantidad in pedido.items():
        p = productos.get(id_producto)
        if p is None:
            raise ErrorNegocio("Uno de los productos ya no está disponible.")
        if cantidad > p.stock_actual:
            raise ErrorNegocio(f"Stock insuficiente de {p.nombre}: quedan {p.stock_actual} y se pidieron "
                               f"{cantidad}. No se descontó nada.")
        DetalleVenta.objects.create(venta=venta, producto=p, cantidad=cantidad, precio_unitario=p.precio,
                                    costo_unitario=p.costo, subtotal=p.precio * cantidad)
        total += p.precio * cantidad
        costo_total += p.costo * cantidad
    venta.total, venta.costo_total = total, costo_total
    venta.save()
    if estado == "completada":
        _descontar(venta, usuario)
    return venta


@transaction.atomic
def confirmar_pedido(venta, usuario, metodo_pago="efectivo"):
    if venta.estado != "pendiente":
        raise ErrorNegocio("Este pedido ya no está pendiente.")
    _descontar(venta, usuario)
    venta.estado, venta.metodo_pago, venta.fecha_hora = "completada", metodo_pago, timezone.now()
    venta.save()


@transaction.atomic
def anular_venta(venta, usuario):
    if venta.estado != "completada":
        raise ErrorNegocio("Solo se pueden anular ventas completadas.")
    for d in venta.detalles.all():
        p = Producto.objects.select_for_update().get(pk=d.producto_id)
        mover_stock(p, d.cantidad, "anulacion", usuario, d.costo_unitario, f"Anulación de venta #{venta.id}")
    venta.estado = "anulada"
    venta.save()


def rechazar_pedido(venta):
    if venta.estado != "pendiente":
        raise ErrorNegocio("Este pedido ya no está pendiente.")
    venta.estado = "rechazada"
    venta.save()


# ----------------------------------------------------------------- informes
def _aware(d):
    return timezone.make_aware(datetime.combine(d, time.min))


def rango(periodo, dia):
    """Devuelve (desde, hasta, etiqueta) para un informe diario, mensual o anual."""
    if periodo == "mes":
        d = dia.replace(day=1)
        h = (d + timedelta(days=32)).replace(day=1)
        etiqueta = f"{MESES[d.month - 1].capitalize()} {d.year}"
    elif periodo == "anio":
        d, h, etiqueta = date(dia.year, 1, 1), date(dia.year + 1, 1, 1), str(dia.year)
    else:
        d, h, etiqueta = dia, dia + timedelta(days=1), dia.strftime("%d-%m-%Y")
    return _aware(d), _aware(h), etiqueta


def resumen_periodo(comercio, desde, hasta):
    ventas = Venta.objects.filter(comercio=comercio, estado="completada",
                                  fecha_hora__gte=desde, fecha_hora__lt=hasta)
    agg = ventas.aggregate(total=Sum("total"), costo=Sum("costo_total"), n=Count("id"))
    ingresos, costo, n = agg["total"] or 0, agg["costo"] or 0, agg["n"] or 0
    por_canal = {c["canal"]: c["t"] for c in ventas.values("canal").annotate(t=Sum("total"))}
    por_pago = {c["metodo_pago"]: c["t"] for c in ventas.values("metodo_pago").annotate(t=Sum("total"))}
    movs = MovimientoInventario.objects.filter(producto__comercio=comercio, fecha_hora__gte=desde,
                                               fecha_hora__lt=hasta)
    mermas = -(movs.filter(tipo="merma").aggregate(t=Sum(F("cantidad") * F("costo_unitario")))["t"] or 0)
    compras = movs.filter(tipo="compra").aggregate(t=Sum(F("cantidad") * F("costo_unitario")))["t"] or 0
    ganancia_bruta = ingresos - costo
    top = (DetalleVenta.objects.filter(venta__in=ventas).values("producto__nombre")
           .annotate(u=Sum("cantidad"), t=Sum("subtotal")).order_by("-u")[:5])
    return {"ingresos": ingresos, "costo": costo, "ganancia_bruta": ganancia_bruta, "mermas": mermas,
            "resultado": ganancia_bruta - mermas, "n_ventas": n, "ticket": ingresos // n if n else 0,
            "presencial": por_canal.get("presencial", 0), "web": por_canal.get("web", 0),
            "por_pago": por_pago, "compras": compras, "top": list(top)}


def serie_periodo(comercio, periodo, desde, hasta):
    """Ingresos y ganancia por hora (día), por día (mes) o por mes (año), para el gráfico de barras."""
    filas = Venta.objects.filter(comercio=comercio, estado="completada", fecha_hora__gte=desde,
                                 fecha_hora__lt=hasta).values_list("fecha_hora", "total", "costo_total")
    if periodo == "dia":
        claves = [(h, f"{h}h") for h in range(24)]
        clave_de = lambda f: f.hour
    elif periodo == "mes":
        dias = (hasta - desde).days
        claves = [(d, str(d)) for d in range(1, dias + 1)]
        clave_de = lambda f: f.day
    else:
        claves = [(m, MESES[m - 1][:3]) for m in range(1, 13)]
        clave_de = lambda f: f.month
    acum = {k: [0, 0] for k, _ in claves}
    for fecha, total, costo in filas:
        k = clave_de(timezone.localtime(fecha))
        acum[k][0] += total
        acum[k][1] += total - costo
    return [{"etiqueta": et, "ingresos": acum[k][0], "ganancia": acum[k][1]} for k, et in claves]


def resumen_hoy(comercio):
    hoy = timezone.localdate()
    desde, hasta, _ = rango("dia", hoy)
    r = resumen_periodo(comercio, desde, hasta)
    r["pendientes"] = Venta.objects.filter(comercio=comercio, estado="pendiente").count()
    r["alertas"] = AlertaStock.objects.filter(producto__comercio=comercio, estado="activa").count()
    return r


# ------------------------------------------------------ indicadores (API pública)
def indicadores():
    """Dólar y UF desde la API pública mindicador.cl. Si no hay internet, devuelve {} sin romper nada."""
    datos = cache.get("indicadores")
    if datos is None:
        try:
            with urllib.request.urlopen("https://mindicador.cl/api", timeout=3) as r:
                j = json.load(r)
            datos = {"dolar": j["dolar"]["valor"], "uf": j["uf"]["valor"], "fecha": j["fecha"][:10]}
        except Exception:
            datos = {}
        cache.set("indicadores", datos, 3600 if datos else 300)
    return datos
