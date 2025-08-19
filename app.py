# app.py
# -------------------------------------------
# PDF → TXT con Streamlit + pdfplumber
# - Carga por arrastrar/soltar (uno o varios)
# - Extrae texto en orden de lectura por página
# - Conserva saltos de línea básicos
# - Muestra el texto en pantalla
# - Descarga .txt (individual o ZIP para lote)
# - Manejo de errores (protegido/corrupto)
# - Logs básicos visibles en la UI
# - Extra: copiar al portapapeles (local)
# -------------------------------------------

import io
import zipfile
import logging
from logging import StreamHandler
from io import StringIO
from typing import Optional, Tuple, List

import streamlit as st
import pdfplumber

# ============ Configuración de logging ============
log_stream = StringIO()
logger = logging.getLogger("pdf2txt")
logger.setLevel(logging.INFO)
# Evitar duplicar handlers si Streamlit recarga el script
if not any(isinstance(h, StreamHandler) for h in logger.handlers):
    stream_handler = logging.StreamHandler(log_stream)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S")
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


# ============ Utilidades de extracción ============
def extract_text_from_pdf(file_bytes: bytes, password: Optional[str] = None) -> Tuple[str, List[str]]:
    """
    Extrae texto de un PDF (en bytes).
    - Intenta abrir con pdfplumber.
    - Si está cifrado, usa password si se provee.
    - Devuelve: (texto, warnings)
    Puede lanzar excepciones si el PDF está corrupto o la password es incorrecta.
    """
    warnings: List[str] = []
    text_chunks: List[str] = []

    try:
        # pdfplumber.open acepta un path o un stream
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if getattr(pdf, "is_encrypted", False):
                logger.info("El PDF está cifrado.")
                if password:
                    ok = pdf.decrypt(password)  # 0/1
                    if not ok:
                        raise ValueError("Contraseña incorrecta para el PDF protegido.")
                    logger.info("Desencriptado con la contraseña proporcionada.")
                else:
                    raise ValueError("El PDF está protegido. Proporciona una contraseña.")

            num_pages = len(pdf.pages)
            logger.info(f"Páginas detectadas: {num_pages}")

            for i, page in enumerate(pdf.pages, start=1):
                # extract_text conserva saltos de línea. Ajustes finos de lectura:
                # x_tolerance/y_tolerance ayudan a reconstruir líneas; valores bajos suelen mantener orden.
                page_text = page.extract_text(x_tolerance=1.5, y_tolerance=1.0)
                if page_text is None:
                    warnings.append(f"Página {i}: no se pudo extraer texto (puede ser escaneada/imagen).")
                    logger.warning(f"Página {i} sin texto extraíble.")
                    continue

                # Separador opcional por página para claridad (no lo añadimos si no hay varias páginas)
                header = f"\n\n--- Página {i} ---\n\n" if num_pages > 1 else ""
                text_chunks.append(header + page_text)

        full_text = "".join(text_chunks).strip()
        if not full_text:
            warnings.append("No se extrajo texto. El PDF podría ser escaneado/imagen sin OCR.")
            logger.warning("Extracción vacía; considerar aplicar OCR externo si el PDF es imagen.")
        return full_text, warnings

    except Exception as e:
        logger.exception("Fallo durante la extracción.")
        raise


def to_txt_filename(pdf_name: str) -> str:
    base = pdf_name.rsplit(".", 1)[0]
    return f"{base}.txt"


# ============ UI (Streamlit) ============
st.set_page_config(page_title="PDF → TXT", page_icon="📄", layout="wide")

st.title("📄 PDF → TXT")
st.write(
    "Arrastra tu(s) PDF(s) y conviértelos a texto plano.\n\n"
    "- Maneja múltiples páginas y conserva saltos de línea.\n"
    "- Muestra el texto y permite descargarlo como `.txt`.\n"
    "- Si un PDF está **protegido**, ingresa la contraseña."
)

with st.sidebar:
    st.header("Opciones")
    process_batch = st.toggle("Procesar en lote (varios PDFs)", value=True)
    show_page_headers = st.toggle("Mostrar separadores por página", value=True)
    st.caption("Nota: si no aparece texto, el PDF podría ser una **imagen** (escaneado) y requerir OCR externo.")

uploaded_files = st.file_uploader(
    "Selecciona uno o varios archivos PDF",
    type=["pdf"],
    accept_multiple_files=True if process_batch else False
)

# Campo global para contraseña (aplica a todos los PDFs protegidos de la corrida)
password = st.text_input("Contraseña (si tus PDFs están protegidos)", type="password", help="Se usará para intentar abrir PDFs cifrados.")

# Espacio para resultados
results_container = st.container()

# Botones de acción
col_a, col_b = st.columns([1, 1])
run = col_a.button("Convertir", type="primary")
clear_logs = col_b.button("Limpiar logs")

if clear_logs:
    log_stream.truncate(0)
    log_stream.seek(0)

if run:
    if not uploaded_files:
        st.warning("Sube al menos un archivo PDF.")
    else:
        multiple = len(uploaded_files) > 1
        outputs = []  # [(filename, text, warnings)]

        progress = st.progress(0, text="Procesando...")
        for idx, up in enumerate(uploaded_files, start=1):
            st.write(f"### 📄 {up.name}")
            try:
                pdf_bytes = up.read()
                text, warns = extract_text_from_pdf(pdf_bytes, password or None)

                # Si el usuario NO quiere headers por página, eliminamos esas líneas añadidas
                if not show_page_headers:
                    # Quitar las líneas que empiezan por --- Página N ---
                    # (Simple pero efectivo mientras este script controla el formato)
                    import re
                    text = re.sub(r"\n*\s*--- Página \d+ ---\s*\n*", "\n", text).strip()

                # Mostrar texto
                st.text_area(
                    label=f"Texto extraído de {up.name}",
                    value=text,
                    height=250,
                    key=f"txt_{up.name}",
                )

                # Descargar TXT
                txt_fname = to_txt_filename(up.name)
                st.download_button(
                    label=f"⬇️ Descargar {txt_fname}",
                    data=text.encode("utf-8"),
                    file_name=txt_fname,
                    mime="text/plain"
                )

                # Extra (local): copiar al portapapeles (usa pyperclip si está disponible)
                cc1, cc2 = st.columns([1, 4])
                with cc1:
                    if st.button("📋 Copiar", key=f"copy_{up.name}"):
                        try:
                            import pyperclip
                            pyperclip.copy(text)
                            st.success("Texto copiado al portapapeles (servidor local).")
                        except Exception:
                            st.info("No se pudo acceder al portapapeles del sistema. "
                                    "Copia manualmente desde el cuadro de texto.")

                # Warnings por archivo
                if warns:
                    with st.expander("⚠️ Avisos de extracción"):
                        for w in warns:
                            st.write(f"- {w}")

                outputs.append((txt_fname, text, warns))
                logger.info(f"Procesado OK: {up.name}")

            except ValueError as ve:
                st.error(f"{up.name}: {ve}")
                logger.error(f"{up.name}: {ve}")
            except Exception as e:
                st.error(f"{up.name}: Error al procesar. Revisa logs.")
                logger.exception(f"{up.name}: Error inesperado.")

            progress.progress(idx / len(uploaded_files), text=f"Procesado {idx}/{len(uploaded_files)}")

        # Si hubo varios, ofrecer ZIP
        if len(outputs) > 1:
            mem_zip = io.BytesIO()
            with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, text, _ in outputs:
                    zf.writestr(fname, text)
            mem_zip.seek(0)
            st.download_button(
                "⬇️ Descargar todos como ZIP",
                data=mem_zip,
                file_name="txt_convertidos.zip",
                mime="application/zip"
            )

# ============ Panel de Logs ============
with st.expander("🛠️ Logs de depuración"):
    st.code(log_stream.getvalue() or "Sin logs aún.", language="text")
