# Screener automatico offerte alimentari

Repository pronto per GitHub Actions. Controlla periodicamente le pagine pubbliche di **Esselunga, Iperal, Il Gigante, MD e Lidl**, cerca solo i prodotti configurati e genera:

- `reports/offerte_latest.html`: cruscotto leggibile da browser;
- `reports/offerte_latest.csv`: dati completi e filtrabili;
- `reports/offerte_latest.md`: sintesi mostrata anche nella pagina GitHub Actions;
- `reports/status.json`: stato tecnico delle fonti;
- `data/history.csv`: storico usato per valutare i prezzi nel tempo.

## Prodotti già configurati

- acqua Sant'Anna naturale da 1,5 L o 2 L;
- acqua Brio Blu Rossa frizzante da 1,5 L;
- caffè Pellini in grani;
- Coca-Cola da 1,5 L;
- yogurt greco;
- Skyr;
- tè Sant'Anna da 1,5 L;
- brioche Misura all'albicocca;
- brioche Misura al miele;
- biscotti integrali Galbusera;
- latte Parmalat Barista.

Le regole sono modificabili in `config/products.yml` senza cambiare il codice Python.

## Punti vendita impostati

- Esselunga: Pioltello;
- Iperal: Vimodrone;
- Il Gigante: Cernusco sul Naviglio;
- MD: Cernusco sul Naviglio, Via Torino 45;
- Lidl: Pioltello, Via Giorgio Amendola 13.

Le fonti ufficiali sono definite in `config/sources.yml`.

## Come attivarlo su GitHub

1. Crea un nuovo repository GitHub, preferibilmente **privato**.
2. Carica nella radice tutti i file di questo progetto.
3. Apri la scheda **Actions** del repository.
4. Se GitHub lo richiede, abilita i workflow.
5. Apri `Screener offerte spesa` e seleziona **Run workflow** per il primo test.
6. Al termine apri il file `reports/offerte_latest.html`, oppure scarica l'artifact prodotto dal workflow.

Il workflow parte automaticamente ogni **lunedì e giovedì alle 07:15, fuso Europe/Rome**. Puoi cambiare giorni e orario nel file `.github/workflows/screener.yml`.

## Esecuzione locale facoltativa

Richiede Python 3.12 e Tesseract OCR con lingua italiana.

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
python -m playwright install chromium
pytest
python -m screener.main
```

## Come funziona

1. Playwright apre le pagine ufficiali con un browser Chromium headless.
2. Il programma tenta di selezionare il punto vendita configurato.
3. Raccoglie testo HTML, risposte JSON e collegamenti a volantini PDF.
4. PyMuPDF estrae il testo dai PDF.
5. Tesseract viene usato soltanto quando il volantino è composto da immagini senza testo selezionabile.
6. Il motore abbina marca, prodotto, formato e prezzo.
7. Calcola il prezzo per litro o chilogrammo quando quantità e prezzo sono interpretabili.
8. Confronta il risultato con gli ultimi 90 giorni dello storico.

## Interpretazione dei giudizi

- `OTTIMA`: prezzo vicino o inferiore al minimo storico disponibile;
- `BUONA`: almeno circa il 10% sotto la mediana storica;
- `NORMALE`: vicino al prezzo abituale;
- `NON CONVENIENTE`: superiore alla mediana storica;
- `MIGLIORE DI OGGI`: miglior prezzo tra le fonti, ma storico ancora insufficiente;
- `DA VERIFICARE`: associazione prodotto/prezzo o formato non abbastanza sicura.

All'inizio lo storico è vuoto. I giudizi diventano più utili dopo alcune settimane.

## Verifiche eseguite

La logica di riconoscimento e calcolo è coperta da test automatici: formati multipli, prezzo al litro/chilogrammo, separazione acqua/tè Sant'Anna, gusti Misura, Galbusera e Parmalat Barista. È stato verificato anche il ciclo locale di generazione dei quattro report.

Il collegamento **live** ai cinque siti deve essere verificato con il primo avvio su GitHub Actions: l'ambiente usato per preparare il repository non consente di eseguire una sessione Internet completa. Per questo il workflow conserva pagine, PDF, immagini ed errori diagnostici negli artifact.

## Limiti realistici

I siti dei supermercati possono cambiare struttura, selettori o visualizzatore del volantino. Il programma è costruito per continuare con le altre catene quando una fonte fallisce e registra gli errori in `reports/status.json` e negli artifact diagnostici. Tuttavia, una fonte modificata può richiedere un aggiornamento di `config/sources.yml` o del modulo `screener/browser.py`.

Non vengono utilizzati account, credenziali, coupon personali o promozioni visibili esclusivamente dopo l'accesso nelle app. Il programma consulta solo contenuti pubblici e non tenta di aggirare sistemi di protezione. Mantieni una frequenza moderata e verifica le condizioni d'uso delle fonti.

## Fonti pubbliche configurate

- Esselunga: `https://www.esselunga.it/it-it/promozioni/volantini.html`
- Iperal: `https://www.iperal.it/promozioni/`
- Il Gigante: `https://ilgigante.net/volantini/`
- MD: `https://www.mdspa.it/volantino/`
- Lidl Pioltello: `https://www.lidl.it/s/it-IT/ricerca-negozio/pioltello-mi/via-giorgio-amendola-13/`
