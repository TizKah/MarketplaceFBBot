import json
import time
import threading
from collections import defaultdict, deque
from dotenv import load_dotenv
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
WAIT_FOR_BOT_SEC = 1


def monitor_from_history(user_searches, active_monitoring_threads, monitor_search):
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
                json.dump(data_to_serialize, f, ensure_ascii=False, indent=4)

        except Exception as e:
            logger.exception(f"Error guardando datos en {filepath}: {e}. Intentando limpiar archivo temporal.")

def load_user_searches(USER_SEARCHES_FILE, user_searches):
    loaded_user_searches_data = load_data(USER_SEARCHES_FILE)
    for user_id_str, alerts_data in loaded_user_searches_data.items():
        try:
            user_id = int(user_id_str)
            if isinstance(alerts_data, dict):
                    user_searches[user_id] = alerts_data 
                    for search_term, alert_details in user_searches[user_id].items():
                        if search_term == 'waiting_for_search':
                            continue
                        if isinstance(alert_details, dict):
                            alert_details['active'] = bool(alert_details.get('active', False))
                            alert_details['chat_id'] = int(alert_details.get('chat_id', 0)) 
                        else:
                            logger.warning(f"Datos de alerta no válidos para user {user_id}: {alerts_data}")
            else:
                    logger.warning(f"Datos de usuario no válidos cargados para user {user_id_str}: {alerts_data}")
        except ValueError:
            logger.warning(f"User ID no válido cargado (no es entero): {user_id_str}")
    
    return user_searches

def load_product_history(PRODUCT_HISTORY_FILE, product_history, MAX_PRODUCT_HISTORY):
    loaded_product_history_data = load_data(PRODUCT_HISTORY_FILE)
    for user_id_str, searches_data in loaded_product_history_data.items():
        try:
            user_id = int(user_id_str)
            if isinstance(searches_data, dict):
                product_history[user_id] = defaultdict(lambda: deque(maxlen=MAX_PRODUCT_HISTORY))
                for search_term, history_list in searches_data.items():
                        if isinstance(history_list, list):
                            product_history[user_id][search_term].extend(history_list)
                        else:
                            logger.warning(f"Historial no válido para user {user_id}, search '{search_term}': {history_list}")
            else:
                    logger.warning(f"Datos de historial de usuario no válidos cargados para user {user_id_str}: {searches_data}")
        except ValueError:
            logger.warning(f"User ID no válido cargado en historial (no es entero): {user_id_str}")
    
    return product_history
