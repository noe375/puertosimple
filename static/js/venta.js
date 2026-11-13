// Venta rápida: buscar o escanear (el lector de códigos escribe el SKU y presiona Enter), armar el carrito y cobrar.
const productos = JSON.parse(document.getElementById('datos-productos').textContent);
const csrf = document.querySelector('meta[name=csrf]').content;
let carrito = {};   // id del producto -> cantidad

const $ = (id) => document.getElementById(id);
const pesos = (n) => '$' + Number(n).toLocaleString('es-CL');
const porId = (id) => productos.find(p => p.id === Number(id));

function pintarLista() {
    const q = $('buscar').value.trim().toLowerCase();
    const visibles = productos.filter(p => !q || p.nombre.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q));
    $('lista').innerHTML = visibles.map(p => `
        <div class="prod ${p.stock <= 0 ? 'agotado' : ''}">
            <div><b>${p.nombre}</b><br><span class="nota">${p.sku} · ${pesos(p.precio)} ·
                ${p.stock <= 0 ? 'Agotado' : p.stock + ' disponibles'}${p.stock > 0 && p.stock < p.minimo ? ' · ⚠ stock bajo' : ''}</span></div>
            <button type="button" class="btn chico" ${p.stock <= 0 ? 'disabled' : ''} onclick="agregar(${p.id})">Agregar</button>
        </div>`).join('') || '<p class="nota">No hay productos que coincidan.</p>';
}

function agregar(id) {
    const p = porId(id);
    if ((carrito[id] || 0) + 1 > p.stock) { mostrarError(`Solo hay ${p.stock} unidades de ${p.nombre}.`); return; }
    carrito[id] = (carrito[id] || 0) + 1;
    ocultarMensajes(); pintarCarrito();
}
function cambiar(id, d) {
    const p = porId(id), nueva = (carrito[id] || 0) + d;
    if (nueva > p.stock) { mostrarError(`Solo hay ${p.stock} unidades de ${p.nombre}.`); return; }
    if (nueva <= 0) delete carrito[id]; else carrito[id] = nueva;
    pintarCarrito();
}
function pintarCarrito() {
    const ids = Object.keys(carrito);
    let total = 0;
    $('carrito').innerHTML = ids.map(id => {
        const p = porId(id), sub = p.precio * carrito[id]; total += sub;
        return `<div class="carrito-linea"><div>${p.nombre}<br><span class="nota">${pesos(p.precio)} c/u</span></div>
            <div class="cant"><button type="button" onclick="cambiar(${id},-1)">−</button><b>${carrito[id]}</b>
            <button type="button" onclick="cambiar(${id},1)">+</button></div><b>${pesos(sub)}</b></div>`;
    }).join('') || '<p class="nota">El carrito está vacío. Busca o escanea un producto.</p>';
    $('total').textContent = pesos(total);
    $('cobrar').disabled = ids.length === 0;
}

function mostrarError(t) { $('error').textContent = t; $('error').style.display = 'block'; }
function ocultarMensajes() { $('error').style.display = 'none'; }

$('buscar').addEventListener('input', pintarLista);
$('buscar').addEventListener('keydown', (e) => {     // Enter: agrega el producto cuyo código coincide, o el único resultado
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const q = $('buscar').value.trim().toLowerCase();
    if (!q) return;
    const exacto = productos.find(p => p.sku.toLowerCase() === q);
    const lista = productos.filter(p => p.nombre.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q));
    const elegido = exacto || (lista.length === 1 ? lista[0] : null);
    if (elegido && elegido.stock > 0) { agregar(elegido.id); $('buscar').value = ''; pintarLista(); }
    else if (!elegido) mostrarError('Escribe el código completo o elige el producto de la lista.');
});

$('cobrar').addEventListener('click', async () => {
    $('cobrar').disabled = true; ocultarMensajes();
    const items = Object.keys(carrito).map(id => ({ id: Number(id), cantidad: carrito[id] }));
    try {
        const resp = await fetch('/venta/registrar/', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ items, metodo_pago: $('pago').value, cliente: $('cliente').value })
        });
        const datos = await resp.json();
        if (!datos.ok) { mostrarError(datos.error); pintarCarrito(); return; }
        datos.lineas.forEach(l => { porId(l.id).stock = l.ahora; });
        $('resultado').innerHTML = `<div class="mensaje success"><b>Venta #${datos.venta_id} completada · ${pesos(datos.total)}</b>
            <table><tr><th>Producto</th><th>Antes</th><th>Vendido</th><th>Ahora</th></tr>
            ${datos.lineas.map(l => `<tr><td>${l.nombre}</td><td>${l.antes}</td><td>-${l.vendido}</td><td><b>${l.ahora}</b></td></tr>`).join('')}
            </table>${datos.lineas.filter(l => l.alerta).map(l => `<div class="aviso-alerta">⚠ <b>${l.nombre}</b> quedó bajo el mínimo (${l.ahora} unidades). <a href="/alertas/">Ver alerta</a></div>`).join('')}
            <p><a class="btn chico" target="_blank" href="/ventas/${datos.venta_id}/comprobante/">Descargar comprobante</a></p></div>`;
        carrito = {}; $('cliente').value = ''; pintarLista(); pintarCarrito(); $('buscar').focus();
    } catch (e) { mostrarError('No se pudo conectar con el servidor. Revisa que siga encendido.'); pintarCarrito(); }
});

pintarLista(); pintarCarrito(); $('buscar').focus();
