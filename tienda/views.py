import copy
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import render, redirect

# Productos precargados. Viven en memoria: no se guardan en una base de datos todavía.
PRODUCTOS_INICIALES = [
    {"id": 1, "nombre": "Café molido Costa 500 g", "precio": 8990, "stock": 8, "minimo": 7},
    {"id": 2, "nombre": "Taza cerámica Puerto", "precio": 6990, "stock": 14, "minimo": 5},
    {"id": 3, "nombre": "Filtro papel Nº4 · 40 un.", "precio": 3490, "stock": 32, "minimo": 10},
]
PRODUCTOS = copy.deepcopy(PRODUCTOS_INICIALES)
HISTORIAL = []  # ventas realizadas desde que se inició (o reinició) la demo


def procesar_venta(pedido):
    """Procesa una venta. pedido = lista de (producto, cantidad).
    Devuelve (resultado, error). Si hay error, NO se descuenta nada."""
    # Paso 1: validar TODOS los productos antes de tocar el stock
    for producto, cantidad in pedido:
        if cantidad > producto["stock"]:
            error = (f"Stock insuficiente de {producto['nombre']}: quedan "
                     f"{producto['stock']} y se pidieron {cantidad}. No se descontó nada.")
            return None, error

    # Paso 2: calcular total, descontar stock y revisar si queda bajo el mínimo
    total = 0
    lineas = []
    for producto, cantidad in pedido:
        antes = producto["stock"]
        producto["stock"] = antes - cantidad
        total += producto["precio"] * cantidad
        lineas.append({
            "nombre": producto["nombre"],
            "antes": antes,
            "vendido": cantidad,
            "ahora": producto["stock"],
            "alerta": producto["stock"] < producto["minimo"],
        })
    return {"total": total, "lineas": lineas}, None


def index(request):
    resultado = None
    error = None

    if request.method == "POST":
        # ENTRADA: leer las cantidades escritas en el formulario
        pedido = []
        for producto in PRODUCTOS:
            texto = request.POST.get("cantidad_" + str(producto["id"]), "0").strip()
            if texto == "":
                texto = "0"
            if not texto.isdigit():
                error = (f"La cantidad de {producto['nombre']} debe ser un número "
                         "ENTERO igual o mayor que 0.")
                break
            cantidad = int(texto)
            if cantidad > 0:
                pedido.append((producto, cantidad))

        if error:
            pass
        elif len(pedido) == 0:
            error = "Ingresa al menos un producto con cantidad mayor a 0."
        else:
            # PROCESAMIENTO
            resultado, error = procesar_venta(pedido)
            if resultado:
                resultado["hora"] = datetime.now().strftime("%H:%M:%S")
                HISTORIAL.insert(0, resultado)

    # SALIDA: todo lo que mostrará la página
    contexto = {
        "productos": PRODUCTOS,
        "resultado": resultado,
        "error": error,
        "historial": HISTORIAL,
        "ventas_hoy": sum(v["total"] for v in HISTORIAL),
        "bajos": [p for p in PRODUCTOS if p["stock"] < p["minimo"]],
    }
    return render(request, "tienda/index.html", contexto)


def reiniciar(request):
    """Vuelve a los datos de demostración (útil para repetir los casos de prueba)."""
    PRODUCTOS[:] = copy.deepcopy(PRODUCTOS_INICIALES)
    HISTORIAL.clear()
    return redirect("index")


# Páginas de error en español (reemplazan los mensajes por defecto de Django)
def error_csrf(request, reason=""):
    return HttpResponse("Error de seguridad del formulario. Vuelve a la página principal y "
                        "recárgala (F5) antes de confirmar la venta.", status=403)


def error_404(request, exception=None):
    return HttpResponse("Página no encontrada. Vuelve a la página principal.", status=404)
