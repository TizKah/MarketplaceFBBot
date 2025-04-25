import html as html_lib

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