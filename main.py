import logging
import io
import base64
from typing import List, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from fastapi import FastAPI, Response, HTTPException
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

app = FastAPI(title="Generador de Infografías - Turismo")
env = Environment(loader=FileSystemLoader("templates"))

COLORES = ['#8968c2', '#10529d', '#d0196b']

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


@app.post("/generar-infografia-esp")
async def procesar_infografia_especial(payload: PayloadInfografia):
    try:
        data = payload.dict()
        
        p: dict = {i: None for i in range(1, 21)}
        nacionalidad = {
            "general": None,
            "mexico": None,
            "internacional": None
        }

        color_idx = 0

        for preg in data["preguntas"]:
            preg['preg_name'] = preg.get('preg_name') or preg.get('titulo') or ""
            pos = preg.get('preg_part_infog') or preg.get('columna')
            
            # Asignar color alternado a la tarjeta
            preg['color_hex'] = COLORES[color_idx % len(COLORES)]
            color_idx += 1

            for resp in preg['respuestas']:
                if not resp.get('respuesta') and resp.get('texto'):
                    resp['respuesta'] = resp['texto']

            if pos and 1 <= pos <= 20:
                p[pos] = preg

            # Mapeo específico de Nacionalidad (4, 5, 6)
            if pos == 4:
                nacionalidad['general'] = preg
            elif pos == 5:
                nacionalidad['mexico'] = preg
            elif pos == 6:
                nacionalidad['internacional'] = preg

        # Identificar la posición index de "Trabajo/negocios" en la pregunta 12 para el conector SVG
        idx_trabajo_12 = 0
        if p[12] and p[12]['respuestas']:
            for index, r in enumerate(p[12]['respuestas']):
                if "trabajo" in r['respuesta'].lower() or "negocio" in r['respuesta'].lower():
                    idx_trabajo_12 = index
                    break

        # Generar Gráfica de Dona en Matplotlib para la pregunta 15
        grafica_dona_base64 = ""
        if p[15] and p[15]['respuestas']:
            fig, ax = plt.subplots(figsize=(2.2, 2.2), subplot_kw=dict(aspect="equal"))
            
            pcts = [r['porcentaje'] for r in p[15]['respuestas']]
            colors_dona = ['#d0196b', '#8968c2', '#10529d', '#22c55e', '#f59e0b'][:len(pcts)]

            ax.pie(
                pcts, 
                colors=colors_dona, 
                startangle=90, 
                counterclock=False,
                wedgeprops=dict(width=0.42, edgecolor='white', linewidth=2)
            )
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', transparent=True, bbox_inches='tight', pad_inches=0)
            plt.close(fig)
            buf.seek(0)
            grafica_dona_base64 = base64.b64encode(buf.read()).decode('utf-8')

        contexto_render = {
            "municipio": data["municipio"],
            "fecha_inicio": data["fecha_inicio"],
            "fecha_fin": data["fecha_fin"],
            "p": p,
            "nacionalidad": nacionalidad,
            "idx_trabajo_12": idx_trabajo_12,
            "grafica_dona": grafica_dona_base64
        }

        template = env.get_template("especial.html")
        html_content = template.render(**contexto_render)

        async with async_playwright() as p_play:
            browser = await p_play.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1450, "height": 1350},
                device_scale_factor=3
            )
            page = await context.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
        
            element = page.locator("#infografia")
            if await element.count() > 0:
                image_bytes = await element.screenshot(type="png")
            else:
                image_bytes = await page.screenshot(type="png", full_page=True)
        
            await browser.close()
        
        return Response(content=image_bytes, media_type="image/png")

    except Exception as e:
        logging.error(f"Error procesando infografía especial: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en servidor Python: {str(e)}")
