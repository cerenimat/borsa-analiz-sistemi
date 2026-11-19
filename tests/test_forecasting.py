import unittest
from forecasting.features import build_features
from forecasting.models import LojistikRegresyonModeli
from forecasting.train import FEATURE_COLUMNS, time_series_split


class TestForecasting(unittest.TestCase):
    def test_no_data_leakage_in_split(self):
        """Eğitim verisindeki en son tarih, test verisindeki ilk tarihten küçük olmalıdır (İOG-G-03)."""
        df = build_features("THYAO")
        train_df, test_df = time_series_split(df, train_ratio=0.8)

        self.assertGreater(len(train_df), 0)
        self.assertGreater(len(test_df), 0)
        self.assertLess(train_df["date"].max(), test_df["date"].min())

    def test_reproducibility(self):
        """Aynı veriyle iki kez eğitilen model birebir aynı sonucu vermelidir (İOG-G-02)."""
        df = build_features("THYAO")
        train_df, test_df = time_series_split(df, train_ratio=0.8)

        m1 = LojistikRegresyonModeli()
        m2 = LojistikRegresyonModeli()
        m1.egit(train_df[FEATURE_COLUMNS], train_df["target"])
        m2.egit(train_df[FEATURE_COLUMNS], train_df["target"])

        self.assertEqual(
            m1.degerlendir(test_df[FEATURE_COLUMNS], test_df["target"]),
            m2.degerlendir(test_df[FEATURE_COLUMNS], test_df["target"]),
        )


if __name__ == "__main__":
    unittest.main()
