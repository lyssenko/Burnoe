import pandapower as pp
import math
from pandapower.plotting import simple_plot


def calculate_radius(S_mm2):
    S_m2 = S_mm2 * 1e-6 
    return math.sqrt(S_m2 / math.pi)

def calculate_active_resistance(rho, L_m, S_mm2):
    return (rho * L_m) / S_mm2  # Ом

def calculate_inductive_reactance(mu_0, D, r, f, L_m):
    L_inductance = (mu_0 / (2 * math.pi)) * math.log(D / r)
    X_L_ohm = 2 * math.pi * f * L_inductance * L_m  # Ом
    X_L_ohm_km = 2 * math.pi * f * L_inductance * 1000  # Ом/км
    return X_L_ohm, X_L_ohm_km

def calculate_capacitance(epsilon, D, r, L_m):
    C_farad = (2 * math.pi * epsilon) / math.log(D / r)
    C_nF = C_farad * 1e9 * L_m  # нФ
    C_nF_km = C_farad * 1e9 * 1000  # нФ/км
    return C_nF, C_nF_km

def create_and_run_network(U, num_nodes, P, Q, Ped_g, cosf_g, rho, L_m, S_mm2, D, f, epsilon, mu_0):
    # Расчет параметров
    r = calculate_radius(S_mm2)
    R_ohm = calculate_active_resistance(rho, L_m, S_mm2)
    X_L_ohm, X_L_ohm_km = calculate_inductive_reactance(mu_0, D, r, f, L_m)
    C_nF, C_nF_km = calculate_capacitance(epsilon, D, r, L_m)

    x_ohm_per_km = X_L_ohm_km
    c_nf_per_km = C_nF_km

    net = pp.create_empty_network()

    buses = [pp.create_bus(net, vn_kv=(U / 1000)) for _ in range(num_nodes + 1)]

    pp.create_ext_grid(net, buses[0], vm_pu=1.0, name="Grid Connection")

    line_data = {
        "c_nf_per_km": c_nf_per_km,
        "r_ohm_per_km": (1000 * R_ohm / L_m),
        "x_ohm_per_km": x_ohm_per_km,
        "max_i_ka": 1.0
    }

    pp.create_std_type(net, line_data, "line_type")

    for i in range(num_nodes):
        pp.create_line(net, from_bus=buses[i], to_bus=buses[i + 1], length_km=(L_m / 1000), std_type="line_type")


    load_per_node_p = P / num_nodes  
    load_per_node_q = Q / num_nodes  

    for i in range(1, num_nodes + 1):
        pp.create_load(net, buses[i], p_mw=(load_per_node_p / 1e6), q_mvar=(load_per_node_q / 1e6))


    load_per_node_p_g = Ped_g / num_nodes  
    for i in range(1, num_nodes + 1):
        pp.create_sgen(net, buses[i], p_mw=(load_per_node_p_g / 1e6), vm_pu=cosf_g)

   
    pp.runpp(net, numba=False)

    return net, R_ohm, X_L_ohm, C_nF

def print_results(net, U, R_ohm, X_L_ohm, C_nF, L_m):
    print("Результаты узлов:")
    print(net.res_bus)

    print(f"Активное сопротивление между двумя шинами: {R_ohm:.4f} Ом")
    print(f"Активное сопротивление на километр: {1000 * R_ohm / L_m} Ом/км")

    
    print(f"\nРеактивное сопротивление между двумя шинами: {X_L_ohm:.4f} Ом")
    print(f"Реактивное сопротивление на километр: {X_L_ohm / (L_m / 1000):.4f} Ом/км")
    print(f"\nЕмкость линии между двумя шинами: {C_nF:.4f} нФ")
    print(f"Емкость линии на километр: {C_nF / (L_m / 1000):.4f} нФ/км")

    print("\nПотери напряжения в каждом узле (В):")
    for i, bus in net.res_bus.iterrows():
        voltage_drop = U - bus.vm_pu * U
        print(f"Узел {i}: Потеря напряжения = {voltage_drop:.2f} В")
       

    print("\nПотери активной мощности в каждой линии (Вт):")
    for i, line in net.res_line.iterrows():
        power_loss = (line.pl_mw * 1e6)
        print(f"Линия {i}: Потеря активной мощности = {power_loss:.2f} Вт")

    total_power_loss = net.res_line.pl_mw.sum() * 1e6
    print(f"\nОбщие потери активной мощности в сети: {total_power_loss:.2f} Вт")

    simple_plot(net)
