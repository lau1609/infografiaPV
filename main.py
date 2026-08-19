import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from fastapi import FastAPI, Response, HTTPException
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
import logging
from typing import List, Optional

app = FastAPI(title="Generador de Infografías - Turismo")
env = Environment(loader=FileSystemLoader("templates"))

class Respuesta(BaseModel):
    texto: str
    porcentaje: float
    conteo: int
    icono: Optional[str] = None

class Pregunta(BaseModel):
    id: int
    titulo: str
    columna: int
    respuestas: List[Respuesta]

class PayloadInfografia(BaseModel):
    municipio: str
    fecha_inicio: str
    fecha_fin: str
    preguntas: List[Pregunta]

@app.post("/generar-infografia")
async def generar_infografia(data: PayloadInfografia):
    try:
        # 1. Filtrar preguntas que tienen respuestas
        preguntas_validas = [p for p in data.preguntas if len(p.respuestas) > 0]

        # 2. Control de escala de fuente dinámico
        total_respuestas = sum(len(p.respuestas) for p in preguntas_validas)
        font_scale = "11px" if total_respuestas > 35 else ("12px" if total_respuestas > 22 else "13px")

        # 3. Distribución por 4 columnas obligatorias
        cols = {1: [], 2: [], 3: [], 4: []}
        for preg in preguntas_validas:
            col_target = min(max(preg.columna, 1), 4)
            cols[col_target].append(preg)

        # 4. Renderizar plantilla Jinja2
        template = env.get_template("base.html")
        html_rendered = template.render(
            municipio=data.municipio.strip(),
            fecha_inicio=data.fecha_inicio,
            fecha_fin=data.fecha_fin,
            columnas=cols,
            font_scale=font_scale
        )

        # 5. Captura con Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            
            page = await browser.new_page(
                viewport={"width": 1400, "height": 900},
                device_scale_factor=2  # Alta resolución HD
            )
            
            # Cargar HTML y esperar carga de fuentes externas (Montserrat y FontAwesome)
            await page.set_content(html_rendered, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            
            # Capturar todo el contenido
            img_bytes = await page.screenshot(type="png", full_page=True)
            await browser.close()

            return Response(content=img_bytes, media_type="image/png")

    except Exception as e:
        logging.error(f"Error procesando infografía: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en servidor Python: {str(e)}")
