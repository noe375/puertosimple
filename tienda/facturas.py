"""Lectura de facturas/boletas (con IA) e importación de catálogos CSV/Excel."""
import base64
import csv
import json
import os
import re
import xml.etree.ElementTree as ET


class ErrorLectura(Exception):
    pass


PROMPT = """Lee esta factura o boleta de compra de un comercio chileno. Devuelve SOLO un JSON, sin texto extra, con este formato:
{"productos": [{"sku": "", "nombre": "", "cantidad": 0, "costo_unitario": 0}]}
- cantidad: unidades compradas (entero).
- costo_unitario: precio NETO por unidad en pesos chilenos, sin puntos ni símbolos (entero).
- sku: código del producto si aparece; si no, deja "".
- No incluyas totales, IVA, descuentos ni despacho como productos."""

TIPOS_IMAGEN = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def _entero(valor):
    try:
        return max(int(float(str(valor).replace(".", "").replace(",", ".").replace("$", "").strip() or 0)), 0)
    except ValueError:
        return 0


a_entero = _entero


def parsear_respuesta(texto):
    """Convierte la respuesta de la IA en una lista de productos (valida que sea un JSON correcto)."""
    texto = re.sub(r"```(?:json)?", "", texto).strip()
    ini, fin = texto.find("{"), texto.rfind("}")
    if ini == -1 or fin == -1:
        raise ErrorLectura("La IA no devolvió datos legibles de la factura.")
    try:
        datos = json.loads(texto[ini:fin + 1])
    except json.JSONDecodeError:
        raise ErrorLectura("La respuesta de la IA no tenía el formato esperado.")
    lineas = []
    for p in datos.get("productos", []):
        nombre = str(p.get("nombre", "")).strip()
        if nombre:
            lineas.append({"sku": str(p.get("sku", "")).strip(), "nombre": nombre,
                           "cantidad": _entero(p.get("cantidad", 0)),
                           "costo_unitario": _entero(p.get("costo_unitario", 0))})
    if not lineas:
        raise ErrorLectura("No se encontraron productos en la factura.")
    return lineas


def leer_factura(ruta, nombre_archivo):
    """Envía la foto o PDF a Claude (API de Anthropic) y devuelve las líneas de productos."""
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if not clave:
        raise ErrorLectura("La lectura automática no está activada (falta la variable ANTHROPIC_API_KEY).")
    try:
        import anthropic
    except ImportError:
        raise ErrorLectura("Falta instalar la librería 'anthropic' (pip install anthropic).")
    ext = nombre_archivo.rsplit(".", 1)[-1].lower()
    with open(ruta, "rb") as f:
        datos = base64.standard_b64encode(f.read()).decode()
    if ext == "pdf":
        bloque = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": datos}}
    elif ext in TIPOS_IMAGEN:
        bloque = {"type": "image", "source": {"type": "base64", "media_type": TIPOS_IMAGEN[ext], "data": datos}}
    else:
        raise ErrorLectura("Formato no soportado. Sube una foto (JPG, PNG) o un PDF.")
    try:
        cliente = anthropic.Anthropic(api_key=clave)
        r = cliente.messages.create(model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                                    max_tokens=2000,
                                    messages=[{"role": "user", "content": [bloque, {"type": "text", "text": PROMPT}]}])
        texto = "".join(b.text for b in r.content if b.type == "text")
    except Exception as e:
        raise ErrorLectura(f"No se pudo leer la factura automáticamente ({type(e).__name__}).")
    return parsear_respuesta(texto)


# ------------------------------------------- lectura GRATUITA: XML y PDF digital
def _nodo(padre, nombre):
    """Texto del primer elemento llamado 'nombre' (ignora el espacio de nombres del XML)."""
    for h in padre.iter():
        if h.tag.split("}")[-1] == nombre and h.text:
            return h.text.strip()
    return ""


def _numero_xml(valor):
    """En el XML del SII los decimales vienen con punto: '2.000000' -> 2."""
    try:
        return max(int(round(float(valor))), 0)
    except (TypeError, ValueError):
        return 0


def leer_xml(ruta):
    """Lee el XML de una factura electrónica chilena (DTE del SII). Es exacto y no usa IA ni internet.
    Nota: en boletas electrónicas el precio puede incluir IVA; revísalo en la pantalla de revisión."""
    with open(ruta, "rb") as f:
        contenido = f.read()
    if b"<!DOCTYPE" in contenido.upper() or b"<!ENTITY" in contenido.upper():   # seguridad
        raise ErrorLectura("El archivo XML contiene elementos no permitidos.")
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        raise ErrorLectura("El archivo XML no es válido.")
    lineas = []
    for det in raiz.iter():
        if det.tag.split("}")[-1] != "Detalle":
            continue
        nombre = _nodo(det, "NmbItem")
        if not nombre:
            continue
        cantidad = _numero_xml(_nodo(det, "QtyItem") or 1)
        precio = _numero_xml(_nodo(det, "PrcItem"))
        if not precio and cantidad:
            precio = _numero_xml(_nodo(det, "MontoItem")) // cantidad
        lineas.append({"sku": _nodo(det, "VlrCodigo"), "nombre": nombre, "cantidad": cantidad, "costo_unitario": precio})
    if not lineas:
        raise ErrorLectura("No se encontraron productos en el XML (¿es una factura electrónica del SII?).")
    return lineas


# Una línea típica: [código] descripción  cantidad  precio unitario  total
PATRON_LINEA = re.compile(r"^(?:(?P<sku>(?=[A-Za-z0-9\-]*\d)[A-Za-z0-9\-]{2,20})\s+)?(?P<nombre>.+?)\s+"
                          r"(?P<cant>\d+(?:[.,]\d+)?)\s+\$?\s*(?P<precio>\d[\d.]*)\s+\$?\s*(?P<total>\d[\d.]*)$")


def leer_pdf_texto(ruta):
    """Extrae las líneas de producto de un PDF digital (con texto), sin IA. Solo acepta una línea si
    cantidad × precio coincide con el total, para no inventar datos."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ErrorLectura("Falta instalar 'pypdf' (pip install pypdf).")
    try:
        texto = "\n".join((p.extract_text() or "") for p in PdfReader(ruta).pages)
    except Exception:
        raise ErrorLectura("No se pudo abrir el PDF.")
    if len(texto.strip()) < 20:
        raise ErrorLectura("El PDF no tiene texto (parece una foto escaneada).")
    lineas = []
    for fila in texto.splitlines():
        m = PATRON_LINEA.match(fila.strip())
        if not m:
            continue
        cantidad = float(m["cant"].replace(",", "."))
        precio, total = _entero(m["precio"]), _entero(m["total"])
        if cantidad > 0 and precio > 0 and abs(cantidad * precio - total) <= max(2, total * 0.02):
            lineas.append({"sku": (m["sku"] or "").strip(), "nombre": m["nombre"].strip(),
                           "cantidad": int(round(cantidad)), "costo_unitario": precio})
    if not lineas:
        raise ErrorLectura("No se pudieron reconocer líneas de productos en el PDF.")
    return lineas


def leer_factura_auto(ruta, nombre_archivo):
    """Elige la mejor forma de leer el archivo. Devuelve (lineas, metodo): xml, pdf o ia."""
    ext = nombre_archivo.rsplit(".", 1)[-1].lower()
    if ext == "xml":
        return leer_xml(ruta), "xml"
    motivo = ""
    if ext == "pdf":
        try:
            return leer_pdf_texto(ruta), "pdf"
        except ErrorLectura as e:
            motivo = str(e) + " "
    try:
        return leer_factura(ruta, nombre_archivo), "ia"
    except ErrorLectura as e:
        raise ErrorLectura(motivo + str(e))


# ------------------------------------------------------------ catálogo CSV / Excel
ALIAS = {"nombre": ["nombre", "producto", "descripcion", "descripción"],
         "sku": ["sku", "codigo", "código", "cod"],
         "precio": ["precio", "precio venta", "precio de venta", "pvp"],
         "costo": ["costo", "precio compra", "costo compra", "precio de compra"],
         "stock": ["stock", "cantidad", "existencias", "unidades"],
         "minimo": ["minimo", "mínimo", "stock minimo", "stock mínimo"]}


def _normalizar(encabezados):
    mapa = {}
    for i, h in enumerate(encabezados):
        h = str(h or "").strip().lower()
        for campo, alias in ALIAS.items():
            if h in alias and campo not in mapa:
                mapa[campo] = i
    return mapa


def leer_tabla(ruta, formato):
    """Devuelve una lista de diccionarios {nombre, sku, precio, costo, stock, minimo} desde CSV o XLSX."""
    if formato == "xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ErrorLectura("Falta instalar 'openpyxl' para leer Excel (pip install openpyxl).")
        filas = [list(f) for f in load_workbook(ruta, read_only=True, data_only=True).active.iter_rows(values_only=True)]
    else:
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            texto = f.read()
        primera = texto.split("\n")[0]
        sep = max([",", ";", "\t"], key=primera.count)     # detecta si separa con coma, punto y coma o tab
        filas = list(csv.reader(texto.splitlines(), delimiter=sep))
    if not filas:
        raise ErrorLectura("El archivo está vacío.")
    mapa = _normalizar(filas[0])
    if "nombre" not in mapa:
        raise ErrorLectura("No se encontró la columna 'nombre'. Revisa la plantilla de ejemplo.")
    resultado = []
    for n, fila in enumerate(filas[1:], start=2):
        if not any(fila):
            continue
        d = {campo: (fila[i] if i < len(fila) else "") for campo, i in mapa.items()}
        d["fila"] = n
        resultado.append(d)
    return resultado
