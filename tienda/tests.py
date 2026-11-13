import io
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import facturas, servicios
from .models import (AlertaStock, CargaCatalogo, CierreCaja, Comercio, MovimientoInventario, Perfil, Producto,
                     SolicitudReposicion, Venta)

MEDIA = tempfile.mkdtemp()

XML_FACTURA = """<?xml version="1.0" encoding="ISO-8859-1"?>
<DTE xmlns="http://www.sii.cl/SiiDte" version="1.0"><Documento ID="F1"><Encabezado><IdDoc><TipoDTE>33</TipoDTE></IdDoc></Encabezado>
<Detalle><NroLinDet>1</NroLinDet><CdgItem><TpoCodigo>INT1</TpoCodigo><VlrCodigo>CAF-500</VlrCodigo></CdgItem><NmbItem>Caf\xe9 molido Costa 500 g</NmbItem><QtyItem>10.000000</QtyItem><PrcItem>6000</PrcItem><MontoItem>60000</MontoItem></Detalle>
<Detalle><NroLinDet>2</NroLinDet><NmbItem>Az\xfacar 1 kg</NmbItem><QtyItem>20</QtyItem><MontoItem>21000</MontoItem></Detalle>
</Documento></DTE>""".encode("latin-1")


def pdf_simple(lineas):
    """Crea un PDF mínimo con texto (solo para las pruebas)."""
    cont = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lineas) + " ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(cont)} >>\nstream\n{cont}\nendstream".encode(), b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, pos = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(out)); out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for p in pos:
        out += f"{p:010d} 00000 n \n".encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


def crear_comercio(nombre="Puerto Simple", usuario="ana", rol="admin"):
    c = Comercio.objects.create(nombre=nombre)
    u = User.objects.create_user(usuario, password="clave123")
    Perfil.objects.create(user=u, comercio=c, rol=rol)
    return c, u


def crear_producto(c, sku, nombre, precio, costo, stock, minimo):
    return Producto.objects.create(comercio=c, sku=sku, nombre=nombre, precio=precio, costo=costo,
                                   stock_actual=stock, stock_minimo=minimo)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch("tienda.views.servicios.indicadores", return_value={})
class AppTests(TestCase):
    def setUp(self):
        self.c, self.u = crear_comercio()
        self.cafe = crear_producto(self.c, "CAF-500", "Café molido Costa 500 g", 8990, 6200, 8, 7)
        self.taza = crear_producto(self.c, "TAZ-001", "Taza cerámica Puerto", 6990, 4100, 14, 5)
        self.client.login(username="ana", password="clave123")

    # ---- funcionalidad corazón
    def test_caso1_venta_descuenta_stock_y_genera_alerta(self, _):
        v = servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2), (self.taza.id, 1)])
        self.cafe.refresh_from_db(); self.taza.refresh_from_db()
        self.assertEqual((v.total, self.cafe.stock_actual, self.taza.stock_actual), (24970, 6, 13))
        self.assertTrue(AlertaStock.objects.filter(producto=self.cafe, estado="activa").exists())
        self.assertFalse(AlertaStock.objects.filter(producto=self.taza).exists())
        self.assertEqual(v.costo_total, 2 * 6200 + 4100)

    def test_caso2_stock_insuficiente_no_descuenta_nada(self, _):
        with self.assertRaises(servicios.ErrorNegocio):
            servicios.registrar_venta(self.c, self.u, [(self.taza.id, 1), (self.cafe.id, 10)])
        self.cafe.refresh_from_db(); self.taza.refresh_from_db()
        self.assertEqual((self.cafe.stock_actual, self.taza.stock_actual, Venta.objects.count()), (8, 14, 0))

    def test_venta_rapida_json(self, _):
        r = self.client.post(reverse("venta_registrar"), data='{"items":[{"id":%d,"cantidad":2}],"metodo_pago":"tarjeta"}' % self.cafe.id,
                             content_type="application/json")
        d = r.json()
        self.assertTrue(d["ok"]); self.assertEqual(d["total"], 17980)
        self.assertEqual(d["lineas"][0]["ahora"], 6); self.assertTrue(d["lineas"][0]["alerta"])
        r = self.client.post(reverse("venta_registrar"), data='{"items":[{"id":%d,"cantidad":99}]}' % self.cafe.id,
                             content_type="application/json")
        self.assertEqual(r.status_code, 400); self.assertIn("Stock insuficiente", r.json()["error"])
        r = self.client.post(reverse("venta_registrar"), data="no es json", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_anular_devuelve_stock(self, _):
        v = servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2)])
        self.client.post(reverse("venta_accion", args=[v.id]), {"accion": "anular"})
        self.cafe.refresh_from_db(); v.refresh_from_db()
        self.assertEqual((self.cafe.stock_actual, v.estado), (8, "anulada"))
        self.assertFalse(AlertaStock.objects.filter(producto=self.cafe, estado="activa").exists())

    # ---- inventario y reposición
    def test_crud_producto_y_sku_automatico(self, _):
        r = self.client.post(reverse("producto_nuevo"), {"sku": "", "nombre": "Té verde", "descripcion": "", "precio": 2500,
                             "costo": 1500, "stock_actual": 10, "stock_minimo": 3, "stock_objetivo": 0})
        self.assertEqual(r.status_code, 302)
        p = Producto.objects.get(nombre="Té verde")
        self.assertTrue(p.sku.startswith("P")); self.assertEqual(p.movimientos.count(), 1)
        r = self.client.post(reverse("producto_nuevo"), {"sku": "CAF-500", "nombre": "Otro", "precio": 1, "costo": 1,
                             "stock_actual": 1, "stock_minimo": 1, "stock_objetivo": 0})
        self.assertContains(r, "Ya existe un producto con ese código")
        self.client.post(reverse("producto_desactivar", args=[p.id]))
        p.refresh_from_db(); self.assertFalse(p.activo)

    def test_merma_y_ajuste(self, _):
        self.client.post(reverse("producto_ajuste", args=[self.taza.id]), {"tipo": "merma", "cantidad": 2, "nota": "Rota"})
        self.taza.refresh_from_db(); self.assertEqual(self.taza.stock_actual, 12)
        self.client.post(reverse("producto_ajuste", args=[self.taza.id]), {"tipo": "ajuste", "cantidad": 20, "nota": ""})
        self.taza.refresh_from_db(); self.assertEqual(self.taza.stock_actual, 20)

    def test_reposicion_resuelve_alerta(self, _):
        servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2)])
        self.client.post(reverse("reponer"), {"producto": self.cafe.id, "proveedor": "Distribuidora Costa", "cantidad": 12})
        s = SolicitudReposicion.objects.get()
        self.assertEqual(s.costo_estimado, 12 * 6200)
        self.client.post(reverse("solicitud_accion", args=[s.id, "recibida"]))
        self.cafe.refresh_from_db()
        self.assertEqual(self.cafe.stock_actual, 18)
        self.assertFalse(AlertaStock.objects.filter(estado="activa").exists())
        self.assertContains(self.client.get(reverse("compras")), "Reposición recibida")

    # ---- facturas y catálogo
    def test_leer_xml_factura_electronica(self, _):
        ruta = tempfile.mktemp(suffix=".xml"); open(ruta, "wb").write(XML_FACTURA)
        self.assertEqual(facturas.leer_xml(ruta), [
            {"sku": "CAF-500", "nombre": "Café molido Costa 500 g", "cantidad": 10, "costo_unitario": 6000},
            {"sku": "", "nombre": "Azúcar 1 kg", "cantidad": 20, "costo_unitario": 1050}])   # precio calculado: 21000 / 20
        malo = tempfile.mktemp(suffix=".xml"); open(malo, "wb").write(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
        with self.assertRaises(facturas.ErrorLectura):
            facturas.leer_xml(malo)
        roto = tempfile.mktemp(suffix=".xml"); open(roto, "wb").write(b"<a><b></a>")
        with self.assertRaises(facturas.ErrorLectura):
            facturas.leer_xml(roto)

    def test_leer_pdf_digital(self, _):
        ruta = tempfile.mktemp(suffix=".pdf")
        open(ruta, "wb").write(pdf_simple(["FACTURA ELECTRONICA N 123 DISTRIBUIDORA COSTA", "Detalle de la compra realizada",
                                           "CAF-500 Cafe molido Costa 500 g 10 6000 60000", "Azucar 1 kg 20 1.050 21.000",
                                           "Linea mala con total que no cuadra 5 100 999", "TOTAL 81000"]))
        lineas = facturas.leer_pdf_texto(ruta)
        self.assertEqual(lineas, [{"sku": "CAF-500", "nombre": "Cafe molido Costa 500 g", "cantidad": 10, "costo_unitario": 6000},
                                  {"sku": "", "nombre": "Azucar 1 kg", "cantidad": 20, "costo_unitario": 1050}])
        vacio = tempfile.mktemp(suffix=".pdf"); open(vacio, "wb").write(pdf_simple(["x"]))
        with self.assertRaises(facturas.ErrorLectura):
            facturas.leer_pdf_texto(vacio)

    def test_subir_xml_y_flujo(self, _):
        r = self.client.post(reverse("cargas"), {"tipo": "factura", "archivo": SimpleUploadedFile("f.xml", XML_FACTURA)}, follow=True)
        self.assertContains(r, "del XML de la factura electrónica")
        carga = CargaCatalogo.objects.get(); det = list(carga.detalles.order_by("fila_origen"))
        self.assertEqual((len(det), det[0].accion, det[1].accion, det[0].cantidad), (2, "actualizar", "crear", 10))

    def test_pdf_sin_texto_cae_a_ingreso_manual(self, _):
        r = self.client.post(reverse("cargas"), {"tipo": "factura", "archivo": SimpleUploadedFile("f.pdf", pdf_simple(["x"]))}, follow=True)
        self.assertContains(r, "no tiene texto"); self.assertContains(r, "ingresar los productos manualmente")

    def test_factura_flujo_completo(self, _):
        lineas = [{"sku": "CAF-500", "nombre": "Café molido Costa 500 g", "cantidad": 10, "costo_unitario": 6000},
                  {"sku": "", "nombre": "Azúcar 1 kg", "cantidad": 20, "costo_unitario": 1050}]
        foto = SimpleUploadedFile("factura.pdf", b"%PDF-fake", content_type="application/pdf")
        with mock.patch("tienda.views.leer_factura_auto", return_value=(lineas, "pdf")):
            r = self.client.post(reverse("cargas"), {"tipo": "factura", "archivo": foto})
        carga = CargaCatalogo.objects.get()
        self.assertRedirects(r, reverse("carga_revision", args=[carga.id]))
        det = list(carga.detalles.order_by("fila_origen"))
        self.assertEqual((det[0].accion, det[1].accion), ("actualizar", "crear"))
        datos = {}
        for d in det:
            datos.update({f"incluir_{d.id}": "on", f"sku_{d.id}": d.sku, f"nombre_{d.id}": d.nombre, f"cantidad_{d.id}": d.cantidad,
                          f"costo_{d.id}": d.costo_unitario, f"precio_{d.id}": d.precio_venta or ""})
        r = self.client.post(reverse("carga_revision", args=[carga.id]), datos)     # falta precio del producto nuevo
        self.assertContains(r, "falta su precio de venta"); self.assertFalse(Producto.objects.filter(nombre="Azúcar 1 kg").exists())
        datos[f"precio_{det[1].id}"] = 1500
        self.client.post(reverse("carga_revision", args=[carga.id]), datos)
        azucar = Producto.objects.get(nombre="Azúcar 1 kg")
        self.cafe.refresh_from_db()
        self.assertEqual((azucar.stock_actual, azucar.precio, azucar.costo, self.cafe.stock_actual, self.cafe.costo), (20, 1500, 1050, 18, 6000))
        carga.refresh_from_db(); self.assertEqual((carga.estado, carga.registros_importados), ("completada", 2))

    def test_importar_catalogo_csv(self, _):
        csv_bytes = "nombre;sku;precio;costo;stock;minimo\nPan de molde;PAN-1;2500;1500;30;10\n;SIN-NOMBRE;1;1;1;1\nCafé molido Costa 500 g;CAF-500;9500;6200;12;7\n".encode("utf-8")
        r = self.client.post(reverse("cargas"), {"tipo": "catalogo", "archivo": SimpleUploadedFile("c.csv", csv_bytes)}, follow=True)
        self.assertContains(r, "2 productos correctos y 1 con errores")
        self.cafe.refresh_from_db()
        self.assertEqual((self.cafe.precio, self.cafe.stock_actual), (9500, 12))
        self.assertEqual(Producto.objects.get(sku="PAN-1").stock_actual, 30)
        r = self.client.post(reverse("cargas"), {"tipo": "catalogo", "archivo": SimpleUploadedFile("c.txt", b"x")}, follow=True)
        self.assertContains(r, "Formato no permitido")

    def test_fotos_no_se_aceptan_como_factura(self, _):
        r = self.client.post(reverse("cargas"), {"tipo": "factura", "archivo": SimpleUploadedFile("f.jpg", b"x", content_type="image/jpeg")}, follow=True)
        self.assertContains(r, "Formato no permitido"); self.assertEqual(CargaCatalogo.objects.count(), 0)

    def test_importar_catalogo_xlsx(self, _):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Producto", "Código", "Precio venta", "Costo", "Stock"]); ws.append(["Galletas", "GAL-1", 1200, 700, 50])
        buf = io.BytesIO(); wb.save(buf)
        self.client.post(reverse("cargas"), {"tipo": "catalogo", "archivo": SimpleUploadedFile("c.xlsx", buf.getvalue())})
        self.assertEqual(Producto.objects.get(sku="GAL-1").stock_actual, 50)

    # ---- informes y cierre de caja
    def test_informe_ganancias_y_mermas(self, _):
        servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2), (self.taza.id, 1)])
        servicios.mover_stock(self.taza, -2, "merma", self.u, self.taza.costo, "Rota")
        r = self.client.get(reverse("informes"), {"periodo": "dia", "fecha": timezone.localdate().isoformat()}).context["r"]
        self.assertEqual((r["ingresos"], r["costo"], r["ganancia_bruta"], r["mermas"], r["resultado"]), (24970, 16500, 8470, 8200, 270))
        for periodo in ("mes", "anio"):
            self.assertEqual(self.client.get(reverse("informes"), {"periodo": periodo}).context["r"]["ingresos"], 24970)
        self.assertEqual(self.client.get(reverse("informes"), {"periodo": "mes", "formato": "csv"})["Content-Type"].split(";")[0], "text/csv")

    def test_cierre_de_caja(self, _):
        servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 1)], metodo_pago="efectivo")
        servicios.registrar_venta(self.c, self.u, [(self.taza.id, 1)], metodo_pago="tarjeta")
        self.client.post(reverse("cierre_caja"), {"efectivo_contado": 8000})
        cierre = CierreCaja.objects.get()
        self.assertEqual((cierre.total_ventas, cierre.efectivo_esperado, cierre.diferencia, cierre.cantidad_ventas), (15980, 8990, -990, 2))
        self.assertContains(self.client.get(reverse("cierre_caja")), "falta dinero")

    def test_api_resumen_en_vivo(self, _):
        servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2)])
        d = self.client.get(reverse("api_resumen")).json()
        self.assertEqual((d["ventas_hoy"], d["n_ventas"], d["alertas"]), (17980, 1, 1))

    # ---- tienda pública y pedidos web
    def test_pedido_web_y_confirmacion(self, _):
        self.client.logout()
        url = reverse("tienda_publica", args=[self.c.slug])
        self.assertContains(self.client.get(url), "Café molido Costa 500 g")
        r = self.client.post(url, {f"cantidad_{self.cafe.id}": 1, "cliente": "", "contacto": ""}, follow=True)
        self.assertContains(r, "Escribe tu nombre")
        self.client.post(url, {f"cantidad_{self.cafe.id}": 20, "cliente": "Ana", "contacto": "123"})
        self.assertEqual(Venta.objects.count(), 0)                                  # no hay stock suficiente
        self.client.post(url, {f"cantidad_{self.cafe.id}": 1, "cliente": "Ana", "contacto": "123"})
        v = Venta.objects.get()
        self.assertEqual((v.estado, v.canal), ("pendiente", "web"))
        self.cafe.refresh_from_db(); self.assertEqual(self.cafe.stock_actual, 8)    # aún no descuenta
        self.client.login(username="ana", password="clave123")
        self.client.post(reverse("venta_accion", args=[v.id]), {"accion": "confirmar", "metodo_pago": "transferencia"})
        v.refresh_from_db(); self.cafe.refresh_from_db()
        self.assertEqual((v.estado, self.cafe.stock_actual), ("completada", 7))
        self.assertEqual(servicios.resumen_hoy(self.c)["web"], 8990)

    # ---- usuarios, permisos y multi-comercio
    def test_registro_crea_comercio_y_admin(self, _):
        self.client.logout()
        r = self.client.post(reverse("registro"), {"nombre_comercio": "Mi Almacén", "tipo_comercio": "almacen", "region": "Valparaíso",
                             "usuario": "pedro", "email": "p@x.cl", "password1": "secreta1", "password2": "secreta1"})
        self.assertRedirects(r, reverse("inicio"))
        self.assertEqual(User.objects.get(username="pedro").perfil.rol, "admin")
        self.assertEqual(Comercio.objects.get(nombre="Mi Almacén").slug, "mi-almacen")

    def test_vendedor_no_ve_informes_y_datos_aislados(self, _):
        c2, _u2 = crear_comercio("Otro Comercio", "luis")
        p2 = crear_producto(c2, "Z-1", "Producto ajeno", 100, 50, 5, 1)
        vend = User.objects.create_user("vend", password="clave123"); Perfil.objects.create(user=vend, comercio=self.c, rol="vendedor")
        self.client.logout(); self.client.login(username="vend", password="clave123")
        self.assertRedirects(self.client.get(reverse("informes")), reverse("inicio"))
        self.assertEqual(self.client.get(reverse("producto_detalle", args=[p2.id])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("inventario")), "Producto ajeno")
        self.assertEqual(self.client.get(reverse("venta_rapida")).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("inventario")).status_code, 302)

    def test_todas_las_paginas_cargan(self, _):
        servicios.registrar_venta(self.c, self.u, [(self.cafe.id, 2)])
        v = Venta.objects.get()
        for nombre, args in [("inicio", []), ("venta_rapida", []), ("ventas", []), ("venta_detalle", [v.id]), ("comprobante", [v.id]),
                             ("inventario", []), ("producto_nuevo", []), ("producto_detalle", [self.cafe.id]), ("producto_editar", [self.cafe.id]),
                             ("producto_desactivar", [self.cafe.id]), ("compras", []), ("alertas", []), ("cargas", []), ("informes", []),
                             ("cierre_caja", []), ("configuracion", [])]:
            self.assertEqual(self.client.get(reverse(nombre, args=args)).status_code, 200, nombre)
