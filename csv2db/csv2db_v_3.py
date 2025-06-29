import re
import pandas as pd
import csv
import io
import os
from dotenv import load_dotenv
from sqlite3 import IntegrityError
from db_session import SessionLocal
from init_db import Sensor, Measurement, User
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for
from collections import defaultdict, namedtuple
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from flask import session, flash, make_response
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from functools import wraps
from sensor_labels import SENSOR_LABELS, UNIT_LABELS
from comparison_utils import (
    get_common_time_series,
    get_measurements,
    get_sensor_names,
    handle_uploaded_file,
    parse_date_range,
    compare_sensors,
)


load_dotenv()
app = Flask(__name__)
secret = os.getenv("SECRET_KEY")
if not secret:
    raise RuntimeError("SECRET_KEY не найден в переменных окружения!")
app.secret_key = secret


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Необходимо войти в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_user():
    def sensor_label(name):
        return SENSOR_LABELS.get(name, name)
    def unit_label(unit):
        return UNIT_LABELS.get(unit, unit)
    return dict(
        username=session.get('username'),
        sensor_label=sensor_label,
        unit_label=unit_label
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with SessionLocal() as db:
            user = db.query(User).filter_by(username=username).first()
            if user and user.check_password(password):
                session['username'] = username
                flash('Вы вошли в систему', 'success')
                return redirect(url_for('index'))
            else:
                flash('Неверный логин или пароль', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    files = request.files.getlist("dataFile")
    if not files:
        return "Файл(ы) не выбраны", 400

    errors = []
    total_inserted = 0
    with SessionLocal() as db:
        for file in files:
            if file and file.filename:
                try:
                    total_inserted += handle_uploaded_file(file, db, errors)
                except Exception as e:
                    errors.append(f"Ошибка обработки {file.filename}: {e}")

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            return f"Ошибка при сохранении данных: {e}", 500

    if errors:
        msg = (
            f"Загружено {total_inserted} измерений, но возникли ошибки:\n"
            + "\n".join(errors[:10])
        )
        if len(errors) > 10:
            msg += f"\n... и ещё {len(errors) - 10} ошибок скрыто."
        return msg, 400

    return f"Данные успешно загружены. Всего записей: {total_inserted}."


@app.route("/upload_forecast", methods=["POST"])
@login_required
def upload_forecast():
    files = request.files.getlist("forecastFile")
    if not files:
        return "Файлы прогноза не выбраны", 400

    total_inserted = 0
    with SessionLocal() as db:
        for file in files:
            if not file or not file.filename:
                continue

            filename_lower = file.filename.lower()
            if "energy" in filename_lower:
                sensor_name = "Forecast Energy"
                sensor_type = "energy_active"
                unit = "kWh"
            elif "irrad" in filename_lower:
                sensor_name = "Forecast Radiation"
                sensor_type = "radiation"
                unit = "W/m2"
            else:
                print(
                    f"Пропущен файл: {file.filename} — не содержит 'energy' или 'irrad'"
                )
                continue

            try:
                df = pd.read_csv(file)
                df.columns = [col.strip().lower() for col in df.columns]
                if "time" in df.columns and "p" in df.columns:
                    df = df.rename(columns={"p": "radiation"})
                elif "time" in df.columns and "rad" in df.columns:
                    df = df.rename(columns={"rad": "radiation"})
                elif "time" in df.columns and "radiation" in df.columns:
                    pass
                else:
                    print(f"Ошибка структуры в файле {file.filename}")
                    continue
            except Exception as e:
                print(f"Ошибка чтения {file.filename}: {e}")
                continue

            try:
                base_name = file.filename.split("/")[-1]
                date_str = re.search(r"(\d{4}-\d{2}-\d{2})", base_name)
                if date_str:
                    forecast_date = datetime.strptime(
                        date_str.group(1), "%Y-%m-%d"
                    ).date()
                else:
                    forecast_date = datetime.today().date()
            except Exception:
                forecast_date = datetime.today().date()

            sensor = db.query(Sensor).filter_by(sensor_name=sensor_name).first()
            if sensor:
                sensor_id = sensor.sensor_id
            else:
                sensor = Sensor(
                    sensor_name=sensor_name, sensor_type=sensor_type, unit=unit
                )
                db.add(sensor)
                db.flush()
                sensor_id = sensor.sensor_id

            for _, row in df.iterrows():
                try:
                    time_obj = datetime.strptime(row["time"], "%H:%M:%S").time()
                    dt = datetime.combine(forecast_date, time_obj)
                    value = float(row["radiation"])

                    stmt = (
                        sqlite_insert(Measurement)
                        .values(sensor_id=sensor_id, measurement_time=dt, value=value)
                        .on_conflict_do_update(
                            index_elements=["sensor_id", "measurement_time"],
                            set_={"value": value},
                        )
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


@app.route("/sensors")
@login_required
def show_sensors():
    with SessionLocal() as db:
        sensors = db.query(Sensor).order_by(Sensor.sensor_id).all()
    return render_template("sensors.html", sensors=sensors)


@app.route("/data", methods=["GET", "POST"])
def show_data():
    selected_sensor_id = request.args.get("sensor_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if not start_date and not end_date and not selected_sensor_id:
        default_start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        default_end = (datetime.now()).strftime("%Y-%m-%d")
        return redirect(
            url_for("show_data", start_date=default_start, end_date=default_end)
        )

    with SessionLocal() as db:
        sensors = db.query(Sensor).all()
        query = db.query(Measurement)
        if selected_sensor_id and selected_sensor_id.isdigit():
            query = query.filter(Measurement.sensor_id == int(selected_sensor_id))

        start_dt, end_dt = parse_date_range(start_date, end_date)
        query = query.filter(Measurement.measurement_time >= start_dt)
        query = query.filter(Measurement.measurement_time <= end_dt)
        measurements = query.order_by(Measurement.measurement_time).all()
        chart_labels = [
            m.measurement_time.strftime("%Y-%m-%d %H:%M:%S") for m in measurements
        ]
        chart_values = [m.value for m in measurements]

    return render_template(
        "data.html",
        sensors=sensors,
        measurements=measurements,
        selected_sensor_id=selected_sensor_id,
        start_date=start_date,
        end_date=end_date,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


@app.route("/compare_select", methods=["GET"])
def compare_select():
    with SessionLocal() as db:

        sensors_actual = (
            db.query(Sensor)
            .filter(~Sensor.sensor_name.ilike("%forecast%"))
            .order_by(Sensor.sensor_name)
            .all()
        )

        sensors_forecast = (
            db.query(Sensor)
            .filter(Sensor.sensor_name.ilike("%forecast%"))
            .order_by(Sensor.sensor_name)
            .all()
        )

        FakeSensor = namedtuple("FakeSensor", ["sensor_id", "sensor_name"])
        sensors_actual.append(
            FakeSensor(sensor_id=-1, sensor_name="Среднее по всем фактическим")
        )

    return render_template(
        "compare_select.html",
        sensors_actual=sensors_actual,
        sensors_forecast=sensors_forecast,
    )


@app.route("/compare", methods=["GET"])
def compare():
    with SessionLocal() as db:

        try:
            actual_id = int(request.args.get("sensor_actual_id"))
            forecast_id = int(request.args.get("sensor_forecast_id"))
            start_date = request.args.get("start_date")
            end_date = request.args.get("end_date")

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = (
                datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                if end_date
                else start_dt + timedelta(days=1)
            )

            actual_name, forecast_name = get_sensor_names(db, actual_id, forecast_id)

            result = compare_sensors(db, actual_id, forecast_id, start_dt, end_dt)

            return render_template(
                "compare.html",
                chart_labels=[dt.strftime("%Y-%m-%d %H:%M:%S") for dt in result["labels"]],
                actual_values=result["actual_values"],
                forecast_values=result["forecast_values"],
                actual_name=actual_name,
                forecast_name=forecast_name,
            )
        except Exception as e:
            print(f"Ошибка в /compare: {e}")
            return redirect(url_for("compare_select"))


@app.route("/compare_table", methods=["GET"])
def compare_table():
    
    with SessionLocal() as db:
        sensor_actual_id = request.args.get("sensor_actual_id")
        sensor_forecast_id = request.args.get("sensor_forecast_id")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        if not (sensor_actual_id and sensor_forecast_id and start_date):
            return redirect(url_for("compare_select"))

        try:
            sensor_actual_id = int(sensor_actual_id)
            sensor_forecast_id = int(sensor_forecast_id)
        except ValueError:
            return "Некорректный формат ID сенсора", 400

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return "Неверный формат начальной даты", 400

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                return "Неверный формат конечной даты", 400
        else:
            end_dt = start_dt + timedelta(days=1)

        actual_name = (
            "Среднее"
            if sensor_actual_id == -1
            else db.get(Sensor, sensor_actual_id).sensor_name
        )
        forecast_name = db.get(Sensor, sensor_forecast_id).sensor_name

        if sensor_actual_id == -1:
            from comparison_utils import get_avg_measurements_for_all
            actual_data = get_avg_measurements_for_all(db, start_dt, end_dt)
        else:
            actual_data = (
                db.query(Measurement)
                .filter(
                    Measurement.sensor_id == sensor_actual_id,
                    Measurement.measurement_time >= start_dt,
                    Measurement.measurement_time < end_dt,
                )
                .order_by(Measurement.measurement_time)
                .all()
            )

        forecast_data = (
            db.query(Measurement)
            .filter(
                Measurement.sensor_id == sensor_forecast_id,
                Measurement.measurement_time >= start_dt,
                Measurement.measurement_time < end_dt,
            )
            .order_by(Measurement.measurement_time)
            .all()
        )

    actual_hourly = defaultdict(list)
    forecast_hourly = defaultdict(list)

    for m in actual_data:
        hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
        actual_hourly[hour].append(m.value)

    for m in forecast_data:
        hour = m.measurement_time.replace(minute=0, second=0, microsecond=0)
        forecast_hourly[hour].append(m.value)

    all_hours = sorted(set(actual_hourly.keys()).union(forecast_hourly.keys()))

    grouped_rows = defaultdict(list)
    daily_totals = []

    for hour in all_hours:
        a_vals = [v if v is not None and v >= 0 else 0 for v in actual_hourly.get(hour, [])]
        f_vals = [v if v is not None and v >= 0 else 0 for v in forecast_hourly.get(hour, [])]

        a_sum = sum(a_vals) if a_vals else None
        f_sum = sum(f_vals) if f_vals else None
        err = a_sum - f_sum if a_sum is not None and f_sum is not None else None
        percent = ((err / a_sum) * 100) if a_sum and err is not None else None

        date_key = hour.strftime("%Y-%m-%d")
        row = {
            "date": date_key,
            "time": hour.strftime("%Y-%m-%d %H:00"),
            "actual": round(a_sum, 3) if a_sum is not None else "",
            "forecast": round(f_sum, 3) if f_sum is not None else "",
            "error": round(err, 3) if err is not None else "",
            "percent": round(percent, 2) if percent is not None else "",
        }
        grouped_rows[date_key].append(row)

    for date, rows in grouped_rows.items():
        actual_sum = sum(row["actual"] for row in rows if isinstance(row["actual"], (int, float)))
        forecast_sum = sum(row["forecast"] for row in rows if isinstance(row["forecast"], (int, float)))
        daily_totals.append({
            "date": date,
            "actual": round(actual_sum, 3),
            "forecast": round(forecast_sum, 3)
        })

    total_actual_sum = sum(
        row["actual"] for rows in grouped_rows.values() for row in rows
        if isinstance(row["actual"], (int, float))
    )
    total_forecast_sum = sum(
        row["forecast"] for rows in grouped_rows.values() for row in rows
        if isinstance(row["forecast"], (int, float))
    )

    abs_error = total_actual_sum - total_forecast_sum
    percent_error = (abs_error / total_actual_sum * 100) if total_actual_sum else None


    return render_template(
        "compare_table.html",
        grouped_rows=grouped_rows,
        daily_totals=daily_totals,
        actual_name=actual_name,
        forecast_name=forecast_name,
        total_actual_sum=round(total_actual_sum, 3),
        total_forecast_sum=round(total_forecast_sum, 3),
        abs_error=round(abs_error, 3),
        percent_error=round(percent_error, 2) if percent_error is not None else "",
    )


@app.route("/compare_table/export")
def export_compare_table():
    db = SessionLocal()
    actual_id = int(request.args.get("sensor_actual_id"))
    forecast_id = int(request.args.get("sensor_forecast_id"))
    start_date = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d")
    end_date = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d") + timedelta(
        days=1
    )

    actual_data = get_measurements(db, actual_id, start_date, end_date)
    forecast_data = get_measurements(db, forecast_id, start_date, end_date)
    labels, actual_dict, forecast_dict = get_common_time_series(
        actual_data, forecast_data
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Время", "Факт", "Прогноз", "Ошибка", "Ошибка (%)"])

    for t in labels:
        a = actual_dict.get(t)
        f = forecast_dict.get(t)
        diff = (a - f) if a is not None and f is not None else ""
        percent = (abs(diff) / a * 100) if a and f else ""
        writer.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), a, f, diff, percent])

    response = make_response(buffer.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=comparison.csv"
    response.headers["Content-type"] = "text/csv"
    return response


@app.route("/compare_table/export_excel")
def export_compare_table_excel():
    db = SessionLocal()
    actual_id = int(request.args.get("sensor_actual_id"))
    forecast_id = int(request.args.get("sensor_forecast_id"))
    start_date = datetime.strptime(request.args.get("start_date"), "%Y-%m-%d")
    end_date = datetime.strptime(request.args.get("end_date"), "%Y-%m-%d") + timedelta(days=1)

    actual_data = get_measurements(db, actual_id, start_date, end_date)
    forecast_data = get_measurements(db, forecast_id, start_date, end_date)
    labels, actual_dict, forecast_dict = get_common_time_series(actual_data, forecast_data)

    wb = Workbook()
    ws = wb.active
    ws.title = "Сравнение"

    ws.append(["Время", "Факт", "Прогноз", "Ошибка", "Ошибка (%)"])

    for t in labels:
        a = actual_dict.get(t)
        f = forecast_dict.get(t)
        diff = (a - f) if a is not None and f is not None else ""
        percent = (abs(diff) / a * 100) if a and f else ""
        ws.append([
            t.strftime("%Y-%m-%d %H:%M:%S"),
            a if a is not None else "",
            f if f is not None else "",
            diff if diff != "" else "",
            round(percent, 2) if percent != "" else ""
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max_len + 2

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers["Content-Disposition"] = "attachment; filename=comparison.xlsx"
    response.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
