from django.contrib import admin
from . import models

for modelo in (models.Comercio, models.Perfil, models.Producto, models.MovimientoInventario, models.Venta,
               models.DetalleVenta, models.AlertaStock, models.SolicitudReposicion, models.CargaCatalogo,
               models.DetalleCarga, models.CierreCaja):
    admin.site.register(modelo)
