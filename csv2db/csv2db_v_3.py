import re
from sqlite3 import IntegrityError
from sqlalchemy import insert
from sqlalchemy.orm import scoped_session
from db_session import SessionLocal
from init_db import Sensor, Measurement
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
import pandas as pd
from collections import defaultdict, namedtuple
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import csv
from flask import make_response
import io

from comparison_utils import (
    get_common_time_series,
    get_measurements,
    get_sensor_names,
    get_sensor_id,
    determine_sensor_type_and_unit,
    process_excel_energy_file,
    process_measurements,
    compare_sensors
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
            filename = file.filename.lower()
            if filename.endswith('.xlsx'):
                total_inserted += process_excel_energy_file(file, db, errors)
            else:
                df = pd.read_csv(file, sep=';')
                if df.shape[1] < 3:
                    errors.append(f"Файл {file.filename} содержит недостаточно столбцов.")
                    continue
                if df.iloc[0, 0].strip().startswith('['):
                    df = df.iloc[1:].reset_index(drop=True)
                sensor_cols = df.columns[2:]
                sensor_map = {
                    col: get_sensor_id(db, col.replace(".irradiation_raw", "").strip(),
                                       *determine_sensor_type_and_unit(col)
)
                    for col in sensor_cols
                }
                total_inserted += process_measurements(df, sensor_cols, sensor_map, db, file.filename, errors)
        except Exception as e:
            errors.append(f"Ошибка обработки {file.filename}: {e}")
            continue

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

@app.route('/upload_forecast', methods=['POST'])
def upload_forecast():
    files = request.files.getlist('forecastFile')
    if not files:
        return "Файлы прогноза не выбраны", 400

    total_inserted = 0
    with SessionLocal() as db:
        for file in files:
            if not file or not file.filename:
                continue

            filename_lower = file.filename.lower()
            if 'energy' in filename_lower:
                sensor_name = "Forecast Energy"
                sensor_type = "energy_active"
                unit = "kWh"
            elif 'irrad' in filename_lower:
                sensor_name = "Forecast Radiation"
                sensor_type = "radiation"
                unit = "W/m2"
            else:
                print(f"Пропущен файл: {file.filename} — не содержит 'energy' или 'irrad'")
                continue

            try:
                df = pd.read_csv(file)
                df.columns = [col.strip().lower() for col in df.columns]
                if 'time' in df.columns and 'p' in df.columns:
                    df = df.rename(columns={'p': 'radiation'})
                elif 'time' in df.columns and 'rad' in df.columns:
                    df = df.rename(columns={'rad': 'radiation'})
                elif 'time' in df.columns and 'radiation' in df.columns:
                    pass
                else:
                    print(f"Ошибка структуры в файле {file.filename}")
                    continue
            except Exception as e:
                print(f"Ошибка чтения {file.filename}: {e}")
                continue

            try:
                base_name = file.filename.split('/')[-1]
                date_str = re.search(r'(\d{4}-\d{2}-\d{2})', base_name)
                if date_str:
                    forecast_date = datetime.strptime(date_str.group(1), "%Y-%m-%d").date()
                else:
                    forecast_date = datetime.today().date()
            except Exception:
                forecast_date = datetime.today().date()

            sensor = db.query(Sensor).filter_by(sensor_name=sensor_name).first()
            if sensor:
                sensor_id = sensor.sensor_id
            else:
                sensor = Sensor(sensor_name=sensor_name, sensor_type=sensor_type, unit=unit)
                db.add(sensor)
                db.flush()
                sensor_id = sensor.sensor_id

            for _, row in df.iterrows():
                try:
                    time_obj = datetime.strptime(row['time'], "%H:%M:%S").time()
                    dt = datetime.combine(forecast_date, time_obj)
                    value = float(row['radiation'])

                    stmt = sqlite_insert(Measurement).values(
                        sensor_id=sensor_id,
                        measurement_time=dt,
                        value=value
                    ).on_conflict_do_update(
                        index_elements=["sensor_id", "measurement_time"],
                        set_={"value": value}
                    )
                    db.execute(stmt)
                    total_inserted += 1
                except Exception as e:
                    print(f"Ошибка прогноза в строке: {e}")

        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            return f"Ошибка при коммите прогноза: {e}", 500

    return f"Загружено: {total_inserted} прогнозных значений."

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
        ~Sensor.sensor_name.ilike('%forecast%')
    ).order_by(Sensor.sensor_name).all()

    sensors_forecast = db.query(Sensor).filter(
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
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) if end_date else start_dt + timedelta(days=1)

        actual_name, forecast_name = get_sensor_names(db, actual_id, forecast_id)

        result = compare_sensors(db, actual_id, forecast_id, start_dt, end_dt)

        return render_template("compare.html",
                               chart_labels=[dt.strftime("%Y-%m-%d %H:%M:%S") for dt in result["labels"]],
                               actual_values=result["actual_values"],
                               forecast_values=result["forecast_values"],
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
          Sensor.sensor_name.ilike('%forecast%')
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

    total_actual = sum(row['actual'] for row in comparison_rows if row['actual'] not in ('', None))
    total_forecast = sum(row['forecast'] for row in comparison_rows if row['forecast'] not in ('', None))


    return render_template(
        "compare_table.html",
        comparison_rows=comparison_rows,
        actual_name=actual_name,
        forecast_name=forecast_name,
        total_actual=total_actual,
        total_forecast=total_forecast
    )

@app.route("/compare_table/export")
def export_compare_table():
    db = SessionLocal()
    actual_id = int(request.args.get("sensor_actual_id"))
    forecast_id = int(request.args.get("sensor_forecast_id"))
    start_date = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d")
    end_date = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d") + timedelta(days=1)

    actual_data = get_measurements(db, actual_id, start_date, end_date)
    forecast_data = get_measurements(db, forecast_id, start_date, end_date)
    labels, actual_dict, forecast_dict = get_common_time_series(actual_data, forecast_data)

    # Буфер CSV в памяти
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Время", "Факт", "Прогноз", "Ошибка", "Ошибка (%)"])

    for t in labels:
        a = actual_dict.get(t)
        f = forecast_dict.get(t)
        diff = (a - f) if a is not None and f is not None else ""
        percent = (abs(diff) / a * 100) if a and f else ""
        writer.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), a, f, diff, percent])

    # Отправляем CSV
    response = make_response(buffer.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=comparison.csv"
    response.headers["Content-type"] = "text/csv"
    return response

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
