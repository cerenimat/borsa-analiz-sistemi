from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

RANDOM_STATE = 42


class TahminModeli(ABC):
    """Tüm tahmin modelleri için ortak soyut arayüz (İOG-D-02)."""

    def __init__(self, ad: str, parametreler: dict[str, Any] | None = None) -> None:
        self.ad = ad
        self.parametreler = parametreler or {}
        self.model: Any = None

    @abstractmethod
    def egit(self, x_egitim: pd.DataFrame, y_egitim: pd.Series) -> None:
        """Modeli eğitim verisiyle eğitir."""

    def tahmin_et(self, x: pd.DataFrame) -> np.ndarray:
        """Sınıf tahmini döndürür (1: Yükseliş, 0: Düşüş/Sabit)."""
        return self.model.predict(x)

    def olasilik_tahmin_et(self, x: pd.DataFrame) -> np.ndarray:
        """Yükseliş (1) sınıfı için olasılık döndürür."""
        return self.model.predict_proba(x)[:, 1]

    def degerlendir(self, x_test: pd.DataFrame, y_test: pd.Series) -> dict[str, Any]:
        """Test kümesinde doğruluk, kesinlik, duyarlılık, F1 ve karışıklık matrisi üretir."""
        y_pred = self.tahmin_et(x_test)
        cm = confusion_matrix(y_test, y_pred, labels=[0, 1])
        return {
            "model": self.ad,
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            "confusion_matrix": {
                "tn": int(cm[0, 0]),
                "fp": int(cm[0, 1]),
                "fn": int(cm[1, 0]),
                "tp": int(cm[1, 1]),
            },
        }


class CogunlukSinifiModeli(TahminModeli):
    """Çoğunluk sınıfı temel yöntemi / baseline (İG-21)."""

    def __init__(self) -> None:
        super().__init__(ad="Cogunluk Sinifi (Temel)", parametreler={"strategy": "most_frequent"})
        self.model = DummyClassifier(strategy="most_frequent")

    def egit(self, x_egitim: pd.DataFrame, y_egitim: pd.Series) -> None:
        self.model.fit(x_egitim, y_egitim)


class LojistikRegresyonModeli(TahminModeli):
    """Ölçeklendirilmiş Lojistik Regresyon modeli (İG-18)."""

    def __init__(self, c: float = 1.0) -> None:
        params = {"C": c, "random_state": RANDOM_STATE, "max_iter": 1000}
        super().__init__(ad="Lojistik Regresyon", parametreler=params)
        self.model = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(C=c, random_state=RANDOM_STATE, max_iter=1000)),
            ]
        )

    def egit(self, x_egitim: pd.DataFrame, y_egitim: pd.Series) -> None:
        self.model.fit(x_egitim, y_egitim)


class RastgeleOrmanModeli(TahminModeli):
    """Random Forest sınıflandırıcısı (İG-18)."""

    def __init__(self, n_estimators: int = 200, max_depth: int = 6) -> None:
        params = {
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "random_state": RANDOM_STATE,
        }
        super().__init__(ad="Random Forest", parametreler=params)
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=RANDOM_STATE,
        )

    def egit(self, x_egitim: pd.DataFrame, y_egitim: pd.Series) -> None:
        self.model.fit(x_egitim, y_egitim)