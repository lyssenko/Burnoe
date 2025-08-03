import os
import requests
import zipfile
from io import BytesIO


LOGIN_URL = "http://localhost:5000/login"
UPLOAD_URL = "http://localhost:5000/upload"
UPLOAD_FORECAST_URL = "http://localhost:5000/upload_forecast"
USERNAME = "admin"
PASSWORD = "Burnoe-123"
FOLDER = r"E:\YandexDisk\Work\PandaPower\db\raw_data"
FORECAST_FOLDER = r"E:\YandexDisk\Work\PandaPower\db\prognoz"


session = requests.Session()

login_data = {"username": USERNAME, "password": PASSWORD}
resp = session.get(LOGIN_URL)
login_resp = session.post(LOGIN_URL, data=login_data)
if "Вход" in login_resp.text or "Неверный логин" in login_resp.text:
    print("Ошибка авторизации! Проверь логин и пароль.")
    exit(1)
print("Успешный вход!")

def upload_file(file_bytes, file_name, url, field):
    files_data = {field: (file_name, file_bytes)}
    response = session.post(url, files=files_data)
    print(f"[{field.upper()}] {file_name}: {response.status_code} — {response.text[:100]}")

def process_folder(folder, url, field):
    for root, dirs, files in os.walk(folder):
        for file in files:
            file_path = os.path.join(root, file)
            if file.lower().endswith((".csv", ".xlsx")):
                with open(file_path, "rb") as f:
                    upload_file(f, file, url, field)
            elif file.lower().endswith(".zip"):
                print(f"Обнаружен архив: {file_path}")
                try:
                    with zipfile.ZipFile(file_path, 'r') as z:
                        for inner_name in z.namelist():
                            if inner_name.lower().endswith((".csv", ".xlsx")):
                                with z.open(inner_name) as zipped_file:
                                    data = zipped_file.read()
                                    upload_file(BytesIO(data), inner_name, url, field)
                except Exception as e:
                    print(f"Ошибка при обработке {file_path}: {e}")


process_folder(FOLDER, UPLOAD_URL, 'dataFile')

process_folder(FORECAST_FOLDER, UPLOAD_FORECAST_URL, 'forecastFile')