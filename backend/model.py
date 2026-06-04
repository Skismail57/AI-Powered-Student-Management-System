
import numpy as np
from sklearn.ensemble import RandomForestRegressor

model = RandomForestRegressor(n_estimators=100, random_state=42)

X_train = np.array([
    [2, 7, 90],
    [3, 8, 85],
    [1, 6, 70],
    [4, 9, 95],
    [2.5, 7.5, 88],
    [0.5, 5, 60],
    [3.5, 8.5, 92]
])

y_train = np.array([75, 82, 65, 90, 80, 55, 87])

model.fit(X_train, y_train)

def predict_marks(study_hours, sleep_hours, attendance):
    features = np.array([[study_hours, sleep_hours, attendance]])
    return float(model.predict(features)[0])
