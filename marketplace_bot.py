# -*- coding: utf-8 -*- # Añadido para asegurar compatibilidad con caracteres especiales
import requests
import json
import time
import telebot
import threading
from collections import defaultdict, deque
from dotenv import load_dotenv
import os
from telebot import types
import logging
import html as html_lib
import random

USER_SEARCHES_FILE = 'user_searches.json'
PRODUCT_HISTORY_FILE = 'product_history.json'

user_searches_lock = threading.Lock()
product_history_lock = threading.Lock()

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
FACEBOOK_COOKIE = os.getenv("FACEBOOK_COOKIE")

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Verificar configuración esencial
if not BOT_TOKEN:
    logger.critical("Error: No se encontró BOT_TOKEN en las variables de entorno.")
    exit() 

if not FACEBOOK_COOKIE:
    logger.warning("Advertencia: No se encontró FACEBOOK_COOKIE en las variables de entorno. Las búsquedas de Marketplace podrían fallar.")
    exit()


# Constantes
REFRESH_INTERVAL_SECONDS_MIN = 185
REFRESH_INTERVAL_SECONDS_MAX = 353
MAX_PRODUCT_HISTORY = 30
DEFAULT_REQUEST_TIMEOUT = 30
WAIT_FOR_BOT_SEC = 1

def rand_refresh_interval():
    return random.randint(REFRESH_INTERVAL_SECONDS_MIN, REFRESH_INTERVAL_SECONDS_MAX)


# Coordenadas por defecto (Rosario)
DEFAULT_LATITUDE = -32.95
DEFAULT_LONGITUDE = -60.64
DEFAULT_RADIUS_KM = 65

# Inicialización del bot
bot = telebot.TeleBot(BOT_TOKEN)

# --- Estructuras de datos globales ---
# user_searches: { user_id: { search_term: {'active': bool, 'chat_id': int}, ... } } - Guarda las alertas configuradas y su estado
user_searches = defaultdict(dict)
# notified_products: { user_id: { search_term: set(product_ids) } } - Rastrea los productos ya notificados por ID
notified_products = defaultdict(lambda: defaultdict(set))
# product_history: { user_id: { search_term: deque([product_dict, ...], maxlen=MAX_PRODUCT_HISTORY) } } - Guarda el historial reciente de productos encontrados
product_history = defaultdict(lambda: defaultdict(lambda: deque(maxlen=MAX_PRODUCT_HISTORY)))
# active_monitoring_threads: { f"{user_id}_{search_term}": threading.Event() } - Para controlar la ejecución de los hilos de monitoreo
active_monitoring_threads = {}
# first_scrape_done: { f"{user_id}_{search_term}": bool } - Flag para la primera búsqueda (no notificar los productos iniciales)
first_scrape_done = defaultdict(bool)
# search_in_progress: { user_id: bool } - Flag para evitar que un usuario inicie múltiples búsquedas manuales a la vez
search_in_progress = defaultdict(bool)



def monitor_from_history():
    time.sleep(WAIT_FOR_BOT_SEC)
    for user_id, alerts_for_user in user_searches.items():
        alert_terms = [term for term in alerts_for_user.keys() if term != 'waiting_for_search']
        for search_term in alert_terms:
            alert_details = alerts_for_user[search_term]
            if alert_details.get('active', False):
                chat_id = alert_details.get('chat_id')
                if chat_id:
                    logger.info(f"Reiniciando monitoreo para '{search_term}' (Usuario: {user_id}, Chat: {chat_id})")
                    thread_key = f"{user_id}_{search_term}"
                    if thread_key not in active_monitoring_threads:
                        stop_event = threading.Event()
                        monitor_thread = threading.Thread(
                            target=monitor_search,
                            args=(user_id, chat_id, search_term, stop_event),
                            daemon=True
                        )
                        monitor_thread.start()
                        active_monitoring_threads[thread_key] = stop_event
                    else:
                        logger.warning(f"Intento de reiniciar hilo para '{search_term}' ({user_id}) pero ya estaba registrado.")
                else:
                    logger.warning(f"Alerta activa para '{search_term}' (Usuario: {user_id}) cargada sin chat_id. No se puede reiniciar monitoreo.")


def load_data(filepath):
    if not os.path.exists(filepath):
        logger.warning(f"Archivo no encontrado: {filepath}. Devolviendo diccionario vacío.")
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info(f"Datos cargados correctamente desde {filepath}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON desde {filepath}: {e}")
        logger.warning(f"Archivo {filepath} parece corrupto. Se ignorarán sus datos y se empezará con un diccionario vacío.")
        return {}
    except Exception as e:
        logger.exception(f"Error inesperado al cargar datos desde {filepath}: {e}")
        return {}

def save_data(data, filepath, lock):
    # Función auxiliar para convertir deques a listas recursivamente
    def convert_deques_to_lists(obj):
        if isinstance(obj, deque):
            # Si encontramos un deque, lo convertimos a lista
            return list(obj)
        elif isinstance(obj, dict):
            # Si encontramos un diccionario, aplicamos la conversión a sus valores
            return {k: convert_deques_to_lists(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            # Si encontramos una lista, aplicamos la conversión a sus elementos (por si hay deques anidados, aunque no debería pasar aquí)
            return [convert_deques_to_lists(item) for item in obj]
        else:
            # Si es otro tipo (string, int, bool, None), lo devolvemos directamente
            return obj

    if isinstance(data, defaultdict):
        data_to_serialize = convert_deques_to_lists(dict(data)) 
    else:
        data_to_serialize = convert_deques_to_lists(data)

    with lock:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_serialize, f, ensure_ascii=False, indent=4) # indent para formato legible

        except Exception as e:
            logger.exception(f"Error guardando datos en {filepath}: {e}. Intentando limpiar archivo temporal.")

def load_user_searches():
    loaded_user_searches_data = load_data(USER_SEARCHES_FILE)
    for user_id_str, alerts_data in loaded_user_searches_data.items():
        try:
            user_id = int(user_id_str) # Asegurarse de que user_id sea INTEGER
            if isinstance(alerts_data, dict):
                    user_searches[user_id] = alerts_data # Copiar el dict de alertas
                    # Asegurarse de que las alertas cargadas tengan la clave 'active' booleana y 'chat_id' int
                    for search_term, alert_details in user_searches[user_id].items():
                        if search_term == 'waiting_for_search':
                            continue
                        if isinstance(alert_details, dict):
                            alert_details['active'] = bool(alert_details.get('active', False)) # Convertir a booleano
                            alert_details['chat_id'] = int(alert_details.get('chat_id', 0)) # Asegurar int, default 0 si falta
                        else:
                            logger.warning(f"Datos de alerta no válidos para user {user_id}: {alerts_data}")
            else:
                    logger.warning(f"Datos de usuario no válidos cargados para user {user_id_str}: {alerts_data}")
        except ValueError:
            logger.warning(f"User ID no válido cargado (no es entero): {user_id_str}")
    return loaded_user_searches_data

def load_product_history():

    loaded_product_history_data = load_data(PRODUCT_HISTORY_FILE)
    for user_id_str, searches_data in loaded_product_history_data.items():
        try:
            user_id = int(user_id_str)
            if isinstance(searches_data, dict):
                product_history[user_id] = defaultdict(lambda: deque(maxlen=MAX_PRODUCT_HISTORY)) # Inicializar defaultdict anidado
                for search_term, history_list in searches_data.items():
                        if isinstance(history_list, list):
                            product_history[user_id][search_term].extend(history_list)
                        else:
                            logger.warning(f"Historial no válido para user {user_id}, search '{search_term}': {history_list}")
            else:
                    logger.warning(f"Datos de historial de usuario no válidos cargados para user {user_id_str}: {searches_data}")
        except ValueError:
            logger.warning(f"User ID no válido cargado en historial (no es entero): {user_id_str}")

# --- Funciones Auxiliares ---

def create_inline_keyboard(options=None, back_button=True, back_callback="main_menu"):
    """Genera teclados inline."""
    markup = types.InlineKeyboardMarkup(row_width=2)

    if not options:
        # Teclado principal
        buttons = [
            types.InlineKeyboardButton("🔍 Nueva Alerta", callback_data="new_search"), # Cambiado a "Alerta"
            types.InlineKeyboardButton("📋 Mis Alertas", callback_data="list_alerts"),
            types.InlineKeyboardButton("🔔 Activar Notif.", callback_data="select_alert_activate"),
            types.InlineKeyboardButton("🔕 Desactivar Notif.", callback_data="select_alert_deactivate"),
            types.InlineKeyboardButton("🔄 Buscar Ahora", callback_data="select_alert_search_now"),
            types.InlineKeyboardButton("❌ Eliminar Alerta", callback_data="select_alert_delete")
        ]
        # Organiza en filas
        markup.add(buttons[0], buttons[1])
        markup.add(buttons[2], buttons[3])
        markup.add(buttons[4], buttons[5])
    else:
        # Teclado personalizado
        button_list = [types.InlineKeyboardButton(text, callback_data=callback) for text, callback in options.items()]
        markup.add(*button_list) # Añade botones desempaquetados

        if back_button:
            markup.add(types.InlineKeyboardButton("⬅️ Volver", callback_data=back_callback))

    return markup

def is_valid_search_term(term):
    """Valida que el término de búsqueda sea adecuado."""
    if not term or not term.strip():
        return False
    return True

def send_product_message(chat_id, product, reply_markup=None):
    """Envía un mensaje de Telegram con la información de un producto."""
    # Usar html_lib.escape para sanear los datos antes de enviarlos con parse_mode='HTML'
    title = html_lib.escape(product.get('titulo', 'Sin título'))
    price = html_lib.escape(product.get('precio', 'Sin precio'))
    url = html_lib.escape(product.get('url', '#'))
    city = html_lib.escape(product.get('ciudad', 'Ubicación desconocida'))
    image_url = product.get('imagen_url')

    message = (
        f"🛍️ Nuevo Producto:\n\n"
        f"<b>{title}</b>\n\n"
        f"💰 <b>Precio:</b> {price}\n"
        f"📍 <b>Ubicación:</b> {city}\n"
        f"🔗 <a href='{url}'>Ver en Facebook Marketplace</a>"
    )
    
    try:
        # Intentar enviar con foto si hay URL de imagen
        if image_url:
            bot.send_photo(
                chat_id,
                photo=image_url,
                caption=message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            # Enviar como mensaje de texto si no hay foto
            bot.send_message(
                chat_id,
                message,
                parse_mode='HTML',
                disable_web_page_preview=True, # Desactivar preview si no hay foto adjunta
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error enviando mensaje de producto al chat {chat_id}: {e}")
        # Si falla send_photo o send_message, intentar enviar solo el enlace como fallback
        try:
             bot.send_message(
                chat_id,
                f"🛍️ Nuevo Producto: <a href='{url}'>{title} - {price}</a>",
                parse_mode='HTML',
                disable_web_page_preview=False # Habilitar preview para el enlace directo
            )
        except Exception as e_fallback:
             logger.error(f"Error en fallback enviando enlace de producto al chat {chat_id}: {e_fallback}")


def generate_html(products, search_term):
    """Genera un archivo HTML con los productos."""
    # Usar html_lib.escape para seguridad
    safe_search_term = html_lib.escape(search_term)
    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resultados Marketplace para {safe_search_term}</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; background-color: #f4f4f4; line-height: 1.6; }}
        .product {{
            border: 1px solid #ddd; padding: 15px; margin-bottom: 15px;
            border-radius: 8px; background-color: #fff;
            display: flex; align-items: center; gap: 15px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .product img {{
            max-width: 100px; max-height: 100px; /* Tamaño de imagen más pequeño */
            object-fit: cover; border-radius: 4px;
            flex-shrink: 0; /* Evita que la imagen se encoja */
        }}
        .product-info {{ flex-grow: 1; }}
        .title {{ font-size: 1.1em; margin: 0 0 5px 0; font-weight: bold; }}
        .price {{ color: #008000; font-weight: bold; margin: 5px 0; font-size: 1em; }}
        .location {{ color: #555; font-size: 0.9em; margin-bottom: 5px; }}
        a {{ color: #1877f2; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        h1 {{ color: #333; border-bottom: 2px solid #1877f2; padding-bottom: 10px; }}
        p {{ margin: 0 0 10px 0; }}
    </style>
</head>
<body>
    <h1>Resultados de Facebook Marketplace para: {safe_search_term}</h1>
"""

    if not products:
        html_content += "<p>No se encontraron productos recientes para esta búsqueda.</p>"
    else:
        for product in products:
            # Usar .get() con valores por defecto por si falta algún campo
            title = html_lib.escape(product.get('titulo', 'Sin título'))
            price = html_lib.escape(product.get('precio', 'Sin precio'))
            url = html_lib.escape(product.get('url', '#'))
            image_url = html_lib.escape(product.get('imagen_url', ''))
            city = html_lib.escape(product.get('ciudad', 'Ubicación desconocida'))

            html_content += f"""
    <div class="product">
        {"<img src='{image_url}' alt='Imagen del producto'>" if image_url else ""}
        <div class="product-info">
            <p class="title"><a href="{url}" target="_blank">{title}</a></p>
            <p class="price">{price}</p>
            <p class="location">{city}</p>
        </div>
    </div>
"""

    html_content += """
</body>
</html>
"""
    return html_content

# from market_scraping import fetch_products_graphql 
# --- Nueva Función para la Lógica de Scraping con Requests ---
def fetch_products_graphql(search_term, user_cookie, latitude=DEFAULT_LATITUDE, longitude=DEFAULT_LONGITUDE, radius=DEFAULT_RADIUS_KM):

    if not user_cookie:
        logger.error(f"Intento de búsqueda sin cookie para '{search_term}'")
        return None # No podemos buscar sin cookie

    request_url = "https://www.facebook.com/api/graphql/"

    # --- Encabezados (Headers) - Copiados exactamente de tu script que funcionaba ---
    headers = {
        'accept': '*/*',
        'accept-language': 'es-ES,es;q=0.6',
        'cache-control': 'no-cache',
        'content-type': 'application/x-www-form-urlencoded',
        'cookie': user_cookie,
        'origin': 'https://www.facebook.com',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': f'https://www.facebook.com/marketplace/rosario/search?sortBy=creation_time_descend&query={search_term.replace(" ", "%20")}&exact=false',
        'sec-ch-ua': '"Brave";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        'sec-ch-ua-full-version-list': '"Brave";v="135.0.0.0", "Not-A.Brand";v="8.0.0.0", "Chromium";v="135.0.0.0"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-ch-ua-platform-version': '"10.0.0"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'sec-gpc': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'x-asbd-id': '359341',
        'x-fb-friendly-name': 'CometMarketplaceSearchContentPaginationQuery',
        'x-fb-lsd': 'AVqOd7icdFk', # Nota: Este y otros pueden ser dinámicos
    }

    # --- Payload (Datos del Formulario) ---
    # Usar los parámetros pasados a la función en lugar de variables hardcodeadas
    variables_dict = {
        "count": 24,
        "cursor": None, # Asumimos primera página, pasar cursor si se implementa paginación
        "params": {
            "bqf": {
                "callsite": "COMMERCE_MKTPLACE_WWW",
                "query": search_term # Usar el término de búsqueda pasado
            },
            "browse_request_params": {
                "commerce_enable_local_pickup": True,
                "commerce_enable_shipping": True,
                "commerce_search_and_rp_available": True,
                "commerce_search_and_rp_category_id": [],
                "commerce_search_and_rp_condition": None,
                "commerce_search_and_rp_ctime_days": None,
                'commerce_search_sort_by': 'CREATION_TIME_DESCEND',
                "filter_location_latitude": latitude, 
                "filter_location_longitude": longitude, 
                "filter_price_lower_bound": 0,
                "filter_price_upper_bound": 214748364700,
                "filter_radius_km": radius
            },
            "custom_request_params": {
                "browse_context": None,
                "contextual_filters": [],
                "referral_code": None,
                "saved_search_strid": None,
                "search_vertical": "C2C",
                "seo_url": None,
                "surface": "SEARCH",
                "virtual_contextual_filters": []
            }
        },
        "scale": 1
    }

    variables_json_string = json.dumps(variables_dict)

    payload_data = {
        'av': '0',
        '__user': '0',
        '__a': '1',
        '__req': 'f',
        '__hs': '20200.HYP:comet_loggedout_pkg.2.1...0', 
        'dpr': '1',
        '__ccg': 'EXCELLENT',
        '__rev': '1022128419', 
        '__s': 'gcqwir:m2h11o:eb9hn4', 
        '__hsi': '7496285990794582045', 
        '__dyn': '7xeUmwlEnwn8K2Wmh0no6u5U4e1ZyUW3q32360CEbo19oe8hw2nVE4W0qa0FE2awpUO0n24oaEd82lwv89k2C1Fwc60D85m1mzXw8W58jwGzE6G1iwJK14xm0zK5o4q0Gpo8o1o8bUGdw46wbS1LwTwNwLwFg2Xwr86C13G1-w8eEb8uwm85K0UE62', 
        '__csr': 'gjYQiIAldf9YyGG_-sxu_jylLHBy95WEwCq9hVFUG6pBiG9y9XnCDACAy8nCxyqezGguyppA9Ury98N4CyryEjxm7F-qE8FpEepoy7oO1wDyE4ep0Lxq78hw8G01qBw0NYLw4kw1jC00gL66808jE0PkE0KG0PS4oB03cU3Qw7Iw0HPwl822w0Myweq08iqxx1JiFU0pmw0Kiw3RU0k9w1LLw2SE1380knw3J41aQ0afw2VoeEcUdonw6Vw', 
        '__comet_req': '15',
        'lsd': 'AVqOd7icdFk', 
        'jazoest': '2979', 
        '__spin_r': '1022128419', 
        '__spin_b': 'trunk',
        '__spin_t': '1745365092', 
        '__crn': 'comet.fbweb.CometMarketplaceSearchRoute', 
        'fb_api_caller_class': 'RelayModern', 
        'fb_api_req_friendly_name': 'CometMarketplaceSearchContentPaginationQuery', 
        'variables': variables_json_string, 
        'server_timestamps': 'true', 
        'doc_id': '9082812915151057' # El ID de la query GraphQL
    }

    # --- Realizar la Petición POST - Copiado de tu script ---
    try:
        logger.info(f"Realizando petición GraphQL para: '{search_term}'")
        response = requests.post(request_url, headers=headers, data=payload_data, timeout=DEFAULT_REQUEST_TIMEOUT)

        # Verificar si la petición fue exitosa
        response.raise_for_status()

        # Procesar la respuesta JSON
        data = response.json()

        # --- Extraer la información - Lógica de tu script que funcionaba ---
        # Accede a la lista de 'edges' que contienen cada listado/nodo
        feed_units = data.get('data', {}).get('marketplace_search', {}).get('feed_units', {})
        edges = feed_units.get('edges', [])

        logger.info(f"GraphQL response: Found {len(edges)} edges.")

        productos_encontrados = []
        for edge in edges:
            node = edge.get('node', {})
            if not node:
                continue

            listing = node.get('listing', {})
            if not listing:
                # Si el nodo no tiene 'listing', no es un producto (podría ser anuncio, sugerencia, etc.)
                continue

            # Extrae los datos específicos del listing usando .get()
            listing_id = listing.get('id')
            if not listing_id: # Necesitamos ID para la URL y seguimiento
                 logger.warning("Listado encontrado sin ID en la respuesta. Saltando.")
                 continue

            titulo = listing.get('marketplace_listing_title', 'Sin título')

            precio_obj = listing.get('listing_price', {})
            precio = precio_obj.get('formatted_amount', 'Sin precio')

            imagen_url = None
            primary_photo = listing.get('primary_listing_photo', {})
            if primary_photo:
                image_data = primary_photo.get('image', {})
                if image_data:
                    imagen_url = image_data.get('uri')

            url_listing = f"https://www.facebook.com/marketplace/item/{listing_id}/"

            ciudad = "Ubicación desconocida"
            location_data = listing.get('location', {})
            if location_data:
                reverse_geocode = location_data.get('reverse_geocode', {})
                if reverse_geocode:
                    ciudad = reverse_geocode.get('city', ciudad)

            # Verifica si está vendido y solo añade si NO está vendido
            esta_vendido = listing.get('is_sold', False)
            if not esta_vendido:
                productos_encontrados.append({
                    'id': listing_id,
                    'titulo': titulo,
                    'precio': precio,
                    'url': url_listing,
                    'imagen_url': imagen_url,
                    'ciudad': ciudad
                })

        logger.info(f"fetch_products_graphql para '{search_term}' completada. Encontrados {len(productos_encontrados)} productos válidos.")
        return productos_encontrados

    except requests.exceptions.Timeout:
        logger.error(f"Timeout ({DEFAULT_REQUEST_TIMEOUT}s) durante petición GraphQL para '{search_term}'")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en petición GraphQL para '{search_term}': {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Código de estado: {e.response.status_code}.")
            # Loggear la respuesta completa si no es JSON para depurar
            if 'application/json' not in response.headers.get('Content-Type', ''):
                 logger.error(f"Respuesta del servidor (no JSON):\n{response.text[:500]}...")
            else:
                 # Si es JSON pero dio error HTTP, loggear los primeros chars del JSON
                 logger.error(f"Respuesta del servidor (JSON, primeros 500 chars):\n{response.text[:500]}...")

            if e.response.status_code in [401, 403]:
                 logger.critical(f"¡¡ERROR DE AUTENTICACIÓN/AUTORIZACIÓN!! Revisa FACEBOOK_COOKIE en tu .env. Asegúrate de incluir 'c_user' y 'xs'.")
            elif e.response.status_code == 429:
                 logger.warning("¡Demasiadas peticiones! Facebook está limitando las solicitudes.")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON de GraphQL para '{search_term}': {e}")
        # Si la respuesta no fue JSON, response.text debería estar disponible
        if 'response' in locals() and response is not None:
            logger.error(f"Respuesta recibida (primeros 500 chars):\n{response.text[:500]}...")
        return None
    except Exception as e:
        logger.exception(f"Ocurrió un error inesperado en fetch_products_graphql para '{search_term}': {e}")
        return None

def monitor_search(user_id, chat_id, search_term, stop_event: threading.Event):
    """
    Hilo de monitoreo para una búsqueda específica.
    Usa fetch_products_graphql y notifica nuevos productos.
    """
    key = f"{user_id}_{search_term}"
    logger.info(f"Hilo de monitoreo iniciado para '{search_term}' (Usuario: {user_id})")

    # Obtener la cookie del archivo .env (asumiendo que es una cookie global para el bot)
    # Si quisieras cookies por usuario, tendrías que guardarlas y recuperarlas aquí.
    user_cookie = FACEBOOK_COOKIE

    if not user_cookie:
        logger.error(f"Monitoreo para '{search_term}' cancelado: No se encontró FACEBOOK_COOKIE.")
        bot.send_message(chat_id, f"❌ No puedo monitorear '{html_lib.escape(search_term)}'. Falta configurar la cookie de Facebook.", parse_mode='HTML')
        # Limpiar estado de monitoreo para esta alerta
        user_searches[user_id][search_term]['active'] = False
        if key in active_monitoring_threads:
            del active_monitoring_threads[key]
        return # Termina el hilo

    # Realizar el primer scrapeo SIN notificar para llenar el historial
    # Esto se hace solo una vez al iniciar el monitoreo para esta alerta.
    if not first_scrape_done[key]:
        logger.info(f"Realizando primer scrapeo (no notificar) para '{search_term}' (Usuario: {user_id})")
        products = fetch_products_graphql(search_term, user_cookie)

        if products:
            # Añadir todos los productos encontrados en el primer scrapeo al historial y notificados
            logger.info(f"Primer scrapeo para '{search_term}': Encontrados {len(products)} productos. Añadiendo a historial y notificados.")
            for product in products:
                product_id = product.get('id') # Usar el ID del producto como identificador
                if product_id:
                    notified_products[user_id][search_term].add(product_id)
                    # Añadir al principio del deque
                    product_history[user_id][search_term].appendleft(product)
            save_data(product_history, PRODUCT_HISTORY_FILE, product_history_lock)
                    
            first_scrape_done[key] = True # Marcar el primer scrapeo como completado
        else:
            logger.warning(f"Primer scrapeo para '{search_term}' no devolvió productos o falló.")
            # Si el primer scrapeo falla, ¿qué hacemos? Podríamos reintentar o notificar error.
            # Por ahora, simplemente logeamos y permitimos que el bucle principal lo intente de nuevo más tarde.
            # No marcamos first_scrape_done[key] como True si falla para reintentar en el siguiente ciclo.
            # bot.send_message(chat_id, f"⚠️ Hubo un problema inicial buscando '{html_lib.escape(search_term)}'. Intentaré de nuevo más tarde.", parse_mode='HTML')


    # Bucle principal de monitoreo
    while not stop_event.is_set() and user_searches.get(user_id, {}).get(search_term, {}).get('active', False):
        logger.info(f"Monitoreando: Buscando nuevos productos para '{search_term}' (Usuario: {user_id})")
        
        products = fetch_products_graphql(search_term, user_cookie)
        refresh_interval = rand_refresh_interval()
        
        if products is None:
            logger.warning(f"La búsqueda GraphQL para '{search_term}' falló en este ciclo. Reintentando en {refresh_interval}s.")
            # No hay nuevos productos si la búsqueda falla. Esperar y reintentar.
        elif not products:
             logger.info(f"Búsqueda para '{search_term}' completada, no se encontraron productos.")
             # No se encontraron productos en este ciclo, lo cual es normal. Esperar.
        else:
            new_products = []
            for product in products:
                product_id = product.get('id')
                if product_id and product_id not in notified_products[user_id][search_term] and product_id not in product_history[user_id][search_term]:
                    # ¡Producto nuevo encontrado!
                    logger.info(f"¡Nuevo producto encontrado para '{search_term}': {product.get('titulo', 'N/A')} ({product_id})")
                    notified_products[user_id][search_term].add(product_id)
                    product_history[user_id][search_term].appendleft(product) # Añadir al principio
                    
                    # El deque mantiene el tamaño máximo automáticamente
                    new_products.append(product)
            save_data(product_history, PRODUCT_HISTORY_FILE, product_history_lock)

            # Notificar solo si hay productos nuevos Y ya se hizo el primer scrapeo (para no floodear al inicio)
            if first_scrape_done[key] and new_products:
                logger.info(f"Notificando {len(new_products)} productos nuevos para '{search_term}'")
                for product in new_products:
                    send_product_message(chat_id, product)
                    time.sleep(0.5) # Pequeña pausa entre notificaciones


        # Esperar antes del siguiente ciclo, a menos que se solicite detener el hilo
        logger.info(f"Monitoreo para '{search_term}' (Usuario: {user_id}) esperando {refresh_interval} segundos.")
        # Usa wait() con timeout para que el hilo pueda detenerse rápidamente si se llama stop_event.set()
        stop_event.wait(refresh_interval)


    # El bucle terminó (por stop_event.is_set() o user_searches[user_id][search_term]['active'] == False)
    logger.info(f"Hilo de monitoreo detenido para '{search_term}' (Usuario: {user_id})")
    # Eliminar el evento de parada de la lista de hilos activos
    if key in active_monitoring_threads:
        del active_monitoring_threads[key]
    # Opcional: notificar al usuario que el monitoreo se detuvo si fue por inactividad o error
    if not stop_event.is_set():
        bot.send_message(chat_id, f"ℹ️ Monitoreo para '{html_lib.escape(search_term)}' se ha detenido.", parse_mode='HTML')


# --- Handlers de Mensajes y Callbacks (Adaptados) ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_msg = (
        "🛍️ <b>Bot de Alertas Marketplace</b>\n\n"
        "¡Te avisaré de nuevos productos en Facebook Marketplace!\n\n"
        "Elige una opción del menú de abajo:"
    )
    # Asegurarse de enviar siempre el menú principal al inicio
    bot.send_message(
        message.chat.id,
        welcome_msg,
        parse_mode='HTML',
        reply_markup=create_inline_keyboard()
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_searches
                     and user_searches[m.from_user.id].get('waiting_for_search'))
def save_search(message):
    """Captura el término de búsqueda después de seleccionar 'Nueva Alerta', valida, normaliza y guarda."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    raw_search_term = message.text # Obtener el texto crudo del usuario
    search_term = raw_search_term.strip() # Eliminar espacios al inicio y final

    logger.debug(f"save_search - Received raw input: '{raw_search_term}' from user {user_id} (Chat: {chat_id})")

    # --- VALIDATION ---
    # Validar el término *después* de hacer strip
    if not is_valid_search_term(search_term):
        logger.warning(f"save_search - Invalid search term received from user {user_id}: '{raw_search_term}'")
        bot.send_message(
            chat_id,
            "❌ El término de búsqueda no es válido. Por favor, intenta de nuevo con texto significativo.",
            reply_markup=create_inline_keyboard() # Volver al menú principal
        )
        user_searches[user_id]['waiting_for_search'] = False # Resetear la bandera de espera
        save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
        eturn # Salir de la función si es inválido

    # --- NORMALIZATION ---
    # Normalizar *después* de la validación inicial.
    # Convertir a minúsculas y reemplazar múltiples espacios con un solo espacio.
    normalized_search_term = ' '.join(search_term.lower().split())
    logger.debug(f"save_search - Normalized search term: '{normalized_search_term}'")


    # --- CHECK IF ALREADY EXISTS ---
    # Usar el término normalizado para verificar si la alerta ya existe
    if normalized_search_term in user_searches.get(user_id, {}):
        logger.info(f"save_search - Alert already exists for user {user_id}: '{normalized_search_term}'")
        bot.send_message(
            chat_id,
            f"ℹ️ Ya tienes una alerta para '{html_lib.escape(normalized_search_term)}'.",
            reply_markup=create_inline_keyboard({
                "🔔 Activar Notif.": f"select_alert_activate", 
                "🔄 Buscar Ahora": f"select_alert_search_now", 
                "📋 Mis Alertas": "list_alerts", 
                "⬅️ Menú Principal": "main_menu"
            }, back_button=False),
            parse_mode='HTML'
        )
        user_searches[user_id]['waiting_for_search'] = False 
        save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
        return 
    
    # --- SAVE NEW ALERT ---
    # Si no es inválido y no existe, guardar la nueva alerta con el término normalizado
    user_searches[user_id][normalized_search_term] = {'active': False, 'chat_id': chat_id}
    user_searches[user_id]['waiting_for_search'] = False
    save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
    
    logger.info(f"save_search - New alert saved for user {user_id}: '{normalized_search_term}' (Chat: {chat_id})")

    # --- GENERATE CALLBACKS AND SEND SUCCESS MESSAGE ---
    # Usar el término normalizado FINAL para construir los callbacks de los botones
    activate_callback = f"activate_{normalized_search_term}"
    search_now_callback = f"search_now_{normalized_search_term}"
    logger.debug(f"save_search - Generated callbacks: Activate='{activate_callback}', SearchNow='{search_now_callback}'")


    markup = create_inline_keyboard({
        "🔔 Activar Notif.": activate_callback, 
        "🔄 Buscar Ahora": search_now_callback, 
        "📋 Mis Alertas": "list_alerts", 
        "⬅️ Menú Principal": "main_menu"
    }, back_button=False)

    bot.send_message(
        chat_id,
        f"✅ ¡Alerta guardada para: '{html_lib.escape(normalized_search_term)}'!\n\n"
        "Puedes activarla para recibir notificaciones automáticas o buscar ahora mismo.",
        reply_markup=markup,
        parse_mode='HTML'
    )

@bot.callback_query_handler(func=lambda call: call.data == "new_search")
def handle_new_search_callback(call):
     """Maneja el callback del botón 'Nueva Alerta'."""
     user_id = call.from_user.id
     chat_id = call.message.chat.id

     # Eliminar el mensaje de los botones anteriores si es posible
     try:
         bot.delete_message(chat_id, call.message.message_id)
     except telebot.apihelper.ApiTelegramException:
         pass # Ignorar si no se puede borrar (ej. mensaje muy viejo)

     msg = bot.send_message(
         chat_id,
         "¿Qué producto deseas buscar y guardar como alerta? Ejemplo: 'TV 32 pulgadas'\n\n"
         "Escribe tu término de búsqueda:",
         reply_markup=types.ForceReply() # Pedir una respuesta directa del usuario
     )
     # Establecer el estado de espera para este usuario
     user_searches[user_id]['waiting_for_search'] = True
     save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
     bot.answer_callback_query(call.id) # Ocultar el indicador de "cargando" en el botón


@bot.callback_query_handler(func=lambda call: call.data == "list_alerts")
def handle_list_alerts(call):
    """Muestra la lista de alertas configuradas por el usuario."""
    try:
        user_id = call.from_user.id
        chat_id = call.message.chat.id

        searches = user_searches.get(user_id, {})
        # Excluir la clave temporal 'waiting_for_search'
        alert_terms = [term for term in searches.keys() if term != 'waiting_for_search']

        if not alert_terms:
            message_text = "No tienes alertas configuradas."
            markup = create_inline_keyboard() # Volver al menú principal
        else:
            alert_lines = []
            for search in alert_terms:
                is_active = searches[search].get('active', False)
                status_icon = "🔔" if is_active else "🔕"
                alert_lines.append(f"{status_icon} {html_lib.escape(search)}") # Usar html.escape

            message_text = "📋 <b>Tus Alertas:</b>\n\n" + "\n".join(alert_lines)
            markup = create_inline_keyboard() # Volver al menú principal

        # Intentar editar el mensaje original
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=message_text,
                parse_mode='HTML',
                reply_markup=markup
            )
        except telebot.apihelper.ApiTelegramException as e:
             logger.warning(f"No se pudo editar el mensaje {call.message.message_id} al listar alertas: {e}")
             # Si falla la edición (ej. mensaje muy viejo), envía uno nuevo y borra el viejo si es posible
             bot.send_message(
                chat_id,
                message_text,
                parse_mode='HTML',
                reply_markup=markup
             )
             try:
                 bot.delete_message(chat_id, call.message.message_id)
             except:
                 pass # Ignorar si borrar también falla

        bot.answer_callback_query(call.id) # Responder al callback vacío para quitar el "loading"

    except Exception as e:
        logger.exception(f"Error listando alertas: {e}")
        bot.answer_callback_query(call.id, "❌ Error al listar alertas.", show_alert=True)
        # Asegurarse de volver al menú principal en caso de error
        try:
            bot.send_message(chat_id, "Ocurrió un error. Volviendo al menú principal.", reply_markup=create_inline_keyboard())
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except: pass
        except: pass

# --- NUEVO HANDLER ESPECÍFICO PARA 'select_alert_search_now' ---
# Coloca este handler *inmediatamente antes* de la función handle_select_alert_action modificada arriba.
@bot.callback_query_handler(func=lambda call: call.data == "select_alert_search_now") # Coincidencia exacta
def handle_select_alert_search_now_action(call):
    """Prepara para mostrar la lista de alertas para que el usuario seleccione una para buscar ahora."""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    callback_data = call.data

    logger.debug(f"handle_select_alert_search_now_action - Received callback data: {callback_data}") # LOG: Para confirmar que este handler se dispara

    try:
        # Este handler solo se activa para 'select_alert_search_now'.
        # La acción fija es "buscar ahora".
        action_prefix = "search_now" # El prefijo de acción para el siguiente paso

        # Obtener solo los términos de búsqueda válidos del usuario
        searches = [k for k in user_searches.get(user_id, {}).keys() if k != 'waiting_for_search']

        if not searches:
            bot.answer_callback_query(call.id, "No tienes alertas configuradas para buscar.", show_alert=True)
            # Si no hay alertas, volver al menú principal
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="No tienes alertas configuradas.", reply_markup=create_inline_keyboard())
            except telebot.apihelper.ApiTelegramException:
                 # Si falla editar, enviar un nuevo mensaje
                 bot.send_message(chat_id, "No tienes alertas configuradas.", reply_markup=create_inline_keyboard())
            except Exception as e: # Captura otros posibles errores en el fallback
                 logger.error(f"handle_select_alert_search_now_action - Error en fallback sin alertas: {e}")
            return

        action_text = "buscar ahora para" # Texto que se muestra al usuario

        markup = types.InlineKeyboardMarkup()
        for search in searches:
            # Generar el callback para el *siguiente* paso: search_now_<término>
            callback_data_generated = f"{action_prefix}_{search}"
            logger.debug(f"handle_select_alert_search_now_action - Generated callback for '{search}': {callback_data_generated}")
            markup.add(types.InlineKeyboardButton(html_lib.escape(search), callback_data=callback_data_generated))

        markup.add(types.InlineKeyboardButton("⬅️ Menú Principal", callback_data="main_menu"))

        # Intentar editar el mensaje original (el del menú principal)
        try:
             bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=call.message.message_id,
                 text=f"Selecciona la alerta que quieres {action_text}:",
                 reply_markup=markup,
                 parse_mode='HTML'
             )
        except telebot.apihelper.ApiTelegramException as e:
            logger.warning(f"handle_select_alert_search_now_action - Could not edit message {call.message.message_id} to list alerts: {e}")
            # Si falla la edición, enviar un nuevo mensaje y intentar borrar el viejo
            try:
                 bot.send_message(
                     chat_id,
                     f"Selecciona la alerta que quieres {action_text}:",
                     reply_markup=markup,
                     parse_mode='HTML'
                 )
                 try:
                      bot.delete_message(chat_id, call.message.message_id)
                 except telebot.apihelper.ApiTelegramException:
                      pass # Ignorar si no se puede borrar el mensaje viejo
                 except Exception as delete_e:
                      logger.error(f"handle_select_alert_search_now_action - Error inesperado borrando mensaje viejo {call.message.message_id}: {delete_e}")
            except Exception as send_e:
                 logger.error(f"handle_select_alert_search_now_action - Error inesperado enviando nuevo mensaje después de fallar edición: {send_e}")


        bot.answer_callback_query(call.id) # Responder al callback vacío para quitar el "loading"

    except Exception as e:
        logger.exception(f"handle_select_alert_search_now_action - Error listando alertas para buscar: {e}")
        bot.answer_callback_query(call.id, "❌ Error al mostrar alertas para buscar.", show_alert=True)
        # Asegurarse de volver al menú principal en caso de error
        try:
            bot.send_message(chat_id, "Ocurrió un error. Volviendo al menú principal.", reply_markup=create_inline_keyboard())
            try:
                 bot.delete_message(chat_id, call.message.message_id)
            except: pass
        except: pass

@bot.callback_query_handler(func=lambda call: call.data in ["select_alert_activate", "select_alert_deactivate", "select_alert_delete"])
def handle_select_alert_action(call):

    """Muestra la lista de alertas para que el usuario seleccione una para activar/desactivar/buscar/eliminar."""
    try:
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        action_prefix = call.data.split('_')[-1] # activate, deactivate, search_now, delete
        callback_data = call.data

        # Obtener solo los términos de búsqueda válidos
        searches = [k for k in user_searches.get(user_id, {}).keys() if k != 'waiting_for_search']

        if not searches:
            bot.answer_callback_query(call.id, "No tienes alertas configuradas.", show_alert=True)
            # Volver al menú principal - Intentar editar o enviar nuevo mensaje
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="No tienes alertas configuradas.", reply_markup=create_inline_keyboard())
            except telebot.apihelper.ApiTelegramException:
                 # Si falla editar, enviar un nuevo mensaje
                 bot.send_message(chat_id, "No tienes alertas configuradas.", reply_markup=create_inline_keyboard())
            return

        action_text_map = {
            "activate": "activar notificaciones para",
            "deactivate": "desactivar notificaciones para",
            "search_now": "buscar ahora para",
            "delete": "eliminar"
        }
        action_text = action_text_map.get(action_prefix, "seleccionar alerta:")

        markup = types.InlineKeyboardMarkup()
        for search in searches:
            # El callback ahora incluye la acción y el término
            markup.add(types.InlineKeyboardButton(html_lib.escape(search), callback_data=f"{action_prefix}_{search}"))

        markup.add(types.InlineKeyboardButton("⬅️ Menú Principal", callback_data="main_menu"))

        # Intentar editar el mensaje original
        try:
             bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=call.message.message_id,
                 text=f"Selecciona la alerta que quieres {action_text}:",
                 reply_markup=markup,
                 parse_mode='HTML'
             )
        except telebot.apihelper.ApiTelegramException as e:
            logger.warning(f"No se pudo editar el mensaje {call.message.message_id} para seleccionar alerta: {e}")
            # Si falla editar, enviar un nuevo mensaje y intentar borrar el viejo
            try:
                bot.send_message(
                    chat_id,
                    f"Selecciona la alerta que quieres {action_text}:",
                    reply_markup=markup,
                    parse_mode='HTML'
                )
                try:
                     bot.delete_message(chat_id, call.message.message_id)
                except telebot.apihelper.ApiTelegramException:
                     pass # Ignorar si no se puede borrar el mensaje viejo
                except Exception as delete_e:
                    logger.error(f"Error inesperado borrando mensaje viejo {call.message.message_id}: {delete_e}")
            except Exception as send_e:
                logger.error(f"Error inesperado enviando nuevo mensaje después de fallar edición: {send_e}")


        bot.answer_callback_query(call.id)

    except Exception as e:
        logger.exception(f"Error en handle_select_alert_action: {e}")
        bot.answer_callback_query(call.id, "❌ Error al procesar la solicitud.", show_alert=True)
        # Intentar volver al menú principal enviando un nuevo mensaje en caso de error grave
        try:
            bot.send_message(chat_id, "Ocurrió un error. Volviendo al menú principal.", reply_markup=create_inline_keyboard())
            # Opcional: intentar borrar el mensaje original con botones de acción que causó el error
            try:
                 bot.delete_message(chat_id, call.message.message_id)
            except telebot.apihelper.ApiTelegramException:
                 pass # Ignorar si no se puede borrar
            except Exception as delete_e_fallback:
                 logger.error(f"Error inesperado borrando mensaje {call.message.message_id} en fallback: {delete_e_fallback}")
        except Exception as send_e_fallback:
            logger.error(f"Error inesperado enviando mensaje fallback en handle_select_alert_action: {send_e_fallback}")


@bot.callback_query_handler(func=lambda call: call.data.startswith(("activate_", "deactivate_")))
def handle_toggle_monitoring(call):
    """Activa o desactiva el monitoreo para una alerta específica."""
    try:
        parts = call.data.split("_", 1)
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Formato de callback inválido.", show_alert=True)
            return

        action, search_term = parts
        user_id = call.from_user.id
        chat_id = call.message.chat.id # Obtener chat_id de la llamada
        key = f"{user_id}_{search_term}"

        # Verificar si la alerta existe para este usuario
        if search_term not in user_searches.get(user_id, {}):
            bot.answer_callback_query(call.id, f"No se encontró la alerta '{html_lib.escape(search_term)}'.", show_alert=True)
            # Intentar volver al menú principal
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"No se encontró la alerta '{html_lib.escape(search_term)}'.", reply_markup=create_inline_keyboard(), parse_mode='HTML')
            except: pass
            return

        current_state = user_searches[user_id][search_term].get('active', False)

        if action == "activate":
            if current_state:
                bot.answer_callback_query(call.id, f"Las notificaciones ya están activas para '{html_lib.escape(search_term)}'.", show_alert=False)
                msg = f"🔔 Notificaciones ya estaban activas para: '{html_lib.escape(search_term)}'"
            else:
                # Verificar si ya hay un hilo activo con la MISMA clave (por si acaso)
                if key in active_monitoring_threads and active_monitoring_threads[key].is_set():
                     logger.warning(f"Intento de activar hilo para '{search_term}' ({user_id}) pero ya existe un evento activo.")
                     bot.answer_callback_query(call.id, "Ya hay un proceso activo para esta alerta.", show_alert=True)
                     msg = f"🔔 Notificaciones ya estaban activas para: '{html_lib.escape(search_term)}'" # Mensaje para la edición

                else:
                    # Marcar como activa y resetear flag de primera búsqueda
                    user_searches[user_id][search_term]['active'] = True
                    user_searches[user_id][search_term]['chat_id'] = chat_id # Asegurar que el chat_id esté guardado
                    save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
                    
                    first_scrape_done[key] = False # Resetear para forzar primer scrapeo al iniciar

                    logger.info(f"Activando monitoreo para '{search_term}' (Usuario: {user_id}, Chat: {chat_id})")

                    # Crear y empezar el hilo de monitoreo
                    stop_event = threading.Event()
                    active_monitoring_threads[key] = stop_event # Guardar el evento para poder detenerlo
                    thread = threading.Thread(
                        target=monitor_search,
                        args=(user_id, chat_id, search_term, stop_event), 
                        daemon=True
                    )
                    thread.start()

                    msg = f"🔔 Notificaciones ACTIVADAS para: '{html_lib.escape(search_term)}'"
                    bot.answer_callback_query(call.id, msg, show_alert=False) # Responder al callback antes de editar el mensaje

        elif action == "deactivate":
            if not current_state:
                bot.answer_callback_query(call.id, f"Las notificaciones ya están inactivas para '{html_lib.escape(search_term)}'.", show_alert=False)
                msg = f"🔕 Notificaciones ya estaban inactivas para: '{html_lib.escape(search_term)}'"
            else:
                # Marcar como inactiva en la estructura principal
                user_searches[user_id][search_term]['active'] = False
                save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
                
                msg = f"🔕 Notificaciones DESACTIVADAS para: '{html_lib.escape(search_term)}'"
                logger.info(f"Desactivando monitoreo para '{search_term}' (Usuario: {user_id})")

                # Detener el hilo si existe
                if key in active_monitoring_threads:
                    stop_event = active_monitoring_threads.pop(key) # Quita la referencia del diccionario
                    stop_event.set() # Señala al hilo que debe detenerse
                    logger.info(f"Evento de parada enviado para el hilo de '{search_term}' (Usuario: {user_id})")
                else:
                     logger.warning(f"Se intentó desactivar monitoreo para '{search_term}' ({user_id}) pero no se encontró un hilo activo registrado.")


                bot.answer_callback_query(call.id, msg, show_alert=False) # Responder al callback antes de editar el mensaje


        # Actualizar el mensaje original para volver al menú principal
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"{msg}\n\n¿Qué más deseas hacer?",
                reply_markup=create_inline_keyboard(),
                parse_mode='HTML'
            )
        except telebot.apihelper.ApiTelegramException as e:
             logger.warning(f"No se pudo editar el mensaje {call.message.message_id} al cambiar estado de notificación: {e}")
             # Si falla, envía uno nuevo
             bot.send_message(chat_id, f"{msg}\n\n¿Qué más deseas hacer?", reply_markup=create_inline_keyboard(), parse_mode='HTML')
             try:
                 bot.delete_message(chat_id, call.message.message_id)
             except: pass

    except Exception as e:
        logger.exception(f"Error en handle_toggle_monitoring: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cambiar estado de notificación.", show_alert=True)
        # Podríamos intentar volver al menú principal incluso si hay error
        try:
            bot.send_message(chat_id, "Ocurrió un error. Volviendo al menú principal.", reply_markup=create_inline_keyboard())
            try:
                 bot.delete_message(chat_id, call.message.message_id)
            except: pass
        except: pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def handle_delete_alert(call):
    """Elimina una alerta específica."""
    try:
        parts = call.data.split("_", 1)
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Formato de callback inválido.", show_alert=True)
            return

        _, search_term = parts
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        key = f"{user_id}_{search_term}"

        if search_term in user_searches.get(user_id, {}):
            if key in active_monitoring_threads:
                stop_event = active_monitoring_threads.pop(key)
                stop_event.set()
                logger.info(f"Evento de parada enviado al eliminar alerta '{search_term}' (Usuario: {user_id})")

            del user_searches[user_id][search_term]
            save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
            
            if not user_searches[user_id]:
                del user_searches[user_id]

            if user_id in notified_products and search_term in notified_products[user_id]:
                del notified_products[user_id][search_term]
                if not notified_products[user_id]:
                    del notified_products[user_id]

            if user_id in product_history and search_term in product_history[user_id]:
                del product_history[user_id][search_term]
                save_data(product_history, PRODUCT_HISTORY_FILE, product_history_lock)
                if not product_history[user_id]:
                    del product_history[user_id]

            # Eliminar flag de primer scrapeo
            if key in first_scrape_done:
                 del first_scrape_done[key]


            msg = f"🗑 ¡Alerta eliminada para: '{html_lib.escape(search_term)}'!"
            bot.answer_callback_query(call.id, msg, show_alert=False)
            logger.info(f"Alerta eliminada para usuario {user_id}: '{search_term}'")

        else:
            msg = f"ℹ️ No se encontró la alerta '{html_lib.escape(search_term)}'."
            bot.answer_callback_query(call.id, msg, show_alert=True)
            logger.warning(f"Intento de eliminar alerta inexistente para usuario {user_id}: '{search_term}'")


        # Volver al menú principal
        try:
             bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=call.message.message_id,
                 text=f"{msg}\n\n¿Qué más deseas hacer?",
                 reply_markup=create_inline_keyboard(),
                 parse_mode='HTML'
             )
        except telebot.apihelper.ApiTelegramException as e:
            logger.warning(f"No se pudo editar el mensaje {call.message.message_id} al eliminar alerta: {e}")
            # Si falla, envía uno nuevo
            bot.send_message(chat_id, f"{msg}\n\n¿Qué más deseas hacer?", reply_markup=create_inline_keyboard(), parse_mode='HTML')
            try:
                 bot.delete_message(chat_id, call.message.message_id)
            except: pass


    except Exception as e:
        logger.exception(f"Error eliminando alerta: {e}")
        bot.answer_callback_query(call.id, "❌ Error al eliminar alerta.", show_alert=True)
        try:
            bot.send_message(chat_id, "Ocurrió un error. Volviendo al menú principal.", reply_markup=create_inline_keyboard())
            try:
                 bot.delete_message(chat_id, call.message.message_id)
            except: pass
        except: pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("search_now_"))
def handle_search_now_specific(call):
    """Inicia una búsqueda inmediata para una alerta seleccionada."""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    callback_data = call.data # Guarda el dato original del callback para depuración

    logger.debug(f"handle_search_now_specific - Received callback data: {callback_data}") # LOG: Muestra el callback exacto recibido

    try:
        # Extraer el término de búsqueda del callback data.
        # El formato esperado es 'search_now_<search_term>'
        prefix = "search_now_"
        if callback_data.startswith(prefix): # Re-verificar por seguridad, aunque el decorador lo hace
            search_term = callback_data[len(prefix):] # Extraer la parte después del prefijo
        else:
            # Este caso no debería ocurrir si el decorador funciona, pero es un manejo seguro
            logger.error(f"handle_search_now_specific - Callback data no inicia con '{prefix}': {callback_data}")
            bot.answer_callback_query(call.id, "Error interno al procesar callback.", show_alert=True)
            # Intenta enviar un mensaje de error y volver al menú principal
            try:
                 bot.send_message(chat_id, "Ocurrió un error al procesar tu solicitud.", reply_markup=create_inline_keyboard())
                 try: bot.delete_message(chat_id, call.message.message_id) # Intenta borrar el mensaje original
                 except: pass
            except: pass
            return # Salir de la función
        
        logger.debug(f"handle_search_now_specific - DEBUG: Valor de search_term justo después de split: '{search_term}'")

        logger.info(f"handle_search_now_specific - User {user_id} triggered search for '{search_term}'. Chat ID: {chat_id}") # Compara este log con el de arriba


        # Verificar si ya hay una búsqueda manual en curso para este usuario
        if search_in_progress.get(user_id, False): # Usar .get() con False por defecto
             bot.answer_callback_query(call.id, "Ya hay una búsqueda en curso. Espera a que termine.", show_alert=True)
             logger.warning(f"handle_search_now_specific - User {user_id} attempted to start search '{search_term}' while another is in progress.")
             return

        # Marcar que hay una búsqueda en curso
        search_in_progress[user_id] = True
        logger.info(f"handle_search_now_specific - Search in progress flag set for user {user_id}.")

        # Responder al callback para quitar el estado de "cargando" del botón
        bot.answer_callback_query(call.id, "Iniciando búsqueda...", show_alert=False)

        # Editar mensaje original para indicar que se está buscando
        loading_message = None # Inicializar a None
        try:
             # Intentar editar el mensaje que contenía los botones de selección de alerta o el menú principal
             loading_message = bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=call.message.message_id,
                 text=f"⏳ Buscando resultados para '{html_lib.escape(search_term)}'...",
                 parse_mode='HTML'
             )
             logger.info(f"handle_search_now_specific - Edited message {call.message.message_id} to show loading.")
        except telebot.apihelper.ApiTelegramException as e:
             # Si falla editar (ej. message to edit not found), enviar un nuevo mensaje
             logger.warning(f"handle_search_now_specific - Could not edit message {call.message.message_id} to show loading: {e}. Sending new message instead.")
             try:
                loading_message = bot.send_message(
                    chat_id,
                    f"⏳ Buscando resultados para '{html_lib.escape(search_term)}'...",
                    parse_mode='HTML'
               )
             except Exception as e_send_loading:
                 logger.error(f"handle_search_now_specific - Unexpected error sending new loading message: {e_send_loading}")
                 loading_message = None # Asegurar que es None si falla el envío


        # Realizar la búsqueda usando la función GraphQL
        logger.info(f"handle_search_now_specific - Calling fetch_products_graphql for '{search_term}' (User: {user_id})")
        # Utiliza FACEBOOK_COOKIE del .env, asegurate de que esté actualizada
        products = fetch_products_graphql(search_term, FACEBOOK_COOKIE)


        # --- Manejar Resultados de la Búsqueda ---
        if products is None: # Error durante la búsqueda (ej: Timeout, RequestException)
             logger.error(f"handle_search_now_specific - fetch_products_graphql returned None for '{search_term}'.")
             error_message = f"❌ Ocurrió un error al buscar productos para '{html_lib.escape(search_term)}'. Revisa los logs del bot para más detalles (puede ser un problema con la cookie)."
             try:
                 if loading_message: # Si enviamos un mensaje de carga, intentar editarlo
                      bot.edit_message_text(chat_id=chat_id, message_id=loading_message.message_id, text=error_message, reply_markup=create_inline_keyboard(), parse_mode='HTML')
                 else: # Si no, enviar un nuevo mensaje
                      bot.send_message(chat_id, error_message, reply_markup=create_inline_keyboard(), parse_mode='HTML')
             except Exception as e_msg:
                 logger.error(f"handle_search_now_specific - Error sending/editing error message: {e_msg}")
                 # Fallback: enviar un mensaje simple si todo lo demás falla
                 try: bot.send_message(chat_id, "❌ Error en la búsqueda.")
                 except: pass
             return # Salir del handler tras el error

        elif not products: # Búsqueda exitosa pero sin resultados
            logger.info(f"handle_search_now_specific - fetch_products_graphql found 0 products for '{search_term}'.")
            success_message = f"✅ No se encontraron productos para '{html_lib.escape(search_term)}'."
            try:
                if loading_message: # Si enviamos un mensaje de carga, intentar editarlo
                     bot.edit_message_text(chat_id=chat_id, message_id=loading_message.message_id, text=success_message, reply_markup=create_inline_keyboard(), parse_mode='HTML')
                else: # Si no, enviar un nuevo mensaje
                     bot.send_message(chat_id, success_message, reply_markup=create_inline_keyboard(), parse_mode='HTML')
            except Exception as e_msg:
                logger.error(f"handle_search_now_specific - Error sending/editing success message: {e_msg}")
                # Fallback: enviar un mensaje simple
                try: bot.send_message(chat_id, "✅ Búsqueda completada sin resultados.")
                except: pass
            return # Salir del handler


        # --- Si se encontraron productos ---
        logger.info(f"handle_search_now_specific - Search for '{search_term}' successful. Found {len(products)} products.")

        # --- Actualizar Historial ---
        current_history = product_history[user_id][search_term]
        newly_added_to_history = 0
        # Añadir productos encontrados al historial (deque con maxlen)
        # Iterar sobre los productos encontrados y añadirlos al historial si no están ya
        for product in reversed(products): # Añadir del más nuevo al más viejo si el orden de la respuesta lo permite
             product_id = product.get('id')
             # Verificar si el producto (por ID) ya está en el historial actual para evitar duplicados
             # Usar any() para una verificación eficiente en el deque
             if product_id and not any(p.get('id') == product_id for p in current_history):
                 current_history.appendleft(product) # Añadir al principio (más reciente)
                 # El deque mantiene el tamaño máximo (MAX_PRODUCT_HISTORY) automáticamente
                 newly_added_to_history += 1

        if newly_added_to_history > 0:
             logger.info(f"handle_search_now_specific - Added {newly_added_to_history} products to history for '{search_term}'. History size: {len(current_history)}.")
        else:
             logger.info(f"handle_search_now_specific - No new products to add to history for '{search_term}'. History size: {len(current_history)}.")


        # Ofrecer opciones de visualización/descarga (basado en el historial actual, no solo los productos de esta búsqueda)
        logger.info(f"handle_search_now_specific - Offering display options for search '{search_term}'.")
        markup = types.InlineKeyboardMarkup()
        history_count = len(current_history) # El historial puede tener más productos que los encontrados en esta búsqueda

        ELEMENTS_SHOW_CHAT = 20
        if history_count > 0:
             # Ofrecer ver los 10 más recientes del historial o descargar todo el historial
             markup.add(
                types.InlineKeyboardButton(f"📱 Ver en chat ({min(ELEMENTS_SHOW_CHAT, history_count)})", callback_data=f"show_history_{search_term}_{min(ELEMENTS_SHOW_CHAT, history_count)}"),
                types.InlineKeyboardButton(f"📄 Descargar HTML ({history_count})", callback_data=f"download_history_{search_term}_all")
             )
        else:
             # Esto no debería ocurrir si products > 0 y el historial se actualizó, pero es un caso de seguridad
             markup.add(types.InlineKeyboardButton("❌ No hay resultados recientes en historial", callback_data="main_menu"))


        markup.add(types.InlineKeyboardButton("⬅️ Menú Principal", callback_data="main_menu"))

        # Editar el mensaje de "Buscando..." o enviar uno nuevo para mostrar las opciones
        message_text = f"🔍 Se encontraron {len(products)} productos en la última búsqueda para '{html_lib.escape(search_term)}'."
        if history_count > 0:
             message_text += f"\nHay {history_count} productos en el historial reciente.\n¿Cómo quieres verlos?"
        else:
             message_text += "\nPero no se pudieron añadir al historial reciente." # Investigar si esto sucede


        if loading_message:
             try:
                 bot.edit_message_text(
                     chat_id=chat_id,
                     message_id=loading_message.message_id, # Usar el ID del mensaje de "Buscando..."
                     text=message_text,
                     reply_markup=markup,
                     parse_mode='HTML'
                 )
                 logger.info(f"handle_search_now_specific - Edited loading message {loading_message.message_id} to show display options.")
             except telebot.apihelper.ApiTelegramException as e_edit_final:
                 logger.warning(f"handle_search_now_specific - Could not edit final message {loading_message.message_id} with display options: {e_edit_final}. Sending new message.")
                 # Si falla la edición, enviar uno nuevo
                 bot.send_message(
                     chat_id,
                     message_text,
                     reply_markup=markup,
                     parse_mode='HTML'
                 )
             except Exception as e_edit_final_unexpected:
                  logger.error(f"handle_search_now_specific - Unexpected error editing final message {loading_message.message_id}: {e_edit_final_unexpected}")
                  # Fallback: enviar nuevo mensaje simple
                  try: bot.send_message(chat_id, "Búsqueda completa. Error mostrando opciones.")
                  except: pass

        else:
             # Si no se pudo enviar/editar un mensaje de carga inicialmente, simplemente enviar el mensaje final con opciones
             logger.warning("handle_search_now_specific - No loading message found. Sending final message with options.")
             try:
                 bot.send_message(
                     chat_id,
                     message_text,
                     reply_markup=markup,
                     parse_mode='HTML'
                 )
             except Exception as e_send_final:
                  logger.error(f"handle_search_now_specific - Unexpected error sending final message with options: {e_send_final}")
                  # Fallback: enviar un mensaje simple
                  try: bot.send_message(chat_id, "Búsqueda completa. Error mostrando opciones.")
                  except: pass


    except Exception as e:
        logger.exception(f"handle_search_now_specific - Unhandled error for '{search_term}': {e}")
        # Responder al callback con una alerta de error genérica
        bot.answer_callback_query(call.id, "❌ Ocurrió un error inesperado durante la búsqueda.", show_alert=True)
        # Intentar enviar un mensaje de error al usuario
        try:
            bot.send_message(chat_id, f"❌ Ocurrió un error inesperado durante la búsqueda de '{html_lib.escape(search_term)}'. Por favor, inténtalo de nuevo más tarde.", reply_markup=create_inline_keyboard(), parse_mode='HTML')
            # Intentar borrar el mensaje de carga si existía
            if loading_message:
                 try: bot.delete_message(chat_id, loading_message.message_id)
                 except telebot.apihelper.ApiTelegramException: pass
                 except Exception as e_delete: logger.error(f"handle_search_now_specific - Error deleting loading message {loading_message.message_id} in error handler: {e_delete}")
        except Exception as e_fallback:
             logger.error(f"handle_search_now_specific - Error sending fallback message in error handler: {e_fallback}")

    finally:
        # Asegurar que la bandera search_in_progress se resetee siempre al finalizar el handler
        if user_id in search_in_progress:
             search_in_progress[user_id] = False
             logger.info(f"handle_search_now_specific - Search in progress flag reset for user {user_id} in finally block.")



@bot.callback_query_handler(func=lambda call: call.data.startswith(("show_history_", "download_history_")))
def handle_display_history_results(call):
    """Muestra o descarga resultados del historial para una alerta específica."""
    try:
        parts = call.data.split("_", 3) # Debería ser action_history_term_quantity
        if len(parts) != 4:
             bot.answer_callback_query(call.id, "Formato de callback inválido.", show_alert=True)
             return

        action_type, _, search_term, quantity_str = parts # Ignorar la parte '_history'

        user_id = call.from_user.id
        chat_id = call.message.chat.id

        # Obtener productos del historial
        products_from_history = list(product_history.get(user_id, {}).get(search_term, deque()))

        if not products_from_history:
            bot.answer_callback_query(call.id, "No hay productos recientes en el historial para esta alerta.", show_alert=True)
            # Volver al menú principal
            try:
                bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="No hay productos recientes en el historial para esta alerta.", reply_markup=create_inline_keyboard())
            except:
                 bot.send_message(chat_id, "No hay productos recientes en el historial para esta alerta.", reply_markup=create_inline_keyboard())
            return

        # Determinar cuántos productos procesar
        if quantity_str.lower() == "all":
            products_to_process = products_from_history # Todos del historial
        else:
            try:
                limit = int(quantity_str)
                products_to_process = products_from_history[:limit] # Los N más recientes del historial
            except ValueError:
                logger.warning(f"Cantidad inválida '{quantity_str}' para mostrar/descargar historial. Usando todos.")
                products_to_process = products_from_history


        bot.answer_callback_query(call.id, f"Procesando {len(products_to_process)} productos...", show_alert=False)

        # Intentar editar el mensaje de opciones para indicar que se está procesando
        try:
            bot.edit_message_text(
                chat_id=chat_id, message_id=call.message.message_id,
                text=f"⚙️ Procesando {len(products_to_process)} resultados para '{html_lib.escape(search_term)}'...",
                parse_mode='HTML'
            )
        except telebot.apihelper.ApiTelegramException:
             logger.warning(f"No se pudo editar el mensaje {call.message.message_id} en handle_display_history_results.")
             # No es crítico si no se puede editar

        if action_type == "show":
            bot.send_message(
                 chat_id,
                 f"👇 Mostrando {len(products_to_process)} productos recientes para '{html_lib.escape(search_term)}':",
                 parse_mode='HTML'
            )
            for product in products_to_process:
                 send_product_message(chat_id, product)
                 time.sleep(0.1)

        elif action_type == "download":
            html_content = generate_html(products_to_process, search_term)
            filename = f"productos_{search_term.replace(' ', '_').replace('/', '_')}.html" # Sanear nombre archivo
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(html_content)

                with open(filename, "rb") as f:
                    bot.send_document(
                        chat_id,
                        f,
                        caption=f"📄 {len(products_to_process)} productos para '{html_lib.escape(search_term)}'",
                        parse_mode='HTML'
                    )
            except Exception as e:
                 logger.exception(f"Error generando o enviando HTML para {search_term}: {e}")
                 bot.send_message(chat_id, "❌ Error al generar el archivo HTML.")
            finally:
                if os.path.exists(filename):
                    os.remove(filename) # Limpiar archivo temporal


        # Enviar menú principal después de la acción
        bot.send_message(
            chat_id,
            "¿Qué más deseas hacer?",
            reply_markup=create_inline_keyboard()
        )
        # Intentar eliminar el mensaje "Procesando..." si aún existe
        try:
             bot.delete_message(chat_id, call.message.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass # Ignorar si no se puede borrar


    except Exception as e:
        logger.exception(f"Error en handle_display_history_results: {e}")
        bot.send_message(call.message.chat.id, "❌ Error al mostrar/descargar resultados del historial.")
        # Intentar volver al menú principal en caso de error grave
        try:
             bot.send_message(chat_id, "¿Qué deseas hacer?", reply_markup=create_inline_keyboard())
             try:
                 bot.delete_message(chat_id, call.message.message_id)
             except: pass
        except: pass


@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def return_to_main_menu(call):
    """Vuelve a mostrar el mensaje de bienvenida con el teclado principal."""
    try:
        welcome_msg = (
            "🛍️ <b>Bot de Alertas Marketplace</b>\n\n"
            "¡Te avisaré de nuevos productos en Facebook Marketplace!\n\n"
            "Elige una opción del menú de abajo:"
        )
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=welcome_msg,
                parse_mode='HTML',
                reply_markup=create_inline_keyboard()
            )
            bot.answer_callback_query(call.id)
        except telebot.apihelper.ApiTelegramException as e:
            logger.warning(f"No se pudo editar el mensaje {call.message.message_id} al volver al menú: {e}")
            bot.send_message(
                call.message.chat.id,
                welcome_msg,
                parse_mode='HTML',
                reply_markup=create_inline_keyboard()
            )
            bot.answer_callback_query(call.id)
            try:
                 bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass

    except Exception as e:
        logger.exception(f"Error al volver al menú: {e}")
        try:
            bot.send_message(
                call.message.chat.id,
                "Menú principal:",
                reply_markup=create_inline_keyboard()
            )
        except Exception as e_fallback:
            logger.error(f"Error en fallback al enviar menú: {e_fallback}")

# --- Main execution block ---
if __name__ == '__main__':
    logger.info("Iniciando Bot de Telegram...")
    logger.info("Verificando cookies...")
    if not FACEBOOK_COOKIE:
         logger.warning("FACEBOOK_COOKIE no configurada en .env. El bot puede no funcionar correctamente para Marketplace.")
    else:
         logger.info("FACEBOOK_COOKIE encontrada. Procediendo.")

    for user_id in list(user_searches.keys()):
        if 'waiting_for_search' in user_searches[user_id]:
            user_searches[user_id]['waiting_for_search'] = False
            save_data(user_searches, USER_SEARCHES_FILE, user_searches_lock)
            
    try:
        load_user_searches()
        load_product_history()
        monitor_from_history()
        bot.infinity_polling()          
         
    except Exception as e:
        logger.critical(f"Error crítico en bot.infinity_polling(): {e}")