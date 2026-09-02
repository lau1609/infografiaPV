import base64
import io
import logging
import re
import urllib.parse
import urllib.request
from typing import List, Optional

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request, Response
from jinja2 import Environment, FileSystemLoader
import matplotlib
from pydantic import BaseModel

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from playwright.async_api import async_playwright

app = FastAPI(title="Generador de Infografías - Turismo")
env = Environment(loader=FileSystemLoader("templates"))

COLORES = ["#8968c2", "#10529d", "#d0196b"]


class Respuesta(BaseModel):
    respuesta: Optional[str] = None
    texto: Optional[str] = None
    porcentaje: float
    conteo: Optional[int] = 0
    icono: Optional[str] = None


class Pregunta(BaseModel):
    id: Optional[int] = None
    titulo: Optional[str] = None
    preg_name: Optional[str] = None
    columna: Optional[int] = None
    preg_part_infog: Optional[int] = None
    respuestas: List[Respuesta]


class PayloadInfografia(BaseModel):
    municipio: str
    fecha_inicio: str
    fecha_fin: str
    preguntas: List[Pregunta]


def cambiar_color_svg(svg_content: str, nuevo_color: str) -> str:
    """Modifica el atributo fill en etiquetas <svg>, <path>, <circle>, <rect>, etc.,

    así como dentro de atributos CSS style='fill:...' para garantizar un color uniforme.
    """
    try:
        soup = BeautifulSoup(svg_content, "xml")
        svg_tag = soup.find("svg")
        if not svg_tag:
            soup = BeautifulSoup(svg_content, "html.parser")
            svg_tag = soup.find("svg")

        if not svg_tag:
            return svg_content

        # Asegurar espacio de nombres XML para que Playwright lo renderice correctamente
        if not svg_tag.get("xmlns"):
            svg_tag["xmlns"] = "http://www.w3.org/2000/svg"

        # Si la etiqueta principal tiene fill (distinto de 'none'), actualizarlo
        if svg_tag.get("fill") and svg_tag["fill"].lower() != "none":
            svg_tag["fill"] = nuevo_color

        # Procesar todos los elementos gráficos internos
        elementos = soup.find_all(
            ["path", "circle", "rect", "polygon", "polyline", "g", "ellipse"]
        )

        for el in elementos:
            # A) Manejar estilos CSS inline (ej: style="fill:#000; stroke:none;")
            if el.get("style"):
                estilos = el["style"].split(";")
                nuevos_estilos = []
                tiene_fill = False
                for est in estilos:
                    if est.strip().startswith("fill:"):
                        if "none" in est.lower():
                            nuevos_estilos.append("fill:none")
                        else:
                            nuevos_estilos.append(f"fill:{nuevo_color}")
                        tiene_fill = True
                    elif est.strip():
                        nuevos_estilos.append(est)

                if not tiene_fill and "none" not in str(
                    el.get("fill", "")
                ).lower():
                    nuevos_estilos.append(f"fill:{nuevo_color}")

                el["style"] = ";".join(nuevos_estilos)

            # B) Manejar atributo fill directos (ej: fill="#123456")
            elif el.get("fill"):
                if el["fill"].lower() != "none":
                    el["fill"] = nuevo_color
            # C) Si no especifica fill, forzar el nuevo color
            else:
                el["fill"] = nuevo_color

        return str(soup)
    except Exception as e:
        logging.warning(f"Error procesando XML/SVG con BeautifulSoup: {e}")
        return svg_content


@app.post("/generar-infografia")
async def procesar_infografia(payload: PayloadInfografia):
    try:
        COLORES = ["#8968c2", "#10529d", "#d0196b"]
        color_index = 0

        data = payload.dict()
        resultado = {
            "municipio": data["municipio"],
            "fecha_inicio": data["fecha_inicio"],
            "fecha_fin": data["fecha_fin"],
            "titulo": "PERFIL DEL VISITANTE",
            "periodo": "ACUMULADO 2026",
            "columnas": {1: [], 2: [], 3: [], 4: []},
            "nacionalidad": {
                "general": None,
                "mexico": None,
                "internacional": None,
            },
        }

        for preg in data["preguntas"]:
            preg["preg_name"] = (
                preg.get("preg_name") or preg.get("titulo") or ""
            )
            part = preg.get("preg_part_infog") or preg.get("columna") or 1

            color_actual = COLORES[color_index % len(COLORES)]
            preg["color_hex"] = color_actual

            for resp in preg["respuestas"]:
                if not resp.get("respuesta") and resp.get("texto"):
                    resp["respuesta"] = resp["texto"]

                url_icono = resp.get("icono")
                if url_icono and url_icono.lower().endswith(".svg"):
                    try:
                        # Codificación limpia de la URL
                        url_limpia = urllib.parse.unquote(url_icono)
                        url_parsed = urllib.parse.urlparse(url_limpia)
                        path_encoded = urllib.parse.quote(url_parsed.path)
                        url_final = urllib.parse.urlunparse(
                            (
                                url_parsed.scheme,
                                url_parsed.netloc,
                                path_encoded,
                                url_parsed.params,
                                url_parsed.query,
                                url_parsed.fragment,
                            )
                        )

                        req = urllib.request.Request(
                            url_final, headers={"User-Agent": "Mozilla/5.0"}
                        )
                        with urllib.request.urlopen(req, timeout=5) as response:
                            svg_bytes = response.read()
                            svg_data = svg_bytes.decode(
                                "utf-8", errors="ignore"
                            )

                        # Parseo inteligente de SVG (sirve para <svg>, <path>, <g>, styles, etc.)
                        svg_modificado = cambiar_color_svg(
                            svg_data, color_actual
                        )

                        svg_b64 = base64.b64encode(
                            svg_modificado.encode("utf-8")
                        ).decode("utf-8")
                        resp["icono"] = f"data:image/svg+xml;base64,{svg_b64}"

                    except Exception as err_icon:
                        logging.warning(
                            f"No se pudo procesar el SVG ({url_icono}): {err_icon}"
                        )

            # Filtrar y ordenar respuestas al 75%
            respuestas_ordenadas = sorted(
                preg["respuestas"], key=lambda x: x["porcentaje"], reverse=True
            )
            respuestas_filtradas = []
            porcentaje_acumulado = 0

            for idx, resp in enumerate(respuestas_ordenadas, start=1):
                if porcentaje_acumulado < 75 or idx <= 2:
                    porcentaje_acumulado += resp["porcentaje"]
                    respuestas_filtradas.append(resp)
                else:
                    break

            preg["respuestas"] = respuestas_filtradas

            if part in [1, 2, 3, 4]:
                resultado["columnas"][part].append(preg)
                color_index += 1
            elif part == 5:
                resultado["nacionalidad"]["general"] = preg
            elif part == 6:
                resultado["nacionalidad"]["mexico"] = preg
            elif part == 7:
                resultado["nacionalidad"]["internacional"] = preg

        template = env.get_template("base.html")
        html_content = template.render(**resultado)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1450, "height": 1350}, device_scale_factor=3
            )
            page = await context.new_page()

            # Cargamos el HTML esperando a que la red se estabilice
            await page.set_content(html_content, wait_until="networkidle")

            # Forzar a esperar que todas las imágenes del DOM carguen sus bytes realmente
            await page.evaluate("""async () => {
                const imgs = Array.from(document.images);
                await Promise.all(imgs.map(img => {
                    if (img.complete) return Promise.resolve();
                    return new Promise(resolve => {
                        img.onload = resolve;
                        img.onerror = resolve; // Continuar aun si una falla
                    });
                }));
            }""")

            await page.evaluate("document.fonts.ready")

            element = page.locator("#infografia")
            if await element.count() > 0:
                image_bytes = await element.screenshot(type="png")
            else:
                image_bytes = await page.screenshot(
                    type="png", full_page=True
                )

            await browser.close()

        return Response(content=image_bytes, media_type="image/png")

    except Exception as e:
        logging.error(
            f"Error procesando infografía: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Error en servidor Python: {str(e)}"
        )


@app.post("/generar-infografia-esp")
async def procesar_infografia_especial(payload: PayloadInfografia):
    try:
        data = payload.dict()

        p: dict = {i: None for i in range(1, 21)}
        nacionalidad = {
            "general": None,
            "mexico": None,
            "internacional": None,
        }

        color_idx = 0

        for preg in data["preguntas"]:
            preg["preg_name"] = (
                preg.get("preg_name") or preg.get("titulo") or ""
            )
            pos = preg.get("preg_part_infog") or preg.get("columna")

            # Asignar color alternado a la tarjeta
            preg["color_hex"] = COLORES[color_idx % len(COLORES)]
            color_idx += 1

            for resp in preg["respuestas"]:
                if not resp.get("respuesta") and resp.get("texto"):
                    resp["respuesta"] = resp["texto"]

            if pos and 1 <= pos <= 20:
                p[pos] = preg

            # Mapeo específico de Nacionalidad (4, 5, 6)
            if pos == 4:
                nacionalidad["general"] = preg
            elif pos == 5:
                nacionalidad["mexico"] = preg
            elif pos == 6:
                nacionalidad["internacional"] = preg

        # Identificar la posición index de "Trabajo/negocios" en la pregunta 12 para el conector SVG
        idx_trabajo_12 = 0
        if p[12] and p[12]["respuestas"]:
            for index, r in enumerate(p[12]["respuestas"]):
                if (
                    "trabajo" in r["respuesta"].lower()
                    or "negocio" in r["respuesta"].lower()
                ):
                    idx_trabajo_12 = index
                    break

        # Generar Gráfica Circular Completa en Matplotlib para la pregunta 15
        grafica_dona_base64 = ""
        if p[15] and p[15]["respuestas"]:
            fig, ax = plt.subplots(
                figsize=(2.5, 2.5), subplot_kw=dict(aspect="equal")
            )

            pcts = [r["porcentaje"] for r in p[15]["respuestas"]]
            labels = [
                f"{int(r['porcentaje'])}%\n{r['respuesta'].upper()}"
                for r in p[15]["respuestas"]
            ]

            colors_pie = [
                "#d0196b",
                "#8968c2",
                "#10529d",
                "#22c55e",
                "#f59e0b",
            ][: len(pcts)]

            wedges, texts = ax.pie(
                pcts,
                labels=labels,
                labeldistance=0.55,
                colors=colors_pie,
                startangle=90,
                counterclock=False,
                wedgeprops=dict(edgecolor="white", linewidth=1.5),
                textprops=dict(
                    color="white",
                    fontweight="bold",
                    fontsize=12,
                    ha="center",
                    va="center",
                ),
            )

            buf = io.BytesIO()
            plt.savefig(
                buf,
                format="png",
                transparent=True,
                bbox_inches="tight",
                pad_inches=0,
            )
            plt.close(fig)
            buf.seek(0)
            grafica_dona_base64 = base64.b64encode(buf.read()).decode("utf-8")

        contexto_render = {
            "municipio": data["municipio"],
            "fecha_inicio": data["fecha_inicio"],
            "fecha_fin": data["fecha_fin"],
            "p": p,
            "nacionalidad": nacionalidad,
            "idx_trabajo_12": idx_trabajo_12,
            "grafica_dona": grafica_dona_base64,
        }

        template = env.get_template("especial.html")
        html_content = template.render(**contexto_render)

        async with async_playwright() as p_play:
            browser = await p_play.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1450, "height": 1350},
                device_scale_factor=3,
            )
            page = await context.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")

            element = page.locator("#infografia")
            if await element.count() > 0:
                image_bytes = await element.screenshot(type="png")
            else:
                image_bytes = await page.screenshot(
                    type="png", full_page=True
                )

            await browser.close()

        return Response(content=image_bytes, media_type="image/png")

    except Exception as e:
        logging.error(
            f"Error procesando infografía especial: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Error en servidor Python: {str(e)}"
        )
