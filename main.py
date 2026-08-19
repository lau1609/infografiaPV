import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt

from fastapi import FastAPI, Response, HTTPException
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
import io
import base64
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

def generar_pie_chart_b64(labels: list, valores: list) -> str:
    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    colores = ['#6B21A8', '#2563EB', '#EC4899', '#10B981', '#F59E0B']
    
    wedges, texts, autotexts = ax.pie(
        valores, 
        labels=labels, 
        autopct='%1.0f%%', 
        startangle=140, 
        colors=colores,
        textprops=dict(color="w", weight="bold")
    )
    plt.setp(autotexts, size=9)
    plt.setp(texts, size=8, color="#333333")
    ax.axis('equal')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=150)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

@app.post("/generar-infografia")
async def generar_infografia(data: PayloadInfografia):
    try:
        muni_key = data.municipio.strip().lower().replace("-", " ")
        es_especial = muni_key in ["chihuahua", "casas grandes"]
        
        # 1. Filtrar preguntas que NO tienen respuestas
        preguntas_validas = [p for p in data.preguntas if len(p.respuestas) > 0]
        
        # 2. Control de desborde
        total_respuestas = sum(len(p.respuestas) for p in preguntas_validas)
        font_scale = "0.78rem" if total_respuestas > 28 else ("0.85rem" if total_respuestas > 20 else "0.95rem")

        # 3. Organizar por columnas (1 a 4)
        cols = {1: [], 2: [], 3: [], 4: []}
        tiene_mexico = False
        tiene_internacional = False

        for preg in preguntas_validas:
            for r in preg.respuestas:
                txt = r.texto.lower()
                if "méxico" in txt or "mexico" in txt:
                    tiene_mexico = True
                if "internacional" in txt:
                    tiene_internacional = True
            
            # Garantiza que el rango sea siempre de 1 a 4
            col_target = min(max(preg.columna, 1), 4)
            cols[col_target].append(preg)

        # 4. Generar gráfico de pastel para municipios especiales
        grafico_pie_b64 = None
        if es_especial:
            labels = ["Hotel", "Casa Familiar", "Airbnb / Otro"]
            valores = [55, 30, 15]
            grafico_pie_b64 = generar_pie_chart_b64(labels, valores)

        # 5. Renderizar plantilla Jinja2
        template_name = "especial.html" if es_especial else "base.html"
        template = env.get_template(template_name)
        
        html_rendered = template.render(
            municipio=data.municipio.replace("-", " ").title(),
            fecha_inicio=data.fecha_inicio,
            fecha_fin=data.fecha_fin,
            columnas=cols,
            grafico_pie=grafico_pie_b64,
            font_scale=font_scale,
            tiene_mexico=tiene_mexico,
            tiene_internacional=tiene_internacional
        )

        # 6. Capturar Screenshot con Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = await browser.new_page(viewport={"width": 1300, "height": 800})
            
            # Cargar contenido y esperar recursos de red (fuentes)
            await page.set_content(html_rendered, wait_until="networkidle")
            
            # Esperar explícitamente a que el motor de fuentes termine
            await page.evaluate("document.fonts.ready")
            
            img_bytes = await page.screenshot(type="png", full_page=False)
            await browser.close()

        return Response(content=img_bytes, media_type="image/png")

    except Exception as e:
        logging.error(f"Error procesando la infografía: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en servidor Python: {str(e)}")
