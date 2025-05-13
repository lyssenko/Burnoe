from collections import defaultdict
from datetime import datetime, timedelta
from collections import namedtuple


DataPoint = namedtuple('DataPoint', ['measurement_time', 'value'])

def get_sensor_names(db, actual_id, forecast_id):
    Sensor = db.query_model('Sensor')
    actual_name = "Среднее" if actual_id == -1 else db.get(Sensor, actual_id).sensor_name
    forecast_name = db.get(Sensor, forecast_id).sensor_name
    return actual_name, forecast_name

def get_measurements(db, sensor_id, start_dt, end_dt):
    Measurement = db.query_model('Measurement')
    return db.query(Measurement).filter(
        Measurement.sensor_id == sensor_id,
        Measurement.measurement_time >= start_dt,
        Measurement.measurement_time < end_dt
    ).order_by(Measurement.measurement_time).all()

def get_avg_measurements_for_all(db, start_dt, end_dt):
    Sensor = db.query_model('Sensor')
    Measurement = db.query_model('Measurement')

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

    avg_data = []
    for t, vals in time_group.items():
        valid_vals = [v if v is not None and v >= 0 else 0 for v in vals]
        if valid_vals:
            avg = sum(valid_vals) / len(valid_vals)
            avg_data.append(DataPoint(t, avg))
    return avg_data

def get_common_time_series(actual_data, forecast_data):
    all_times = sorted(set([m.measurement_time for m in actual_data] + [m.measurement_time for m in forecast_data]))
    actual_dict = {m.measurement_time: m.value for m in actual_data}
    forecast_dict = {m.measurement_time: m.value for m in forecast_data}

    return all_times, actual_dict, forecast_dict

def get_sensor_id(db, sensor_name, sensor_type, unit):
    from init_db import Sensor
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