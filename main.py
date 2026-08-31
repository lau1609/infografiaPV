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
        
        # Mapeo directo por posición de preguntas (1 a 20)
        p: dict = {i: None for i in range(1, 21)}
        nacionalidad = {
            "general": None,
            "mexico": None,
            "internacional": None
        }

        color_index = 0

        for preg in data["preguntas"]:
            preg['preg_name'] = preg.get('preg_name') or preg.get('titulo') or ""
            pos = preg.get('preg_part_infog') or preg.get('columna')
            
            # Formatear nombres de respuestas si viene 'texto'
            for resp in preg['respuestas']:
                if not resp.get('respuesta') and resp.get('texto'):
                    resp['respuesta'] = resp['texto']

            # Asignación de color alternado a la pregunta
            preg['color_hex'] = COLORES[color_index % len(COLORES)]
            color_index += 1

            if pos and 1 <= pos <= 20:
                p[pos] = preg

            # Manejo específico para los bloques de Nacionalidad si vienen separados (5, 6, 7)
            if pos == 4 or pos == 5:
                nacionalidad['general'] = preg
            elif pos == 6:
                nacionalidad['mexico'] = preg
            elif pos == 7:
                nacionalidad['internacional'] = preg

        # Generar gráfica de dona transparente en Matplotlib para la Pregunta 15
        grafica_dona_base64 = ""
        if p[15] and p[15]['respuestas']:
            fig, ax = plt.subplots(figsize=(2.2, 2.2), subplot_kw=dict(aspect="equal"))
            pcts = [r['porcentaje'] for r in p[15]['respuestas']]
            colors_dona = ['#10529d', '#d0196b', '#8968c2'][:len(pcts)]

            ax.pie(
                pcts, 
                colors=colors_dona, 
                startangle=90, 
                counterclock=False,
                wedgeprops=dict(width=0.45, edgecolor='white', linewidth=2)
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
