from sqlalchemy.orm import scoped_session
from db_session import SessionLocal
from init_db import Sensor, Measurement
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
import pandas as pd
from collections import namedtuple, defaultdict


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

    def get_sensor_id(sensor_name, sensor_type, unit):
        sensor = db.query(Sensor).filter_by(sensor_name=sensor_name).first()
        if sensor:
            return sensor.sensor_id
        new_sensor = Sensor(sensor_name=sensor_name, sensor_type=sensor_type, unit=unit)
        db.add(new_sensor)
        db.flush()
        return new_sensor.sensor_id

    def determine_sensor_params(col_name):
        lower = col_name.lower()
        if "irradiation" in lower or "pyranometer" in lower:
            return "radiation", "W/m2"
        elif "wind" in lower or "ветра" in lower:
            return "wind", "m/s"
        elif "temp" in lower or "temperature" in lower or "температура" in lower:
            return "temperature", "℃"
        else:
            return "unknown", "unknown"

    for file in files:
        if not file.filename:
            continue
        try:
            df = pd.read_csv(file, sep=';')
        except Exception as e:
            print(f"Ошибка чтения файла {file.filename}: {e}")
            continue

        if df.iloc[0, 0].strip().startswith('['):
            df = df.iloc[1:].reset_index(drop=True)

        sensor_cols = df.columns[2:]
        sensor_map = {}
        for col in sensor_cols:
            sensor_name = col.replace(".irradiation_raw", "").strip()
            sensor_type, unit = determine_sensor_params(col)
            sensor_id = get_sensor_id(sensor_name, sensor_type, unit)
            sensor_map[col] = sensor_id

        for index, row in df.iterrows():
            try:
                date_str = str(row.iloc[0]).strip()
                time_str = str(row.iloc[1]).strip()
                dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M:%S")
            except Exception as e:
                print(f"Ошибка парсинга даты в строке {index}: {e}")
                continue

            for col in sensor_cols:
                try:
                    value = row[col]
                    sensor_id = sensor_map[col]
                    m = Measurement(sensor_id=sensor_id, measurement_time=dt, value=value)
                    db.add(m)
                except Exception as e:
                    print(f"Ошибка в строке {index}, столбец {col}: {e}")
    try:
        db.commit()
    except Exception as e:
        print(f"Ошибка при коммите: {e}")
        db.rollback()
    finally:
        db.close()

    return "Данные успешно загружены в базу данных."

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

    sensor_actual_id = request.args.get("sensor_actual_id")
    sensor_forecast_id = request.args.get("sensor_forecast_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if not (sensor_actual_id and sensor_forecast_id and start_date):
        db.close()
        return redirect(url_for("compare_select"))

    try:
        sensor_actual_id = int(sensor_actual_id)
        sensor_forecast_id = int(sensor_forecast_id)
    except ValueError:
        db.close()
        return "Некорректный формат ID сенсора", 400

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        db.close()
        return "Неверный формат начальной даты", 400

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            db.close()
            return "Неверный формат конечной даты", 400
    else:
        end_dt = start_dt + timedelta(days=1)

    actual_name = "Среднее" if sensor_actual_id == -1 else db.get(Sensor, sensor_actual_id).sensor_name
    forecast_name = db.get(Sensor, sensor_forecast_id).sensor_name


    if sensor_actual_id == -1:
        sensors = db.query(Sensor).filter(
            Sensor.sensor_type == 'radiation',
            ~Sensor.sensor_name.ilike('%forecast%')
        ).all()
        all_ids = [s.sensor_id for s in sensors]

        all_data = db.query(Measurement).filter(
            Measurement.sensor_id.in_(all_ids),
            Measurement.measurement_time >= start_dt,
            Measurement.measurement_time < end_dt
        ).all()

        from collections import defaultdict
        time_group = defaultdict(list)
        for m in all_data:
            time_group[m.measurement_time].append(m.value)

        actual_data = []
        for t, vals in time_group.items():
            valid_vals = [v if v is not None and v >= 0 else 0 for v in vals]
            if valid_vals:
                avg = sum(valid_vals) / len(valid_vals)
                actual_data.append(type('Obj', (), {'measurement_time': t, 'value': avg}))
    else:
        actual_data = db.query(Measurement).filter(
            Measurement.sensor_id == sensor_actual_id,
            Measurement.measurement_time >= start_dt,
            Measurement.measurement_time < end_dt
        ).order_by(Measurement.measurement_time).all()

    forecast_data = db.query(Measurement).filter(
        Measurement.sensor_id == sensor_forecast_id,
        Measurement.measurement_time >= start_dt,
        Measurement.measurement_time < end_dt
    ).order_by(Measurement.measurement_time).all()

    db.close()

    label_set = sorted(set([m.measurement_time for m in actual_data] + [m.measurement_time for m in forecast_data]))
    label_strs = [dt.strftime("%Y-%m-%d %H:%M:%S") for dt in label_set]
    actual_dict = {m.measurement_time: m.value for m in actual_data}
    forecast_dict = {m.measurement_time: m.value for m in forecast_data}

    actual_values = [actual_dict.get(t, None) for t in label_set]
    forecast_values = [forecast_dict.get(t, None) for t in label_set]

    return render_template(
        "compare.html",
        chart_labels=label_strs,
        actual_values=actual_values,
        forecast_values=forecast_values,
        actual_name=actual_name,
        forecast_name=forecast_name
    )

@app.route('/compare_table', methods=['GET'])
def compare_table():
    db = SessionLocal()

    sensor_actual_id = request.args.get("sensor_actual_id")
    sensor_forecast_id = request.args.get("sensor_forecast_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if not (sensor_actual_id and sensor_forecast_id and start_date):
        db.close()
        return redirect(url_for("compare_select"))

    try:
        sensor_actual_id = int(sensor_actual_id)
        sensor_forecast_id = int(sensor_forecast_id)
    except ValueError:
        db.close()
        return "Некорректный формат ID сенсора", 400

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        db.close()
        return "Неверный формат начальной даты", 400

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            db.close()
            return "Неверный формат конечной даты", 400
    else:
        end_dt = start_dt + timedelta(days=1)

    actual_name = "Среднее" if sensor_actual_id == -1 else db.get(Sensor, sensor_actual_id).sensor_name
    forecast_name = db.get(Sensor, sensor_forecast_id).sensor_name


    if sensor_actual_id == -1:
        sensors = db.query(Sensor).filter(
            Sensor.sensor_type == 'radiation',
            ~Sensor.sensor_name.ilike('%forecast%')
        ).all()
        all_ids = [s.sensor_id for s in sensors]

        all_data = db.query(Measurement).filter(
            Measurement.sensor_id.in_(all_ids),
            Measurement.measurement_time >= start_dt,
            Measurement.measurement_time < end_dt
        ).all()

        time_group = defaultdict(list)
        for m in all_data:
            time_group[m.measurement_time].append(m.value)

        actual_data = []
        for t, vals in time_group.items():
            valid_vals = [v for v in vals if v is not None]
            if valid_vals:
                avg = sum(valid_vals) / len(valid_vals)
                actual_data.append(type('Obj', (), {'measurement_time': t, 'value': avg}))
    else:
        actual_data = db.query(Measurement).filter(
            Measurement.sensor_id == sensor_actual_id,
            Measurement.measurement_time >= start_dt,
            Measurement.measurement_time < end_dt
        ).order_by(Measurement.measurement_time).all()

    forecast_data = db.query(Measurement).filter(
        Measurement.sensor_id == sensor_forecast_id,
        Measurement.measurement_time >= start_dt,
        Measurement.measurement_time < end_dt
    ).order_by(Measurement.measurement_time).all()

    db.close()

    label_set = sorted(set([m.measurement_time for m in actual_data] + [m.measurement_time for m in forecast_data]))
    actual_dict = {m.measurement_time: m.value for m in actual_data}
    forecast_dict = {m.measurement_time: m.value for m in forecast_data}

    comparison_rows = []
    actual_hourly = defaultdict(list)
    forecast_hourly = defaultdict(list)

    for m in actual_data:
        hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
        actual_hourly[hour].append(m.value)

    for m in forecast_data:
        hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
        forecast_hourly[hour].append(m.value)

    all_hours = sorted(set(actual_hourly.keys()).union(forecast_hourly.keys()))
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

    return render_template(
        "compare_table.html",
        comparison_rows=comparison_rows,
        actual_name=actual_name,
        forecast_name=forecast_name
    )


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
