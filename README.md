# 🛍️ Alertas de Facebook Marketplace por Telegram

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-pyTelegramBotAPI-blue)
![Requests](https://img.shields.io/badge/HTTP%20Library-Requests-blue)
![GraphQL](https://img.shields.io/badge/Data%20Fetching-GraphQL-blue)
![License](https://img.shields.io/github/license/tu_usuario_github/nombre_de_tu_repo)

Cansado de revisar Marketplace a cada rato para ver si aparece ese producto que buscás? Creé este bot de Telegram en Python justo para eso. **Te avisa al instante por Telegram** cuando encuentra productos nuevos en Facebook Marketplace para tus búsquedas.

La clave? **No usa Selenium ni abre navegadores.** Va directo a la API de Facebook (GraphQL) usando la librería `requests`. Es mucho más liviano y rápido.

## ✨ Qué Puede Hacer?

* **Guardar búsquedas** como alertas (ej: "ps5 usada", "libros stephen king").
* Mandarte una **notificación al toque** si aparece algo nuevo para tus alertas activas.
* Buscar **manualmente** para cualquier alerta guardada cuando quieras.
* Llevar un **historial** de lo que encuentra para no repetirse.
* Mostrarte los resultados en el chat o darte un **HTML** prolijo.
* Dejarte **activar/desactivar** el monitoreo automático de cada alerta.
* Manejar tus alertas guardadas (listar, borrar).

## 🛠️ Cómo Empezar

Necesitás tener Python instalado (mejor 3.8+).

1.  **Bajate el código:**
    ```bash
    git clone [https://github.com/TizKah/Marketplace_Scrap_bot.git](https://github.com/TizKah/Marketplace_Scrap_bot.git)
    cd Marketplace_Scrap_bot
    ```

2.  **Instalá lo necesario:**
    ```bash
    pip install -r requirements.txt
    # requirements.txt tiene que tener: pyTelegramBotAPI, requests, python-dotenv
    ```

3.  **Configurá tus datos:**
    Creá un archivo `.env` en la misma carpeta que el bot. Adentro poné:
    ```dotenv
    BOT_TOKEN="EL_TOKEN_QUE_TE_DA_BOTFATHER"
    FACEBOOK_COOKIE="EL_VALOR_COMPLETO_DE_TU_COOKIE_DE_FACEBOOK"
    # Si querés buscar en otra zona o radio que no sea la default:
    # DEFAULT_LATITUDE=latitud_de_la_zona
    # DEFAULT_LONGITUDE=longitud_de_la_zona
    # DEFAULT_RADIUS_KM=radio_en_km
    ```
    * El `BOT_TOKEN` lo sacás hablando con BotFather en Telegram.

4.  **Corré el bot:**
    ```bash
    python marketplace_bot.py
    ```
    Listo, el bot ya debería estar vivo en Telegram.

## ⚠️ Ojo Con Esto

* Este método de usar cookies para la API **puede fallar**. Facebook puede cambiar la API o hacer que las cookies venzan seguido. Si el bot deja de andar, puede que necesites actualizar la cookie o que Facebook haya cambiado algo internamente.
* No le des demasiada frecuencia a las búsquedas automáticas. Si te pasás, Facebook podría detectarlo como sospechoso. Usalo con cuidado.
* Es un proyecto personal y experimental. No hay garantía de que funcione para siempre por los cambios externos de Facebook.

## 🤝 Querés Ayudar?

Si tenés ideas para mejorarlo, encontrás algún bug o querés agregar algo, bienvenido sea! Mandale un issue o un pull request.
