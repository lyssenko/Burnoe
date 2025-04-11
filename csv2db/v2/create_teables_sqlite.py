import sqlite3

# Путь к файлу базы данных
DB_PATH = 'burnoe.db'

# SQL-запрос для создания таблиц и индексов
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_name TEXT NOT NULL,
    sensor_type TEXT NOT NULL,
    unit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    measurement_time TEXT NOT NULL,
    value REAL,
    FOREIGN KEY(sensor_id) REFERENCES sensors(sensor_id)
);

CREATE INDEX IF NOT EXISTS idx_measurements_time ON measurements (measurement_time);
CREATE INDEX IF NOT EXISTS idx_measurements_sensor_time ON measurements (sensor_id, measurement_time);
CREATE UNIQUE INDEX IF NOT EXISTS unique_sensor_time ON measurements (sensor_id, measurement_time);
"""

# Создание базы и выполнение SQL
def initialize_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(CREATE_SQL)  # executescript позволяет выполнять сразу несколько SQL-команд
    conn.commit()
    cursor.close()
    conn.close()
    print("База данных и таблицы успешно созданы.")

if __name__ == "__main__":
    initialize_database()
