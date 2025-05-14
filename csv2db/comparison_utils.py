from collections import defaultdict
from datetime import datetime, timedelta
from collections import namedtuple
from init_db import Sensor, Measurement
import logging
from sqlalchemy import func
import pandas as pd
import os
from sqlalchemy.dialects.sqlite import insert
import re

DataPoint = namedtuple("DataPoint", ["measurement_time", "value"])

logger = logging.getLogger(__name__)

def process_measurements(df, sensor_cols, sensor_map, db, filename, errors):
    inserted = 0
    for index, row in df.iterrows():
        try:
            date_str = str(row.iloc[0]).strip()
            time_str = str(row.iloc[1]).strip()
            dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
        except Exception as e:
            errors.append(f"{filename}, строка {index+2}: ошибка даты/времени — {e}")
            continue

        for col in sensor_cols:
            try:
                value = float(row[col])
                sensor_id = sensor_map[col]
                stmt = (
                    insert(Measurement)
                    .values(sensor_id=sensor_id, measurement_time=dt, value=value)
                    .on_conflict_do_update(
                        index_elements=["sensor_id", "measurement_time"],
                        set_={"value": value},
                    )
                )
                db.execute(stmt)
                inserted += 1
            except Exception as e:
                errors.append(f"{filename}, строка {index+2}, столбец '{col}': {e}")
    return inserted


def process_excel_energy_file(file, db, errors):
    inserted = 0
    try:
        xl = pd.ExcelFile(file)
        df = xl.parse("Лист1")
        df.columns = [col.strip().split("\n")[0] for col in df.columns]
        df = df.dropna(subset=[df.columns[1]])
        df = df[~df[df.columns[1]].isin(["Сумма", "Среднее"])]
        df[df.columns[1]] = pd.to_datetime(df[df.columns[1]], format="%d.%m.%Y %H:%M")
        melted = df.melt(
            id_vars=[df.columns[1]],
            value_vars=df.columns[2:],
            var_name="sensor_name",
            value_name="value",
        )
        melted = melted.rename(columns={df.columns[1]: "measurement_time"})
        melted = melted.dropna(subset=["value"])
      
        match = re.search(r"T-\d{1,2}", file.filename.upper())
        source_label = match.group(0) if match else "T-?"

        for _, row in melted.iterrows():
            try:
                raw_sensor_name = row["sensor_name"].strip()
                full_sensor_name = f"{source_label} {raw_sensor_name}"

                if "Активная энергия" in raw_sensor_name:
                    sensor_type = "energy_active"
                    unit = "kWh"
                elif "Реактивная энергия" in raw_sensor_name:
                    sensor_type = "energy_reactive"
                    unit = "kvarh"
                else:
                    sensor_type = "unknown"
                    unit = ""

                sensor_id = get_sensor_id(db, full_sensor_name, sensor_type, unit)
                stmt = (
                    insert(Measurement)
                    .values(
                        sensor_id=sensor_id,
                        measurement_time=row["measurement_time"],
                        value=float(row["value"]),
                    )
                    .on_conflict_do_update(
                        index_elements=["sensor_id", "measurement_time"],
                        set_={"value": float(row["value"])},
                    )
                )
                db.execute(stmt)
                inserted += 1
            except Exception as e:
                errors.append(f"Ошибка в строке Excel: {e}")
    except Exception as e:
        errors.append(f"Не удалось обработать Excel: {e}")
    return inserted


def get_sensor_names(db, actual_id: int, forecast_id: int):
    try:
        if actual_id == -1:
            actual_name = "Среднее"
        else:
            sensor = db.query(Sensor).get(actual_id)
            actual_name = sensor.sensor_name if sensor else None

        forecast = db.query(Sensor).get(forecast_id)
        forecast_name = forecast.sensor_name if forecast else None

        return actual_name, forecast_name
    except Exception as e:
        logger.error("Error in get_sensor_names: %s", e, exc_info=True)
        raise


def determine_sensor_type_and_unit(col_name):
    lower = col_name.lower()
    if "irradiation" in lower or "pyranometer" in lower:
        return "radiation", "W/m2"
    elif "wind" in lower or "ветра" in lower:
        return "wind", "m/s"
    elif "temp" in lower or "temperature" in lower or "температура" in lower:
        return "temperature", "℃"
    else:
        return "unknown", "unknown"


def get_measurements(db, sensor_id: int, start_dt=None, end_dt=None):
    try:
        query = db.query(Measurement.measurement_time, Measurement.value).filter(
            Measurement.sensor_id == sensor_id
        )
        if start_dt:
            query = query.filter(Measurement.measurement_time >= start_dt)
        if end_dt:
            query = query.filter(Measurement.measurement_time < end_dt)
        return query.order_by(Measurement.measurement_time).all()
    except Exception as e:
        logger.error(
            "Error in get_measurements for sensor %s: %s", sensor_id, e, exc_info=True
        )
        raise


def get_avg_measurements_for_all(db, start_dt, end_dt):
    Sensor = db.query_model("Sensor")
    Measurement = db.query_model("Measurement")

    sensors = (
        db.query(Sensor)
        .filter(
            Sensor.sensor_type == "radiation", ~Sensor.sensor_name.ilike("%forecast%")
        )
        .all()
    )
    all_ids = [s.sensor_id for s in sensors]

    all_data = (
        db.query(Measurement)
        .filter(
            Measurement.sensor_id.in_(all_ids),
            Measurement.measurement_time >= start_dt,
            Measurement.measurement_time < end_dt,
        )
        .all()
    )

    time_group = defaultdict(list)
    for m in all_data:
        time_group[m.measurement_time].append(m.value)

    avg_data = []
    for t, vals in time_group.items():
        valid_vals = [v if v is not None and v >= 0 else 0 for v in vals]
        if valid_vals:
            avg = sum(valid_vals) / len(valid_vals)
            avg_data.append(DataPoint(t, avg))
    return avg_data


def get_common_time_series(actual_data, forecast_data):
    all_times = sorted(
        set(
            [m.measurement_time for m in actual_data]
            + [m.measurement_time for m in forecast_data]
        )
    )
    actual_dict = {m.measurement_time: m.value for m in actual_data}
    forecast_dict = {m.measurement_time: m.value for m in forecast_data}

    return all_times, actual_dict, forecast_dict


def get_sensor_id(db, sensor_name, sensor_type, unit):
    sensor = db.query(Sensor).filter_by(sensor_name=sensor_name).first()
    if sensor:
        return sensor.sensor_id
    new_sensor = Sensor(sensor_name=sensor_name, sensor_type=sensor_type, unit=unit)
    db.add(new_sensor)
    db.flush()
    return new_sensor.sensor_id


def compare_sensors(db, actual_id, forecast_id, start_dt, end_dt):
    actual_data = (
        get_avg_measurements_for_all(db, start_dt, end_dt)
        if actual_id == -1
        else get_measurements(db, actual_id, start_dt, end_dt)
    )
    forecast_data = get_measurements(db, forecast_id, start_dt, end_dt)
    labels, actual_dict, forecast_dict = get_common_time_series(
        actual_data, forecast_data
    )

    return {
        "labels": labels,
        "actual_values": [actual_dict.get(t) for t in labels],
        "forecast_values": [forecast_dict.get(t) for t in labels],
    }
