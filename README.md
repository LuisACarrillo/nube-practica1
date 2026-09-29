# InstaBox

Backend de un servicio para bodas y eventos. Los invitados suben una foto y un mensaje. El servidor guarda la foto reducida, arma una polaroid y, al cerrar el evento, entrega las polaroids en un zip.

La API corre en una instancia EC2. Las fotos están en S3 y los registros en RDS. La contraseña de la base se lee en tiempo de ejecución desde Secrets Manager, con el instance profile `LabInstanceProfile`.

## Recursos

| Recurso | Nombre |
|---|---|
| API | EC2 `instabox-api`, puerto 8000 |
| Fotos | bucket `instabox-824471256666` (`pictures/` y `polaroids/`) |
| Base | RDS `instabox-db`, MySQL, base `instabox` |
| Tablas | `events` y `photos`, relacionadas por `event_id` |
| Secreto | el que RDS crea en Secrets Manager para el usuario `instabox` |

La dirección actual de la API es http://44.199.189.100:8000. Si la instancia se reinicia, usa la IP pública nueva de `instabox-api`.

## Cómo correrlo

En la instancia el servicio ya queda instalado en `/opt/instabox` y arranca con:

```bash
python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Las dependencias están en `requirements.txt`. La base no es pública: la API solo puede conectarse desde la EC2 que tiene el security group `instabox-api-sg`.

Crear un evento:

```bash
curl -X POST http://44.199.189.100:8000/events \
  -H "Content-Type: application/json" \
  -d '{"client_name":"Luis","event_type":"practica","event_date":"2026-09-28"}'
```

Subir una foto:

```bash
curl -X POST http://44.199.189.100:8000/upload \
  -F "event_id=2" \
  -F "message=Felicidades" \
  -F "photo=@foto.jpg"
```

Consultar el evento y el número de fotos:

```bash
curl http://44.199.189.100:8000/events/2
```

Descargar las polaroids:

```bash
curl -X POST http://44.199.189.100:8000/finish \
  -H "Content-Type: application/json" \
  -d '{"event_id":2}' \
  -o event-2.zip
```

También se pueden probar desde http://44.199.189.100:8000/docs.

## Eliminar los recursos

Con la AWS CLI apuntando a `us-east-1`:

```bash
bash teardown.sh
```

El script termina la EC2, borra la base, el secreto, el bucket y los security groups `instabox-api-sg` y `instabox-db-sg`. No borra la VPC por defecto, la llave `vockey`, `LabInstanceProfile` ni el bucket `logging-824471256666`.
