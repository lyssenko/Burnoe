import logging
import pandas as pd
import re
from collections import defaultdict
from datetime import datetime, timedelta
from collections import namedtuple
from init_db import Sensor, Measurement
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sensor_labels import VIRTUAL_SENSOR_GROUPS, MONTH_DIGIT

DataPoint = namedtuple("DataPoint", ["measurement_time", "value"])

logger = logging.getLogger(__name__)


def excel_date_to_datetime(x):
    return datetime(1899, 12, 30) + timedelta(days=x)


def date_to_wind_speed(dt):
    if not isinstance(dt, datetime):
        return None
    return float(f"{dt.day}.{dt.month}")


def try_parse_excel_date(val):

    try:
        x = float(val)
        if x > 40000 and x < 90000:
            dt = datetime(1899, 12, 30) + timedelta(days=x)
            return float(f"{dt.day}.{dt.month}")
    except Exception:
        pass
    return None


def parse_messy_excel_number(val):
    if pd.isna(val):
        return None
    s = str(val).strip().lower()

    date_speed = try_parse_excel_date(s)
    if date_speed is not None:
        return date_speed

    match = re.match(r"(\d+)[\.,]?\s*([а-яё]+)", s)
    if match:
        int_part = match.group(1)
        month_part = match.group(2)
        frac = MONTH_DIGIT.get(month_part[:4], None)
        if frac is not None:
            return float(f"{int_part}.{frac}")

    s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None


def parse_value_by_type(col, val):
    col_l = col.lower()
    if any(word in col_l for word in ["wind", "ветр", "temp", "температ"]):
        value = parse_messy_excel_number(val)
    else:
        try:
            value = float(str(val).replace(",", "."))
        except Exception:
            return None

    if value is not None:
        if any(word in col_l for word in ["wind", "ветр"]):
            if value < 0 or value > 80:
                return None
        if any(word in col_l for word in ["temp", "температ"]):
            if value < -60 or value > 70:
                return None

    return value


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
                value = parse_value_by_type(col, row[col])
                if value is None:
                    continue

                sensor_id = sensor_map[col]
                stmt = (
                    sqlite_insert(Measurement)
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
    skipped_time = 0
    skipped_value = 0
    skipped_sensor = 0
    inserted = 0
    date = "2000-01-01"
    try:
        xl = pd.ExcelFile(file)
        df = xl.parse("Лист1")

        original_columns = df.columns.tolist()
        df.columns = [col.strip().split("\n")[0] for col in df.columns]

        df = df.dropna(subset=[df.columns[1]])
        df = df[~df[df.columns[1]].isin(["Сумма", "Среднее"])]
        dt1 = pd.to_datetime(
            df[df.columns[1]].astype(str), dayfirst=True, errors="coerce"
        )
        dt2 = pd.to_datetime(
            df[df.columns[1]].astype(str),
            format="%d.%m.%Y %H:%M",
            dayfirst=True,
            errors="coerce",
        )
        dt_final = dt1.combine_first(dt2)
        df[df.columns[1]] = dt_final

        df = df.dropna(subset=[df.columns[1]])

        df[df.columns[1]] = df[df.columns[1]].dt.floor("min")

        def correct_time(dt):
            if pd.isna(dt):
                return dt
            return (
                dt + timedelta(hours=5)
                if dt.date() < datetime(2024, 3, 1).date()
                else dt + timedelta(hours=4)
            )

        df[df.columns[1]] = df[df.columns[1]].apply(correct_time)

        melted = df.melt(
            id_vars=[df.columns[1]],
            value_vars=df.columns[2:],
            var_name="sensor_name",
            value_name="value",
        )
        melted = melted.rename(columns={df.columns[1]: "measurement_time"})
        skipped_value = melted["value"].isna().sum()
        skipped_time = melted["measurement_time"].isna().sum()
        melted = melted.dropna(subset=["value", "measurement_time"])

        match = re.search(r"T[\s\-]?(\d)", file.filename.upper())
        source_label = f"T-{match.group(1)}" if match else "T-?"
        date = melted["measurement_time"].iloc[0].date().strftime("%Y-%m-%d")

        if any("Показания счетчика" in col for col in original_columns):
            print("Обнаружены накопленные данные — преобразуем в приращения.")
            melted.sort_values("measurement_time", inplace=True)
            for sensor_name in melted["sensor_name"].unique():
                mask = melted["sensor_name"] == sensor_name
                melted.loc[mask, "value"] = melted.loc[mask, "value"].diff()
            melted = melted.dropna(subset=["value"])

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
                if pd.isna(sensor_id) or not isinstance(sensor_id, int):
                    skipped_sensor += 1
                    continue

                stmt = (
                    sqlite_insert(Measurement)
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

        print(
            f"Всего вставлено: {inserted}, пропущено по времени: {skipped_time}, по значению: {skipped_value}, по sensor_id: {skipped_sensor}"
        )
        total_value = melted["value"].sum()
        print(f"Суммарное значение: {total_value}")
    except Exception as e:
        errors.append(f"Не удалось обработать Excel: {e}")
    return inserted, date


def get_sensor_names(db, actual_id: int, forecast_id: int):
    try:
        if actual_id == -1:
            actual_name = "Среднее"
            actual_unit = "W/m2"
        else:
            sensor = db.query(Sensor).get(actual_id)
            actual_name = sensor.sensor_name if sensor else None
            actual_unit = sensor.unit if sensor else ""

        forecast = db.query(Sensor).get(forecast_id)
        forecast_name = forecast.sensor_name if forecast else None
        forecast_unit = forecast.unit if forecast else ""

        return actual_name, forecast_name, actual_unit, forecast_unit
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


def handle_uploaded_file(file, db, errors):
    inserted = 0
    date = "2000-01-01"
    filename = file.filename.lower()

    if filename.endswith(".xlsx"):
        ins, date = process_excel_energy_file(file, db, errors)
        inserted += ins
    else:
        df = pd.read_csv(file, sep=";")
        date = datetime.strptime(df["Date"][3], "%d.%m.%Y").strftime("%Y-%m-%d")

        if df.shape[1] < 3:
            errors.append(f"Файл {file.filename} содержит недостаточно столбцов.")
            return 0
        if df.iloc[0, 0].strip().startswith("["):
            df = df.iloc[1:].reset_index(drop=True)

        sensor_cols = df.columns[2:]
        sensor_map = {}
        for col in sensor_cols:
            name = re.sub(r"\.irradiation_(raw|temp_compensated)$", "", col.strip())
            name = re.sub(
                r"^Pyranometer\.(horizontal|module)\.(\d+)",
                r"Pyranometer.module.\2",
                name,
            )
            sensor_type, unit = determine_sensor_type_and_unit(col)
            sensor_id = get_sensor_id(db, name, sensor_type, unit)
            sensor_map[col] = sensor_id

        inserted += process_measurements(
            df, sensor_cols, sensor_map, db, file.filename, errors
        )

    return inserted, date


def parse_date_range(start_str, end_str):
    try:
        if start_str and len(start_str) == 10:
            start_str += " 00:00:00"
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        start_dt = None

    try:
        if end_str and len(end_str) == 10:
            end_str += " 23:59:59"
        end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        end_dt = None

    return start_dt, end_dt


def get_avg_measurements_for_all(db, start_dt, end_dt):
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
        valid_vals = [v for v in vals if v is not None]
        if valid_vals:
            avg = sum(valid_vals) / len(valid_vals)
            avg_data.append(type("Obj", (), {"measurement_time": t, "value": avg}))
    return avg_data


def group_measurements(measurements, interval_minutes):

    grouped = defaultdict(list)
    for m in measurements:
        dt = m.measurement_time
        if m.value is not None:
            minute_bucket = (dt.minute // interval_minutes) * interval_minutes
            dt_group = dt.replace(minute=minute_bucket, second=0, microsecond=0)
            grouped[dt_group].append(m.value)

    return {dt: sum(vals) / len(vals) for dt, vals in grouped.items() if vals}


def save_virtual_averages(db, start_time, end_time):
    for virtual_name, source_names in VIRTUAL_SENSOR_GROUPS.items():
        virtual_sensor = db.query(Sensor).filter_by(sensor_name=virtual_name).first()
        if not virtual_sensor:
            print(f"Виртуальный сенсор {virtual_name} не найден.")
            continue

        sensors = db.query(Sensor).filter(Sensor.sensor_name.in_(source_names)).all()
        sensor_ids = [s.sensor_id for s in sensors if s]
        if len(sensor_ids) != len(source_names):
            print(f"Не все сенсоры группы найдены для {virtual_name}")
            continue

        rows = (
            db.query(
                Measurement.measurement_time, Measurement.value, Measurement.sensor_id
            )
            .filter(
                Measurement.sensor_id.in_(sensor_ids),
                Measurement.measurement_time.between(start_time, end_time),
            )
            .all()
        )
        if not rows:
            print(f"Нет данных для расчёта {virtual_name}")
            continue

        df = pd.DataFrame(rows, columns=["time", "value", "sensor_id"])
        df = df.dropna()
        if df.empty:
            continue

        df["time"] = pd.to_datetime(df["time"])
        avg_df = df.groupby("time")["value"].mean().reset_index()
        avg_df["value"] = avg_df["value"].round(2)
        for _, row in avg_df.iterrows():
            stmt = (
                sqlite_insert(Measurement)
                .values(
                    sensor_id=virtual_sensor.sensor_id,
                    measurement_time=row["time"],
                    value=row["value"],
                )
                .on_conflict_do_update(
                    index_elements=["sensor_id", "measurement_time"],
                    set_={"value": row["value"]},
                )
            )
            db.execute(stmt)

    print("Средние значения для виртуальных сенсоров успешно сохранены.")
