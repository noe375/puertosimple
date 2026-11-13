"""Vistas: reciben la petición del navegador, llaman a servicios.py y devuelven una página."""
import csv
import json
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import servicios
from .facturas import ErrorLectura, a_entero, leer_factura_auto, leer_tabla
from .forms import (AjusteForm, CargaForm, ComercioForm, ProductoForm, RegistroForm, VendedorForm)
from .models import (AlertaStock, CargaCatalogo, CierreCaja, Comercio, DetalleCarga, MovimientoInventario,
                     Perfil, Producto, SolicitudReposicion, Venta)
from .servicios import ErrorNegocio


# ------------------------------------------------------------------ acceso
def acceso(solo_admin=False):
    """Exige iniciar sesión (y, si se pide, ser administrador). Deja el comercio en request.comercio."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not hasattr(request.user, "perfil"):
                return render(request, "tienda/sin_comercio.html", status=403)
            if solo_admin and request.user.perfil.rol != "admin":
                messages.error(request, "Solo el administrador puede entrar a esa sección.")
                return redirect("inicio")
            request.comercio = request.user.perfil.comercio
            return vista(request, *args, **kwargs)
        return login_required(envoltura)
    return decorador


def registro(request):
    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            comercio = Comercio.objects.create(nombre=d["nombre_comercio"], tipo_comercio=d["tipo_comercio"],
                                               region=d["region"], email=d["email"])
            user = User.objects.create_user(d["usuario"], d["email"], d["password1"])
            Perfil.objects.create(user=user, comercio=comercio, rol="admin")
        login(request, user)
        messages.success(request, "¡Tu comercio está listo! Empieza agregando productos o cargando una factura.")
        return redirect("inicio")
    return render(request, "registration/registro.html", {"form": form})


# ------------------------------------------------------------------ inicio
@acceso()
def inicio(request):
    c = request.comercio
    contexto = {
        "hoy": servicios.resumen_hoy(c),
        "bajos": c.productos.filter(activo=True, stock_actual__lt=F("stock_minimo"))[:6],
        "ultimas": c.ventas.filter(estado="completada")[:6],
        "pendientes": c.ventas.filter(estado="pendiente")[:5],
        "indicadores": servicios.indicadores(),
        "hay_productos": c.productos.filter(activo=True).exists(),
    }
    return render(request, "tienda/inicio.html", contexto)


@acceso()
def api_resumen(request):
    """Lo consulta la página cada 10 segundos para actualizar los totales al instante."""
    r = servicios.resumen_hoy(request.comercio)
    return JsonResponse({"ventas_hoy": r["ingresos"], "n_ventas": r["n_ventas"], "ganancia": r["ganancia_bruta"],
                         "ticket": r["ticket"], "pendientes": r["pendientes"], "alertas": r["alertas"]})


# ------------------------------------------------------------------ ventas
@acceso()
def venta_rapida(request):
    productos = [{"id": p.id, "sku": p.sku, "nombre": p.nombre, "precio": p.precio, "stock": p.stock_actual,
                  "minimo": p.stock_minimo} for p in request.comercio.productos.filter(activo=True)]
    return render(request, "tienda/venta.html", {"productos": productos, "pagos": Venta.PAGOS})


@acceso()
@require_POST
def venta_registrar(request):
    try:
        datos = json.loads(request.body)
        items = [(int(i["id"]), int(i["cantidad"])) for i in datos.get("items", [])]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "Los datos de la venta no son válidos."}, status=400)
    pago = datos.get("metodo_pago")
    pago = pago if pago in dict(Venta.PAGOS) else "efectivo"
    try:
        venta = servicios.registrar_venta(request.comercio, request.user, items, metodo_pago=pago,
                                          cliente=str(datos.get("cliente", ""))[:100])
    except ErrorNegocio as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    lineas = []
    for d in venta.detalles.select_related("producto"):
        p = Producto.objects.get(pk=d.producto_id)
        lineas.append({"id": p.id, "nombre": p.nombre, "vendido": d.cantidad, "antes": p.stock_actual + d.cantidad,
                       "ahora": p.stock_actual, "alerta": p.bajo_minimo})
    return JsonResponse({"ok": True, "venta_id": venta.id, "total": venta.total, "lineas": lineas})


@acceso()
def ventas(request):
    c = request.comercio
    lista = c.ventas.exclude(estado="pendiente")
    estado = request.GET.get("estado", "")
    if estado:
        lista = lista.filter(estado=estado)
    if request.GET.get("fecha"):
        try:
            lista = lista.filter(fecha_hora__date=date.fromisoformat(request.GET["fecha"]))
        except ValueError:
            messages.error(request, "La fecha no es válida.")
    return render(request, "tienda/ventas.html", {
        "ventas": lista[:100], "pendientes": c.ventas.filter(estado="pendiente"), "estado": estado,
        "fecha": request.GET.get("fecha", ""), "estados": Venta.ESTADOS, "pagos": Venta.PAGOS})


@acceso()
def venta_detalle(request, pk):
    venta = get_object_or_404(Venta, pk=pk, comercio=request.comercio)
    return render(request, "tienda/venta_detalle.html", {"venta": venta, "pagos": Venta.PAGOS})


@acceso()
def comprobante(request, pk):
    venta = get_object_or_404(Venta, pk=pk, comercio=request.comercio)
    return render(request, "tienda/comprobante.html", {"venta": venta})


@acceso()
@require_POST
def venta_accion(request, pk):
    venta = get_object_or_404(Venta, pk=pk, comercio=request.comercio)
    accion = request.POST.get("accion")
    try:
        if accion == "anular":
            servicios.anular_venta(venta, request.user)
            messages.success(request, f"Venta #{venta.id} anulada. El stock se devolvió al inventario.")
        elif accion == "confirmar":
            pago = request.POST.get("metodo_pago")
            servicios.confirmar_pedido(venta, request.user, pago if pago in dict(Venta.PAGOS) else "efectivo")
            messages.success(request, f"Pedido #{venta.id} confirmado y stock descontado.")
        elif accion == "rechazar":
            servicios.rechazar_pedido(venta)
            messages.success(request, f"Pedido #{venta.id} rechazado.")
    except ErrorNegocio as e:
        messages.error(request, str(e))
    return redirect(request.POST.get("volver") or "ventas")


# --------------------------------------------------------------- inventario
def generar_sku(comercio):
    n = comercio.productos.count() + 1
    while comercio.productos.filter(sku=f"P{n:04d}").exists():
        n += 1
    return f"P{n:04d}"


@acceso()
def inventario(request):
    productos = request.comercio.productos.all()
    q = request.GET.get("q", "").strip()
    if q:
        productos = productos.filter(Q(nombre__icontains=q) | Q(sku__icontains=q))
    if request.GET.get("filtro") == "bajo":
        productos = productos.filter(activo=True, stock_actual__lt=F("stock_minimo"))
    if request.GET.get("inactivos") != "1":
        productos = productos.filter(activo=True)
    return render(request, "tienda/inventario.html", {"productos": productos, "q": q,
                                                       "filtro": request.GET.get("filtro", ""),
                                                       "inactivos": request.GET.get("inactivos") == "1"})


@acceso()
def producto_nuevo(request):
    form = ProductoForm(request.POST or None, comercio=request.comercio)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.comercio = request.comercio
        p.sku = p.sku or generar_sku(request.comercio)
        p.save()
        if p.stock_actual > 0:
            MovimientoInventario.objects.create(producto=p, tipo="ajuste", cantidad=p.stock_actual,
                                                stock_resultante=p.stock_actual, costo_unitario=p.costo,
                                                nota="Stock inicial", usuario=request.user)
        servicios.revisar_alerta(p)
        messages.success(request, f"Producto «{p.nombre}» agregado al inventario.")
        return redirect("inventario")
    return render(request, "tienda/producto_form.html", {"form": form, "titulo": "Agregar producto"})


@acceso()
def producto_editar(request, pk):
    p = get_object_or_404(Producto, pk=pk, comercio=request.comercio)
    form = ProductoForm(request.POST or None, instance=p, comercio=request.comercio, editando=True)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.sku = p.sku or generar_sku(request.comercio)
        p.save()
        servicios.revisar_alerta(p)
        messages.success(request, "Producto actualizado. Los márgenes se recalcularon con los nuevos precios.")
        return redirect("producto_detalle", pk=p.pk)
    return render(request, "tienda/producto_form.html", {"form": form, "titulo": f"Editar {p.nombre}"})


@acceso()
def producto_detalle(request, pk):
    p = get_object_or_404(Producto, pk=pk, comercio=request.comercio)
    return render(request, "tienda/producto_detalle.html", {
        "p": p, "movimientos": p.movimientos.all()[:30], "form": AjusteForm()})


@acceso()
@require_POST
def producto_ajuste(request, pk):
    p = get_object_or_404(Producto, pk=pk, comercio=request.comercio)
    form = AjusteForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            if d["tipo"] == "merma":
                servicios.mover_stock(p, -d["cantidad"], "merma", request.user, p.costo, d["nota"] or "Merma")
                messages.success(request, f"Merma registrada: se restaron {d['cantidad']} unidades.")
            else:
                servicios.mover_stock(p, d["cantidad"] - p.stock_actual, "ajuste", request.user, p.costo,
                                      d["nota"] or "Ajuste de inventario")
                messages.success(request, f"Stock ajustado a {d['cantidad']} unidades.")
        except ErrorNegocio as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Revisa los datos del ajuste: la cantidad debe ser un número entero.")
    return redirect("producto_detalle", pk=p.pk)


@acceso()
def producto_desactivar(request, pk):
    p = get_object_or_404(Producto, pk=pk, comercio=request.comercio)
    if request.method == "POST":
        p.activo = False
        p.save()
        servicios.revisar_alerta(p)
        messages.success(request, f"«{p.nombre}» se marcó como inactivo y ya no aparece en la lista activa.")
        return redirect("inventario")
    return render(request, "tienda/producto_confirmar.html", {"p": p})


@acceso()
def compras(request):
    movs = (MovimientoInventario.objects.filter(producto__comercio=request.comercio, tipo="compra")
            .select_related("producto")[:100])
    return render(request, "tienda/compras.html", {"movimientos": movs})


# ------------------------------------------------------- alertas y reposición
@acceso()
def alertas(request):
    c = request.comercio
    return render(request, "tienda/alertas.html", {
        "alertas": AlertaStock.objects.filter(producto__comercio=c, estado="activa").select_related("producto"),
        "solicitudes": SolicitudReposicion.objects.filter(producto__comercio=c, estado="pendiente"),
        "resueltas": AlertaStock.objects.filter(producto__comercio=c, estado="resuelta")
                     .select_related("producto").order_by("-fecha_resolucion")[:8]})


@acceso()
@require_POST
def reponer(request):
    p = get_object_or_404(Producto, pk=request.POST.get("producto"), comercio=request.comercio)
    cantidad = a_entero(request.POST.get("cantidad"))
    proveedor = request.POST.get("proveedor", "").strip()
    if cantidad <= 0 or not proveedor:
        messages.error(request, "Indica el proveedor y una cantidad mayor a 0.")
    else:
        SolicitudReposicion.objects.create(producto=p, proveedor=proveedor, cantidad=cantidad,
                                           costo_estimado=cantidad * p.costo, usuario=request.user)
        messages.success(request, f"Solicitud de reposición creada: {cantidad} × {p.nombre} a {proveedor}.")
    return redirect("alertas")


@acceso()
@require_POST
def solicitud_accion(request, pk, accion):
    s = get_object_or_404(SolicitudReposicion, pk=pk, producto__comercio=request.comercio, estado="pendiente")
    if accion == "recibida":
        servicios.mover_stock(s.producto, s.cantidad, "compra", request.user, s.producto.costo,
                              f"Reposición recibida de {s.proveedor}")
        s.estado, s.fecha_recepcion = "recibida", timezone.now()
        messages.success(request, f"Reposición recibida: el stock de {s.producto.nombre} subió a {s.producto.stock_actual}.")
    else:
        s.estado = "cancelada"
        messages.success(request, "Solicitud cancelada.")
    s.save()
    return redirect("alertas")


# ------------------------------------------------- facturas y catálogo (cargas)
def _buscar_producto(comercio, sku, nombre):
    qs = comercio.productos.all()
    if sku:
        p = qs.filter(sku__iexact=sku).first()
        if p:
            return p
    return qs.filter(nombre__iexact=nombre).first() if nombre else None


def _importar_catalogo(request, carga, filas):
    c, ok, mal = request.comercio, 0, 0
    for f in filas:
        nombre = str(f.get("nombre") or "").strip()
        sku = str(f.get("sku") or "").strip()
        try:
            if not nombre:
                raise ValueError("Falta el nombre del producto.")
            p = _buscar_producto(c, sku, nombre)
            precio, costo = a_entero(f.get("precio")), a_entero(f.get("costo"))
            if p is None:
                p = Producto.objects.create(comercio=c, sku=sku or generar_sku(c), nombre=nombre, precio=precio,
                                            costo=costo, stock_minimo=a_entero(f.get("minimo")) or 5)
                accion = "crear"
            else:
                p.precio, p.costo = precio or p.precio, costo or p.costo
                p.save()
                accion = "actualizar"
            if f.get("stock") not in (None, ""):
                servicios.mover_stock(p, a_entero(f.get("stock")) - p.stock_actual, "ajuste", request.user, p.costo,
                                      f"Importado desde {carga.nombre_archivo}")
            DetalleCarga.objects.create(carga=carga, fila_origen=f["fila"], nombre=nombre, sku=p.sku,
                                        producto=p, accion=accion)
            ok += 1
        except ValueError as e:
            DetalleCarga.objects.create(carga=carga, fila_origen=f["fila"], nombre=nombre, accion="error",
                                        mensaje_error=str(e))
            mal += 1
    carga.registros_importados, carga.registros_con_error, carga.estado = ok, mal, "completada"
    carga.save()
    return ok, mal


@acceso()
def cargas(request):
    form = CargaForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        archivo, tipo = form.cleaned_data["archivo"], form.cleaned_data["tipo"]
        ext = archivo.name.rsplit(".", 1)[-1].lower()
        permitidas = ["xml", "pdf"] if tipo == "factura" else ["csv", "xlsx"]
        if ext not in permitidas:
            messages.error(request, "Formato no permitido. Usa: " + ", ".join(permitidas).upper() + ".")
            return redirect("cargas")
        carga = CargaCatalogo.objects.create(comercio=request.comercio, usuario=request.user, archivo=archivo,
                                             nombre_archivo=archivo.name[:200], formato="factura" if tipo == "factura" else ext)
        if tipo == "factura":
            try:
                lineas, metodo = leer_factura_auto(carga.archivo.path, archivo.name)
                origen = {"xml": "del XML de la factura electrónica", "pdf": "del texto del PDF"}[metodo]
                messages.success(request, f"Se leyeron {len(lineas)} productos {origen}. Revísalos y completa el precio de venta.")
            except ErrorLectura as e:
                lineas = []
                messages.warning(request, f"{e} Puedes ingresar los productos manualmente en la siguiente pantalla.")
            for i, l in enumerate(lineas, 1):
                p = _buscar_producto(request.comercio, l["sku"], l["nombre"])
                DetalleCarga.objects.create(carga=carga, fila_origen=i, sku=l["sku"] or (p.sku if p else ""),
                                            nombre=l["nombre"], cantidad=l["cantidad"], costo_unitario=l["costo_unitario"],
                                            producto=p, accion="actualizar" if p else "crear",
                                            precio_venta=p.precio if p else None)
            if not lineas:
                for i in range(1, 6):
                    DetalleCarga.objects.create(carga=carga, fila_origen=i)
            return redirect("carga_revision", pk=carga.pk)
        try:
            ok, mal = _importar_catalogo(request, carga, leer_tabla(carga.archivo.path, ext))
            messages.success(request, f"Catálogo importado: {ok} productos correctos y {mal} con errores.")
        except ErrorLectura as e:
            carga.estado = "cancelada"
            carga.save()
            messages.error(request, str(e))
        return redirect("cargas")
    return render(request, "tienda/cargas.html", {"form": form, "cargas": request.comercio.cargas.all()[:15]})


@acceso()
def carga_revision(request, pk):
    carga = get_object_or_404(CargaCatalogo, pk=pk, comercio=request.comercio)
    if carga.estado != "revision":
        return redirect("cargas")
    c, errores = request.comercio, []
    detalles = list(carga.detalles.all())
    if request.method == "POST":
        if request.POST.get("accion") == "cancelar":
            carga.estado = "cancelada"
            carga.save()
            messages.success(request, "Carga cancelada. No se modificó el inventario.")
            return redirect("cargas")
        for d in detalles:   # se guardan las ediciones para no perderlas si hay errores
            k = str(d.id)
            d.incluir = ("incluir_" + k) in request.POST
            d.sku, d.nombre = request.POST.get("sku_" + k, "").strip(), request.POST.get("nombre_" + k, "").strip()
            d.cantidad, d.costo_unitario = a_entero(request.POST.get("cantidad_" + k)), a_entero(request.POST.get("costo_" + k))
            precio = request.POST.get("precio_" + k, "").strip()
            d.precio_venta = a_entero(precio) if precio else None
            d.producto = _buscar_producto(c, d.sku, d.nombre)
            d.accion = "actualizar" if d.producto else "crear"
            d.save()
        validos = [d for d in detalles if d.incluir and d.nombre]
        if not validos:
            errores.append("Marca al menos un producto con nombre para ingresar al inventario.")
        for d in validos:
            if d.cantidad <= 0:
                errores.append(f"«{d.nombre}»: la cantidad debe ser mayor a 0.")
            if d.producto is None and not d.precio_venta:
                errores.append(f"«{d.nombre}»: es un producto nuevo, falta su precio de venta.")
        if not errores:
            with transaction.atomic():
                for d in validos:
                    p = d.producto
                    if p is None:
                        p = Producto.objects.create(comercio=c, sku=d.sku or generar_sku(c), nombre=d.nombre,
                                                    precio=d.precio_venta, costo=d.costo_unitario, stock_minimo=5)
                    else:
                        p.costo = d.costo_unitario or p.costo
                        p.precio = d.precio_venta or p.precio
                        p.save()
                    servicios.mover_stock(p, d.cantidad, "compra", request.user, d.costo_unitario,
                                          f"Factura/boleta: {carga.nombre_archivo}")
                carga.estado, carga.registros_importados = "completada", len(validos)
                carga.save()
            messages.success(request, f"Inventario actualizado con {len(validos)} productos de la factura.")
            return redirect("inventario")
    return render(request, "tienda/carga_revision.html", {"carga": carga, "detalles": detalles, "errores": errores})


# ----------------------------------------------------------------- informes
def _fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return timezone.localdate()


@acceso(solo_admin=True)
def informes(request):
    periodo = request.GET.get("periodo", "dia")
    periodo = periodo if periodo in ("dia", "mes", "anio") else "dia"
    dia = _fecha(request.GET.get("fecha"))
    desde, hasta, etiqueta = servicios.rango(periodo, dia)
    resumen = servicios.resumen_periodo(request.comercio, desde, hasta)
    serie = servicios.serie_periodo(request.comercio, periodo, desde, hasta)
    if request.GET.get("formato") == "csv":
        r = HttpResponse(content_type="text/csv; charset=utf-8")
        r["Content-Disposition"] = f'attachment; filename="informe-{periodo}-{dia}.csv"'
        r.write("\ufeff")
        w = csv.writer(r, delimiter=";")
        w.writerow(["Período", "Ingresos", "Ganancia"])
        for s in serie:
            w.writerow([s["etiqueta"], s["ingresos"], s["ganancia"]])
        w.writerow([])
        for k in ("ingresos", "costo", "ganancia_bruta", "mermas", "resultado", "n_ventas"):
            w.writerow([k, resumen[k]])
        return r
    maximo = max([s["ingresos"] for s in serie] + [1])
    for s in serie:
        s["alto"] = round(s["ingresos"] * 100 / maximo)
    return render(request, "tienda/informes.html", {"periodo": periodo, "fecha": dia, "etiqueta": etiqueta,
                                                    "r": resumen, "serie": serie})


@acceso(solo_admin=True)
def cierre_caja(request):
    c = request.comercio
    hoy = timezone.localdate()
    desde, hasta, _ = servicios.rango("dia", hoy)
    r = servicios.resumen_periodo(c, desde, hasta)
    efectivo = r["por_pago"].get("efectivo", 0)
    ventas_hoy = c.ventas.filter(estado="completada", fecha_hora__gte=desde, fecha_hora__lt=hasta)
    if request.method == "POST":
        contado = a_entero(request.POST.get("efectivo_contado"))
        CierreCaja.objects.update_or_create(comercio=c, fecha=hoy, defaults={
            "total_presencial": r["presencial"], "total_web": r["web"], "total_ventas": r["ingresos"],
            "cantidad_ventas": r["n_ventas"], "ganancia": r["ganancia_bruta"], "efectivo_esperado": efectivo,
            "efectivo_contado": contado, "diferencia": contado - efectivo, "usuario": request.user})
        messages.success(request, "Cierre de caja guardado.")
        return redirect("cierre_caja")
    return render(request, "tienda/cierre.html", {
        "r": r, "efectivo": efectivo, "ventas": ventas_hoy, "hoy": hoy,
        "cierre_hoy": c.cierres.filter(fecha=hoy).first(), "anteriores": c.cierres.exclude(fecha=hoy)[:7]})


# ------------------------------------------------------------ configuración
@acceso(solo_admin=True)
def configuracion(request):
    c = request.comercio
    form = ComercioForm(request.POST or None, request.FILES or None, instance=c)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Datos del comercio guardados.")
        return redirect("configuracion")
    return render(request, "tienda/configuracion.html", {"form": form, "form_vendedor": VendedorForm(),
                                                         "usuarios": c.perfiles.select_related("user")})


@acceso(solo_admin=True)
@require_POST
def vendedor_nuevo(request):
    form = VendedorForm(request.POST)
    if form.is_valid():
        user = User.objects.create_user(form.cleaned_data["usuario"], password=form.cleaned_data["password"])
        Perfil.objects.create(user=user, comercio=request.comercio, rol="vendedor")
        messages.success(request, f"Vendedor «{user.username}» creado.")
    else:
        for errores in form.errors.values():
            messages.error(request, errores[0])
    return redirect("configuracion")


# ---------------------------------------------------------- tienda pública
def tienda_publica(request, slug):
    c = get_object_or_404(Comercio, slug=slug)
    productos = c.productos.filter(activo=True)
    if request.method == "POST":
        cliente, contacto = request.POST.get("cliente", "").strip(), request.POST.get("contacto", "").strip()
        items = [(p.id, a_entero(request.POST.get(f"cantidad_{p.id}"))) for p in productos]
        if not cliente or not contacto:
            messages.error(request, "Escribe tu nombre y un contacto (teléfono o correo) para enviar el pedido.")
        else:
            try:
                v = servicios.registrar_venta(c, None, items, canal="web", estado="pendiente",
                                              cliente=cliente[:100], contacto=contacto[:100])
                messages.success(request, f"¡Pedido #{v.id} enviado! {c.nombre} te contactará para coordinar.")
                return redirect("tienda_publica", slug=slug)
            except ErrorNegocio as e:
                messages.error(request, str(e))
    return render(request, "tienda/tienda_publica.html", {"c": c, "productos": productos})


# ------------------------------------------------------- errores en español
def error_csrf(request, reason=""):
    return HttpResponse("Error de seguridad del formulario. Vuelve a la página anterior, recárgala (F5) "
                        "e inténtalo de nuevo.", status=403)


def error_404(request, exception=None):
    return HttpResponse("Página no encontrada. Vuelve al inicio.", status=404)
