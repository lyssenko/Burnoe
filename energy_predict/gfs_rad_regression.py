# %%
import os
import numpy as np
import glob
import xarray
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import requests
from sklearn.ensemble._forest import ExtraTreesRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, \
    mean_absolute_error
import xgboost as xgb
from sklearn.preprocessing import StandardScaler


ROOT_DIR = "/home/kairat/Build_WRF/"
ICBC_DIR = os.path.join(ROOT_DIR, "icbc")


# %% 
def read_gfs_data(file_path):
    h = int(file_path[-2:])
    offset = datetime.timedelta(hours=h+5)
    delta = pd.Timedelta(offset)
    data = xarray.open_dataset(file_path, engine='cfgrib', filter_by_keys={'typeOfLevel': 'surface'})
    dt = pd.to_datetime(data['time'].values + delta)        # Date and Time
    rad = data['sdswrf'].values        # Downward short-wave radiation flux, units: W m**-2 (Поток нисходящего коротковолнового излучения, ед.: Вт м**-2)
    data.close()
    return  dt, rad


# %%
def extract_data(start_date):
    # GFS
    gfs_files_dir = os.path.join(ICBC_DIR, 'rad', f"{start_date.strftime('%Y%m%d')}")
    data = []
    for gfs_file_path in glob.glob(f"{gfs_files_dir}/*.f*"):
        if os.path.isfile(gfs_file_path + ".5b7b6.idx"):
            os.remove(gfs_file_path + ".5b7b6.idx")
        if gfs_file_path[-4:] == '.idx':
            continue
        gfs_dt, gfs_rad = read_gfs_data(gfs_file_path)  
        # plt.imshow(gfs_rad)
        # plt.show()
        x_hour = gfs_rad.ravel()
        if (x_hour == 0).all():
            continue
        data.append([gfs_dt, x_hour])
    if len(data) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=['datetime', 'X'])
    df.set_index('datetime', inplace=True)
    
    # OBS sensor 1
    url = f"http://213.5.184.182/get_data?sensor_id=1&start_date={df.index[0].strftime('%Y-%m-%d')}&end_date={df.index[-1].strftime('%Y-%m-%d')}&interval=60"
    res = requests.get(url)
    if res.status_code != 200:
        return pd.DataFrame()
    res_data = res.json()
    if len(res_data['values']) > 0:
        obs_dt = np.array(res_data['time'], dtype=np.datetime64)
        obs_rad = np.array(res_data['values'])
        obs_rad[obs_rad<0] = 0
        obs_data = np.array([obs_dt, obs_rad]).T    
        df_target = pd.DataFrame(obs_data, columns=['datetime', 'target'])
        df_target.set_index('datetime', inplace=True)
        df = pd.merge(df, df_target, on="datetime", how="inner")
    else:
        # OBS sensor 2
        url = f"http://213.5.184.182/get_data?sensor_id=2&start_date={df.index[0].strftime('%Y-%m-%d')}&end_date={df.index[-1].strftime('%Y-%m-%d')}&interval=60"
        res = requests.get(url)
        if res.status_code != 200:
            return pd.DataFrame()
        res_data = res.json()
        if len(res_data['values']) == 0:
            return pd.DataFrame()
        obs_dt = np.array(res_data['time'], dtype=np.datetime64)
        obs_rad = np.array(res_data['values'])
        obs_rad[obs_rad<0] = 0
        obs_data = np.array([obs_dt, obs_rad]).T    
        df_target = pd.DataFrame(obs_data, columns=['datetime', 'target'])
        df_target.set_index('datetime', inplace=True)
        df = pd.merge(df, df_target, on="datetime", how="inner")

    # rad_pred sensor 3
    #     url = f"http://213.5.184.182/get_data?sensor_id=3&start_date={df.index[0].strftime('%Y-%m-%d')}&end_date={df.index[-1].strftime('%Y-%m-%d')}&interval=60"
    #     res = requests.get(url)
    #     if res.status_code != 200:
    #         return pd.DataFrame()
    #     res_data = res.json()
    #     if len(res_data['values']) == 0:
    #         return pd.DataFrame()
    #     obs_dt = np.array(res_data['time'], dtype=np.datetime64)
    #     obs_rad = np.array(res_data['values'])
    #     obs_rad[obs_rad<0] = 0
    #     obs_data = np.array([obs_dt, obs_rad]).T    
    #     df_target = pd.DataFrame(obs_data, columns=['datetime', 'rad_pred'])
    #     df_target.set_index('datetime', inplace=True)
    #     df = pd.merge(df, df_target, on="datetime", how="inner")

    # energy_pred sensor 4
    #     url = f"http://213.5.184.182/get_data?sensor_id=4&start_date={df.index[0].strftime('%Y-%m-%d')}&end_date={df.index[-1].strftime('%Y-%m-%d')}&interval=60"
    #     res = requests.get(url)
    #     if res.status_code != 200:
    #         return pd.DataFrame()
    #     res_data = res.json()
    #     if len(res_data['values']) == 0:
    #         return pd.DataFrame()
    #     obs_dt = np.array(res_data['time'], dtype=np.datetime64)
    #     obs_rad = np.array(res_data['values'])
    #     obs_rad[obs_rad<0] = 0
    #     obs_data = np.array([obs_dt, obs_rad]).T    
    #     df_target = pd.DataFrame(obs_data, columns=['datetime', 'energy_pred'])
    #     df_target.set_index('datetime', inplace=True)
    #     df = pd.merge(df, df_target, on="datetime", how="inner")

    # # energy_true sensor 5
    # url = f"http://213.5.184.182/get_data?sensor_id=5&start_date={df.index[0].strftime('%Y-%m-%d')}&end_date={df.index[-1].strftime('%Y-%m-%d')}&interval=60"
    # res = requests.get(url)
    # if res.status_code != 200:
    #     return pd.DataFrame()
    # res_data = res.json()
    # if len(res_data['values']) == 0:
    #     return pd.DataFrame()
    # obs_dt = np.array(res_data['time'], dtype=np.datetime64)
    # obs_rad = np.array(res_data['values'])
    # obs_rad[obs_rad<0] = 0
    # obs_data = np.array([obs_dt, obs_rad]).T    
    # df_target = pd.DataFrame(obs_data, columns=['datetime', 'energy_true'])
    # df_target.set_index('datetime', inplace=True)
    # df = pd.merge(df, df_target, on="datetime", how="inner")

    return df


# %%
def preprocessing_data(start_date, end_date,clear=True):
    df = pd.DataFrame()
    while start_date < end_date:
        try:
            # if start_date.strftime('%Y%m%d') != "20250617": 
            #     continue
            print('File:', start_date)
            df_local = extract_data(start_date)
            if len(df_local) > 0:
                if clear:
                    df = df.combine_first(df_local)
                elif (not is_clear_day(df_local)):
                    df = df.combine_first(df_local)
        except Exception as e:
            print('Error:', start_date, e)
        finally:
            start_date += datetime.timedelta(days=1)

    return df


# %%
def test(reg, df, delta_t=1):
    X = np.array([np.hstack(df['X'].values[i-delta_t:i+delta_t+1]) for i in range(delta_t, len(df)-delta_t)])
    Y = df['target'].values[delta_t:-delta_t]
    # X = np.vstack(df['X'].values)
    # Y = df['target1'].values
    y_pred = reg.predict(X)
    # Calculate the mean squared error and R-squared score
    mse = mean_squared_error(Y, y_pred)
    print(f"Mean Squared Error: GFS: {mse}")
    r2 = r2_score(Y, y_pred)
    print(f"R-squared Score: GFS: {r2}")
    mae = mean_absolute_error(Y, y_pred)
    print(f"Mean Absolute Error: GFS: {mae}")
    rmse = mean_squared_error(Y, y_pred, squared=False)
    print(f"Root Mean Squared Error: GFS: {rmse}")

    return reg


# %%
# def predict(reg, df):
#     for dt, group in df.groupby(df.index.date):   # группируем только по дате
#         plt.figure(figsize=(8,4))
#         plt.title(str(dt))

#         date_label, y_pred, y_true = [], [], []
#         for i, row in group.iterrows():
#             X = row['X'].reshape(1, -1)
#             y = reg.predict(X)
#             date_label.append(i)
#             y_pred.append(y)
#             y_true.append(row['target1'])

#         plt.plot(date_label, y_pred, label=f'y_pred')
#         plt.plot(date_label, y_true, label=f'y_true')
#         ax = plt.gca()
#         ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))   # тики каждые 1 час
#         ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))  # формат ЧЧ:ММ
#         plt.gcf().autofmt_xdate()  # авто-поворот подписей, чтобы не налезали
#         plt.legend()
#         plt.show()


# %%
def predict(reg, df, delta_t=1):
    for dt, group in df.groupby(df.index.date):   # группируем только по дате
        plt.figure(figsize=(8,4))
        plt.title(str(dt))

        dt_label, y_pred, y_true, y_wrf_pred = [], [], [], []
        for i in range(delta_t, len(group)-delta_t):
            X = np.hstack(group['X'].values[i-delta_t:i+delta_t+1]).reshape(1, -1)
            y = reg.predict(X)
            dt_label.append(group.index[i])
            y_pred.append(y)
            y_true.append(group['target'].values[i])

        plt.plot(dt_label, y_true, label=f'y_true')
        plt.plot(dt_label, y_pred, label=f'gfs_pred')
        ax = plt.gca()
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))   # тики каждые 1 час
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))  # формат ЧЧ:ММ
        plt.gcf().autofmt_xdate()  # авто-поворот подписей, чтобы не налезали
        plt.legend()
        plt.show()


# %%
def split_train_test(df, test_size=0.1, random_state=18):
    # Уникальные даты
    unique_dates = df.index.normalize().unique()   # normalize -> обрезает время
    # train/test split по датам
    train_dates, test_dates = train_test_split(unique_dates, test_size=test_size, random_state=random_state)
    # Собираем обратно строки
    train_df = df[df.index.normalize().isin(train_dates)]
    test_df  = df[df.index.normalize().isin(test_dates)]
        
    return train_df, test_df

# %%
def is_clear_day(fc_df, rad_max_treshold=600, rad_delta=20):
    data = np.stack(fc_df['X'].values)
    for x in range(data.shape[1]):
        rad_max = np.max(data[:, x])
        rad_max_n = np.argmax(data[:, x])
        if any(np.diff(data[:, x])[:rad_max_n] < -rad_delta) or\
            any(np.diff(data[:, x])[rad_max_n:] > rad_delta):
            return False
        if rad_max < rad_max_treshold:
            return False
    return True

# %%
def train(df, delta_t=1):
    X = np.array([np.hstack(df['X'].values[i-delta_t:i+delta_t+1]) for i in range(delta_t, len(df)-delta_t)])
    Y = df['target'].values[delta_t:-delta_t]
    # X = np.vstack(df['X'].values)
    # Y = df['target1'].values
    # reg = LinearRegression().fit(X, Y)
    # reg = xgb.XGBRegressor().fit(X, Y)
    reg = ExtraTreesRegressor().fit(X, Y)
    # reg = MLPRegressor(
    #     hidden_layer_sizes=(2000,),
    #     activation="relu",
    #     solver="adam",
    #     random_state=1, 
    #     max_iter=500).fit(X, Y)
    return reg


# Preprocessing 
# %%
# start_date = datetime.datetime(2025, 2, 1)
# # start_date = datetime.datetime(2025, 8, 24)
# end_date= datetime.datetime(2025, 12, 16)
# df = preprocessing_data(start_date, end_date, clear=True)
# df.to_pickle('energy_dataset.pkl')
            
# %% 
df = pd.read_pickle('rad_dataset.pkl')
# df = pd.read_pickle('noclear_energy_dataset.pkl')
# test_df = pd.read_pickle('test_noclear_wrf_rad_dataset.pkl')


# %%
df_train, df_test = split_train_test(df, test_size=0.2, random_state=18)
# df_test = pd.concat([df_test, test_df])


# TRAIN
# %% 
reg = train(df, delta_t=2)

# TEST
# %%
test(reg, df_test, delta_t=2)

# PREDICT
# %%
# predict(reg, df_test, delta_t=2)

# # %%
# w = reg.coef_
# ww = w.reshape(-1, int(np.sqrt(len(w))))
# plt.imshow(ww, label='w')
# plt.colorbar()
# # %%
# df_test = df[df['date'] == '2017-01-02']
# # %%
# arr = df_test.X.values
# # %%
# plt.imshow(arr[0][180].reshape(15, 15))
# # %%

# %%
import pickle
pickle.dump(reg, open('rad_xtr_model.pkl', "wb"))

# %%