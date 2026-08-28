import logging
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


@app.post("/generar-infografia")
async def procesar_infografia(payload: PayloadInfografia):
    try:
        COLORES = ['#8968c2', '#10529d', '#d0196b']  # Morado, Azul, Rosa
        color_index = 0

        # Convertimos el payload a diccionario para manipular los datos dinámicamente
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
            # Homologación de llaves para compatibilidad con HTML/Jinja2
            preg['preg_name'] = preg.get('preg_name') or preg.get('titulo') or ""
            part = preg.get('preg_part_infog') or preg.get('columna') or 1

            for resp in preg['respuestas']:
                if not resp.get('respuesta') and resp.get('texto'):
                    resp['respuesta'] = resp['texto']

            # 1. Filtro de respuestas (mínimo 2 respuestas o hasta sumar >= 75%)
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

            # 2. Asignación de color alternado
            preg['color_hex'] = COLORES[color_index % len(COLORES)]
            
            # 3. Separación por sección / columnas
            if part in [1, 2, 3, 4]:
                resultado['columnas'][part].append(preg)
                color_index += 1  # Cambia color solo en preguntas generales
            elif part == 5:
                resultado['nacionalidad']['general'] = preg
            elif part == 6:
                resultado['nacionalidad']['mexico'] = preg
            elif part == 7:
                resultado['nacionalidad']['internacional'] = preg

        template = env.get_template("base.html")
        html_content = template.render(**resultado)

        # 2. Capturar la imagen en alta calidad enfocada en el diseño
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            # 3x DPI para calidad Retina / 4K
            context = await browser.new_context(
                viewport={"width": 1450, "height": 1350},
                device_scale_factor=3
            )
            
            page = await context.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
        
            # Localizamos el contenedor directo
            element = page.locator("#infografia")
            
            if await element.count() > 0:
                # Toma el screenshot ajustado ÚNICAMENTE a los límites del div #infografia
                image_bytes = await element.screenshot(type="png")
            else:
                # Respaldos en caso de fallo
                image_bytes = await page.screenshot(type="png", full_page=True)
        
            await browser.close()
        
        return Response(content=image_bytes, media_type="image/png")


    except Exception as e:
        logging.error(f"Error procesando infografía: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en servidor Python: {str(e)}")
