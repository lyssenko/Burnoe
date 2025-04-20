import power_network as pn
import math
import matplotlib.pyplot as plt
import random
import pandas as pd


rho = 0.01724
L_m = 30
S_mm2 = 50
D = 0.4
f = 50
U = 400
epsilon = 8.854e-12
mu_0 = 4 * math.pi * 1e-7
num_nodes = 3
Ped = 200000
P = Ped * num_nodes
cosf = 1
cosf_g = 1
Qed = Ped * math.sqrt(1 - cosf * cosf)
Q = Qed * num_nodes
Ped_g = 20000
P_g = Ped_g * num_nodes
file_path = "rad_2024-08-28.csv"


def load_variation():
    return P * random.random()

def get_voltage_values(net):
    return net.res_bus['vm_pu'].values * U  

def read_solar_radiation_data(file_path):
    data = pd.read_csv(file_path)
    return data

def solar_radiation_to_power(radiation, efficiency=0.2, area=10):
    return radiation * efficiency * area



solar_data = read_solar_radiation_data(file_path)

solar_data['power_generation'] = solar_data['rad'].apply(solar_radiation_to_power)

voltage_results = []

for index, row in solar_data.iterrows():
    
    P_g_interval = row['power_generation']

    net, R_ohm, X_L_ohm, C_nF = pn.create_and_run_network(U, num_nodes, load_variation(), Q, P_g_interval, cosf_g, rho, L_m, S_mm2, D, f, epsilon, mu_0)

    voltage_values = get_voltage_values(net)
    voltage_results.append(voltage_values)

    print(f"Время {row['datetime']}: Генерация мощности = {P_g_interval:.2f} Вт, Напряжения в узлах = {voltage_values}")


plt.figure(figsize=(10, 6))

for i in range(num_nodes):
    node_voltages = [voltages[i] for voltages in voltage_results]
    plt.plot(solar_data['datetime'], node_voltages, marker='o', label=f'Узел {i+1}')

plt.xlabel('Время')
plt.ylabel('Напряжение (В)')
plt.title('Зависимость напряжения в узлах от времени')
plt.legend()
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()