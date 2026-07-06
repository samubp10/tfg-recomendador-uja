# ADR-0002: Scrapy frente a alternativas para la extracción de datos

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** Aceptada
- **Fecha:** 2026-07-05
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 0 (scraping + chunking) del Recomendador UJA

## Contexto

El proyecto necesita construir un dataset estructurado a partir de la web
pública de la Escuela Politécnica Superior de Jaén (EPSJ) de la Universidad
de Jaén, que sirva de base documental para el chatbot RAG. El dataset debe contener la información de los grados y asignaturas y más información que se considere relevante para el funcionamiento del chatbot de los grados de la EPSJ.

La web de la EPSJ está construida sobre Drupal y sirve HTML estático (no
requiere renderizado de JavaScript). Se detectaron dos particularidades determinantes:

1. **Encoding inconsistente:** las 296 guías docentes declaran UTF-8 en la
   etiqueta `<meta>` del HTML pero el servidor las sirve como ISO-8859-1 en
   la cabecera HTTP `Content-Type`. Un extractor que priorice la cabecera
   HTTP decodifica correctamente; uno que priorice el `<meta>` corrompe
   tildes y eñes.
2. **Slugs (parte final de la URL) inconsistentes:** las URLs de asignaturas y guías no siguen un
   patrón predecible, por lo que la extracción debe seguir los `href`
   reales del DOM en vez de construir URLs por plantilla.

Se requiere además: respeto de `robots.txt`, una cadencia de peticiones acorde hacia el
servidor de la UJA, testeabilidad offline con fixtures HTML reales y un
framework maduro y mantenido.

## Alternativas consideradas

### Opción A — Scrapy (elegida)

Framework asíncrono completo de crawling (rastreo web).
- **URL:** [https://scrapy.org/](https://scrapy.org/)

- **Encoding:** `TextResponse`/`HtmlResponse` resuelven la codificación en
  este orden: 
    1. cabecera HTTP `Content-Type`, 
    2. BOM/declaración,
    3. `<meta>` del cuerpo, 
    4. autodetección. 
  Al priorizar la cabecera HTTP, Scrapy decodifica correctamente las guías ISO-8859-1 servidas como tal, resolviendo el problema 1 sin código adicional.
- **robots.txt:** soporte nativo mediante `ROBOTSTXT_OBEY = True` 
- **Throttling:** `DOWNLOAD_DELAY`, `AUTOTHROTTLE_ENABLED` y
  `CONCURRENT_REQUESTS_PER_DOMAIN` permiten que el proceso de rastreo web no sature al servidor.
- **Testing offline:** `HtmlResponse` es un objeto que contiene el cuerpo HTML, la URL, cabeceras HTTP, permitiendo usarlo en pruebas sin necesidad de red.
- **Madurez:** framework de referencia, mantenido activamente, con
  `py.typed` (PEP 561) desde la serie 2.13.
- **Contra:** Difícil de aprender y entender al inicio por su complejidad y completitud.

### Opción B — BeautifulSoup + requests

Parser de HTML (BeautifulSoup) combinado con un cliente HTTP (requests).
- **URL BeautifulSoup:** [https://www.crummy.com/software/BeautifulSoup/](https://www.crummy.com/software/BeautifulSoup/)
- **URL requests:** [https://requests.readthedocs.io/](https://requests.readthedocs.io/)

- **Pros:** simplicidad, ideal para tareas pequeñas y estáticas.
- **Contras:** BeautifulSoup no es un rastreador web (no gestiona colas, reintentos
  ni rate limiting); requests no respeta `robots.txt` automáticamente; el
  manejo de encoding queda en manos del desarrollador. Una herramienta demasiado simple para lo que realmente necesitamos

### Opción C — Selenium / Playwright

Automatización de navegador con renderizado real.
- **URL Selenium:** [https://www.selenium.dev/](https://www.selenium.dev/)
- **URL Playwright:** [https://playwright.dev/](https://playwright.dev/)

- **Pros:** imprescindibles para SPAs y contenido cargado por JavaScript. 
- **Contras:** la web de la EPSJ es Drupal estático, por lo que el
  renderizado de JS es innecesario, por lo que haría que el programa fuera más lento y pesado en recursos.


## Decisión

Se adopta **Scrapy**. La evidencia del encoding fue el factor decisivo, reforzado por el soporte
nativo de `robots.txt`, el throttling configurable, la testabilidad offline
con `HtmlResponse` y la gran comunidad de soporte que tiene. Las alternativas o bien
exigían reimplementar manualmente esas garantías o bien estaban
sobredimensionadas para un sitio estático.

## Consecuencias

### Positivas
- Scrapy resuelve automáticamente el problema de los caracteres extraños (como ñ, á, ü) sin tener que escribir funciones manuales de decodificación.
- Scrapy permite hacer peticiones respetuosas hacia la web de la EPSJ (para no saturar el servidor).
- Tests deterministas y offline con fixtures HTML reales de la propia página.
- `py.typed` permite type-checking del código del spider con mypy.

### Negativas
- Curva de aprendizaje de Scrapy y de su modelo basado en llamadas asíncronas y eventos.
- Dependencia pesada, por lo que seguramente traiga cosas que no vayamos a utilizar en el proyecto.
- Si en un futuro la EPSJ cambia su web por una SPA con mucho JavaScript, habría que integrar `scrapy-playwright`, que es otra librería más que deberíamos aprender y usar.

## Referencias
- Sitio oficial de Scrapy: [https://scrapy.org/](https://scrapy.org/)
- Sitio oficial de BeautifulSoup: [https://www.crummy.com/software/BeautifulSoup/](https://www.crummy.com/software/BeautifulSoup/)
- Documentación oficial de requests: [https://requests.readthedocs.io/](https://requests.readthedocs.io/)
- Sitio oficial de Selenium: [https://www.selenium.dev/](https://www.selenium.dev/)
- Sitio oficial de Playwright: [https://playwright.dev/](https://playwright.dev/)
- Documentación de Scrapy: TextResponse y resolución de encoding ([docs.scrapy.org, "Requests and Responses"](https://docs.scrapy.org/en/latest/topics/request-response.html)).
- Documentación de Scrapy: [RobotsTxtMiddleware](https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#module-scrapy.downloadermiddlewares.robotstxt) / [AutoThrottle](https://docs.scrapy.org/en/latest/topics/autothrottle.html) / [Settings](https://docs.scrapy.org/en/latest/topics/settings.html).
- PEP 561; notas de la versión Scrapy 2.13 ("Added py.typed, in line with
  PEP 561").
- M. Nygard, "Documenting Architecture Decisions", cognitect.com ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).