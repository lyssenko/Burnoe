from sqlalchemy.orm import scoped_session
from db_session import SessionLocal
from init_db import Sensor, Measurement
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
import pandas as pd
from collections import namedtuple
from helpers.comparison_utils import (
    get_sensor_names,
    get_measurements,
    get_avg_measurements_for_all,
    get_common_time_series,
    get_sensor_id,
    determine_sensor_params
)


app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('dataFile')
    if not files:
        return "Файл(ы) не выбраны", 400

    db = scoped_session(SessionLocal)
    total_inserted = 0
    errors = []

    for file in files:
        if not file.filename:
            continue
        try:
            df = pd.read_csv(file, sep=';')
        except Exception as e:
            errors.append(f"Ошибка чтения {file.filename}: {e}")
            continue

        if df.shape[1] < 3:
            errors.append(f"Файл {file.filename} содержит недостаточно столбцов.")
            continue

        if df.iloc[0, 0].strip().startswith('['):
            df = df.iloc[1:].reset_index(drop=True)

        sensor_cols = df.columns[2:]
        sensor_map = {}

        for col in sensor_cols:
            sensor_name = col.replace(".irradiation_raw", "").strip()
            sensor_type, unit = determine_sensor_params(col)
            sensor_id = get_sensor_id(db, sensor_name, sensor_type, unit)
            sensor_map[col] = sensor_id

        total_inserted += process_measurements(df, sensor_cols, sensor_map, db, file.filename, errors)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return f"Ошибка при сохранении данных: {e}", 500
    finally:
        db.close()

    if errors:
        msg = f"Загружено {total_inserted} измерений, но возникли ошибки:\n" + "\n".join(errors[:10])
        if len(errors) > 10:
            msg += f"\n... и ещё {len(errors) - 10} ошибок скрыто."
        return msg, 400

    return f"Данные успешно загружены. Всего записей: {total_inserted}."


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
                m = Measurement(sensor_id=sensor_id, measurement_time=dt, value=value)
                db.add(m)
                inserted += 1
            except Exception as e:
                errors.append(f"{filename}, строка {index+2}, столбец '{col}': {e}")
    return inserted


@app.route('/upload_forecast', methods=['POST'])
def upload_forecast():
    from sqlalchemy.exc import IntegrityError
    file = request.files.get('forecastFile')
    if not file or not file.filename:
        return "Файл прогноза не выбран", 400

    db = scoped_session(SessionLocal)

    sensor_name = "B1_forecast"
    sensor_type = "radiation"
    unit = "W/m2"

    sensor = db.query(Sensor).filter_by(sensor_name=sensor_name).first()
    if sensor:
        sensor_id = sensor.sensor_id
    else:
        sensor = Sensor(sensor_name=sensor_name, sensor_type=sensor_type, unit=unit)
        db.add(sensor)
        db.flush()
        sensor_id = sensor.sensor_id

    try:
        df = pd.read_csv(file)
        df = df.rename(columns={"Time": "time", "rad": "radiation"})
        if 'time' not in df.columns or 'radiation' not in df.columns:
            return "Ошибка: файл должен содержать столбцы 'time' и 'radiation'", 400
    except Exception as e:
        db.close()
        return f"Ошибка чтения файла прогноза: {e}", 400

    try:
        base_name = file.filename.split('/')[-1]
        date_str = base_name.replace("irrad_", "").replace(".csv", "")
        forecast_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        forecast_date = datetime.today().date()

    inserted = 0
    updated = 0

    for _, row in df.iterrows():
        try:
            time_obj = datetime.strptime(row['time'], "%H:%M:%S").time()
            dt = datetime.combine(forecast_date, time_obj)
            value = float(row['radiation'])

            existing = db.query(Measurement).filter_by(sensor_id=sensor_id, measurement_time=dt).first()
            if existing:
                existing.value = value
                updated += 1
            else:
                m = Measurement(sensor_id=sensor_id, measurement_time=dt, value=value)
                db.add(m)
                inserted += 1
        except Exception as e:
            print(f"Ошибка прогноза в строке: {e}")

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        return f"Ошибка при коммите прогноза: {e}", 500
    finally:
        db.close()

    return f"Загружено: {inserted}, обновлено: {updated} прогнозных значений."

@app.route('/sensors')
def show_sensors():
    db = SessionLocal()
    sensors = db.query(Sensor).order_by(Sensor.sensor_id).all()
    db.close()
    return render_template('sensors.html', sensors=sensors)

@app.route('/data', methods=['GET', 'POST'])
def show_data():
    selected_sensor_id = request.args.get('sensor_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # ЕСЛИ нет ни одного фильтра (первый заход) → редирект с дефолтным фильтром
    if not start_date and not end_date and not selected_sensor_id:
        default_start = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        default_end = (datetime.now()).strftime('%Y-%m-%d')
        return redirect(url_for('show_data', start_date=default_start, end_date=default_end))
    
    with SessionLocal() as db:
        sensors = db.query(Sensor).all()
        query = db.query(Measurement)
        if selected_sensor_id and selected_sensor_id.isdigit():
            query = query.filter(Measurement.sensor_id == int(selected_sensor_id))

        if start_date:
            try:
                # Приводим к datetime если это дата без времени
                if len(start_date) == 10:
                    start_date += ' 00:00:00'
                start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
                query = query.filter(Measurement.measurement_time >= start_dt)
            except Exception as e:
                print(f"Ошибка парсинга start_date: {e}")

        if end_date:
            try:
                if len(end_date) == 10:
                    end_date += ' 23:59:59'
                end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
                query = query.filter(Measurement.measurement_time <= end_dt)
            except Exception as e:
                print(f"Ошибка парсинга end_date: {e}")

        measurements = query.order_by(Measurement.measurement_time.desc()).all()

        chart_labels = [m.measurement_time.strftime('%Y-%m-%d %H:%M:%S') for m in measurements]
        chart_values = [m.value for m in measurements]
    
    return render_template(
        'data.html',
        sensors=sensors,
        measurements=measurements,
        selected_sensor_id=selected_sensor_id,
        start_date=start_date,
        end_date=end_date,
        chart_labels=chart_labels,
        chart_values=chart_values
    )

@app.route('/compare_select', methods=['GET'])
def compare_select():
    db = SessionLocal()
    sensors_actual = db.query(Sensor).filter(
        Sensor.sensor_type == 'radiation',
        ~Sensor.sensor_name.ilike('%forecast%')
    ).order_by(Sensor.sensor_name).all()

    sensors_forecast = db.query(Sensor).filter(
        Sensor.sensor_type == 'radiation',
        Sensor.sensor_name.ilike('%forecast%')
    ).order_by(Sensor.sensor_name).all()

    FakeSensor = namedtuple('FakeSensor', ['sensor_id', 'sensor_name'])
    sensors_actual.append(FakeSensor(sensor_id=-1, sensor_name='Среднее по всем фактическим'))

    db.close()
    return render_template('compare_select.html', sensors_actual=sensors_actual, sensors_forecast=sensors_forecast)

@app.route('/compare', methods=['GET'])
def compare():
    db = SessionLocal()
    try:
        actual_id = int(request.args.get("sensor_actual_id"))
        forecast_id = int(request.args.get("sensor_forecast_id"))
        start_dt = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d")
        end_dt_raw = request.args.get("end_date")
        end_dt = datetime.strptime(end_dt_raw, "%Y-%m-%d") + timedelta(days=1) if end_dt_raw else start_dt + timedelta(days=1)

        actual_name, forecast_name = get_sensor_names(db, actual_id, forecast_id)

        actual_data = (
            get_avg_measurements_for_all(db, start_dt, end_dt)
            if actual_id == -1 else get_measurements(db, actual_id, start_dt, end_dt)
        )
        forecast_data = get_measurements(db, forecast_id, start_dt, end_dt)

        labels, actual_dict, forecast_dict = get_common_time_series(actual_data, forecast_data)

        return render_template("compare.html",
                               chart_labels=[dt.strftime("%Y-%m-%d %H:%M:%S") for dt in labels],
                               actual_values=[actual_dict.get(t) for t in labels],
                               forecast_values=[forecast_dict.get(t) for t in labels],
                               actual_name=actual_name,
                               forecast_name=forecast_name)
    except Exception as e:
        print(f"Ошибка в /compare: {e}")
        return redirect(url_for("compare_select"))
    finally:
        db.close()

@app.route('/compare_table', methods=['GET'])
def compare_table():
    db = SessionLocal()
    try:
        actual_id = int(request.args.get("sensor_actual_id"))
        forecast_id = int(request.args.get("sensor_forecast_id"))
        start_dt = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d")
        end_dt_raw = request.args.get("end_date")
        end_dt = datetime.strptime(end_dt_raw, "%Y-%m-%d") + timedelta(days=1) if end_dt_raw else start_dt + timedelta(days=1)

        actual_name, forecast_name = get_sensor_names(db, actual_id, forecast_id)

        actual_data = (
            get_avg_measurements_for_all(db, start_dt, end_dt)
            if actual_id == -1 else get_measurements(db, actual_id, start_dt, end_dt)
        )
        forecast_data = get_measurements(db, forecast_id, start_dt, end_dt)

        # группировка по часам
        from collections import defaultdict
        actual_hourly = defaultdict(list)
        forecast_hourly = defaultdict(list)

        for m in actual_data:
            hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
            actual_hourly[hour].append(m.value)

        for m in forecast_data:
            hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
            forecast_hourly[hour].append(m.value)

        all_hours = sorted(set(actual_hourly.keys()).union(forecast_hourly.keys()))

        comparison_rows = []
        for hour in all_hours:
            a_vals = [v if v is not None and v >= 0 else 0 for v in actual_hourly.get(hour, [])]
            f_vals = [v if v is not None and v >= 0 else 0 for v in forecast_hourly.get(hour, [])]

            a_sum = sum(a_vals) if a_vals else None
            f_sum = sum(f_vals) if f_vals else None
            err = a_sum - f_sum if a_sum is not None and f_sum is not None else None
            percent = ((err / a_sum) * 100) if a_sum and err is not None else None

            comparison_rows.append({
                'time': hour.strftime("%Y-%m-%d %H:00"),
                'actual': round(a_sum, 3) if a_sum is not None else '',
                'forecast': round(f_sum, 3) if f_sum is not None else '',
                'error': round(err, 3) if err is not None else '',
                'percent': round(percent, 2) if percent is not None else ''
            })

        return render_template("compare_table.html",
                               comparison_rows=comparison_rows,
                               actual_name=actual_name,
                               forecast_name=forecast_name)
    except Exception as e:
        print(f"Ошибка в /compare_table: {e}")
        return redirect(url_for("compare_select"))
    finally:
        db.close()


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
