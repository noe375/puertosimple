"""Modelos (tablas de la base de datos). Siguen el diagrama entidad-relación del Entregable II."""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Comercio(models.Model):
    TIPOS = [("minimarket", "Minimarket"), ("almacen", "Almacén"), ("libreria", "Librería"),
             ("cafeteria", "Cafetería"), ("otro", "Otro")]
    nombre = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)       # dirección de la tienda pública
    rut = models.CharField("RUT", max_length=12, blank=True)
    tipo_comercio = models.CharField("Tipo de comercio", max_length=20, choices=TIPOS, default="minimarket")
    region = models.CharField("Región", max_length=60, default="Valparaíso")
    telefono = models.CharField("Teléfono", max_length=30, blank=True)
    email = models.EmailField("Correo de contacto", blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre) or "comercio"
            slug, n = base, 2
            while Comercio.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Perfil(models.Model):
    """Une un usuario de Django con su comercio y su rol."""
    ROLES = [("admin", "Administrador"), ("vendedor", "Vendedor")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    comercio = models.ForeignKey(Comercio, on_delete=models.CASCADE, related_name="perfiles")
    rol = models.CharField(max_length=10, choices=ROLES, default="vendedor")

    def __str__(self):
        return f"{self.user.username} ({self.get_rol_display()})"


class Producto(models.Model):
    comercio = models.ForeignKey(Comercio, on_delete=models.CASCADE, related_name="productos")
    sku = models.CharField("SKU / código", max_length=30)
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField("Descripción", max_length=200, blank=True)
    precio = models.PositiveIntegerField("Precio de venta ($)", default=0)
    costo = models.PositiveIntegerField("Costo de compra ($)", default=0)
    stock_actual = models.IntegerField("Stock actual", default=0)
    stock_minimo = models.PositiveIntegerField("Stock mínimo", default=0)
    stock_objetivo = models.PositiveIntegerField("Stock objetivo (para reponer)", default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ("comercio", "sku")
        ordering = ["nombre"]

    @property
    def bajo_minimo(self):
        return self.stock_actual < self.stock_minimo

    @property
    def objetivo(self):
        return self.stock_objetivo or self.stock_minimo * 2

    @property
    def sugerido(self):
        return max(self.objetivo - self.stock_actual, 1)

    @property
    def margen(self):
        return self.precio - self.costo

    def __str__(self):
        return f"{self.nombre} ({self.sku})"


class MovimientoInventario(models.Model):
    """Cada cambio de stock queda registrado (cantidad negativa = sale, positiva = entra)."""
    TIPOS = [("venta", "Venta"), ("compra", "Compra / reposición"), ("ajuste", "Ajuste"),
             ("merma", "Merma (pérdida)"), ("anulacion", "Anulación de venta")]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=TIPOS)
    cantidad = models.IntegerField()
    stock_resultante = models.IntegerField()
    costo_unitario = models.PositiveIntegerField(default=0)
    nota = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha_hora", "-id"]


class Venta(models.Model):
    CANALES = [("presencial", "Presencial"), ("web", "Web")]
    ESTADOS = [("completada", "Completada"), ("pendiente", "Pendiente"),
               ("anulada", "Anulada"), ("rechazada", "Rechazada")]
    PAGOS = [("efectivo", "Efectivo"), ("tarjeta", "Tarjeta"), ("transferencia", "Transferencia")]
    comercio = models.ForeignKey(Comercio, on_delete=models.CASCADE, related_name="ventas")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    canal = models.CharField(max_length=12, choices=CANALES, default="presencial")
    estado = models.CharField(max_length=12, choices=ESTADOS, default="completada")
    metodo_pago = models.CharField(max_length=14, choices=PAGOS, default="efectivo")
    cliente = models.CharField(max_length=100, blank=True)
    contacto = models.CharField(max_length=100, blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now)
    total = models.PositiveIntegerField(default=0)
    costo_total = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-fecha_hora", "-id"]

    @property
    def ganancia(self):
        return self.total - self.costo_total


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.PositiveIntegerField()
    costo_unitario = models.PositiveIntegerField(default=0)   # se guarda para calcular la ganancia real
    subtotal = models.PositiveIntegerField()


class AlertaStock(models.Model):
    ESTADOS = [("activa", "Activa"), ("resuelta", "Resuelta")]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="alertas")
    stock_actual = models.IntegerField()
    stock_minimo = models.IntegerField()
    estado = models.CharField(max_length=10, choices=ESTADOS, default="activa")
    fecha_creacion = models.DateTimeField(default=timezone.now)
    fecha_resolucion = models.DateTimeField(null=True, blank=True)


class SolicitudReposicion(models.Model):
    ESTADOS = [("pendiente", "Pendiente"), ("recibida", "Recibida"), ("cancelada", "Cancelada")]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="solicitudes")
    proveedor = models.CharField(max_length=100)
    cantidad = models.PositiveIntegerField()
    costo_estimado = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=10, choices=ESTADOS, default="pendiente")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    fecha_creacion = models.DateTimeField(default=timezone.now)
    fecha_recepcion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha_creacion"]


class CargaCatalogo(models.Model):
    """Una subida de archivo: XML/PDF de factura, o catálogo en CSV/Excel."""
    ESTADOS = [("revision", "En revisión"), ("completada", "Completada"), ("cancelada", "Cancelada")]
    comercio = models.ForeignKey(Comercio, on_delete=models.CASCADE, related_name="cargas")
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    archivo = models.FileField(upload_to="cargas/")
    nombre_archivo = models.CharField(max_length=200)
    formato = models.CharField(max_length=10)               # factura, csv, xlsx
    fecha_carga = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=12, choices=ESTADOS, default="revision")
    registros_importados = models.PositiveIntegerField(default=0)
    registros_con_error = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-fecha_carga"]


class DetalleCarga(models.Model):
    carga = models.ForeignKey(CargaCatalogo, on_delete=models.CASCADE, related_name="detalles")
    fila_origen = models.PositiveIntegerField(default=0)
    incluir = models.BooleanField(default=True)
    sku = models.CharField(max_length=30, blank=True)
    nombre = models.CharField(max_length=100, blank=True)
    cantidad = models.PositiveIntegerField(default=0)
    costo_unitario = models.PositiveIntegerField(default=0)
    precio_venta = models.PositiveIntegerField(null=True, blank=True)
    producto = models.ForeignKey(Producto, null=True, blank=True, on_delete=models.SET_NULL)
    accion = models.CharField(max_length=12, default="crear")   # crear / actualizar / error
    mensaje_error = models.CharField(max_length=200, blank=True)


class CierreCaja(models.Model):
    """Cierre de caja diario (equivale al panel de ventas diarias del Entregable II)."""
    comercio = models.ForeignKey(Comercio, on_delete=models.CASCADE, related_name="cierres")
    fecha = models.DateField()
    total_presencial = models.PositiveIntegerField(default=0)
    total_web = models.PositiveIntegerField(default=0)
    total_ventas = models.PositiveIntegerField(default=0)
    cantidad_ventas = models.PositiveIntegerField(default=0)
    ganancia = models.IntegerField(default=0)
    efectivo_esperado = models.PositiveIntegerField(default=0)
    efectivo_contado = models.PositiveIntegerField(default=0)
    diferencia = models.IntegerField(default=0)
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("comercio", "fecha")
        ordering = ["-fecha"]
