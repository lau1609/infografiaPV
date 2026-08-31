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


# --- ENDPOINT BASE ORIGINAL ---
@app.post("/generar-infografia")
async def procesar_infografia(payload: PayloadInfografia):
    try:
        COLORES = ['#8968c2', '#10529d', '#d0196b']
        color_index = 0

        data = payload.dict()
        resultado = {
            "municipio": data["municipio"],
            "fecha_inicio": data["fecha_inicio"],
            "fecha_fin": data["fecha_fin"],
            "titulo": "PERFIL DEL VISITANTE",
            "periodo": "ACUMULADO 2026",
            "columnas": {1: [], 2: [], 3: [], 4: []},
            "nacionalidad": {"general": None, "mexico": None, "internacional": None}
        }

        for preg in data["preguntas"]:
            preg['preg_name'] = preg.get('preg_name') or preg.get('titulo') or ""
            part = preg.get('preg_part_infog') or preg.get('columna') or 1

            for resp in preg['respuestas']:
                if not resp.get('respuesta') and resp.get('texto'):
                    resp['respuesta'] = resp['texto']

            respuestas_ordenadas = sorted(preg['respuestas'], key=lambda x: x['porcentaje'], reverse=True)
            respuestas_filtradas = []
            porcentaje_acumulado = 0

            for idx, resp in enumerate(respuestas_ordenadas, start=1):
                if porcentaje_acumulado < 75 or idx <= 2:
                    porcentaje_acumulado += resp['porcentaje']
                    respuestas_filtradas.append(resp)
                else:
                    break
            
            preg['respuestas'] = respuestas_filtradas
            preg['color_hex'] = COLORES[color_index % len(COLORES)]
            
            if part in [1, 2, 3, 4]:
                resultado['columnas'][part].append(preg)
                color_index += 1
            elif part == 5:
                resultado['nacionalidad']['general'] = preg
            elif part == 6:
                resultado['nacionalidad']['mexico'] = preg
            elif part == 7:
                resultado['nacionalidad']['internacional'] = preg

        template = env.get_template("base.html")
        html_content = template.render(**resultado)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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
        logging.error(f"Error procesando infografía: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en servidor Python: {str(e)}")


# --- NUEVO ENDPOINT PARA INFOGRAFÍA ESPECIAL ---
@app.post("/generar-infografia-esp")
async def procesar_infografia_especial(payload: PayloadInfografia):
    try:
        data = payload.dict()
        
        # Diccionario para mapear las 20 preguntas fijas por su posición
        p: dict = {i: None for i in range(1, 21)}

        for preg in data["preguntas"]:
            preg['preg_name'] = preg.get('preg_name') or preg.get('titulo') or ""
            pos = preg.get('preg_part_infog') or preg.get('columna')
            
            if pos and 1 <= pos <= 20:
                for resp in preg['respuestas']:
                    if not resp.get('respuesta') and resp.get('texto'):
                        resp['respuesta'] = resp['texto']
                
                # Para la pregunta 12, nos aseguramos que "Trabajo/negocios" esté siempre de segunda 
                # o identificada para que el conector apunte correctamente a las tarjetas 13 y 14.
                if pos == 12:
                    resp_trabajo = None
                    otras_resp = []
                    for r in preg['respuestas']:
                        if "trabajo" in r['respuesta'].lower() or "negocio" in r['respuesta'].lower():
                            resp_trabajo = r
                        else:
                            otras_resp.append(r)
                    if resp_trabajo:
                        # Colocamos Trabajo/negocios en la posición 2 del arreglo
                        preg['respuestas'] = [otras_resp[0]] + [resp_trabajo] + otras_resp[1:] if otras_resp else [resp_trabajo]

                p[pos] = preg

        # Generar Gráfica de Dona en Matplotlib para la pregunta 15
        grafica_dona_base64 = ""
        if p[15] and p[15]['respuestas']:
            fig, ax = plt.subplots(figsize=(2.2, 2.2), subplot_kw=dict(aspect="equal"))
            
            labels = [r['respuesta'] for r in p[15]['respuestas']]
            pcts = [r['porcentaje'] for r in p[15]['respuestas']]
            colors = ['#8968c2', '#d0196b', '#10529d', '#22c55e'][:len(pcts)]

            wedges, _ = ax.pie(
                pcts, 
                colors=colors, 
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
            "grafica_dona": grafica_dona_base64
        }

        template = env.get_template("especial.html")
        html_content = template.render(**contexto_render)

        # Captura con Playwright
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
