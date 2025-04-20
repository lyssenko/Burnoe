import math
import pandas as pd
import matplotlib.pyplot as plt
import random

# Константы
I_sc = 1361  # Солнечная постоянная, Вт/м²
phi_default = 42.7185  # Географическая широта

# Улучшенные коэффициенты

tau_clear = 0.78  # Повышенная прозрачность атмосферы (~78% для ясного неба)
k_diff_improved = 1.25  # Повышенный вклад рассеянного излучения (~25% от прямого)
threshold_tolerance = 0.05  # Допуск для максимального значения
tolerance = 0.03  # Допуск
err_level = 500  # Порог ошибки

# Пути к файлу с данными
data_file_path = 'data_rad.xlsx'  # Файл с данными по радиации
cur_month = "10"  # Октябрь

data_rad = pd.read_excel(data_file_path, sheet_name=cur_month)

# Функция расчёта максимальной солнечной радиации
def calc_radiation_improved(n, phi):
    delta = 23.45 * math.sin(math.radians((360/365) * (n - 81)))
    alpha = 90 - abs(phi - delta)
    alpha = max(alpha, 0)  # Убеждаемся, что α ≥ 0
    
    E0 = 1 + 0.033 * math.cos(math.radians((360/365) * n))
    I_ext = I_sc * E0 * math.sin(math.radians(alpha))
    I_dir = I_ext * tau_clear
    I_global = I_dir * k_diff_improved
    
    return I_global

# Функция для определения максимальной радиации по заданной дате
def get_max_radiation_for_date(date_str, phi=phi_default):
    date_obj = pd.to_datetime(date_str)
    day_of_year = date_obj.timetuple().tm_yday  # Номер дня в году (1-365/366)
    return calc_radiation_improved(day_of_year, phi)

# Функция проверки, является ли день солнечным
def is_sunny_day(values, threshold, tolerance, threshold_tolerance):
    if values.isnull().any():
        print("Warning: Пропуски в данных радиации обнаружены. День считается пасмурным.")
        return False
    
    max_value = values.max()
    if max_value < threshold * (1 - threshold_tolerance):
        return False
    
    max_index = values.idxmax()
    before_max = values.iloc[:max_index]
    after_max = values.iloc[max_index+1:]
    
    # Проверка краевых случаев
    if len(before_max) < 1 or len(after_max) < 1:
        return False
    
    # Векторизованная проверка монотонности
    before_increasing = (before_max.diff().dropna() >= -tolerance * before_max.shift().dropna()).all()
    after_decreasing = (after_max.diff().dropna() <= tolerance * after_max.shift().dropna()).all()
    
    return before_increasing and after_decreasing


# Функция анализа дней с использованием расчетных значений порогов
def analyze_days_updated(data_rad, tolerance, err_level, phi=phi_default):
    sunny_days = {}
    for column in data_rad.columns[1:]:  # Пропускаем столбец с временем
        day_date = pd.to_datetime(column)  # Преобразуем имя столбца в дату
        try:
            threshold = get_max_radiation_for_date(day_date.strftime('%Y-%m-%d'), phi)
        except Exception as e:
            print(f"Ошибка при расчёте для {day_date}: {e}")
            continue
        sunny_days[column] = "Sunny" if is_sunny_day(data_rad[column], threshold, tolerance, threshold_tolerance) else "Cloudy"
    return sunny_days


# Анализ данных
sunny_days_updated = analyze_days_updated(data_rad, tolerance, err_level)
sunny_days_df = pd.DataFrame(list(sunny_days_updated.items()), columns=["Дата", "Тип"])

print(sunny_days_df)

# Визуализация
# Преобразуем столбец времени в строку
time_labels = data_rad[data_rad.columns[0]].astype(str)

plt.figure(figsize=(12, 6))
colors = [f"#{random.randint(0, 0xFFFFFF):06x}" for _ in range(len(sunny_days_updated))]
for idx, (column, day_type) in enumerate(sunny_days_updated.items()):
    if day_type == "Sunny":
        plt.plot(time_labels, data_rad[column], label=f"{column}", color=colors[idx])

plt.xlabel("Время")
plt.ylabel("Уровень радиации")
plt.title("Радиация для солнечных дней")
plt.legend(loc='upper left')
plt.xticks(rotation=45)
plt.show()


# Проверяем тип данных в столбце времени
if isinstance(data_rad[data_rad.columns[0]].iloc[0], pd.Timestamp):
    time_labels = data_rad[data_rad.columns[0]].dt.strftime('%H:%M')  # Если Timestamp, форматируем как HH:MM
else:
    time_labels = data_rad[data_rad.columns[0]].astype(str)  # В противном случае просто в строку

plt.figure(figsize=(12, 6))
for idx, (column, day_type) in enumerate(sunny_days_updated.items()):
    if day_type == "Cloudy":
        plt.plot(time_labels, data_rad[column], label=f"{column}", color='gray')

plt.xlabel("Время")
plt.ylabel("Уровень радиации")
plt.title("Радиация для пасмурных дней")
plt.legend(loc='upper left')
plt.xticks(rotation=45)
plt.show()

