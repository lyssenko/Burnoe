import os
import pickle
import numpy as np


class RadRegressionModel():

    def __init__(self):
        self.model = pickle.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'rad_xtr_model.pkl'), "rb"))


    def predict(self, df, delta_t=2):
        rad = np.vstack(df['rad'].values)
        T, F = rad.shape
        pad = np.zeros((delta_t, F))
        rad_pad = np.vstack([pad, rad, pad])
        windows = [
            rad_pad[i : i + 2 * delta_t + 1].reshape(-1)
            for i in range(T)
        ]
        X = np.array(windows)
        y_pred = self.model.predict(X)
        return y_pred


class EnergyRegressionModel():

    def __init__(self):
        self.model = pickle.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'energy_xtr_model.pkl'), "rb"))


    def predict(self, df, delta_t=2):
        rad = np.vstack(df['rad'].values)
        T, F = rad.shape
        pad = np.zeros((delta_t, F))
        rad_pad = np.vstack([pad, rad, pad])
        windows = [
            rad_pad[i : i + 2 * delta_t + 1].reshape(-1)
            for i in range(T)
        ]
        X = np.array(windows)
        y_pred = self.model.predict(X)
        return y_pred
