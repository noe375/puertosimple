# Guion del video (máximo 5 minutos) - ordenado según la rúbrica

Antes de grabar: python manage.py runserver, abrir http://127.0.0.1:8000/ y tener views.py abierto en VS Code.

1) 0:00-0:20  Presentación: equipo, idea (inventario + venta rápida para PYMEs).
2) 0:20-1:40  CASO 1 (escenario principal)
   - Presionar "Reiniciar datos de demostración".
   - Decir los datos de entrada: Café x2 y Taza x1 (botón "Cargar Caso 1").
   - Decir el resultado esperado: total $24970, café queda en 6 con alerta, taza en 13.
   - Confirmar venta y mostrar el resultado observado. Decir si coincide.
3) 1:40-2:50  CASO 2 (escenario alternativo)
   - Presionar "Reiniciar datos de demostración".
   - Entrada: Café x10 (botón "Cargar Caso 2"). Esperado: venta rechazada, stock sigue en 8.
   - Confirmar, mostrar el mensaje de error y que el stock del café no cambió. Decir si coincide.
   - Si algo no funcionó como se esperaba, mostrarlo y explicar el problema (la rúbrica lo valora).
4) 2:50-4:30  CÓDIGO (views.py, función procesar_venta, ~20 líneas)
   - Qué hace: valida todos los productos y recién después descuenta y calcula el total.
   - Decisión técnica: validar ANTES de descontar para no dejar una venta a medias.
   - Cómo lo verificaron: el Caso 2 comprueba que el stock no cambia al rechazar la venta.
   - Uso de IA: qué le pidieron a Copilot/IA, qué agregó que no habían pedido y por qué lo
     mantuvieron o lo sacaron 
5) 4:30-5:00  Qué falta: base de datos, carga de inventario desde factura, panel de cierre de caja.
