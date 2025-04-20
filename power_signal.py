import asyncio
import random
import math
import time
from itertools import count
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt

# Импорт модуля, содержащего функции для расчёта параметров сети
import power_network as pn

# --------------------------- Параметры модели (из def_model.py) ---------------------------
rho = 0.01724                               
L_m = 30                                    
S_mm2 = 50                                  
D = 0.4                                      
f = 50                                      
U = 400                                      
epsilon = 8.854e-12                          
mu_0 = 4 * math.pi * 1e-7                    
num_nodes = 2                                
Ped = 200000                                
P = Ped * num_nodes                          
cosf = 1                                    
cosf_g = 1                                  
Qed = Ped * math.sqrt(1 - cosf * cosf)      
Q = Qed * num_nodes                          
Ped_g = 20000                               
P_g = Ped_g * num_nodes                      

def load_variation():
    return P * random.random()

def get_voltage_values(net):
    return net.res_bus['vm_pu'].values * U  

def read_solar_radiation_data(file_path):
    data = pd.read_csv(file_path)
    return data

def solar_radiation_to_power(radiation, efficiency=0.2, area=10):
    return radiation * efficiency * area

# Считывание данных о солнечной радиации и вычисление мощности генерации
file_path = "rad_2024-08-28.csv"
solar_data = read_solar_radiation_data(file_path)
solar_data['power_generation'] = solar_data['rad'].apply(solar_radiation_to_power)

# Глобальная переменная, в которую будут записываться вычисленные напряжения узлов
calculated_voltages = [0] * num_nodes

# ---------------------- Асинхронная симуляция сигналов (из signal_test_v2.py) ----------------------
signal_history_data = []
signal_reception_data = []

async def log_signal_history(node_id, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    signal_history_data.append({"Timestamp": timestamp, "Node": node_id + 1, "Message": message})

async def log_signal_reception(node_id, voltage):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    signal_reception_data.append({"Timestamp": timestamp, "Node": node_id + 1, "Voltage": voltage})

# Функция симуляции отправки сигнала с узла; вместо генерации случайного напряжения здесь берётся значение из calculated_voltages.
async def simulate_node_signal(node_id, x_vals, y_vals, indices, lock):
    global calculated_voltages
    while True:
        try:
            if lock.locked():
                message = f"Сигнал прерван, так как идет отправка из другого узла (активный узел: {lock._owner_node_id + 1})."
                await log_signal_history(node_id, message)
                await asyncio.sleep(random.uniform(1, 5))
                continue

            async with lock:
                lock._owner_node_id = node_id

                await log_signal_history(node_id, "Попытка отправки сигнала")

                # Вместо генерации случайного напряжения берем расчетное значение для данного узла
                voltage = calculated_voltages[node_id]

                # Обновляем данные для построения графика (если требуется)
                x_vals[node_id].append(next(indices[node_id]))
                y_vals[node_id].append(voltage)

                message = f"Напряжение: {voltage:.2f} В"
                await log_signal_history(node_id, message)
                await log_signal_reception(node_id, voltage)

                # Задержка, имитирующая время удержания lock
                await asyncio.sleep(2)

            random_interval = random.uniform(1, 5)
            await asyncio.sleep(random_interval)

        except Exception as e:
            message = f"Произошла ошибка: {e}"
            await log_signal_history(node_id, message)
            await asyncio.sleep(random.uniform(1, 3))

# Функция, запускающая симуляцию сигналов для всех узлов
async def simulate_voltage_signals(node_count):
    x_vals = {node: [] for node in range(node_count)}
    y_vals = {node: [] for node in range(node_count)}
    indices = {node: count() for node in range(node_count)}

    lock = asyncio.Lock()
    lock._owner_node_id = -1

    tasks = [simulate_node_signal(node_id, x_vals, y_vals, indices, lock) for node_id in range(node_count)]
    update_task = asyncio.create_task(update_calculated_voltages())
    timer_task = asyncio.create_task(show_runtime())

    await asyncio.gather(*tasks, update_task, timer_task)

# Функция обновления рассчитанных напряжений по данным солнечной радиации
async def update_calculated_voltages():
    global calculated_voltages
    for index, row in solar_data.iterrows():
        P_g_interval = row['power_generation']
        net, R_ohm, X_L_ohm, C_nF = pn.create_and_run_network(
            U, num_nodes, load_variation(), Q, P_g_interval, cosf_g,
            rho, L_m, S_mm2, D, f, epsilon, mu_0)
        voltage_values = get_voltage_values(net)
        calculated_voltages = list(voltage_values)
        print(f"Время {row['datetime']}: Генерация мощности = {P_g_interval:.2f} Вт, Напряжения в узлах = {calculated_voltages}")
        # Задержка перед следующим обновлением (например, 5 секунд)
        await asyncio.sleep(5)

async def show_runtime():
    start_time = time.time()
    while True:
        elapsed_time = time.time() - start_time
        print(f"Время работы программы: {elapsed_time:.2f} секунд", end="\r")
        await asyncio.sleep(1)

async def main(node_count):
    await simulate_voltage_signals(node_count)

if __name__ == "__main__":
    try:
        asyncio.run(main(num_nodes))
    finally:
        # Сохранение логов в CSV по завершении работы
        pd.DataFrame(signal_history_data).to_csv("signal_history.csv", index=False)
        pd.DataFrame(signal_reception_data).to_csv("signal_reception.csv", index=False)
