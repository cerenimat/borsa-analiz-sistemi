
from fastapi import FastAPI
from web.backend.routes import stocks, prices

app = FastAPI(
    title="Borsa Analiz Sistemi API",
    description="BIST 50 hisse senedi analiz sistemi",
    version="1.0.0"
)

# Hisse senedi endpointleri
app.include_router(stocks.router)
app.include_router(prices.router)


@app.get("/")
def home():
    return {"message": "Borsa Analiz Sistemi API çalışıyor!"}
