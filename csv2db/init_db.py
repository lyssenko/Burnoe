from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, create_engine, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from db_session import engine


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


def init_db():
    Base.metadata.create_all(engine)
    print("База данных и таблицы успешно созданы.")


if __name__ == "__main__":
    init_db()
