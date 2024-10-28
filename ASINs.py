import asyncio
import json
import random
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from typing import AsyncGenerator
import re  # Para limpiar el nombre del archivo

app = FastAPI()

async def wait_for_results(page, retries=3):
    """Espera a que se carguen los resultados con reintentos."""
    for attempt in range(retries):
        try:
            await page.wait_for_selector('div[data-component-type="s-search-result"]', timeout=10000)
            return
        except PlaywrightTimeoutError:
            if attempt + 1 == retries:
                raise HTTPException(status_code=408, detail="Timeout esperando resultados.")

async def wait_random_time(page_count):
    """Espera un tiempo aleatorio para evitar ser detectado como bot."""
    delay = random.uniform(2, 4) + (page_count * 0.02)
    await asyncio.sleep(delay)

def extract_keyword_from_url(url: str) -> str:
    """Extrae una posible palabra clave de la URL para usar como nombre de archivo."""
    parts = re.findall(r'[\w-]+', url)  # Extrae solo palabras y guiones
    if parts:
        filename = parts[-1]  # Usar la última palabra como nombre del archivo
        return re.sub(r'\W+', '_', filename) + ".json"  # Limpiar caracteres no permitidos
    return "asins.json"

async def extract_asins(url: str) -> AsyncGenerator[str, None]:
    """Extrae los ASINs de la búsqueda y guarda los resultados en un archivo JSON."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36"
        })

        all_asins = []
        page_count = 0

        try:
            await page.goto(url, timeout=30000)
            while True:
                await wait_for_results(page)
                asins = await page.evaluate('''() =>
                    Array.from(document.querySelectorAll('div[data-component-type="s-search-result"]'))
                        .map(div => div.getAttribute('data-asin'))
                        .filter(Boolean)
                ''')

                if asins:
                    all_asins.extend(asins)
                    page_count += 1
                    yield f"data: Página {page_count} - {len(asins)} ASINs encontrados. Total: {len(all_asins)}\n\n"
                else:
                    yield "data: No se encontraron más ASINs en esta página.\n\n"
                    break

                next_button = await page.query_selector('a.s-pagination-next:not([aria-disabled="true"])')
                if next_button:
                    await next_button.click()
                    await wait_random_time(page_count)
                else:
                    yield "data: No hay más páginas disponibles.\n\n"
                    break

        except PlaywrightTimeoutError:
            yield "data: Timeout esperando elementos. Terminando la extracción.\n\n"
        except Exception as e:
            yield f"data: Error inesperado: {str(e)}\n\n"
        finally:
            await browser.close()

    # Guardar los ASINs en un archivo JSON con el nombre extraído de la URL
    filename = extract_keyword_from_url(url)
    with open(filename, "w") as f:
        json.dump(all_asins, f)

    yield f"data: Extracción completada. Total de ASINs: {len(all_asins)}\n\n"

@app.get("/scrape_asins/")
async def scrape_asins(url: str):
    """Endpoint para iniciar el scraping y enviar progreso en tiempo real."""
    return StreamingResponse(extract_asins(url), media_type="text/event-stream")
