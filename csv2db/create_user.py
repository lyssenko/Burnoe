from db_session import SessionLocal
from init_db import User

def create_user(username, password):
    with SessionLocal() as db:
        user = User(username=username)
        user.set_password(password)
        db.add(user)
        db.commit()
        print(f"Пользователь {username} создан.")

if __name__ == "__main__":
    username = input("Введите имя пользователя: ")
    password = input("Введите пароль: ")
    create_user(username, password)

