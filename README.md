# Puerto Simple · Entrega final (Equipo 8 "Los πr²")

Aplicación web SaaS en Django para PYMEs del comercio: inventario con alertas de stock mínimo, venta rápida,
cierre de caja diario, informes de ganancias y pérdidas, carga de inventario desde facturas y tienda pública.

## 1. Instalar (una sola vez)
```
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py cargar_demo
```
(`cargar_demo` crea un comercio de ejemplo con productos y 60 días de ventas. Es opcional.)

## 2. Ejecutar
```
python manage.py runserver
```
Abrir http://127.0.0.1:8000/ en el navegador.

- Administrador de demostración: usuario `demo` / contraseña `demo1234`
- Vendedor de demostración: usuario `vendedor` / contraseña `demo1234`
- Tienda pública de ejemplo: http://127.0.0.1:8000/tienda/puerto-simple/
- Sin datos de ejemplo: crear cuenta en http://127.0.0.1:8000/registro/

## 3. Carga de inventario desde facturas (gratis)
En **Cargar factura / catálogo** se puede subir:
1. **XML de factura electrónica** (el .xml que llega al correo junto al PDF): lectura exacta, sin IA ni internet.
2. **PDF digital** (con texto): se leen las líneas de productos sin IA. Solo acepta una línea si cantidad × precio coincide con el total.
3. **Foto o PDF escaneado**: se lee con IA, *opcional* (requiere clave de la API de Anthropic, ver abajo).
4. Si nada se puede leer, la pantalla de revisión permite **ingresar los productos a mano**.

En todos los casos hay una pantalla para revisar y corregir, y para escribir el precio de venta de los productos nuevos.
Para probar, en la carpeta `ejemplos/` hay una factura XML, una factura PDF y un catálogo CSV.

### Lectura de fotos con IA (opcional, de pago por uso)
Definir la clave antes de ejecutar el servidor, en la misma terminal:
- Windows (PowerShell): `$env:ANTHROPIC_API_KEY="tu-clave"`
- Mac/Linux: `export ANTHROPIC_API_KEY="tu-clave"`

## Funcionalidades (según los entregables)
| Funcionalidad | Dónde |
|---|---|
| Control de inventario con descuento automático y alertas de stock mínimo | Venta rápida, Inventario, Alertas de stock |
| Reposición con solicitud a proveedor | Alertas de stock |
| Historial de compras | Historial de compras |
| Venta rápida en una pantalla (buscador / lector de código) y comprobante | Venta rápida |
| Panel de ventas en tiempo real y cierre de caja | Inicio, Cierre de caja |
| Informe de ganancias y pérdidas diario, mensual y anual (+ CSV) | Ganancias y pérdidas |
| Carga de inventario desde XML, PDF o foto de factura o boleta (XML y PDF digital gratis; foto con IA opcional) | Cargar factura / catálogo |
| Importación de catálogo anterior (Excel/CSV) | Cargar factura / catálogo |
| Datos del comercio (nombre, logo, contacto) y usuarios con roles | Configuración |
| Página pública con productos y pedidos web | Ver mi tienda pública |
| Indicadores en moneda local (dólar y UF) desde API pública mindicador.cl | Inicio |

## Estructura
- `tienda/models.py`: tablas (diagrama entidad-relación)
- `tienda/servicios.py`: lógica del negocio (ventas, stock, alertas, informes)
- `tienda/facturas.py`: lectura de facturas con IA e importación de catálogos
- `tienda/views.py` y `tienda/urls.py`: páginas
- `tienda/templates/`, `static/`: diseño
- `tienda/tests.py`: pruebas automáticas → `python manage.py test`
