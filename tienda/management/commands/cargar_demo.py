"""Crea un comercio de demostración con productos y ventas de los últimos 60 días.
Uso:  python manage.py cargar_demo      (usuario: demo  /  contraseña: demo1234)"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from tienda import servicios
from tienda.models import Comercio, MovimientoInventario, Perfil, Producto, Venta

PRODUCTOS = [  # sku, nombre, precio, costo, stock final, mínimo
    ("CAF-500", "Café molido Costa 500 g", 8990, 6200, 8, 7),
    ("TAZ-001", "Taza cerámica Puerto", 6990, 4100, 14, 5),
    ("FIL-040", "Filtro papel Nº4 · 40 un.", 3490, 1900, 32, 10),
    ("MER-014", "Mermelada artesanal de mora 250 g", 6990, 4300, 2, 5),
    ("TAZ-008", "Tazón cerámica puerto", 12990, 8200, 3, 5),
    ("CAF-021", "Café tostado Cerro Alegre 500 g", 10500, 7400, 5, 6),
    ("BOL-004", "Bolsa reutilizable Valparaíso", 4990, 2100, 24, 8),
    ("POS-012", "Set postales ascensores", 8490, 4800, 18, 6),
]


class Command(BaseCommand):
    help = "Carga datos de demostración"

    def handle(self, *args, **opciones):
        if User.objects.filter(username="demo").exists():
            self.stdout.write("Los datos de demostración ya existen (usuario: demo / contraseña: demo1234).")
            return
        random.seed(7)
        c = Comercio.objects.create(nombre="Puerto Simple", tipo_comercio="cafeteria", region="Valparaíso",
                                    telefono="+56 9 1234 5678", email="contacto@puertosimple.cl")
        admin = User.objects.create_user("demo", "demo@puertosimple.cl", "demo1234")
        Perfil.objects.create(user=admin, comercio=c, rol="admin")
        vend = User.objects.create_user("vendedor", password="demo1234")
        Perfil.objects.create(user=vend, comercio=c, rol="vendedor")

        productos = []
        for sku, nombre, precio, costo, _stock, minimo in PRODUCTOS:
            p = Producto.objects.create(comercio=c, sku=sku, nombre=nombre, precio=precio, costo=costo,
                                        stock_minimo=minimo, stock_objetivo=minimo * 3)
            servicios.mover_stock(p, 300, "compra", admin, costo, "Compra inicial")
            productos.append(p)

        ahora = timezone.now()
        for dias in range(60, 0, -1):            # ventas históricas para que los informes tengan datos
            for _ in range(random.randint(2, 6)):
                items = [(p.id, random.randint(1, 3)) for p in random.sample(productos, random.randint(1, 3))]
                v = servicios.registrar_venta(c, random.choice([admin, vend]), items,
                                              metodo_pago=random.choice(["efectivo", "tarjeta", "transferencia"]))
                momento = (ahora - timedelta(days=dias)).replace(hour=random.randint(9, 20), minute=random.randint(0, 59))
                Venta.objects.filter(pk=v.pk).update(fecha_hora=momento)
                MovimientoInventario.objects.filter(nota=f"Venta #{v.id}").update(fecha_hora=momento)
        MovimientoInventario.objects.filter(nota="Compra inicial").update(fecha_hora=ahora - timedelta(days=61))

        for p, (_s, _n, _pr, _co, stock, _m) in zip(productos, PRODUCTOS):   # stock final de la demostración
            p.stock_actual = stock
            p.save()
            servicios.revisar_alerta(p)
        servicios.registrar_venta(c, admin, [(productos[2].id, 1)])         # una venta de "hoy"
        servicios.registrar_venta(c, None, [(productos[7].id, 2)], canal="web", estado="pendiente",
                                  cliente="Hostal Horizonte", contacto="+56 9 8765 4321")
        self.stdout.write(self.style.SUCCESS(
            "Listo. Entra con usuario «demo» y contraseña «demo1234» (administrador) "
            "o «vendedor» / «demo1234»."))
