CREATE DATABASE db_Burnoe;

CREATE TABLE sensors (
    sensor_id SERIAL PRIMARY KEY,
    sensor_name VARCHAR(255) NOT NULL,
    sensor_type VARCHAR(50) NOT NULL,
    unit VARCHAR(50) NOT NULL
);

CREATE TABLE measurements (
    measurement_id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(sensor_id),
    measurement_time TIMESTAMP NOT NULL,
    VALUE NUMERIC
);

CREATE INDEX idx_measurements_time ON measurements (measurement_time);

CREATE INDEX idx_measurements_sensor_time ON measurements (sensor_id, measurement_time);