from sqlalchemy import select, func, delete
from db_session import SessionLocal
from init_db import Sensor, Measurement


def delete_incomplete_measurements():
    session = SessionLocal()
    try:
        # --- 1. Получаем ID нужных сенсоров ---
        sensors = (
            session.query(Sensor.sensor_id, Sensor.sensor_name)
            .filter(Sensor.sensor_name.in_(["Forecast Radiation", "T-1 Активная энергия, отдача"]))
            .all()
        )

        if len(sensors) != 2:
            print("❌ Ошибка: не найдены оба сенсора!")
            return

        forecast_id = next(s.sensor_id for s in sensors if s.sensor_name == "Forecast Radiation")
        pyrano_id = next(s.sensor_id for s in sensors if s.sensor_name == "T-1 Активная энергия, отдача")

        # --- 2. Находим временные метки, где есть оба сенсора ---
        valid_times_subq = (
            session.query(Measurement.measurement_time)
            .filter(Measurement.sensor_id.in_([forecast_id, pyrano_id]))
            .group_by(Measurement.measurement_time)
            .having(func.count(Measurement.sensor_id) == 2)
            .subquery()
        )

        # --- 3. Удаляем измерения, где времени нет в valid_times ---
        stmt = (
            delete(Measurement)
            .where(Measurement.measurement_time.not_in(select(valid_times_subq.c.measurement_time)))
        )

        result = session.execute(stmt)
        session.commit()

        print(f"✅ Удалено записей: {result.rowcount}")

    except Exception as e:
        session.rollback()
        print(f"❌ Ошибка при удалении: {e}")

    finally:
        session.close()


if __name__ == "__main__":
    delete_incomplete_measurements()
