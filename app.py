import io
import json
import textwrap
import uuid
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import date

import boto3
import pymysql
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel

REGION = "us-east-1"
BUCKET = "instabox-824471256666"
DB_HOST = "instabox-db.cj1xxgduvgco.us-east-1.rds.amazonaws.com"
DB_NAME = "instabox"
SECRET_ID = "arn:aws:secretsmanager:us-east-1:824471256666:secret:rds!db-8696e644-2eb6-4f22-9009-e37faa50902f-PJZHSk"

s3 = boto3.client("s3", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)


class EventIn(BaseModel):
    client_name: str
    event_type: str
    event_date: date


class FinishIn(BaseModel):
    event_id: int


@contextmanager
def db():
    secret = json.loads(secrets.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    connection = pymysql.connect(
        host=DB_HOST,
        user=secret["username"],
        password=secret["password"],
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            yield cursor
    finally:
        connection.close()


def event_exists(cursor, event_id):
    cursor.execute("SELECT 1 FROM events WHERE event_id = %s", (event_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")


def jpeg_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def make_polaroid(photo, message):
    side, bottom = 20, 72
    canvas = Image.new("RGB", (photo.width + side * 2, photo.height + side + bottom), "white")
    canvas.paste(photo, (side, side))
    text = "\n".join(textwrap.wrap(message, width=20)[:3])
    draw = ImageDraw.Draw(canvas)
    draw.multiline_text(
        (canvas.width / 2, photo.height + side + 14),
        text,
        fill="black",
        font=ImageFont.load_default(size=14),
        anchor="ma",
        align="center",
    )
    return canvas


def init_db():
    with db() as cursor:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS events (
                event_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                client_name VARCHAR(200) NOT NULL,
                event_type VARCHAR(100) NOT NULL,
                event_date DATE NOT NULL)"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS photos (
                photo_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                event_id INT NOT NULL,
                message VARCHAR(300) NOT NULL,
                picture_key VARCHAR(255) NOT NULL,
                polaroid_key VARCHAR(255) NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events (event_id))"""
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/events")
def create_event(body: EventIn):
    with db() as cursor:
        cursor.execute(
            "INSERT INTO events (client_name, event_type, event_date) VALUES (%s, %s, %s)",
            (body.client_name, body.event_type, body.event_date),
        )
        return {"event_id": cursor.lastrowid}


@app.post("/upload")
async def upload(event_id: int = Form(...), message: str = Form(...), photo: UploadFile = File(...)):
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(await photo.read()))).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="El archivo no es una imagen valida")

    small = image.resize((128, 128))
    picture_key = f"pictures/{uuid.uuid4()}.jpg"
    polaroid_key = f"polaroids/{uuid.uuid4()}.jpg"

    with db() as cursor:
        event_exists(cursor, event_id)
        s3.put_object(Bucket=BUCKET, Key=picture_key, Body=jpeg_bytes(small), ContentType="image/jpeg")
        s3.put_object(
            Bucket=BUCKET,
            Key=polaroid_key,
            Body=jpeg_bytes(make_polaroid(small, message)),
            ContentType="image/jpeg",
        )
        cursor.execute(
            "INSERT INTO photos (event_id, message, picture_key, polaroid_key) VALUES (%s, %s, %s, %s)",
            (event_id, message, picture_key, polaroid_key),
        )
        return {"photo_id": cursor.lastrowid, "picture_key": picture_key, "polaroid_key": polaroid_key}


@app.get("/events/{event_id}")
def get_event(event_id: int):
    with db() as cursor:
        cursor.execute(
            """SELECT e.event_id, e.client_name, e.event_type, e.event_date,
                      COUNT(p.photo_id) AS photo_count
               FROM events e
               LEFT JOIN photos p ON p.event_id = e.event_id
               WHERE e.event_id = %s
               GROUP BY e.event_id""",
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        row["event_date"] = row["event_date"].isoformat()
        return row


@app.post("/finish")
def finish(body: FinishIn):
    with db() as cursor:
        event_exists(cursor, body.event_id)
        cursor.execute(
            "SELECT polaroid_key FROM photos WHERE event_id = %s ORDER BY photo_id",
            (body.event_id,),
        )
        keys = [row["polaroid_key"] for row in cursor.fetchall()]

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for key in keys:
            obj = s3.get_object(Bucket=BUCKET, Key=key)
            bundle.writestr(key.split("/")[-1], obj["Body"].read())

    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=event-{body.event_id}.zip"},
    )
