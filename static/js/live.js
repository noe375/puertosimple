// Actualiza los totales del día "al instante": consulta el servidor cada 10 segundos.
(function () {
    const elementos = document.querySelectorAll('[data-live]');
    if (!elementos.length) return;
    const formato = (v, tipo) => tipo === 'pesos' ? '$' + Number(v).toLocaleString('es-CL') : String(v);
    function actualizar() {
        fetch('/api/resumen/').then(r => r.ok ? r.json() : null).then(datos => {
            if (!datos) return;
            elementos.forEach(el => {
                const clave = el.dataset.live;
                if (clave in datos) el.textContent = formato(datos[clave], el.dataset.fmt);
            });
        }).catch(() => {});
    }
    setInterval(actualizar, 10000);
})();
