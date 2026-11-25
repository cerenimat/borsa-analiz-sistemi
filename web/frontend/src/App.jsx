
import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'

function App() {
  const [hisseler, setHisseler] = useState([])
  const [seciliHisse, setSeciliHisse] = useState('')
  const [hata, setHata] = useState('')
  const [fiyatlar, setFiyatlar] = useState([])
  const [fiyatYukleniyor, setFiyatYukleniyor] = useState(false)
  const [baslangicTarihi, setBaslangicTarihi] = useState('')
  const [bitisTarihi, setBitisTarihi] = useState('')

  const [tahmin, setTahmin] = useState(null)
  const [tahminYukleniyor, setTahminYukleniyor] = useState(false)
  const [tahminHata, setTahminHata] = useState('')
  const [duyguAnalizleri, setDuyguAnalizleri] = useState([]);
  const [duyguYukleniyor, setDuyguYukleniyor] = useState(false);
  const [duyguHata, setDuyguHata] = useState('');
  const [icerikler, setIcerikler] = useState([]);
  const [icerikYukleniyor, setIcerikYukleniyor] = useState(false);
  const [icerikHata, setIcerikHata] = useState('');


  useEffect(() => {
    fetch('/api/hisseler')
      .then((cevap) => {
        if (!cevap.ok) {
          throw new Error('Hisse listesi alınamadı.')
        }
        return cevap.json()
      })
      .then((veri) => {
        setHisseler(veri.hisseler)
      })
      .catch((error) => {
        setHata(error.message)
      })
  }, [])


  useEffect(() => {

    if (!seciliHisse) {
      setFiyatlar([])
      setHata('')
      setFiyatYukleniyor(false)
      return
    }

    setFiyatYukleniyor(true)
    setFiyatlar([])
    setHata('')

    const controller = new AbortController()


    const parametreler = new URLSearchParams()

    if (baslangicTarihi) {
      parametreler.append('start', baslangicTarihi)
    }

    if (bitisTarihi) {
      parametreler.append('end', bitisTarihi)
    }

    fetch(`/api/fiyat/${seciliHisse}?${parametreler.toString()}`, {
      signal: controller.signal,
    })

      .then(async (cevap) => {
        if (!cevap.ok) {
          const hataVerisi = await cevap.json()

          throw new Error(
            typeof hataVerisi.detail === 'string'
              ? hataVerisi.detail
              : 'Fiyat verileri alınamadı.'
          )
        }





        return cevap.json()
      })

      .then((veri) => {
        setFiyatlar(veri.fiyatlar)
        setHata('')
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setFiyatlar([])
          setHata(error.message)
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setFiyatYukleniyor(false)
        }
      })

    return () => controller.abort()
  }, [seciliHisse, baslangicTarihi, bitisTarihi])


  useEffect(() => {
    if (!seciliHisse) {
      setTahmin(null)
      setTahminHata('')
      setTahminYukleniyor(false)
      return
    }

    setTahmin(null)
    setTahminHata('')
    setTahminYukleniyor(true)

    const controller = new AbortController()

    fetch(`/api/tahmin/${seciliHisse}`, {
      signal: controller.signal,
    })
      .then(async (cevap) => {
        if (!cevap.ok) {
          const hataVerisi = await cevap.json().catch(() => ({}))

          throw new Error(
            typeof hataVerisi.detail === 'string'
              ? hataVerisi.detail
              : 'Tahmin verileri alınamadı.'
          )
        }

        return cevap.json()
      })
      .then((veri) => {
        if (!controller.signal.aborted) {
          setTahmin(veri)
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setTahminHata(error.message)
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setTahminYukleniyor(false)
        }
      })

    return () => controller.abort()
  }, [seciliHisse])

  useEffect(() => {
    setDuyguAnalizleri([]);
    setDuyguHata('');

    if (!seciliHisse) {
      setDuyguYukleniyor(false);
      return;
    }

    const controller = new AbortController();

    const duyguVerileriniGetir = async () => {
      setDuyguYukleniyor(true);

      try {
        const parametreler = new URLSearchParams();

        if (baslangicTarihi) {
          parametreler.append('baslangic', baslangicTarihi);
        }

        if (bitisTarihi) {
          parametreler.append('bitis', bitisTarihi);
        }

        const response = await fetch(
          `/api/duygu/${seciliHisse}?${parametreler.toString()}`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          throw new Error('Duygu analizi verileri alınamadı.');
        }

        const data = await response.json();

        setDuyguAnalizleri(data.duygu_analizleri);
      } catch (error) {
        if (error.name !== 'AbortError') {
          setDuyguHata(error.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setDuyguYukleniyor(false);
        }
      }
    };

    duyguVerileriniGetir();

    return () => controller.abort();
  }, [seciliHisse, baslangicTarihi, bitisTarihi]);

  useEffect(() => {
    setIcerikler([]);
    setIcerikHata('');

    if (!seciliHisse) {
      setIcerikYukleniyor(false);
      return;
    }

    const controller = new AbortController();

    const icerikleriGetir = async () => {
      setIcerikYukleniyor(true);

      try {
        const parametreler = new URLSearchParams();

        if (baslangicTarihi) {
          parametreler.append('baslangic', baslangicTarihi);
        }

        if (bitisTarihi) {
          parametreler.append('bitis', bitisTarihi);
        }

        const response = await fetch(
          `/api/icerikler/${seciliHisse}?${parametreler.toString()}`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          throw new Error('Haber ve yorumlar alınamadı.');
        }

        const data = await response.json();

        setIcerikler(data.icerikler);

      } catch (error) {
        if (error.name !== 'AbortError') {
          setIcerikHata(error.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setIcerikYukleniyor(false);
        }
      }
    };

    icerikleriGetir();

    return () => controller.abort();

  }, [seciliHisse, baslangicTarihi, bitisTarihi]);



  return (
    <div>
      <h1>Borsa Analiz Sistemi</h1>

      <p>
        Yapay zeka destekli borsa ve finansal piyasa analiz sistemi
      </p>

      <h2>Hisse Secimi</h2>

      {hata && <p style={{ color: 'red' }}>{hata}</p>}

      <select
        value={seciliHisse}
        onChange={(event) => setSeciliHisse(event.target.value)}
      >
        <option value="">Bir hisse seçiniz</option>

        {hisseler.map((hisse) => (
          <option key={hisse.symbol} value={hisse.symbol}>
            {hisse.symbol} - {hisse.name}
          </option>
        ))}
      </select>


      {seciliHisse && (
        <div>
          <h2>{seciliHisse} Fiyat Bilgileri</h2>


          <div>
            <label>
              Başlangıç Tarihi:
              <input
                type="date"
                value={baslangicTarihi}
                onChange={(event) =>
                  setBaslangicTarihi(event.target.value)
                }
              />
            </label>

            <label>
              Bitiş Tarihi:
              <input
                type="date"
                value={bitisTarihi}
                onChange={(event) =>
                  setBitisTarihi(event.target.value)
                }
              />
            </label>
          </div>



          {!fiyatYukleniyor && fiyatlar.length > 0 && (
            <Plot
              data={[
                {
                  x: fiyatlar.map((fiyat) => fiyat.date),
                  y: fiyatlar.map((fiyat) => fiyat.close),
                  type: 'scatter',
                  mode: 'lines',
                  name: 'Kapanış Fiyatı',
                  line: {
                    color: '#2563eb',
                    width: 2,
                  },
                },
              ]}
              layout={{
                title: {
                  text: `${seciliHisse} Kapanış Fiyatları`,
                },
                xaxis: {
                  title: { text: 'Tarih' },
                },
                yaxis: {
                  title: { text: 'Fiyat (TL)' },
                },
                autosize: true,
              }}
              useResizeHandler={true}
              style={{ width: '100%', height: '450px' }}
              config={{
                responsive: true,
                displaylogo: false,
              }}
            />
          )}


          {!fiyatYukleniyor && fiyatlar.length > 0 && (
            <Plot
              data={[
                {
                  x: fiyatlar.map((fiyat) => fiyat.date),
                  y: fiyatlar.map((fiyat) => fiyat.volume),
                  type: 'bar',
                  name: 'İşlem Hacmi',
                  marker: {
                    color: '#0d9488',
                  },
                },
              ]}
              layout={{
                title: {
                  text: `${seciliHisse} İşlem Hacmi`,
                },
                xaxis: {
                  title: { text: 'Tarih' },
                },
                yaxis: {
                  title: { text: 'İşlem Hacmi (Adet)' },
                },
                autosize: true,
              }}
              useResizeHandler={true}
              style={{ width: '100%', height: '300px' }}
              config={{
                responsive: true,
                displaylogo: false,
              }}
            />
          )}


          <div>
            <h2>Duygu Analizi</h2>

            {duyguYukleniyor && (
              <p>Duygu analizi verileri yükleniyor...</p>
            )}

            {duyguHata && (
              <p style={{ color: 'red' }}>{duyguHata}</p>
            )}

            {!duyguYukleniyor &&
              !duyguHata &&
              duyguAnalizleri.length === 0 && (
                <p>Seçilen tarih aralığında duygu analizi verisi bulunamadı.</p>
              )}

            {!duyguYukleniyor &&
              !duyguHata &&
              duyguAnalizleri.length > 0 && (
                <Plot
                  data={[
                    {
                      x: duyguAnalizleri.map((veri) => veri.trading_date),
                      y: duyguAnalizleri.map((veri) => veri.news_avg_score),
                      type: 'scatter',
                      mode: 'lines+markers',
                      name: 'Haberler',
                      line: { color: '#2563eb', width: 2 },
                      connectgaps: false,
                    },
                    {
                      x: duyguAnalizleri.map((veri) => veri.trading_date),
                      y: duyguAnalizleri.map((veri) => veri.comment_avg_score),
                      type: 'scatter',
                      mode: 'lines+markers',
                      name: 'Yorumlar',
                      line: { color: '#ea580c', width: 2 },
                      connectgaps: false,
                    },
                  ]}
                  layout={{
                    title: {
                      text: `${seciliHisse} Günlük Duygu Analizi`,
                    },
                    xaxis: {
                      title: { text: 'Tarih' },
                    },
                    yaxis: {
                      title: { text: 'Duygu Skoru' },
                      range: [-1, 1],
                      zeroline: true,
                      zerolinewidth: 2,
                    },
                    autosize: true,
                  }}
                  useResizeHandler={true}
                  style={{ width: '100%', height: '400px' }}
                  config={{
                    responsive: true,
                    displaylogo: false,
                  }}
                />
              )}
          </div>

          <div>
            <h2>Haber ve Yorumlar</h2>

            {icerikYukleniyor && (
              <p>Haber ve yorumlar yükleniyor...</p>
            )}

            {icerikHata && (
              <p style={{ color: 'red' }}>{icerikHata}</p>
            )}

            {!icerikYukleniyor &&
              !icerikHata &&
              icerikler.length === 0 && (
                <p>Bu aralıkta haber veya yorum bulunamadı.</p>
              )}

            {!icerikYukleniyor &&
              !icerikHata &&
              icerikler.length > 0 && (
                <div>
                  <p>Gösterilen içerik sayısı: {icerikler.length}</p>

                  {icerikler.map((icerik) => (
                    <div
                      key={icerik.id}
                      style={{
                        border: '1px solid #d1d5db',
                        borderRadius: '8px',
                        padding: '16px',
                        marginBottom: '12px',
                        overflowWrap: 'anywhere'
                      }}
                    >
                      <p>
                        {new Date(icerik.published_at).toLocaleString(
                          'tr-TR',
                          { timeZone: 'Europe/Istanbul' }
                        )}
                        {' | '}
                        {icerik.source}
                        {' | '}
                        {icerik.type === 'news'
                          ? 'Haber'
                          : icerik.type === 'kap'
                            ? 'KAP Bildirimi'
                            : icerik.type === 'comment'
                              ? 'Yorum'
                              : icerik.type}
                      </p>

                      {icerik.title && <h3>{icerik.title}</h3>}

                      <p>
                        {icerik.text.length > 300
                          ? icerik.text.slice(0, 300) + '...'
                          : icerik.text}
                      </p>

                      <p>
                        Duygu:{' '}
                        <strong
                          style={{
                            color:
                              icerik.label === 'positive'
                                ? '#16a34a'
                                : icerik.label === 'negative'
                                  ? '#dc2626'
                                  : '#6b7280'
                          }}
                        >
                          {icerik.label === 'positive'
                            ? 'Olumlu'
                            : icerik.label === 'negative'
                              ? 'Olumsuz'
                              : icerik.label === 'neutral'
                                ? 'Nötr'
                                : icerik.label}
                        </strong>
                        {' | '}
                        Skor: {icerik.score.toFixed(4)}
                      </p>

                      {icerik.url && (
                        <a
                          href={icerik.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Kaynağa git
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
          </div>



          <div>
            <h2>Yapay Zekâ Tahminleri</h2>

            {tahminYukleniyor && (
              <p>Tahminler yükleniyor...</p>
            )}

            {tahminHata && (
              <p style={{ color: 'red' }}>{tahminHata}</p>
            )}

            {!tahminYukleniyor && tahmin && tahmin.symbol === seciliHisse && (
              <div>
                <p>Son işlem günü: {tahmin.son_islem_gunu}</p>
                <p>Bir sonraki işlem günü için tahminler:</p>

                {tahmin.tahminler.map((model) => (
                  <div key={model.model}>
                    <h3>{model.model}</h3>

                    <p>
                      Tahmin edilen yön:{' '}
                      <strong
                        style={{
                          color: model.yon === 'Yükseliş'
                            ? 'green'
                            : 'red',
                        }}
                      >
                        {model.yon}
                      </strong>
                    </p>

                    <p>
                      Tahmin olasılığı: %
                      {(model.olasilik * 100).toFixed(2)}
                    </p>
                  </div>
                ))}

                <p style={{ color: '#b45309' }}>
                  {tahmin.uyari}
                </p>
              </div>
            )}
          </div>


          {fiyatYukleniyor && <p>Fiyatlar yükleniyor...</p>}

          {!fiyatYukleniyor && (
            <table>
              <thead>
                <tr>
                  <th>Tarih</th>
                  <th>Kapanis Fiyati (TL)</th>
                  <th>Islem Hacmi (Adet)</th>
                </tr>
              </thead>
              <tbody>
                {fiyatlar.map((fiyat) => (
                  <tr key={fiyat.date}>
                    <td>{fiyat.date}</td>
                    <td>{fiyat.close}</td>
                    <td>{fiyat.volume}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

    </div>
  )
}

export default App
