

def fetch_products_graphql(search_term, user_cookie, latitude=DEFAULT_LATITUDE, longitude=DEFAULT_LONGITUDE, radius=DEFAULT_RADIUS_KM):

    if not user_cookie:
        logger.error(f"Intento de búsqueda sin cookie para '{search_term}'")
        return None # No podemos buscar sin cookie

    request_url = "https://www.facebook.com/api/graphql/"

    # --- Encabezados (Headers) ---
    headers = {
        'accept': '*/*',
        'accept-language': 'es-ES,es;q=0.6',
        'cache-control': 'no-cache',
        'content-type': 'application/x-www-form-urlencoded',
        'cookie': user_cookie,
        'origin': 'https://www.facebook.com',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': f'https://www.facebook.com/marketplace/104009312969362/search/?query={search_term.replace(" ", "%20")}',
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