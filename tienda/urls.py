from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("registro/", views.registro, name="registro"),
    path("ingresar/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/resumen/", views.api_resumen, name="api_resumen"),
    path("venta/", views.venta_rapida, name="venta_rapida"),
    path("venta/registrar/", views.venta_registrar, name="venta_registrar"),
    path("ventas/", views.ventas, name="ventas"),
    path("ventas/<int:pk>/", views.venta_detalle, name="venta_detalle"),
    path("ventas/<int:pk>/comprobante/", views.comprobante, name="comprobante"),
    path("ventas/<int:pk>/accion/", views.venta_accion, name="venta_accion"),
    path("inventario/", views.inventario, name="inventario"),
    path("inventario/nuevo/", views.producto_nuevo, name="producto_nuevo"),
    path("inventario/<int:pk>/", views.producto_detalle, name="producto_detalle"),
    path("inventario/<int:pk>/editar/", views.producto_editar, name="producto_editar"),
    path("inventario/<int:pk>/ajuste/", views.producto_ajuste, name="producto_ajuste"),
    path("inventario/<int:pk>/desactivar/", views.producto_desactivar, name="producto_desactivar"),
    path("compras/", views.compras, name="compras"),
    path("alertas/", views.alertas, name="alertas"),
    path("alertas/reponer/", views.reponer, name="reponer"),
    path("alertas/solicitud/<int:pk>/<str:accion>/", views.solicitud_accion, name="solicitud_accion"),
    path("cargas/", views.cargas, name="cargas"),
    path("cargas/<int:pk>/", views.carga_revision, name="carga_revision"),
    path("informes/", views.informes, name="informes"),
    path("cierre-caja/", views.cierre_caja, name="cierre_caja"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/vendedor/", views.vendedor_nuevo, name="vendedor_nuevo"),
    path("tienda/<slug:slug>/", views.tienda_publica, name="tienda_publica"),
]
