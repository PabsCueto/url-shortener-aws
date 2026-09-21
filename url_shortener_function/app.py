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
- Dominio 2: Gestion de secretos con Secrets Manager, autorizacion en capas
- Dominio 4: Observabilidad - logging estructurado y X-Ray tracing (Fase 4)
"""

import json
import os
import string
import random
import traceback
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from aws_xray_sdk.core import patch_all, xray_recorder

# patch_all() intercepta las llamadas de boto3 (y otras librerias soportadas)
# para crear subsegmentos de X-Ray automaticamente, SIN tocar el codigo de
# cada llamada. Debe correr una sola vez, al cargar el modulo (cold start),
# antes de que se hagan llamadas reales - por eso va aqui arriba.
patch_all()

TABLE_NAME = os.environ["TABLE_NAME"]
ADMIN_SECRET_ARN = os.environ["ADMIN_SECRET_ARN"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

secrets_client = boto3.client("secretsmanager")

_cached_admin_token = None

ALPHABET = string.ascii_letters + string.digits


def _log(level: str, message: str, request_id: str = "", **extra) -> None:
    """Emite una linea de log en formato JSON a stdout (ver Fase 4, paso 1)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "request_id": request_id,
    }
    entry.update(extra)
    print(json.dumps(entry), flush=True)


def _generate_shortcode(length: int = 6) -> str:
    """Genera un codigo corto aleatorio alfanumerico."""
    return "".join(random.choices(ALPHABET, k=length))


def _response(status_code: int, body: dict, extra_headers: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body),
    }


def _get_admin_token() -> str:
    global _cached_admin_token
    if _cached_admin_token is None:
        response = secrets_client.get_secret_value(SecretId=ADMIN_SECRET_ARN)
        secret_dict = json.loads(response["SecretString"])
        _cached_admin_token = secret_dict["token"]
    return _cached_admin_token


def _create_short_url(event: dict, request_id: str) -> dict:
    """POST /shorten - crea un nuevo shortcode para una URL larga."""
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        _log("WARNING", "Body invalido en /shorten", request_id=request_id)
        return _response(400, {"error": "Body invalido, se esperaba JSON"})

    original_url = payload.get("url")
    if not original_url:
        _log("WARNING", "Falta el campo 'url' en /shorten", request_id=request_id)
        return _response(400, {"error": "El campo 'url' es requerido"})

    # Subsegmento MANUAL de X-Ray (Dominio 4): patch_all() ya traza las
    # llamadas individuales a boto3 (cada put_item), pero aqui agrupamos
    # todo el bloque "generar shortcode unico" (que puede reintentar
    # varias veces) bajo un subsegmento propio, con nombre legible, en
    # vez de ver llamadas sueltas a DynamoDB sin contexto de negocio.
    with xray_recorder.capture("generate_unique_shortcode"):
        for _ in range(5):
            shortcode = _generate_shortcode()
            try:
                table.put_item(
                    Item={
                        "shortcode": shortcode,
                        "original_url": original_url,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "click_count": 0,
                    },
                    ConditionExpression="attribute_not_exists(shortcode)",
                )
                # Annotation: queda INDEXADO, se puede filtrar en la consola
                # de X-Ray (ej. annotation.shortcode = "meRfLo") o via API
                # (get_trace_summaries con FilterExpression). El "metadata"
                # (a diferencia de las annotations) NO se indexa, solo sirve
                # para inspeccionar el detalle de un trace ya encontrado.
                xray_recorder.current_subsegment().put_annotation("shortcode", shortcode)
                _log("INFO", "Shortcode creado", request_id=request_id,
                     shortcode=shortcode, event_type="url_created")
                return _response(201, {
                    "shortcode": shortcode,
                    "original_url": original_url,
                })
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    _log("WARNING", "Colision de shortcode, reintentando",
                         request_id=request_id, shortcode=shortcode)
                    continue
                raise

    _log("ERROR", "No se pudo generar un shortcode unico tras 5 intentos",
         request_id=request_id)
    return _response(500, {"error": "No se pudo generar un shortcode unico"})


def _redirect(shortcode: str, request_id: str) -> dict:
    """GET /{shortcode} - busca la URL original e incrementa el contador."""
    result = table.get_item(Key={"shortcode": shortcode})
    item = result.get("Item")

    if not item:
        _log("WARNING", "Shortcode no encontrado en redirect",
             request_id=request_id, shortcode=shortcode)
        return _response(404, {"error": "Shortcode no encontrado"})

    table.update_item(
        Key={"shortcode": shortcode},
        UpdateExpression="SET click_count = click_count + :inc",
        ExpressionAttributeValues={":inc": 1},
    )

    _log("INFO", "Redirect exitoso", request_id=request_id,
         shortcode=shortcode, event_type="redirect")
    return _response(302, {}, extra_headers={"Location": item["original_url"]})


def _get_stats(shortcode: str, request_id: str) -> dict:
    """GET /stats/{shortcode} - regresa metadata y contador de clics."""
    result = table.get_item(Key={"shortcode": shortcode})
    item = result.get("Item")

    if not item:
        _log("WARNING", "Shortcode no encontrado en stats",
             request_id=request_id, shortcode=shortcode)
        return _response(404, {"error": "Shortcode no encontrado"})

    return _response(200, {
        "shortcode": item["shortcode"],
        "original_url": item["original_url"],
        "created_at": item["created_at"],
        "click_count": int(item["click_count"]),
    })


def _delete_shortcode(event: dict, shortcode: str, request_id: str) -> dict:
    """DELETE /admin/{shortcode} - elimina un shortcode."""
    headers = event.get("headers") or {}
    provided_token = headers.get("x-admin-token") or headers.get("X-Admin-Token")

    if not provided_token or provided_token != _get_admin_token():
        _log("WARNING", "Intento de borrado con token admin invalido o ausente",
             request_id=request_id, shortcode=shortcode, event_type="admin_auth_failed")
        return _response(401, {"error": "Token de administrador invalido o ausente"})

    result = table.get_item(Key={"shortcode": shortcode})
    if "Item" not in result:
        _log("WARNING", "Intento de borrar shortcode inexistente",
             request_id=request_id, shortcode=shortcode)
        return _response(404, {"error": "Shortcode no encontrado"})

    table.delete_item(Key={"shortcode": shortcode})
    _log("INFO", "Shortcode eliminado", request_id=request_id,
         shortcode=shortcode, event_type="url_deleted")
    return _response(200, {"message": f"Shortcode '{shortcode}' eliminado correctamente"})


def lambda_handler(event: dict, context) -> dict:
    """Punto de entrada de la Lambda."""
    request_id = context.aws_request_id
    http_method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}
    resource = event.get("resource", "")

    _log("INFO", "Peticion recibida", request_id=request_id,
         method=http_method, resource=resource)

    try:
        if http_method == "POST" and resource == "/shorten":
            return _create_short_url(event, request_id)

        if http_method == "GET" and resource == "/stats/{shortcode}":
            return _get_stats(path_params.get("shortcode", ""), request_id)

        if http_method == "DELETE" and resource == "/admin/{shortcode}":
            return _delete_shortcode(event, path_params.get("shortcode", ""), request_id)

        if http_method == "GET" and resource == "/{shortcode}":
            return _redirect(path_params.get("shortcode", ""), request_id)

        _log("WARNING", "Ruta no encontrada", request_id=request_id,
             method=http_method, resource=resource)
        return _response(404, {"error": "Ruta no encontrada"})

    except Exception as exc:
        _log("ERROR", "Excepcion no controlada", request_id=request_id,
             error=str(exc), traceback=traceback.format_exc())
        return _response(500, {"error": "Error interno del servidor"})
