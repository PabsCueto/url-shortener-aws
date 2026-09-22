# URL Shortener API — Proyecto AWS Serverless

Proyecto de portafolio AWS de **Pablo Cueto Gatica**, construido para generar
experiencia práctica real con los servicios centrales del examen
**AWS Certified Developer – Associate (DVA-C02)**.

API serverless que acorta URLs largas, funcionalmente equivalente a las APIs
del portafolio en RapidAPI (FastAPI + Render), pero construida 100% sobre el
stack nativo de AWS — y con seguridad, CI/CD y observabilidad de nivel
producción, no solo el camino feliz.

## Arquitectura

Todo el stack se define como código en `template.yaml` (AWS SAM) y se
despliega automáticamente vía CI/CD en cada push a `main` — sin clicks
manuales en la consola.

## Endpoints

| Método | Ruta | Auth | Qué hace |
|---|---|---|---|
| `POST` | `/shorten` | API Key | Recibe `{"url": "..."}`, crea un shortcode y lo guarda |
| `GET` | `/{shortcode}` | Público | Redirige (302) a la URL original, incrementa contador |
| `GET` | `/stats/{shortcode}` | API Key | Devuelve metadata y número de clics |
| `DELETE` | `/admin/{shortcode}` | API Key + header `x-admin-token` | Elimina un shortcode |

`/{shortcode}` queda público a propósito: es el enlace que hace clic el
usuario final, no tiene sentido pedirle una API Key.

## Seguridad (Fase 2 — Dominio 2)

- **API Gateway API Key + Usage Plan** protege todos los endpoints excepto el
  redirect público. Throttle de 10 req/s (burst 20), cuota de 1000
  llamadas/mes.
- **Token de administrador en Secrets Manager**, requerido además de la API
  Key para `DELETE /admin/{shortcode}` (header `x-admin-token`) — dos capas
  de autorización independientes: infraestructura (API Gateway) y aplicación
  (lógica de negocio).
- El token se cachea en memoria fuera del handler para no llamar a Secrets
  Manager en cada invocación "caliente" (warm start).

## CI/CD (Fase 3 — Dominio 3)

- **GitHub Actions** despliega automáticamente en cada push a `main`:
  checkout → setup Python 3.13 → instala SAM CLI → asume rol vía OIDC →
  `sam build` → `sam deploy`.
- **Autenticación OIDC**: el pipeline asume el rol IAM
  `github-actions-url-shortener-deploy` de forma temporal — cero llaves de
  acceso IAM de larga duración guardadas como secreto en GitHub.
- El rol tiene una política de mínimo privilegio, ampliada de forma
  incremental conforme el proyecto lo requiere (ver el ejemplo real en
  Fase 4 abajo).

## Observabilidad y Troubleshooting (Fase 4 — Dominio 4)

- **Logging estructurado**: cada línea de log es un objeto JSON
  (`timestamp`, `level`, `request_id`, campos de contexto) impreso a
  `stdout` con `flush=True` explícito. Permite consultas de CloudWatch Logs
  Insights por campo (`filter level = "ERROR"`) en vez de grep sobre texto
  libre.
- **X-Ray**: tracing activo en la Lambda (`Tracing: Active`) y en el stage
  de API Gateway (`TracingEnabled: true`). `aws-xray-sdk` instrumenta
  automáticamente las llamadas a DynamoDB y Secrets Manager (`patch_all()`),
  más un subsegmento manual (`generate_unique_shortcode`) con una
  annotation indexada del shortcode generado.
- **CloudWatch Alarms + SNS**: 4 alarmas (errores de Lambda, duración
  acercándose al timeout, throttling de Lambda, errores 5xx de API
  Gateway) que notifican por correo vía un SNS Topic. El topic tiene una
  política explícita (`AWS::SNS::TopicPolicy`) que autoriza a
  `cloudwatch.amazonaws.com` a publicar — sin ella, las alarmas se disparan
  pero ningún correo llega.

**Dos bugs reales encontrados y resueltos en esta fase** (troubleshooting
real, no hipotético — buen material para entrevista, Dominio 4):

1. **Los logs no llegaban a CloudWatch** pese a que el código era correcto:
   el entorno de ejecución de Lambda se reutiliza entre invocaciones (warm
   start) en vez de terminar el proceso, así que el buffer de `stdout`
   nunca se vaciaba solo. Fix: `flush=True` explícito en cada log.
2. **El primer deploy con SNS/CloudWatch falló** con `AccessDenied` en
   `SNS:GetTopicAttributes`: el rol IAM del pipeline no tenía ningún
   permiso de SNS. Se agregó una política adicional
   (`sam-deploy-observability-permissions`) acotada a los ARNs exactos de
   este proyecto — nunca `"Resource": "*"`.

## Estructura del proyecto

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
> DynamoDB y Secrets Manager siguen yendo a los recursos reales en AWS.

## Cómo desplegarlo a AWS

Desde la Fase 3, el despliegue es automático: cualquier push a `main`
dispara el pipeline de GitHub Actions (`sam build` + `sam deploy` vía OIDC),
sin intervención manual. Para desplegar manualmente desde tu máquina (por
ejemplo, para depurar el propio pipeline):

```bash
sam-activate
sam build
sam deploy --guided   # primera vez: te pregunta nombre de stack, región, etc.
sam deploy             # despliegues siguientes
```

Al terminar, SAM (o el output `ApiEndpoint` del stack) te da la URL pública
real en AWS.

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
| Incremento atómico de contador con `UpdateExpression` | **1.3** Operaciones atómicas | "Implemento operaciones atómicas en DynamoDB para evitar condiciones de carrera" |
| `ConditionExpression` para evitar colisiones de shortcode | **1.3** Condition expressions | "Uso expresiones condicionales para garantizar integridad de datos sin transacciones explícitas" |
| Rol IAM con `DynamoDBCrudPolicy` (solo a esta tabla) | **2.1.5/2.1.6** Mínimo privilegio | "Implemento permisos de mínimo privilegio con roles IAM dedicados por función" |
| API Gateway API Key + Usage Plan (rate limit, cuota) | **2.1** Mecanismos de autenticación/autorización | "Configuro rate limiting y cuotas de uso en API Gateway para proteger el backend" |
| Token admin en Secrets Manager, cacheado fuera del handler | **2.2/2.3** Gestión de secretos | "Gestiono secretos rotables con Secrets Manager y optimizo su costo cacheándolos en memoria" |
| Autorización en dos capas (API Key + token de aplicación) | **2.1** Autorización en capas | "Separo el control de acceso de infraestructura del de lógica de negocio" |
| CI/CD con GitHub Actions + OIDC (sin llaves IAM estáticas) | **3.3** Despliegue automatizado y seguro | "Implemento pipelines que asumen roles IAM temporales vía OIDC en vez de credenciales de larga duración" |
| `template.yaml` define TODO el stack | **3.2** Infrastructure as Code | "Uso AWS SAM/CloudFormation para infraestructura reproducible y versionada en Git" |
| Política IAM del pipeline ampliada por recurso, diagnosticando el error exacto | **2.1.5/4.1** Mínimo privilegio + troubleshooting | "Diseño políticas IAM leyendo el mensaje de AccessDenied para agregar solo el permiso exacto que falta" |
| Logging estructurado en JSON con `request_id` | **Dominio 4** Instrumentar código para observabilidad | "Implemento logging estructurado para correr consultas de CloudWatch Logs Insights por campo" |
| X-Ray automático (`patch_all`) + subsegmento manual + annotation | **Dominio 4** Trazado distribuido | "Combino instrumentación automática del SDK con subsegmentos manuales para dar contexto de negocio al trace" |
| CloudWatch Alarms sobre Lambda/API Gateway + notificación SNS | **Dominio 4** Monitoreo proactivo | "Configuro alarmas proactivas con notificación automática en vez de descubrir fallas por quejas de usuarios" |
| Diagnóstico del bug de buffering de `stdout` en Lambda | **Dominio 4** Troubleshooting de causa raíz | "Diagnostiqué que los logs no llegaban por el comportamiento de reutilización de contenedores en Lambda, no por un bug de código" |
| `BillingMode: PAY_PER_REQUEST` (On-Demand) | **1.3** Modos de capacidad DynamoDB | "Elijo entre On-Demand y Provisioned Capacity según el patrón de carga esperado" |

### Progreso del proyecto

- ✅ **Fase 1 — Fundamentos (Dominio 1):** Lambda + API Gateway + DynamoDB, IaC con SAM.
- ✅ **Fase 2 — Seguridad (Dominio 2):** API Key + Usage Plan, Secrets Manager, autorización en dos capas.
- ✅ **Fase 3 — CI/CD (Dominio 3):** GitHub Actions con OIDC, cero credenciales de larga duración.
- ✅ **Fase 4 — Observabilidad y Troubleshooting (Dominio 4):** logging estructurado, X-Ray, CloudWatch Alarms + SNS.

---

**Stack:** Python 3.13 · AWS Lambda · API Gateway · DynamoDB · Secrets Manager
· X-Ray · CloudWatch · SNS · AWS SAM · GitHub Actions (OIDC)
**Licencia:** All rights reserved (repo privado — mismo patrón que el resto
del portafolio de Pablo en RapidAPI)
