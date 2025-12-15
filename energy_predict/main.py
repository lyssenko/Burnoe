import os
import time
import shutil
import requests
import datetime
import xarray as xr
import numpy as np
import pandas as pd
import glob
import logging
# smtplib provides functionality to send emails using SMTP.
import smtplib
# MIMEMultipart send emails with both text content and attachments.
from email.mime.multipart import MIMEMultipart
# MIMEText for creating body of the email message.
from email.mime.text import MIMEText
# MIMEApplication attaching application-specific data (like CSV files) to email messages.
from email.mime.application import MIMEApplication
from regression import RadRegressionModel, EnergyRegressionModel

logging.basicConfig(level=logging.INFO, filename="/home/kairat/Burnoe/energy_predict/main.log", filemode="a",
                    format="%(asctime)s %(levelname)s %(message)s")


ROOT_DIR = "/home/kairat/Build_WRF/"
ICBC_DIR = os.path.join(ROOT_DIR, "icbc")
OUT_DIR = os.path.join(ROOT_DIR, "out/Burnoe")

 

def download_radiation(dt, hour):
    start_hour = 18
    end_hour = 33
    grib_dir = os.path.join(ICBC_DIR, 'rad', f"{dt.strftime('%Y%m%d')}")
    os.makedirs(ICBC_DIR, exist_ok=True)
    os.makedirs(grib_dir, exist_ok=True)
    url_dir = f"/gfs.{dt.strftime('%Y%m%d')}/{hour:02}/atmos"
    url_template = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file={0}\
&lev_surface=on&var_DSWRF=on&subregion=&leftlon=69&rightlon=72.6&toplat=44&bottomlat=41.4\
&dir={1}"
    for i in range(start_hour, end_hour+1):
        filename = f"gfs.t{hour:02}z.pgrb2.0p25.f{i:03}"
        url = url_template.format(filename, url_dir)
        filepath = os.path.join(grib_dir, filename)
        if not os.path.isfile(filepath):
            for i in range(30):
                try:
                    with requests.get(url, stream=True) as r:
                        with open(filepath, 'wb') as f:
                            shutil.copyfileobj(r.raw, f)
                    break
                except:
                    time.sleep(30)
    logging.info("Данные радиации скачены")
    

def read_grib(grib_file):
    ds_sfc = xr.open_dataset(grib_file, engine='cfgrib', filter_by_keys={'typeOfLevel': 'surface', 'stepType': 'avg'})
    time = pd.to_datetime(ds_sfc['time'].values)
    rad = ds_sfc['sdswrf'].values.ravel()
    ds_sfc.close()
    return time, rad


def read_rad_data(dt):
    time_zone = 5
    start_hour = 18
    end_hour = 33
    grib_dir = os.path.join(ICBC_DIR, 'rad', f"{dt.strftime('%Y%m%d')}")
    time_list = []
    data_list = []
    for i in range(start_hour, end_hour+1):
        filename = f"gfs.t{hour:02}z.pgrb2.0p25.f{i:03}"
        grib_file = os.path.join(grib_dir, filename)
        if not os.path.isfile(grib_file):
            logging.error("File not found:", grib_file)
            break
        time, data = read_grib(grib_file)
        time_list.append(time + datetime.timedelta(hours=time_zone+i))
        data_list.append(data)
    df = pd.DataFrame({'DateTime': time_list, 'rad': data_list})
    df['Time'] = df['DateTime'].dt.time
    return df


def run_rad_prediction(df):
    model = RadRegressionModel()
    rad_pred = model.predict(df)
    return df.assign(rad=rad_pred)


def run_energy_prediction(df):
    model = EnergyRegressionModel()
    energy_pred = model.predict(df)
    return df.assign(P=energy_pred)


def save_to_file(df, suffix, fc_date):
    
    csv_out_path = os.path.join(OUT_DIR, f'{suffix}_{fc_date}.csv')
    df.to_csv(csv_out_path)
    ax = df.plot(rot=90)
    ax.set_title(fc_date)
    jpg_out_path = os.path.join(OUT_DIR, f'{suffix}_{fc_date}.jpg')
    ax.figure.savefig(jpg_out_path, transparent=False, bbox_inches='tight', pad_inches=0.1, dpi=300)
    logging.info(f"Результаты сохранены в файлы {csv_out_path} и {jpg_out_path}")


def login_to_db():
    login_url = 'http://127.0.0.1:5050/login'
    # Используем requests.Session для сохранения куки сессии
    session = requests.Session()
    # Эмулируем форму логина (такой же формат, как <form method="POST">)
    login_data = {
        'username': 'admin',
        'password': 'Burnoe-123'
    }
    # Выполняем логин
    login_response = session.post(login_url, data=login_data)
    if login_response.status_code != 200 or 'Загрузка данных в базу данных' not in login_response.text:
        logging.info('Не удалось войти в систему')
        return None
    logging.info('Авторизация успешна')
    return session


def run_sending_to_db(fc_datetime):
    session = login_to_db()
    if session is None:
        return
    
    # Sending forecast data
    irrad_csv_file_path = os.path.join(OUT_DIR, f"irrad_{fc_datetime}.csv")
    energy_csv_file_path = os.path.join(OUT_DIR, f"energy_{fc_datetime}.csv")
    
    if os.path.isfile(irrad_csv_file_path) and os.path.isfile(irrad_csv_file_path):
        csv_files = [('forecastFile', (irrad_csv_file_path, open(irrad_csv_file_path, 'rb'))), 
                     ('forecastFile', (energy_csv_file_path, open(energy_csv_file_path, 'rb')))]

        url = f"http://127.0.0.1:5050/upload_forecast"
        try:
            res = session.post(url, files=csv_files)
            if res.status_code == 200:
                logging.info(f"Результаты прогноза отправлены в БД")
            else:
                logging.error(f"Ошибка при отправке результатов прогноза в БД: {res.status_code} {res.text}")
        except Exception as ex:
            logging.exception("ERROR", ex)


def run_sending_email(fc_datetime):
    subject = f"Solar radiation forecasts in Burnoe for {fc_datetime}"
    body = f"Прогноз солнечной радиации в СЭС Бурное за {fc_datetime}"
    sender_email = "boss.kairat@bk.ru"
    # recipients_email = ["team@ugos.kz", "rm@ugos.kz", "is@ugos.kz", "ik@skug.kz", "kairat.boss@gmail.com", "dmitriy.kim@narxoz.kz", "lyssenkori@gmail.com"]
    recipients_email = ["team@ugos.kz", "kairat.boss@gmail.com", "dmitriy.kim@narxoz.kz", "lyssenkori@gmail.com"]
    sender_password = "8ZRvFDgQwFtyKknQiTqD"
    smtp_server = 'smtp.mail.ru'
    smtp_port = 465
    
    # MIMEMultipart() creates a container for an email message that can hold
    # different parts, like text and attachments and in next line we are
    # attaching different parts to email container like subject and others.
    message = MIMEMultipart()
    message['Subject'] = subject
    message['From'] = sender_email
    message['To'] = ", ".join(recipients_email)
    body_part = MIMEText(body)
    message.attach(body_part)

    # section 1 to attach file
    csv_file_path = os.path.join(OUT_DIR, f"irrad_{fc_datetime}.csv")
    with open(csv_file_path,'rb') as file:
        # Attach the file with filename to the email
        message.attach(MIMEApplication(file.read(), Name=f"irrad_{fc_datetime}.csv"))

    # section 2 to attach file
    jpg_file_path = os.path.join(OUT_DIR, f"irrad_{fc_datetime}.jpg")
    with open(jpg_file_path,'rb') as file:
        # Attach the file with filename to the email
        message.attach(MIMEApplication(file.read(), Name=f"irrad_{fc_datetime}.jpg"))

    # section 3 to attach file
    csv_file_path = os.path.join(OUT_DIR, f"energy_{fc_datetime}.csv")
    with open(csv_file_path,'rb') as file:
        # Attach the file with filename to the email
        message.attach(MIMEApplication(file.read(), Name=f"energy_{fc_datetime}.csv"))

    # section 4 to attach file
    jpg_file_path = os.path.join(OUT_DIR, f"energy_{fc_datetime}.jpg")
    with open(jpg_file_path,'rb') as file:
        # Attach the file with filename to the email
        message.attach(MIMEApplication(file.read(), Name=f"energy_{fc_datetime}.jpg"))

    # secction 3 for sending email
    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipients_email, message.as_string())

    logging.info(f"Результаты отправлены на почту")



if __name__ == "__main__":
    dt = datetime.datetime.now() - datetime.timedelta(days=0)  
    hour = 6

    logging.info(f"Запущено: {dt.strftime('%Y-%m-%d')}")

    download_radiation(dt, hour)
    df_rad = read_rad_data(dt)
    rad_pred = run_rad_prediction(df_rad)
    energy_pred = run_energy_prediction(df_rad)
    
    # Save results
    fc_date = (dt + datetime.timedelta(days=1)).date()
    df_rad['Time'] = df_rad['DateTime'].dt.time
    save_to_file(rad_pred[['Time', 'rad']], 'irrad', fc_date)
    save_to_file(energy_pred[['Time', 'P']], 'energy', fc_date)

    # run_sending_email(fc_date)
    run_sending_to_db(fc_date)
    
