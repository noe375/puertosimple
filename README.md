# Puerto Simple - Entregable III (Equipo 8 "Los πr²")

## Requisitos
- Python 3.10 o superior
- Django 5.1.1  ->  pip install Django==5.1.1  

## Cómo ejecutarlo (localhost)
1. Abrir la terminal en la carpeta donde está manage.py
2. python manage.py runserver
3. Abrir http://127.0.0.1:8000/ en el navegador

## Datos para probar la funcionalidad corazón (precargados en tienda/views.py)
| Producto | Precio | Stock | Mínimo |
|---|---|---|---|
| Café molido Costa 500 g | $8990 | 8 | 7 |
| Taza cerámica Puerto | $6990 | 14 | 5 |
| Filtro papel Nº4 | $3490 | 32 | 10 |

## Casos de prueba (usar el botón "Reiniciar datos de demostración" antes de cada uno)
- Caso 1: Café x2 + Taza x1 -> total $24970, café queda en 6 con alerta de stock bajo, taza en 13.
- Caso 2: Café x10 -> venta rechazada por stock insuficiente, no se descuenta nada (café sigue en 8).

Los botones "Cargar Caso 1/2" solo llenan las cantidades; la venta se procesa al presionar "Confirmar venta".

## Limitaciones actuales
- Los datos viven en memoria (sin base de datos): al reiniciar el servidor vuelven a los valores iniciales.
- Sin buscador de productos, sin login, sin carga de facturas (se desarrollarán para la versión final).

