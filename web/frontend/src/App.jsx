
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


  useEffect(() => {
    fetch('/api/hisseler')
      .then((cevap) => {
        if (!cevap.ok) {
          throw new Error('Hisse listesi alinamadi.')
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
              : 'Tahmin verileri alinamadi.'
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
        <option value="">Bir hisse seciniz</option>

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
              Baslangic Tarihi:
              <input
                type="date"
                value={baslangicTarihi}
                onChange={(event) =>
                  setBaslangicTarihi(event.target.value)
                }
              />
            </label>

            <label>
              Bitis Tarihi:
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
                  name: 'Kapanis Fiyati',
                  line: {
                    color: '#2563eb',
                    width: 2,
                  },
                },
              ]}
              layout={{
                title: {
                  text: `${seciliHisse} Kapanis Fiyatlari`,
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


          {fiyatYukleniyor && <p>Fiyatlar yukleniyor...</p>}

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
