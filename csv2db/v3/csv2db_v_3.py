from flask import Flask, request, render_template
from sqlalchemy.orm import scoped_session
from db_session import SessionLocal
from init_db import Sensor, Measurement, Base
from datetime import datetime
import pandas as pd

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
        db.flush()  # Получаем ID до коммита
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

@app.route('/sensors')
def show_sensors():
    db = SessionLocal()
    sensors = db.query(Sensor).order_by(Sensor.sensor_id).all()
    db.close()
    return render_template('sensors.html', sensors=sensors)

@app.route('/data', methods=['GET', 'POST'])
def show_data():
    db = SessionLocal()
    sensors = db.query(Sensor).all()

    selected_sensor_id = request.args.get('sensor_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = db.query(Measurement)
    if selected_sensor_id:
        query = query.filter(Measurement.sensor_id == int(selected_sensor_id))
    if start_date:
        query = query.filter(Measurement.measurement_time >= start_date)
    if end_date:
        query = query.filter(Measurement.measurement_time <= end_date)

    measurements = query.order_by(Measurement.measurement_time.desc()).all()

   
    chart_labels = [m.measurement_time.strftime('%Y-%m-%d %H:%M:%S') for m in measurements]
    chart_values = [m.value for m in measurements]

    db.close()

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

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
