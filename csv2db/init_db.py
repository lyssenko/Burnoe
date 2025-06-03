from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from db_session import SessionLocal, engine
from werkzeug.security import generate_password_hash, check_password_hash


Base = declarative_base()

class Sensor(Base):
    __tablename__ = 'sensors'

    sensor_id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_name = Column(String, nullable=False)
    sensor_type = Column(String, nullable=False)
    unit = Column(String, nullable=False)

    measurements = relationship("Measurement", back_populates="sensor")

class Measurement(Base):
    __tablename__ = 'measurements'

    measurement_id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey('sensors.sensor_id'), nullable=False)
    measurement_time = Column(DateTime, nullable=False)
    value = Column(Float)

    sensor = relationship("Sensor", back_populates="measurements")

    __table_args__ = (
        UniqueConstraint('sensor_id', 'measurement_time', name='unique_sensor_time'),
        Index('idx_measurements_time', 'measurement_time'),
        Index('idx_measurements_sensor_time', 'sensor_id', 'measurement_time'),
    )

class User(Base):
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


def init_db():
    Base.metadata.create_all(engine)
    print("База данных и таблицы успешно созданы.")


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        existing_user = db.query(User).filter_by(username="admin").first()
        if not existing_user:
            user = User(username="admin")
            user.set_password("12345")
            db.add(user)
            db.commit()
            print("Создан пользователь admin с паролем 12345")
        else:
            print("Пользователь admin уже существует")

