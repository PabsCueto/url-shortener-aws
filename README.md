# URL Shortener API — Proyecto AWS Serverless

Proyecto de portafolio AWS de **Pablo Cueto Gatica**, construido para generar
experiencia práctica real con los servicios centrales del examen
**AWS Certified Developer – Associate (DVA-C02)**.

API serverless que acorta URLs largas, funcionalmente equivalente a las APIs
del portafolio en RapidAPI (FastAPI + Render), pero construida 100% sobre el
stack nativo de AWS.

## Arquitectura

```
Cliente (curl / Postman / RapidAPI)
        │
        ▼
   API Gateway (REST API)
        │
        ▼
   AWS Lambda (Python 3.13) ── app.py
        │
        ▼
   DynamoDB (tabla: url-shortener-table)
```

Todo el stack se define como código en `template.yaml` (AWS SAM) y se
despliega con un solo comando — sin clicks manuales en la consola.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/shorten` | Recibe `{"url": "..."}`, crea un shortcode y lo guarda |
| `GET` | `/{shortcode}` | Redirige (302) a la URL original, incrementa contador |
| `GET` | `/stats/{shortcode}` | Devuelve metadata y número de clics |

## Estructura del proyecto

```
url-shortener-aws/
├── template.yaml              # Infraestructura como código (SAM)
├── url_shortener_function/
│   ├── app.py                 # Lógica de la Lambda (los 3 endpoints)
│   └── requirements.txt
├── events/                    # Eventos de prueba para sam local invoke
│   ├── event_create.json
│   ├── event_redirect.json
│   └── event_stats.json
└── README.md
```

## Cómo correrlo localmente

```bash
# 1. Activar el entorno virtual de SAM CLI (ver nota macOS abajo)
sam-activate

# 2. Construir el proyecto (empaqueta la Lambda y sus dependencias)
sam build

# 3. Probar UNA invocación local (sin desplegar nada a AWS)
sam local invoke UrlShortenerFunction --event events/event_create.json

# 4. O levantar la API completa localmente (simula API Gateway + Lambda)
sam local start-api
# luego en otra terminal:
curl -X POST http://127.0.0.1:3000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

> **Nota:** `sam local` simula la Lambda y API Gateway, pero las llamadas a
> DynamoDB siguen yendo a la tabla real en AWS (o puedes usar
> [DynamoDB Local](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.html)
> para pruebas 100% offline — fase futura).

## Cómo desplegarlo a AWS

```bash
sam-activate
sam build
sam deploy --guided   # primera vez: te pregunta nombre de stack, región, etc.
# despliegues siguientes:
sam deploy
```

Al terminar, SAM imprime el `ApiEndpoint` real en AWS — esa es tu URL pública.

## Nota macOS Monterey (Intel)

El instalador oficial `.pkg` de SAM CLI está roto en macOS 12 (error
`Symbol not found: (_mkfifoat)`). Este proyecto se desarrolla usando SAM CLI
instalado vía `pip` en un entorno virtual dedicado:

```bash
python3 -m venv ~/.sam-cli-venv
source ~/.sam-cli-venv/bin/activate
pip install aws-sam-cli==1.132.0
```

Alias en `~/.zshrc` para activarlo rápido: `sam-activate`

---

## Mapeo a AWS Certified Developer – Associate (DVA-C02)

Este proyecto no es solo "una API más" — cada decisión técnica corresponde
deliberadamente a una habilidad evaluada en el examen, para poder hablar de
**experiencia real** en entrevistas aunque la certificación todavía esté en
proceso.

| Qué se construyó | Habilidad DVA-C02 | Qué puedo decir en entrevista |
|---|---|---|
| Lambda en Python procesando eventos de API Gateway (`event`, `context`) | **1.1** Desarrollar código para AWS Lambda | "Escribo funciones Lambda en Python que procesan eventos HTTP nativos de API Gateway" |
| Rutas REST en API Gateway conectadas a Lambda (integración proxy) | **1.1.6** Crear y mantener APIs | "Diseño APIs REST con API Gateway, separando routing de lógica de negocio" |
| Tabla DynamoDB con partition key `shortcode`, `put_item`/`get_item`/`update_item` | **1.3** Interactuar con DynamoDB | "Modelo datos NoSQL en DynamoDB diseñando primero los patrones de acceso" |
| Incremento atómico de contador con `UpdateExpression` (sin leer-modificar-escribir) | **1.3** Operaciones atómicas / condition expressions | "Implemento operaciones atómicas en DynamoDB para evitar condiciones de carrera" |
| `ConditionExpression` para evitar colisiones de shortcode | **1.3** Condition expressions | "Uso expresiones condicionales para garantizar integridad de datos sin transacciones explícitas" |
| Rol IAM con `DynamoDBCrudPolicy` (solo a esta tabla) en vez de permisos amplios | **2.1.5 / 2.1.6** Principio de mínimo privilegio | "Implemento permisos de mínimo privilegio con roles IAM dedicados por función" |
| `TABLE_NAME` vía variable de entorno, no hardcodeado | **2.2** Gestión segura de configuración | "Gestiono configuración sensible vía variables de entorno en vez de hardcodearla" |
| `template.yaml` define TODO el stack (Lambda + API Gateway + DynamoDB) | **3.2** Infrastructure as Code | "Uso AWS SAM/CloudFormation para infraestructura reproducible y versionada en Git" |
| `sam local start-api` / `sam local invoke` antes de desplegar | **3.1** Empaquetar y probar localmente | "Pruebo Lambdas localmente con SAM antes de desplegar a producción" |
| `sam deploy` | **3.3** Desplegar aplicaciones serverless | "Despliego aplicaciones serverless completas con un solo comando vía SAM" |
| `print()` en Lambda → CloudWatch Logs, manejo de excepciones con status codes correctos | **Dominio 4** Resolución de problemas | "Diagnostico errores en producción usando CloudWatch Logs y manejo estructurado de excepciones" |
| `BillingMode: PAY_PER_REQUEST` (On-Demand) | **1.3** Modos de capacidad DynamoDB | "Elijo entre On-Demand y Provisioned Capacity según el patrón de carga esperado" |

### Próximas fases (mismo proyecto, subiendo complejidad gradualmente)

- **Fase 2 — Seguridad (Dominio 2):** API Key de API Gateway o Cognito para
  autenticar `/shorten`; mover cualquier secreto a Secrets Manager / Parameter Store.
- **Fase 3 — CI/CD (Dominio 3):** GitHub Actions ejecutando `sam build` +
  `sam deploy` automáticamente en cada push a `main`.
- **Fase 4 — Resiliencia (Dominio 4):** Dead Letter Queue (SQS) para
  invocaciones fallidas, alarmas de CloudWatch sobre errores y latencia.

---

**Stack:** Python 3.13 · AWS Lambda · API Gateway · DynamoDB · AWS SAM
**Licencia:** All rights reserved (repo privado — mismo patrón que el resto
del portafolio de Pablo en RapidAPI)
