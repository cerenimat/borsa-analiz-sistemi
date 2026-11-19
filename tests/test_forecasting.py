import unittest

import numpy as np
import pandas as pd

from forecasting.models import LojistikRegresyonModeli
from forecasting.train import FEATURE_COLUMNS, time_series_split


def _make_dummy_df(n_rows: int = 120) -> pd.DataFrame:
    """Veritabanına bağımlı olmadan test için yapay zaman serisi üretir."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n_rows, freq="B")
    data = {"date": dates}
    for col in FEATURE_COLUMNS:
        data[col] = rng.normal(0.0, 1.0, size=n_rows)
    data["target"] = rng.integers(0, 2, size=n_rows)
    return pd.DataFrame(data)


class TestForecasting(unittest.TestCase):
    def setUp(self):
        self.df = _make_dummy_df()

    def test_no_data_leakage_in_split(self):
        """Eğitim son tarihi, test ilk tarihinden küçük olmalıdır (İOG-G-03)."""
        train_df, test_df = time_series_split(self.df, train_ratio=0.8)
        self.assertLess(train_df["date"].max(), test_df["date"].min())

    def test_reproducibility(self):
        """Aynı veriyle iki kez eğitilen model birebir aynı sonucu vermelidir (İOG-G-02)."""
        train_df, test_df = time_series_split(self.df, train_ratio=0.8)
        x_train, y_train = train_df[FEATURE_COLUMNS], train_df["target"]
        x_test = test_df[FEATURE_COLUMNS]

        m1 = LojistikRegresyonModeli()
        m1.egit(x_train, y_train)
        pred1 = m1.tahmin_et(x_test)

        m2 = LojistikRegresyonModeli()
        m2.egit(x_train, y_train)
        pred2 = m2.tahmin_et(x_test)

        self.assertTrue((pred1 == pred2).all())


if __name__ == "__main__":
    unittest.main()