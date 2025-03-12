import os
import glob
import pandas as pd
from datetime import datetime
import psycopg2
from flask import Flask, request, render_template_string

app = Flask(__name__)

HTML_FORM = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка данных в БД</title>
</head>
<body>
    <h1>Загрузка данных в базу данных</h1>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <label for="dataFile">Выберите CSV-файлы с данными:</label>
        <input type="file" name="dataFile" id="dataFile" accept=".csv" multiple>
        <br><br>
        <input type="submit" value="Загрузить в БД">
    </form>
</body>
</html>
'''

def get_sensor_id(cursor, sensor_name, sensor_type, unit):

    cursor.execute("SELECT sensor_id FROM sensors WHERE sensor_name = %s", (sensor_name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    else:
        cursor.execute(
            "INSERT INTO sensors (sensor_name, sensor_type, unit) VALUES (%s, %s, %s) RETURNING sensor_id",
            (sensor_name, sensor_type, unit)
        )
        sensor_id = cursor.fetchone()[0]
        return sensor_id

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
    return HTML_FORM

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('dataFile')
    if not files or len(files) == 0:
        return "Файл(ы) не выбраны", 400

    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5432",
            dbname="db_Burnoe",
            user="postgres",
            password="123"
        )
        cursor = conn.cursor()
    except Exception as e:
        return f"Ошибка подключения к базе данных: {str(e)}", 500

    create_constraint_query = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'unique_sensor_time'
        ) THEN
            ALTER TABLE measurements ADD CONSTRAINT unique_sensor_time UNIQUE (sensor_id, measurement_time);
        END IF;
    END $$;
    """
    try:
        cursor.execute(create_constraint_query)
    except Exception as e:
        print(f"Ошибка создания уникального ограничения: {e}")
        conn.rollback()

    insert_query = """
        INSERT INTO measurements (sensor_id, measurement_time, value)
        VALUES (%s, %s, %s)
        ON CONFLICT (sensor_id, measurement_time) DO NOTHING
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
                cursor.execute("SAVEPOINT sp1")
                try:
                    value = row.loc[col]
                    sensor_id = sensor_map[col]
                    cursor.execute(insert_query, (sensor_id, measurement_time, value))
                    cursor.execute("SAVEPOINT sp1")
                except Exception as e:
                    print(f"Ошибка обработки строки {index}, датчик '{col}' файла {file.filename}: {e}")
                    cursor.execute("ROLLBACK TO SAVEPOINT sp1")
                    continue

    try:
        conn.commit()
    except Exception as e:
        print(f"Ошибка коммита: {e}")
        conn.rollback()

    cursor.close()
    conn.close()
    return "Данные успешно загружены в базу данных."

if __name__ == '__main__':
    app.run(debug=True)
