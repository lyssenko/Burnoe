SENSOR_LABELS = {
    "Pyranometer.B1 St20": "Солнечная радиация (пирометр B1-St20 накл.)",
    "Pyranometer.B1 St10": "Солнечная радиация (пирометр B1-St10 накл.)",
    "Pyranometer.B1 St05": "Солнечная радиация (пирометр B1-St05 накл.)",
    "Pyranometer.module.08": "Солнечная радиация (пирометр 08 гориз.)",
    "Pyranometer.horizontal.08": "Солнечная радиация (пирометр 08 гориз.)",
    "Pyranometer.module.02": "Солнечная радиация (пирометр 02 гориз.)",
    "Pyranometer.horizontal.02": "Солнечная радиация (пирометр 02 гориз.)",
    "Pyranometer.B1 AVG": "Солнечная радиация (пирометр B1 AVG)",
    "Pyranometer.module.AVG": "Солнечная радиация (пирометр module AVG)",
    "Forecast Radiation": "Солнечная радиация (прогноз)",
    "Forecast Energy": "Выработка энергии (прогноз)",
    "Meteo.Temp.02.temperature_module": "Температура модуля",
    "Meteo.Temp.02.temperature_ambient": "Температура окружающей среды",
    "Wind_Sensor.01.Wind speed": "Скорость ветра",
}

UNIT_LABELS = {
    "W/m2": "Вт/м²",
    "kWh": "кВт·ч",
    "°C": "°C",
    "": "—",
    "m/s": "м/с",
    "kvarh": "кВА·ч",
}

VIRTUAL_SENSOR_GROUPS = {
    "Pyranometer.B1 AVG": [
        "Pyranometer.B1 St20",
        "Pyranometer.B1 St05",
        "Pyranometer.B1 St10",
    ],
    "Pyranometer.module.AVG": ["Pyranometer.module.08", "Pyranometer.module.02"],
}

MONTH_DIGIT = {
    "янв": "1", "фев": "2", "февр": "2", "мар": "3", "март": "3", "апр": "4",
    "май": "5", "июн": "6", "июнь": "6", "июл": "7", "июль": "7",
    "авг": "8", "сен": "9", "сент": "9", "окт": "0", "ноя": "1", "нояб": "1", "дек": "2"
}
