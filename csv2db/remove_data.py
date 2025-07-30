# from datetime import datetime, date
from sqlalchemy import extract
from db_session import SessionLocal
from init_db import Measurement  # предполагаем, что так называется файл с моделями
from datetime import datetime, timedelta

start = datetime(2025, 7, 13)
end = start + timedelta(days=1)

with SessionLocal() as db:
    deleted_rows = db.query(Measurement).filter(
        Measurement.measurement_time >= start,
        Measurement.measurement_time < end
    ).delete(synchronize_session=False)

    db.commit()
    print(f"Удалено записей: {deleted_rows}")