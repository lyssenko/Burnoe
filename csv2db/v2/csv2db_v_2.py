import pandas as pd
from datetime import datetime
import sqlite3
from flask import Flask, request, render_template

app = Flask(__name__)


DB_PATH = 'burnoe.db'

def get_sensor_id(cursor, sensor_name, sensor_type, unit):
    cursor.execute("SELECT sensor_id FROM sensors WHERE sensor_name = ?", (sensor_name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    else:
        cursor.execute(
            "INSERT INTO sensors (sensor_name, sensor_type, unit) VALUES (?, ?, ?)",
            (sensor_name, sensor_type, unit)
        )
        return cursor.lastrowid

def determine_sensor_params(col_name):
    lower_name = col_name.lower()
    if "irradiation" in lower_name or "pyranometer" in lower_name:
        return "radiation", "W/m2"
    elif "wind" in lower_name or "ветра" in lower_name:
        return "wind", "m/s"
    elif "temp" in lower_name or "temperature" in lower_name or "температура" in lower_name:
        return "temperature", "℃"
    else:
        return "unknown", "unknown"

@app.route('/', methods=['GET'])
def index():
    print('display index page')
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('dataFile')
    if not files or len(files) == 0:
        return "Файл(ы) не выбраны", 400

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
    except Exception as e:
        return f"Ошибка подключения к базе данных: {str(e)}", 500

    # Создание ограничения уникальности при необходимости
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS unique_sensor_time
            ON measurements (sensor_id, measurement_time)
        """)
    except Exception as e:
        print(f"Ошибка создания уникального ограничения: {e}")
        conn.rollback()

    insert_query = """
        INSERT OR IGNORE INTO measurements (sensor_id, measurement_time, value)
        VALUES (?, ?, ?)
    """

    for file in files:
        if file.filename == '':
            continue
        try:
            df = pd.read_csv(file, sep=';')
        except Exception as e:
            print(f"Ошибка чтения файла {file.filename}: {str(e)}")
            continue

        if df.iloc[0, 0].strip().startswith('['):
            df = df.iloc[1:].reset_index(drop=True)

        sensor_cols = df.columns[2:]
        sensor_map = {}
        for col in sensor_cols:
            sensor_name = col.replace(".irradiation_raw", "").strip()
            sensor_type, unit = determine_sensor_params(col)
            sensor_id = get_sensor_id(cursor, sensor_name, sensor_type, unit)
            sensor_map[col] = sensor_id

        for index, row in df.iterrows():
            try:
                date_str = str(row.iloc[0]).strip()
                time_str = str(row.iloc[1]).strip()
                dt_str = f"{date_str} {time_str}"
                dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M:%S")
                measurement_time = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Ошибка обработки временной метки в строке {index} файла {file.filename}: {e}")
                continue

            for col in sensor_cols:
                try:
                    value = row.loc[col]
                    sensor_id = sensor_map[col]
                    cursor.execute(insert_query, (sensor_id, measurement_time, value))
                except Exception as e:
                    print(f"Ошибка обработки строки {index}, датчик '{col}' файла {file.filename}: {e}")
                    continue

    try:
        conn.commit()
    except Exception as e:
        print(f"Ошибка коммита: {e}")
        conn.rollback()

    cursor.close()
    conn.close()
    return "Данные успешно загружены в базу данных."


@app.route('/sensors')
def show_sensors():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sensors ORDER BY sensor_id")
    sensors = cursor.fetchall()

    conn.close()
    return render_template('sensors.html', sensors=sensors)


@app.route('/data', methods=['GET', 'POST'])
def show_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Получим список всех сенсоров
    cursor.execute("SELECT * FROM sensors")
    sensors = cursor.fetchall()

    # Получим фильтры
    selected_sensor_id = request.args.get('sensor_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Формируем запрос для фильтрации
    query = "SELECT * FROM measurements WHERE 1=1"
    params = []

    if selected_sensor_id:
        query += " AND sensor_id = ?"
        params.append(selected_sensor_id)

    if start_date:
        query += " AND measurement_time >= ?"
        params.append(start_date)

    if end_date:
        query += " AND measurement_time <= ?"
        params.append(end_date)

    query += " ORDER BY measurement_time DESC"
    
    cursor.execute(query, params)
    measurements = cursor.fetchall()

    conn.close()

    return render_template(
        'data.html',
        sensors=sensors,
        measurements=measurements,
        selected_sensor_id=selected_sensor_id,
        start_date=start_date,
        end_date=end_date
    )


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)