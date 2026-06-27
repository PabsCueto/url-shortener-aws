"""
URL Shortener API - AWS Lambda Handler
========================================
Proyecto de portafolio AWS - Pablo Cueto Gatica

Arquitectura: API Gateway -> Lambda (este archivo) -> DynamoDB

Mapeo a temario AWS Certified Developer - Associate (DVA-C02):
- Dominio 1.1: Desarrollo de código para AWS Lambda (handler, event, context)
- Dominio 1.1.6: Crear y mantener APIs (routing manual por método+path)
- Dominio 1.3: Interactuar con DynamoDB (put_item, get_item, update_item atomico)
- Dominio 2.2: Configuracion segura via variables de entorno (no hardcoded)
- Dominio 4: Manejo de errores y logging para troubleshooting
"""

import json
import os
import string
import random
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# --- Configuracion via variables de entorno (Dominio 2.2) ---
# Nunca hardcodear el nombre de la tabla: se inyecta desde template.yaml
TABLE_NAME = os.environ["TABLE_NAME"]

# El cliente de DynamoDB se inicializa FUERA del handler.
# Esto es una buena practica de Lambda (Dominio 1.1): la conexion se
# reutiliza entre invocaciones "calientes" (warm starts), en vez de
# recrearse en cada llamada.
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

ALPHABET = string.ascii_letters + string.digits


def _generate_shortcode(length: int = 6) -> str:
    """Genera un codigo corto aleatorio alfanumerico."""
    return "".join(random.choices(ALPHABET, k=length))


def _response(status_code: int, body: dict, extra_headers: dict | None = None) -> dict:
    """
    Construye la respuesta en el formato EXACTO que API Gateway
    (integracion proxy) espera de una Lambda: statusCode, headers, body (string).
    """
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body),
    }


def _create_short_url(event: dict) -> dict:
    """POST /shorten - crea un nuevo shortcode para una URL larga."""
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Body invalido, se esperaba JSON"})

    original_url = payload.get("url")
    if not original_url:
        return _response(400, {"error": "El campo 'url' es requerido"})

    # Generamos shortcode y verificamos colision (poco probable, pero correcto)
    for _ in range(5):
        shortcode = _generate_shortcode()
        try:
            # condition_expression evita sobre-escribir un shortcode existente
            # (Dominio 1.3: operaciones condicionales en DynamoDB)
            table.put_item(
                Item={
                    "shortcode": shortcode,
                    "original_url": original_url,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "click_count": 0,
                },
                ConditionExpression="attribute_not_exists(shortcode)",
            )
            return _response(201, {
                "shortcode": shortcode,
                "original_url": original_url,
            })
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                continue  # colision rara, reintenta con otro shortcode
            raise

    return _response(500, {"error": "No se pudo generar un shortcode unico"})


def _redirect(shortcode: str) -> dict:
    """GET /{shortcode} - busca la URL original e incrementa el contador."""
    result = table.get_item(Key={"shortcode": shortcode})
    item = result.get("Item")

    if not item:
        return _response(404, {"error": "Shortcode no encontrado"})

    # Incremento ATOMICO del contador (Dominio 1.3): se hace en una sola
    # operacion update_item, sin leer-modificar-escribir, para evitar
    # condiciones de carrera si varios usuarios hacen clic al mismo tiempo.
    table.update_item(
        Key={"shortcode": shortcode},
        UpdateExpression="SET click_count = click_count + :inc",
        ExpressionAttributeValues={":inc": 1},
    )

    return _response(302, {}, extra_headers={"Location": item["original_url"]})


def _get_stats(shortcode: str) -> dict:
    """GET /stats/{shortcode} - regresa metadata y contador de clics."""
    result = table.get_item(Key={"shortcode": shortcode})
    item = result.get("Item")

    if not item:
        return _response(404, {"error": "Shortcode no encontrado"})

    return _response(200, {
        "shortcode": item["shortcode"],
        "original_url": item["original_url"],
        "created_at": item["created_at"],
        "click_count": int(item["click_count"]),
    })


def lambda_handler(event: dict, context) -> dict:
    """
    Punto de entrada de la Lambda.

    'event' y 'context' son los dos parametros estandar que AWS Lambda
    pasa siempre (Dominio 1.1). 'event' contiene los datos del trigger
    (en este caso, la peticion HTTP de API Gateway); 'context' contiene
    metadata de la ejecucion (request_id, tiempo restante, etc).
    """
    http_method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}
    resource = event.get("resource", "")

    try:
        if http_method == "POST" and resource == "/shorten":
            return _create_short_url(event)

        if http_method == "GET" and resource == "/stats/{shortcode}":
            return _get_stats(path_params.get("shortcode", ""))

        if http_method == "GET" and resource == "/{shortcode}":
            return _redirect(path_params.get("shortcode", ""))

        return _response(404, {"error": "Ruta no encontrada"})

    except Exception as exc:
        # Logging para CloudWatch (Dominio 4: troubleshooting).
        # Lo que se imprime con print() en Lambda aparece automaticamente
        # en CloudWatch Logs.
        print(f"ERROR no controlado: {exc}")
        return _response(500, {"error": "Error interno del servidor"})
